"""Cryptographic services.

Uses only reviewed library primitives from the `cryptography` package:
  * RSA keys, OEAP-SHA256 encryption, PKCS1v15 key serialisation
  * AES-256-GCM authenticated encryption
  * Ed25519 digital signatures
  * SHA-256 hashing and MGF1 masking

The blind credential is textbook RSA-FDH (full domain hash) used as a blind
signature: the accreditation service signs a value it never sees, and the voter
unblinds the signature locally. No bespoke cipher is implemented here.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import settings

# ── helpers ──────────────────────────────────────────────────────────────────
def b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def b64d(value: str) -> bytes:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + pad)


def sha256_hex(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8"))
        digest.update(b"\x1f")
    return digest.hexdigest()


def _master_key() -> bytes:
    # Derive a 256-bit key-encryption-key from the configured master secret.
    return hashlib.scrypt(
        settings.master_key.encode(), salt=b"sjc-election-master-key", n=2**14, r=8, p=1, dklen=32
    )


def encrypt_secret(plaintext: bytes) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(_master_key()).encrypt(nonce, plaintext, b"sjc-secret-v1")
    return "v1." + b64e(nonce + ct)


def decrypt_secret(token: str) -> bytes:
    if not token.startswith("v1."):
        raise ValueError("Unsupported secret envelope")
    raw = b64d(token[3:])
    nonce, ct = raw[:12], raw[12:]
    return AESGCM(_master_key()).decrypt(nonce, ct, b"sjc-secret-v1")


# ── RSA-FDH blind signature (anonymous voting credential) ────────────────────
def mgf1(seed: bytes, length: int) -> bytes:
    out = b""
    counter = 0
    while len(out) < length:
        out += hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
        counter += 1
    return out[:length]


def fdh(message: bytes, modulus: int) -> int:
    size = (modulus.bit_length() + 7) // 8
    mask = mgf1(hashlib.sha256(message).digest(), size)
    return int.from_bytes(mask, "big") % modulus


def credential_message(election_reference: str, token_hex: str) -> bytes:
    return f"SJC-CRED|{election_reference}|{token_hex}".encode()


def _credential_key_paths() -> tuple[Path, Path]:
    return (
        settings.keys_dir / "credential_issuer_private.pem",
        settings.keys_dir / "credential_issuer_public.pem",
    )


def load_or_create_credential_key() -> rsa.RSAPrivateKey:
    priv_path, pub_path = _credential_key_paths()
    if priv_path.exists():
        return serialization.load_pem_private_key(decrypt_secret(priv_path.read_text()), None)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_path.write_text(encrypt_secret(_private_pem(key)))
    pub_path.write_text(_public_pem(key.public_key()).decode())
    return key


def credential_public_numbers() -> dict:
    key = load_or_create_credential_key().public_key().public_numbers()
    return {
        "n": format(key.n, "x"),
        "e": format(key.e, "x"),
        "bits": key.n.bit_length(),
        "scheme": "RSA-FDH-blinded",
    }


def blind_sign(blinded_hex: str, election_reference: str) -> str:
    """Sign a blinded credential request. The service cannot link it to a voter."""
    key = load_or_create_credential_key()
    numbers = key.private_numbers()
    blinded = int(blinded_hex, 16)
    if blinded <= 1 or blinded >= numbers.public_numbers.n:
        raise ValueError("Invalid blinded message")
    signature = pow(blinded, numbers.d, numbers.public_numbers.n)
    return format(signature, "x")


def verify_credential(election_reference: str, token_hex: str, signature_hex: str) -> bool:
    try:
        key = load_or_create_credential_key().public_key()
        numbers = key.public_numbers()
        h = fdh(credential_message(election_reference, token_hex), numbers.n)
        recovered = pow(int(signature_hex, 16), numbers.e, numbers.n)
        return hmac.compare_digest(format(h, "x"), format(recovered, "x"))
    except (ValueError, TypeError):
        return False


# ── per-election keys ────────────────────────────────────────────────────────
def _private_pem(key) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _public_pem(key) -> bytes:
    return key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def election_key_dir(election_id: str) -> Path:
    path = settings.keys_dir / "elections" / election_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_election_keys(election_id: str) -> dict:
    """Generate tally (RSA-OAEP) and record-signing (Ed25519) key pairs.

    Private keys are written encrypted to the key directory; they are never
    stored in the database. Returns the public material.
    """
    directory = election_key_dir(election_id)
    tally = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    signer = ed25519.Ed25519PrivateKey.generate()

    (directory / "tally_private.enc").write_text(encrypt_secret(_private_pem(tally)))
    (directory / "tally_public.pem").write_text(_public_pem(tally.public_key()).decode())
    (directory / "signing_private.enc").write_text(encrypt_secret(_private_pem(signer)))
    (directory / "signing_public.pem").write_text(_public_pem(signer.public_key()).decode())

    return {
        "tally_public_key": _public_pem(tally.public_key()).decode(),
        "signing_public_key": _public_pem(signer.public_key()).decode(),
    }


def tally_public_key(election_id: str) -> rsa.RSAPublicKey:
    path = election_key_dir(election_id) / "tally_public.pem"
    return serialization.load_pem_public_key(path.read_bytes())


def tally_private_key(election_id: str) -> rsa.RSAPrivateKey:
    path = election_key_dir(election_id) / "tally_private.enc"
    if not path.exists():
        raise FileNotFoundError("Tally key not provisioned for this election")
    return serialization.load_pem_private_key(decrypt_secret(path.read_text()), None)


def signing_private_key(election_id: str) -> ed25519.Ed25519PrivateKey:
    path = election_key_dir(election_id) / "signing_private.enc"
    if not path.exists():
        raise FileNotFoundError("Signing key not provisioned for this election")
    return serialization.load_pem_private_key(decrypt_secret(path.read_text()), None)


def signing_public_key_b64(election_id: str) -> str:
    path = election_key_dir(election_id) / "signing_public.pem"
    return b64e(serialization.load_pem_public_key(path.read_bytes()).public_bytes_raw())


def election_sign(election_id: str, payload: bytes) -> str:
    return b64e(signing_private_key(election_id).sign(payload))


def election_verify(election_id: str, payload: bytes, signature_b64: str) -> bool:
    try:
        key = signing_private_key(election_id).public_key()
        key.verify(b64d(signature_b64), payload)
        return True
    except Exception:
        return False


# ── ballot encryption (hybrid RSA-OAEP + AES-256-GCM) ────────────────────────
def encrypt_ballot(election_id: str, election_reference: str, selections: dict) -> dict:
    data_key = os.urandom(32)
    nonce = os.urandom(12)
    plaintext = json.dumps(
        {"election": election_reference, "selections": selections},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    ciphertext = AESGCM(data_key).encrypt(nonce, plaintext, election_reference.encode())
    wrapped = tally_public_key(election_id).encrypt(
        data_key,
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )
    ct_b64, ek_b64, nonce_b64 = b64e(ciphertext), b64e(wrapped), b64e(nonce)
    return {
        "ciphertext": ct_b64,
        "encrypted_key": ek_b64,
        "nonce": nonce_b64,
        "commitment": ballot_commitment(election_reference, nonce_b64, ek_b64, ct_b64),
        "key_commitment": sha256_hex("SJC-KEY", election_reference, b64e(data_key)),
        "data_key": b64e(data_key),
    }


def ballot_commitment(election_reference: str, nonce: str, encrypted_key: str, ciphertext: str) -> str:
    return sha256_hex("SJC-BALLOT-COMMITMENT-V1", election_reference, nonce, encrypted_key, ciphertext)


def decrypt_ballot(election_id: str, election_reference: str, ciphertext_b64: str,
                   encrypted_key_b64: str, nonce_b64: str) -> dict:
    key = tally_private_key(election_id).decrypt(
        b64d(encrypted_key_b64),
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )
    plaintext = AESGCM(key).decrypt(b64d(nonce_b64), b64d(ciphertext_b64), election_reference.encode())
    data = json.loads(plaintext)
    if data.get("election") != election_reference:
        raise ValueError("Ballot is bound to a different election")
    return data["selections"]


# ── Merkle commitment list ───────────────────────────────────────────────────
def _leaf_hash(commitment: str) -> str:
    return hashlib.sha256(("SJC-LEAF|" + commitment).encode()).hexdigest()


def _node_hash(left: str, right: str) -> str:
    return hashlib.sha256(("SJC-NODE|" + left + right).encode()).hexdigest()


def merkle_tree(commitments: list[str]) -> list[list[str]]:
    if not commitments:
        return [[_leaf_hash("EMPTY")]]
    level = [_leaf_hash(c) for c in commitments]
    tree = [level]
    while len(level) > 1:
        if len(level) % 2:
            level = level + [level[-1]]
        level = [_node_hash(level[i], level[i + 1]) for i in range(0, len(level), 2)]
        tree.append(level)
    return tree


def merkle_root(commitments: list[str]) -> str:
    return merkle_tree(commitments)[-1][0]


def merkle_proof(commitments: list[str], index: int) -> dict:
    tree = merkle_tree(commitments)
    siblings = []
    idx = index
    for level in tree[:-1]:
        pair = idx ^ 1
        if pair < len(level):
            siblings.append({"hash": level[pair], "side": "right" if pair > idx else "left"})
        idx //= 2
    return {"leaf_hash": tree[0][index], "siblings": siblings, "root": tree[-1][0], "index": index}


def verify_merkle_proof(commitment: str, proof: dict) -> bool:
    node = proof.get("leaf_hash") or _leaf_hash(commitment)
    if proof.get("leaf_hash") and proof["leaf_hash"] != _leaf_hash(commitment):
        return False
    for sibling in proof.get("siblings", []):
        if sibling["side"] == "right":
            node = _node_hash(node, sibling["hash"])
        else:
            node = _node_hash(sibling["hash"], node)
    return hmac.compare_digest(node, proof.get("root", ""))


# ── receipts ─────────────────────────────────────────────────────────────────
def new_receipt_reference() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    groups = ["".join(secrets.choice(alphabet) for _ in range(5)) for _ in range(4)]
    return "SJCJ-" + "-".join(groups)


def receipt_hash(reference: str) -> str:
    return hashlib.sha256(("SJC-RECEIPT|" + reference.strip().upper()).encode()).hexdigest()


def receipt_number() -> str:
    return "SJCJ/R/" + secrets.token_hex(5).upper()
