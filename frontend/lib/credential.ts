/**
 * Browser-side anonymous credential client.
 *
 * The voter's browser chooses a random secret token, blinds its RSA-FDH hash,
 * asks the accreditation service for a signature, then unblinds it locally. The
 * service therefore signs a value it never sees, so it cannot link the issued
 * credential to the voter's ballot.
 */
import { API_BASE } from "./api";

export type Credential = { token: string; signature: string; turnout_token: string };
export type CredentialKeys = { n: string; e: string; bits: number };

const encoder = new TextEncoder();

function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function bigIntToHex(value: bigint): string {
  return value.toString(16);
}

function modPow(base: bigint, exponent: bigint, modulus: bigint): bigint {
  let result = 1n;
  let b = base % modulus;
  let e = exponent;
  while (e > 0n) {
    if (e & 1n) result = (result * b) % modulus;
    b = (b * b) % modulus;
    e >>= 1n;
  }
  return result;
}

function egcd(a: bigint, b: bigint): [bigint, bigint, bigint] {
  if (b === 0n) return [a, 1n, 0n];
  const [g, x, y] = egcd(b, a % b);
  return [g, y, x - (a / b) * y];
}

function modInverse(a: bigint, m: bigint): bigint {
  const [g, x] = egcd(((a % m) + m) % m, m);
  if (g !== 1n) throw new Error("Blinding factor is not invertible");
  return ((x % m) + m) % m;
}

function gcd(a: bigint, b: bigint): bigint {
  let x = a;
  let y = b;
  while (y) {
    const t = x % y;
    x = y;
    y = t;
  }
  return x;
}

async function sha256(data: Uint8Array): Promise<Uint8Array> {
  const digest = await crypto.subtle.digest("SHA-256", data);
  return new Uint8Array(digest);
}

async function hashParts(parts: string[]): Promise<string> {
  return bytesToHex(await sha256(encoder.encode(parts.map((part) => part + "\x1f").join(""))));
}

async function mgf1(seed: Uint8Array, length: number): Promise<Uint8Array> {
  const output = new Uint8Array(length);
  let offset = 0;
  let counter = 0;
  while (offset < length) {
    const block = new Uint8Array(seed.length + 4);
    block.set(seed);
    new DataView(block.buffer).setUint32(seed.length, counter, false);
    const digest = await sha256(block);
    output.set(digest.subarray(0, Math.min(digest.length, length - offset)), offset);
    offset += digest.length;
    counter += 1;
  }
  return output;
}

async function fullDomainHash(message: string, modulus: bigint): Promise<bigint> {
  const seed = await sha256(encoder.encode(message));
  const size = Math.ceil(modulus.toString(2).length / 8);
  const mask = await mgf1(seed, size);
  let value = 0n;
  for (const byte of mask) value = (value << 8n) | BigInt(byte);
  return value % modulus;
}

function randomScalarBelow(bound: bigint): bigint {
  const bytes = new Uint8Array(48);
  crypto.getRandomValues(bytes);
  let value = 0n;
  for (const byte of bytes) value = (value << 8n) | BigInt(byte);
  return value % (bound - 3n) + 2n;
}

export async function issueCredential(
  electionId: string,
  electionReference: string,
  accreditationToken: string,
  turnoutToken: string
): Promise<Credential> {
  const keysResponse = await fetch(`${API_BASE}/api/crypto/${electionId}`, { cache: "no-store" });
  if (!keysResponse.ok) throw new Error("Unable to load credential issuer keys");
  const keys = (await keysResponse.json()).credential as CredentialKeys;
  const n = BigInt("0x" + keys.n);
  const e = BigInt("0x" + keys.e);

  const token = bytesToHex(crypto.getRandomValues(new Uint8Array(32)));
  const message = `SJC-CRED|${electionReference}|${token}`;
  const hash = await fullDomainHash(message, n);

  let r = randomScalarBelow(n);
  while (gcd(r, n) !== 1n) r = randomScalarBelow(n);
  const blinded = (hash * modPow(r, e, n)) % n;

  const response = await fetch(`${API_BASE}/api/accreditation/credential`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ accreditation_token: accreditationToken, blinded_message: bigIntToHex(blinded) }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? "Credential issuance failed");
  }
  const data = await response.json();
  const blindSignature = BigInt("0x" + data.blind_signature);
  const signature = (blindSignature * modInverse(r, n)) % n;

  if (modPow(signature, e, n) !== hash) {
    throw new Error("Credential signature failed local verification");
  }

  return { token, signature: bigIntToHex(signature), turnout_token: turnoutToken };
}

export function storeCredential(electionId: string, credential: Credential) {
  window.sessionStorage.setItem(`sjc_credential_${electionId}`, JSON.stringify(credential));
}

export function loadCredential(electionId: string): Credential | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(`sjc_credential_${electionId}`);
    return raw ? (JSON.parse(raw) as Credential) : null;
  } catch {
    return null;
  }
}

export type ChallengeMaterial = {
  election_reference: string;
  ciphertext: string;
  encrypted_key: string;
  nonce: string;
  data_key: string;
  key_commitment: string;
  commitment: string;
  revealed_selections: Record<string, string>;
};

function b64ToBytes(value: string): Uint8Array {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
  const raw = atob(padded);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value as Record<string, unknown>)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalJson((value as any)[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

export type ChallengeCheck = { label: string; passed: boolean; detail?: string };

/** Independently verify the revealed challenge material in the voter's browser. */
export async function verifyChallenge(
  material: ChallengeMaterial,
  expectedSelections: Record<string, string>
): Promise<ChallengeCheck[]> {
  const checks: ChallengeCheck[] = [];

  const selectionsMatch =
    canonicalJson(material.revealed_selections) === canonicalJson(expectedSelections);
  checks.push({
    label: "Revealed selections match the choices I made",
    passed: selectionsMatch,
  });

  try {
    const key = b64ToBytes(material.data_key);
    const cryptoKey = await crypto.subtle.importKey("raw", key, "AES-GCM", false, ["decrypt"]);
    const plaintext = await crypto.subtle.decrypt(
      {
        name: "AES-GCM",
        iv: b64ToBytes(material.nonce),
        additionalData: encoder.encode(material.election_reference),
      },
      cryptoKey,
      b64ToBytes(material.ciphertext)
    );
    const decoded = JSON.parse(new TextDecoder().decode(plaintext));
    const ciphertextSelectionsMatch =
      canonicalJson(decoded.selections) === canonicalJson(expectedSelections) &&
      decoded.election === material.election_reference;
    checks.push({
      label: "The encrypted ballot decrypts to exactly those selections",
      passed: ciphertextSelectionsMatch,
    });
  } catch {
    checks.push({ label: "The encrypted ballot decrypts to exactly those selections", passed: false });
  }

  const keyDigest = await hashParts(["SJC-KEY", material.election_reference, material.data_key]);
  checks.push({
    label: "Encryption key matches the published key commitment",
    passed: keyDigest === material.key_commitment,
    detail: `key commitment ${material.key_commitment.slice(0, 24)}…`,
  });

  const commitmentDigest = await hashParts([
    "SJC-BALLOT-COMMITMENT-V1",
    material.election_reference,
    material.nonce,
    material.encrypted_key,
    material.ciphertext,
  ]);
  checks.push({
    label: "Ballot commitment matches the ciphertext",
    passed: commitmentDigest === material.commitment,
  });

  return checks;
}
