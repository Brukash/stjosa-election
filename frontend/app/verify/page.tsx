"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { PublicShell } from "@/components/PublicShell";
import { Alert, Card, CheckRow, Loading } from "@/components/ui";
import { api, formatLongDate, shortHash } from "@/lib/api";

// What each check means, in the words a voter would use.
const CHECK_LABELS: Record<string, string> = {
  receipt_valid: "The receipt is genuine and was issued by this election",
  ballot_recorded: "An accepted ballot exists for this receipt",
  commitment_present: "The ballot is stored in the election record",
  published: "The ballot appears in the published record",
  merkle_verified: "The published batch is signed and unaltered",
  counted_in_tally: "The ballot was included in the final count",
  signature_verified: "The batch signature checks out",
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

  const passed = result?.found
    ? Object.keys(CHECK_LABELS).filter((key) => Boolean(result.checks?.[key])).length
    : 0;

  return (
    <div className="mx-auto max-w-3xl">
      <p className="eyebrow">Check a ballot</p>
      <h1 className="page-title mt-2">
        Check that your ballot was counted
      </h1>
      <p className="mt-2 max-w-xl text-[13.5px] leading-relaxed text-ink/65">
        Enter the reference from your receipt. We confirm the ballot is in the record — never who you
        are or how you voted.
      </p>

      <Card className="card-pad mt-6">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            lookup(reference);
          }}
          className="flex flex-col gap-3 sm:flex-row"
        >
          <label className="flex-1">
            <span className="sr-only">Your receipt reference</span>
            <input
              className="input font-mono text-[13px]"
              placeholder="For example SJCJ/R/C7621D49DD"
              value={reference}
              onChange={(event) => setReference(event.target.value.toUpperCase())}
              autoComplete="off"
              spellCheck={false}
            />
          </label>
          <button className="btn-primary shrink-0" disabled={busy}>
            {busy ? "Checking…" : "Check"}
          </button>
        </form>
        <p className="mt-3 text-[12px] leading-relaxed text-ink/50">
          The reference is long and random, so it cannot be guessed from another voter's.
        </p>
      </Card>

      {error ? <div className="mt-5"><Alert tone="error">{error}</Alert></div> : null}
      {busy ? <Loading label="Reading the published record…" /> : null}

      {result && !result.found ? (
        <div className="mt-5">
          <Alert tone="error">{result.message}</Alert>
        </div>
      ) : null}

      {result?.found ? (
        <div className="mt-6 space-y-4 animate-rise">
          <div className="rounded-[10px] border border-rule bg-surface shadow-ballot">
            <div className="flex items-start justify-between gap-4 border-b border-rule px-5 py-5 sm:px-6">
              <div className="min-w-0">
                <p className="eyebrow">{result.election.title}</p>
                <h2 className="mt-1.5 font-display text-[22px] leading-tight text-ink">
                  {result.accepted ? "Ballot accepted and on record" : "Ballot not accepted"}
                </h2>
                <p className="mt-1 text-[12.5px] text-ink/55">
                  Receipt {result.receipt_number} · issued {formatLongDate(result.issued_at)}
                </p>
              </div>
              <span
                aria-hidden="true"
                className={`hidden shrink-0 -rotate-6 rounded-[3px] border-2 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-[0.14em] sm:block ${
                  result.accepted
                    ? "border-forest/60 text-forest"
                    : "border-clay/60 text-clay"
                }`}
              >
                {result.accepted ? "On record" : "Rejected"}
              </span>
            </div>

            <div className="px-5 py-5 sm:px-6">
              <div className="flex items-baseline justify-between gap-3">
                <p className="text-[13px] font-semibold text-ink">
                  {passed} of {Object.keys(CHECK_LABELS).length} checks passed
                </p>
                <Link
                  href={`/receipt?ref=${encodeURIComponent(result.verification_reference)}`}
                  className="text-[12px] font-medium text-forest underline decoration-rule decoration-1 underline-offset-4 hover:decoration-forest"
                >
                  Open receipt
                </Link>
              </div>

              <div className="mt-3">
                {Object.entries(CHECK_LABELS).map(([key, label]) => (
                  <CheckRow key={key} passed={Boolean(result.checks?.[key])}>
                    {label}
                  </CheckRow>
                ))}
              </div>

              {result.message ? (
                <div className="mt-4">
                  <Alert tone={result.checks?.merkle_verified ? "success" : "info"}>
                    {result.message}
                  </Alert>
                </div>
              ) : null}

              <dl className="mt-5">
                <div className="kv">
                  <dt>Election</dt>
                  <dd className="text-right text-[13px]">{result.election.reference}</dd>
                </div>
                <div className="kv">
                  <dt>Election status</dt>
                  <dd className="text-right capitalize">
                    {String(result.election.status ?? "").replace(/_/g, " ")}
                  </dd>
                </div>
                {result.tally ? (
                  <div className="kv">
                    <dt>Included in the count</dt>
                    <dd className="text-right">{result.tally.counted ? "Yes" : "Not yet"}</dd>
                  </div>
                ) : null}
                <div className="kv">
                  <dt>Ballot fingerprint</dt>
                  <dd className="code max-w-[62%] text-right">{result.ballot_commitment}</dd>
                </div>
              </dl>
            </div>
          </div>

          {result.batch ? (
            <Card className="card-pad">
              <h3 className="font-display text-[18px] text-ink">Published batch</h3>
              <p className="mt-1 text-[13px] leading-relaxed text-ink/60">
                Your ballot is one of the anonymous fingerprints published on{" "}
                {formatLongDate(result.batch.published_at)}.
              </p>
              <dl className="mt-3">
                <div className="kv">
                  <dt>Batch</dt>
                  <dd className="text-right text-[13px]">{result.batch.reference}</dd>
                </div>
                <div className="kv">
                  <dt>Ballots in batch</dt>
                  <dd className="text-right tabular">{result.batch.commitment_count}</dd>
                </div>
                <div className="kv">
                  <dt>Batch signature</dt>
                  <dd className="text-right">{shortHash(result.batch.digital_signature, 14)}</dd>
                </div>
              </dl>

              <details className="mt-4 border-t border-rule pt-3">
                <summary className="cursor-pointer text-[12px] font-medium text-ink/55">
                  Material for an independent check
                </summary>
                <dl className="mt-3">
                  <div className="kv">
                    <dt>Batch fingerprint (root)</dt>
                    <dd className="code max-w-[60%] text-right">{result.batch.merkle_root}</dd>
                  </div>
                </dl>
                <pre className="mt-3 max-h-56 overflow-auto whitespace-pre-wrap break-all rounded-[6px] border border-rule bg-paper p-3 font-mono text-[11px] text-ink/60">
                  {JSON.stringify(result.batch.merkle_proof, null, 2)}
                </pre>
                <Link
                  href="/commitments"
                  className="mt-3 inline-block text-[12px] font-medium text-forest underline decoration-rule decoration-1 underline-offset-4 hover:decoration-forest"
                >
                  See the full published record
                </Link>
              </details>
            </Card>
          ) : (
            <Alert tone="info">
              The anonymous ballot record has not been published yet. Your ballot is recorded — check
              again after voting closes.
            </Alert>
          )}

          {result.tally ? (
            <Card className="card-pad">
              <h3 className="font-display text-[18px] text-ink">Counting record</h3>
              <dl className="mt-3">
                <div className="kv">
                  <dt>Count completed</dt>
                  <dd className="text-right">{formatLongDate(result.tally.finished_at)}</dd>
                </div>
                <div className="kv">
                  <dt>Ballot hash</dt>
                  <dd className="code max-w-[62%] text-right">{result.tally.ballot_hash}</dd>
                </div>
                <div className="kv">
                  <dt>Evidence hash</dt>
                  <dd className="code max-w-[62%] text-right">{result.tally.evidence_hash}</dd>
                </div>
              </dl>
            </Card>
          ) : null}

          <div className="flex flex-col gap-3 sm:flex-row">
            <Link href="/results" className="btn-outline w-full sm:w-auto">
              See the results
            </Link>
            <Link href="/vote" className="btn-ghost w-full sm:w-auto">
              Back to the ballot
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
      <Suspense fallback={<Loading label="Opening the check page…" />}>
        <VerifyInner />
      </Suspense>
    </PublicShell>
  );
}
