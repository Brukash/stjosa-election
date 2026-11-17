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
import threading
from functools import lru_cache
from pathlib import Path
from typing import Callable

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import settings
from .keyarchive import archive_error

class KeyMaterialError(RuntimeError):
    """Election key material is missing or unreadable on this deployment.

    Raised instead of generating a throwaway key: a credential issuer key that
    changes between instances would invalidate credentials already given out.
    """


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


@lru_cache(maxsize=4)
def _derive_master_key(secret: str) -> bytes:
    # scrypt is deliberately slow (~100 ms); it only needs to run once per process.
    return hashlib.scrypt(
        secret.encode(), salt=b"sjc-election-master-key", n=2**14, r=8, p=1, dklen=32
    )


def _master_key() -> bytes:
    # Derive a 256-bit key-encryption-key from the configured master secret.
    return _derive_master_key(settings.master_key)


# Keys read from disk were decrypted (scrypt) and PEM-parsed on every use, which
# cost a public page ~170 ms. Cache the loaded objects and key the cache on the
# file's (mtime, size) so a rotated key is picked up without a restart.
_KEY_CACHE: dict[tuple[str, int, int], object] = {}
_KEY_CACHE_LOCK = threading.Lock()
_KEY_CACHE_LIMIT = 64


def _cached_key_file(path: Path, load: Callable[[bytes], object], encrypted: bool = False):
    stamp = path.stat()
    cache_key = (str(path), stamp.st_mtime_ns, stamp.st_size)
    cached = _KEY_CACHE.get(cache_key)
    if cached is not None:
        return cached
    payload = path.read_bytes()
    if encrypted:
        payload = decrypt_secret(payload.decode())
    key = load(payload)
    with _KEY_CACHE_LOCK:
        if len(_KEY_CACHE) >= _KEY_CACHE_LIMIT:
            _KEY_CACHE.clear()
        _KEY_CACHE[cache_key] = key
    return key


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


def _publish_key_file_once(path: Path, payload: str) -> bool:
    """Create ``path`` exactly once, atomically, so no reader sees a partial key.

    Writing straight into the destination left a window where a second worker
    found the file, read it half-written, and failed to decrypt it. The payload
    is written beside the destination and hard-linked into place, which is atomic
    and fails when another worker already published the key.
    """
    if path.exists():
        return False
    temp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp")
    temp.write_text(payload, encoding="utf-8")
    try:
        try:
            os.link(temp, path)
        except FileExistsError:
            return False
        except OSError:
            # A filesystem without hard links: publish by atomic replace, which
            # still never exposes a partially written file.
            if path.exists():
                return False
            os.replace(temp, path)
        return True
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def load_or_create_credential_key() -> rsa.RSAPrivateKey:
    priv_path, pub_path = _credential_key_paths()
    if priv_path.exists():
        try:
            return _cached_key_file(
                priv_path, lambda pem: serialization.load_pem_private_key(pem, None), encrypted=True
            )
        except Exception as exc:  # noqa: BLE001 - every failure is a provisioning problem
            raise KeyMaterialError(
                "The election key file could not be read. It may have been encrypted with a "
                "different MASTER_KEY than this deployment uses."
            ) from exc
    if settings.is_production or not settings.keys_dir_is_durable:
        # No key, and nowhere this process can put one that other processes
        # share. Generating here gave every serverless instance its own
        # credential key: the browser blinds a credential with the published
        # key, so a ballot signed by another instance never unblinded. Fail
        # with something actionable instead of issuing unusable credentials.
        raise KeyMaterialError(
            "Election keys are not provisioned on this deployment." + _provisioning_hint()
        )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    if not _publish_key_file_once(priv_path, encrypt_secret(_private_pem(key))):
        # Another process won the race to create the key. Use its key so every
        # process signs with the same credential key the first one published.
        return _cached_key_file(
            priv_path, lambda pem: serialization.load_pem_private_key(pem, None), encrypted=True
        )
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
    # Reading must not try to create the directory: on a read-only serverless
    # filesystem the mkdir itself is what failed, hiding the real cause.
    return settings.keys_dir / "elections" / election_id


