"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { PublicShell } from "@/components/PublicShell";
import { Alert, Card, CheckRow, Loading } from "@/components/ui";
import { api, formatDate, shortHash } from "@/lib/api";

const CHECK_LABELS: Record<string, string> = {
  receipt_valid: "This is a valid receipt issued by the election system",
  ballot_recorded: "An accepted encrypted ballot exists for this commitment",
  commitment_present: "The ballot commitment is recorded in the election database",
  published: "The commitment appears in the published election record",
  merkle_verified: "The commitment is covered by the signed Merkle root",
  counted_in_tally: "The ballot was included in the final counting record",
  signature_verified: "The published batch signature is valid",
};

function VerifyInner() {
  const params = useSearchParams();
  const [reference, setReference] = useState(params.get("ref") ?? "");
  const [result, setResult] = useState<any | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [searched, setSearched] = useState(false);

  async function lookup(value: string) {
    if (!value.trim()) return;
    setBusy(true);
    setError("");
    try {
      const data = await api(`/api/verify/${encodeURIComponent(value.trim())}`);
      setResult(data);
      setSearched(true);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    const initial = params.get("ref");
    if (initial) lookup(initial);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="mx-auto max-w-3xl">
      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-green">Public verification portal</p>
      <h1 className="mt-2 text-3xl text-ink">Verify your ballot</h1>
      <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink/60">
        Enter the verification reference printed on your receipt, or scan the receipt QR code. This
        service confirms inclusion only — it never reveals who you are or how you voted.
      </p>

      <Card className="card-pad mt-6">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            lookup(reference);
          }}
          className="flex flex-col gap-3 sm:flex-row"
        >
          <input
            className="input font-mono"
            placeholder="SJCJ-XXXXX-XXXXX-XXXXX-XXXXX"
            value={reference}
            onChange={(event) => setReference(event.target.value.toUpperCase())}
            aria-label="Verification reference"
          />
          <button className="btn-primary shrink-0" disabled={busy}>
            {busy ? "Checking…" : "Verify ballot"}
          </button>
        </form>
        <p className="mt-3 text-xs text-ink/45">
          The reference is 160 bits of randomness: it cannot be guessed or enumerated.
        </p>
      </Card>

      {error ? <div className="mt-5"><Alert tone="error">{error}</Alert></div> : null}
      {busy ? <Loading label="Checking the published election record…" /> : null}

      {result && !result.found ? (
        <div className="mt-5">
          <Alert tone="error">{result.message}</Alert>
        </div>
      ) : null}

      {result?.found ? (
        <div className="mt-6 space-y-4 animate-rise">
          <Card className="card-pad">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-ink/45">
                  {result.election.title}
                </p>
                <h2 className="mt-1 font-display text-xl text-ink">
                  Receipt {result.receipt_number}
                </h2>
                <p className="mt-1 text-xs text-ink/50">
                  Issued {formatDate(result.issued_at)} · {result.election.reference}
                </p>
              </div>
              <span className={result.accepted ? "pill-green" : "pill-red"}>
                {result.accepted ? "Ballot accepted" : "Not accepted"}
              </span>
            </div>

            <div className="mt-5">
              {Object.entries(CHECK_LABELS).map(([key, label]) => (
                <CheckRow key={key} passed={Boolean(result.checks?.[key])}>
                  {label}
                </CheckRow>
              ))}
            </div>

            {result.message ? (
              <div className="mt-4">
                <Alert tone={result.checks?.merkle_verified ? "success" : "info"}>{result.message}</Alert>
              </div>
            ) : null}

            <dl className="mt-5 space-y-1">
              <div className="kv">
                <dt>Ballot commitment</dt>
                <dd className="code max-w-[75%] text-right">{result.ballot_commitment}</dd>
              </div>
              <div className="kv">
                <dt>Election status</dt>
                <dd className="capitalize">{result.election.status.replace(/_/g, " ")}</dd>
              </div>
              {result.tally ? (
                <div className="kv">
                  <dt>Counted in tally</dt>
                  <dd>{result.tally.counted ? "Yes" : "Not counted"}</dd>
                </div>
              ) : null}
            </dl>
          </Card>

          {result.batch ? (
            <Card className="card-pad">
              <h3 className="font-display text-lg text-ink">Published commitment batch</h3>
              <dl className="mt-3 space-y-1">
                <div className="kv">
                  <dt>Batch reference</dt>
                  <dd className="font-mono text-xs">{result.batch.reference}</dd>
                </div>
                <div className="kv">
                  <dt>Merkle root</dt>
                  <dd className="code max-w-[70%] text-right">{result.batch.merkle_root}</dd>
                </div>
                <div className="kv">
                  <dt>Commitments in batch</dt>
                  <dd>{result.batch.commitment_count}</dd>
                </div>
                <div className="kv">
                  <dt>Published</dt>
                  <dd>{formatDate(result.batch.published_at)}</dd>
                </div>
                <div className="kv">
                  <dt>Digital signature</dt>
                  <dd>{shortHash(result.batch.digital_signature, 14)}</dd>
                </div>
              </dl>
              <details className="mt-4 rounded-xl border border-line bg-cream/50 p-4">
                <summary className="cursor-pointer text-sm font-semibold text-ink">
                  Merkle inclusion proof (independent verification material)
                </summary>
                <pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] text-ink/65">
                  {JSON.stringify(result.batch.merkle_proof, null, 2)}
                </pre>
                <a
                  href={`/commitments`}
                  className="mt-3 inline-block text-xs font-semibold text-green underline"
                >
                  Open the full published commitment list
                </a>
              </details>
            </Card>
          ) : (
            <Alert tone="info">
              The anonymous commitment list has not been published yet. Your ballot is recorded; check
              again after voting closes.
            </Alert>
          )}

          {result.tally ? (
            <Card className="card-pad">
              <h3 className="font-display text-lg text-ink">Counting evidence</h3>
              <dl className="mt-3 space-y-1">
                <div className="kv">
                  <dt>Count completed</dt>
                  <dd>{formatDate(result.tally.finished_at)}</dd>
                </div>
                <div className="kv">
                  <dt>Ballot proof hash</dt>
                  <dd className="code max-w-[70%] text-right">{result.tally.ballot_hash}</dd>
                </div>
                <div className="kv">
                  <dt>Evidence hash</dt>
                  <dd className="code max-w-[70%] text-right">{result.tally.evidence_hash}</dd>
                </div>
              </dl>
            </Card>
          ) : null}

          <div className="flex flex-wrap gap-3">
            <Link href={`/receipt?ref=${encodeURIComponent(result.verification_reference)}`} className="btn-outline">
              Open receipt
            </Link>
            <Link href="/results" className="btn-outline">
              Declared results
            </Link>
          </div>
        </div>
      ) : null}

      {searched && !result ? <Alert tone="error">No result returned.</Alert> : null}
    </div>
  );
}

export default function VerifyPage() {
  return (
    <PublicShell>
      <Suspense fallback={<Loading label="Opening verification portal…" />}>
        <VerifyInner />
      </Suspense>
    </PublicShell>
  );
}
