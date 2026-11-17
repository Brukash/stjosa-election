"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PublicShell } from "@/components/PublicShell";
import { Alert, Card, Loading, Stat } from "@/components/ui";
import { API_BASE, api, formatLongDate } from "@/lib/api";

export default function ResultsPage() {
  const [data, setData] = useState<any | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api("/api/results/public/current")
      .then(setData)
      .catch((err) => setError(err.message));
  }, []);

  const figures = data?.figures;
  const totals = figures?.totals;

  return (
    <PublicShell>
      <div className="mx-auto max-w-3xl">
        <p className="eyebrow">Official results</p>
        <h1 className="page-title mt-2">
          {data?.election?.title ?? "Election results"}
        </h1>
        <p className="mt-2 max-w-xl text-[13.5px] leading-relaxed text-ink/65">
          Results are declared by the Electoral Committee and published with the record they were
          counted from, so the figures can be checked without asking anyone.
        </p>

        {error ? <div className="mt-6"><Alert tone="error">{error}</Alert></div> : null}
        {!data && !error ? <Loading /> : null}

        {data && !data.published ? (
          <div className="mt-6 space-y-4">
            <Alert tone="info">{data.message}</Alert>
            {data.turnout ? (
              <div className="grid grid-cols-3 gap-2.5 sm:gap-3">
                <Stat label="Eligible" value={data.turnout.eligible_voters} />
                <Stat label="Accredited" value={data.turnout.accredited_voters} />
                <Stat label="Ballots cast" value={data.turnout.votes_cast} />
              </div>
            ) : null}
          </div>
        ) : null}

        {data?.published && figures ? (
          <div className="mt-6 space-y-5">
            <div className="rounded-[10px] border border-rule bg-surface shadow-ballot">
              <div className="flex items-start justify-between gap-4 border-b border-rule px-5 py-5 sm:px-6">
                <div>
                  <p className="eyebrow">Declaration</p>
                  <p className="mt-1.5 text-[12.5px] text-ink/60">
                    {formatLongDate(data.declared_at)} · {data.declared_by}
                  </p>
                </div>
                <span
                  aria-hidden="true"
                  className={`hidden shrink-0 -rotate-6 rounded-[3px] border-2 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-[0.14em] sm:block ${
                    data.signature_valid ? "border-forest/60 text-forest" : "border-clay/60 text-clay"
                  }`}
                >
                  {data.signature_valid ? "Signed" : "Unverified"}
                </span>
              </div>

              <div className="px-5 py-5 sm:px-6">
                {data.correction_reason ? (
                  <div className="mb-4">
                    <Alert tone="warn">Corrected declaration: {data.correction_reason}</Alert>
                  </div>
                ) : null}

                <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 sm:gap-3">
                  <Stat label="Eligible voters" value={totals.eligible_voters} />
                  <Stat label="Accredited voters" value={totals.accredited_voters} />
                  <Stat label="Turnout" value={`${totals.turnout_percentage}%`} />
                  <Stat label="Votes cast" value={totals.votes_cast} />
                  <Stat label="Valid ballots" value={totals.valid_ballots} />
                  <Stat label="Invalid ballots" value={totals.invalid_ballots} />
                </div>

                <p className="mt-4 text-[12px] leading-relaxed text-ink/50">
                  {totals.challenged_ballots} checked-and-spoiled ballot(s) were excluded from the
                  count. Those were ballots voters deliberately spoiled to test the process.
                </p>
              </div>
            </div>

            {figures.positions.map((position: any) => (
              <Card key={position.id} className="card-pad">
                <div className="flex flex-wrap items-baseline justify-between gap-2 border-b-2 border-ink/80 pb-2">
                  <h2 className="font-display text-[19px] leading-tight text-ink">{position.title}</h2>
                  <span className="shrink-0 text-[10.5px] font-semibold uppercase tracking-[0.1em] text-ink/45">
                    {position.seats} seat{position.seats === 1 ? "" : "s"}
                  </span>
                </div>

                <div className="mt-1">
                  {position.candidates.map((candidate: any) => (
                    <div
                      key={candidate.id}
                      className={`flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-rule/70 py-3 ${
                        candidate.is_winner ? "bg-forest/[0.04]" : ""
                      }`}
                    >
                      <div className="min-w-0 flex-1">
                        <p
                          className={`text-[14.5px] leading-snug ${
                            candidate.is_winner ? "font-semibold text-forest" : "text-ink"
                          }`}
                        >
                          {candidate.full_name}
                        </p>
                        {candidate.is_winner ? (
                          <p className="mt-0.5 text-[10.5px] font-semibold uppercase tracking-[0.1em] text-ochre">
                            Elected{candidate.tie ? " · tied" : ""}
                          </p>
                        ) : null}
                      </div>
                      <div className="flex items-baseline gap-4 tabular">
                        <span className="text-[12px] text-ink/50">{candidate.percentage}%</span>
                        <span className="min-w-[3ch] text-right text-[14px] font-semibold text-ink">
                          {candidate.votes}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </Card>
            ))}

            <Card className="card-pad">
              <h2 className="font-display text-[18px] text-ink">The record</h2>
              <dl className="mt-3">
                <div className="kv">
                  <dt>Receipts issued</dt>
                  <dd className="text-right tabular">{figures.verification?.receipts_issued}</dd>
                </div>
                <div className="kv">
                  <dt>Published ballot fingerprints</dt>
                  <dd className="text-right tabular">{figures.verification?.published_commitments}</dd>
                </div>
                <div className="kv">
                  <dt>Ballots proven at counting</dt>
                  <dd className="text-right tabular">{figures.verification?.counted_ballot_proofs}</dd>
                </div>
              </dl>

              <details className="mt-4 border-t border-rule pt-3">
                <summary className="cursor-pointer text-[12px] font-medium text-ink/55">
                  Material for an independent check
                </summary>
                <dl className="mt-3">
                  <div className="kv">
                    <dt>Signed results hash</dt>
                    <dd className="code max-w-[62%] text-right">{data.signed_payload_hash}</dd>
                  </div>
                  <div className="kv">
                    <dt>Counting evidence hash</dt>
                    <dd className="code max-w-[62%] text-right">
                      {figures.verification?.tally_evidence_hash}
                    </dd>
                  </div>
                  <div className="kv">
                    <dt>Signing key</dt>
                    <dd className="code max-w-[62%] text-right">{data.signing_public_key}</dd>
                  </div>
                </dl>
              </details>

              <div className="mt-5 flex flex-col gap-3 sm:flex-row">
                <a
                  className="btn-primary w-full sm:w-auto"
                  href={`${API_BASE}/api/monitoring/${data.election.id}/result-certificate.pdf`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Download result certificate
                </a>
                <Link href="/verify" className="btn-outline w-full sm:w-auto">
                  Check my ballot
                </Link>
                <Link href="/commitments" className="btn-ghost w-full sm:w-auto">
                  Published record
                </Link>
              </div>
            </Card>
          </div>
        ) : null}
      </div>
    </PublicShell>
  );
}