def _provisioning_hint() -> str:
    """Explain how to supply key material, naming a failed archive when there is one."""
    detail = archive_error()
    if detail:
        return f" Key material could not be restored: {detail}."
    return (
        " Set KEYS_ARCHIVE_B64 (an encrypted archive of the key directory), or "
        "publish one to the database with scripts/escrow_keys.py, so the API can "
        "serve the ballot."
    )


def _required_key(path: Path, load: Callable[[bytes], object], label: str, encrypted: bool = False):
    """Read a key file, reporting absence as a provisioning problem."""
    try:
        return _cached_key_file(path, load, encrypted=encrypted)
    except FileNotFoundError as exc:
        raise KeyMaterialError(
            f"{label} is not provisioned on this deployment." + _provisioning_hint()
        ) from exc
    except KeyMaterialError:
        raise
    except Exception as exc:  # noqa: BLE001 - unreadable key material is a setup error
        raise KeyMaterialError(
            f"{label} could not be read. It may have been encrypted with a different "
            "MASTER_KEY than this deployment uses."
        ) from exc


def create_election_keys(election_id: str) -> dict:
    """Generate tally (RSA-OAEP) and record-signing (Ed25519) key pairs.

    Private keys are written encrypted to the key directory; they are never
    stored in the database. Returns the public material.
    """
    directory = election_key_dir(election_id)
    directory.mkdir(parents=True, exist_ok=True)
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


def tally_public_key_from_pem(pem: str | None) -> rsa.RSAPublicKey:
    """Load the tally public key stored on the election row.

    Public material is read from the database because a deployment can serve an
    election without holding its key files at all. Only private operations need
    the files.
    """
    if not pem:
        raise KeyMaterialError(
            "This election has no tally public key on record. Provision its keys "
            "before ballots can be prepared."
        )
    try:
        key = serialization.load_pem_public_key(pem.encode())
    except Exception as exc:  # noqa: BLE001 - unreadable stored material is a setup error
        raise KeyMaterialError("The stored election tally public key could not be read.") from exc
    if not isinstance(key, rsa.RSAPublicKey):
        raise KeyMaterialError("The stored election tally public key is not an RSA key.")
    return key


def tally_private_key(election_id: str) -> rsa.RSAPrivateKey:
    path = election_key_dir(election_id) / "tally_private.enc"
    return _required_key(
        path,
        lambda pem: serialization.load_pem_private_key(pem, None),
        "The election tally private key",
        encrypted=True,
    )


def signing_private_key(election_id: str) -> ed25519.Ed25519PrivateKey:
    path = election_key_dir(election_id) / "signing_private.enc"
    return _required_key(
        path,
        lambda pem: serialization.load_pem_private_key(pem, None),
        "The election signing private key",
        encrypted=True,
    )


def signing_public_b64_from_pem(pem: str | None) -> str | None:
    """Convert a stored public-key PEM to the base64 form the browser expects.

    The election row already carries its signing public key, so publishing it
    does not need the key files to exist on the host.
    """
    if not pem:
        return None
    try:
        return b64e(serialization.load_pem_public_key(pem.encode()).public_bytes_raw())
    except Exception:  # noqa: BLE001 - unusable stored material is reported as absent
        return None


def election_sign(election_id: str, payload: bytes) -> str:
    return b64e(signing_private_key(election_id).sign(payload))


def election_verify(signing_public_pem: str | None, payload: bytes,
                    signature_b64: str) -> bool:
    """Verify a record signature against the election's stored signing key."""
    if not signing_public_pem:
        return False
    try:
        key = serialization.load_pem_public_key(signing_public_pem.encode())
        key.verify(b64d(signature_b64), payload)
        return True
    except Exception:
        return False


# ── ballot encryption (hybrid RSA-OAEP + AES-256-GCM) ────────────────────────
def encrypt_ballot(election_reference: str, selections: dict,
                   tally_public_pem: str | None) -> dict:
    data_key = os.urandom(32)
    nonce = os.urandom(12)
    plaintext = json.dumps(
        {"election": election_reference, "selections": selections},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    ciphertext = AESGCM(data_key).encrypt(nonce, plaintext, election_reference.encode())
    wrapped = tally_public_key_from_pem(tally_public_pem).encrypt(
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
