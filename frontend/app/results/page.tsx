"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PublicShell } from "@/components/PublicShell";
import { Alert, Card, Loading, Stat } from "@/components/ui";
import { API_BASE, api, formatDate, shortHash } from "@/lib/api";

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
      <div className="mx-auto max-w-4xl">
        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-green">Official results</p>
        <h1 className="mt-2 text-3xl text-ink">{data?.election?.title ?? "Election results"}</h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink/60">
          Declared results are digitally signed and published together with the counting evidence.
          Anyone can check the signature and the anonymous commitment list without relying on the
          administrator.
        </p>

        {error ? <div className="mt-6"><Alert tone="error">{error}</Alert></div> : null}
        {!data && !error ? <Loading /> : null}

        {data && !data.published ? (
          <div className="mt-6 space-y-4">
            <Alert tone="info">{data.message}</Alert>
            {data.turnout ? (
              <div className="grid gap-3 sm:grid-cols-3">
                <Stat label="Eligible voters" value={data.turnout.eligible_voters} />
                <Stat label="Accredited voters" value={data.turnout.accredited_voters} />
                <Stat label="Ballots cast" value={data.turnout.votes_cast} />
              </div>
            ) : null}
          </div>
        ) : null}

        {data?.published && figures ? (
          <div className="mt-6 space-y-5">
            <Card className="card-pad">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="font-display text-xl text-ink">Declaration</h2>
                  <p className="mt-1 text-xs text-ink/50">
                    Version {data.version} · {formatDate(data.declared_at)} · {data.declared_by}
                  </p>
                </div>
                <span className={data.signature_valid ? "pill-green" : "pill-red"}>
                  {data.signature_valid ? "Signature valid" : "Signature invalid"}
                </span>
              </div>
              {data.correction_reason ? (
                <div className="mt-3">
                  <Alert tone="warn">Corrected declaration: {data.correction_reason}</Alert>
                </div>
              ) : null}
              <div className="mt-5 grid gap-3 sm:grid-cols-3">
                <Stat label="Eligible voters" value={totals.eligible_voters} />
                <Stat label="Accredited voters" value={totals.accredited_voters} />
                <Stat label="Turnout" value={`${totals.turnout_percentage}%`} />
                <Stat label="Votes cast" value={totals.votes_cast} />
                <Stat label="Valid ballots" value={totals.valid_ballots} />
                <Stat label="Invalid ballots" value={totals.invalid_ballots} />
              </div>
              <p className="mt-3 text-xs text-ink/45">
                {totals.challenged_ballots} challenged verification ballot(s) were excluded from the count.
              </p>
            </Card>

            {figures.positions.map((position: any) => (
              <Card key={position.id} className="card-pad">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h3 className="font-display text-lg text-ink">{position.title}</h3>
                  <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-ink/40">
                    {position.seats} seat{position.seats === 1 ? "" : "s"}
                  </span>
                </div>
                <div className="table-wrap mt-3">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Candidate</th>
                        <th className="text-right">Votes</th>
                        <th className="text-right">Share</th>
                        <th>Result</th>
                      </tr>
                    </thead>
                    <tbody>
                      {position.candidates.map((candidate: any) => (
                        <tr key={candidate.id}>
                          <td className="font-medium text-ink">{candidate.full_name}</td>
                          <td className="text-right font-mono">{candidate.votes}</td>
                          <td className="text-right">{candidate.percentage}%</td>
                          <td>
                            {candidate.is_winner ? (
                              <span className="pill-green">Elected{candidate.tie ? " · tie" : ""}</span>
                            ) : (
                              <span className="text-xs text-ink/40">Not elected</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            ))}

            <Card className="card-pad">
              <h3 className="font-display text-lg text-ink">Verification evidence</h3>
              <dl className="mt-3 space-y-1">
                <div className="kv">
                  <dt>Signed payload hash</dt>
                  <dd className="code max-w-[72%] text-right">{data.signed_payload_hash}</dd>
                </div>
                <div className="kv">
                  <dt>Tally evidence hash</dt>
                  <dd className="code max-w-[72%] text-right">
                    {figures.verification?.tally_evidence_hash}
                  </dd>
                </div>
                <div className="kv">
                  <dt>Receipts issued</dt>
                  <dd>{figures.verification?.receipts_issued}</dd>
                </div>
                <div className="kv">
                  <dt>Published commitments</dt>
                  <dd>{figures.verification?.published_commitments}</dd>
                </div>
                <div className="kv">
                  <dt>Counted ballot proofs</dt>
                  <dd>{figures.verification?.counted_ballot_proofs}</dd>
                </div>
                <div className="kv">
                  <dt>Signing public key (Ed25519)</dt>
                  <dd className="font-mono text-[11px]">{shortHash(data.signing_public_key, 16)}</dd>
                </div>
              </dl>
              <div className="mt-5 flex flex-wrap gap-2">
                <a
                  className="btn-primary"
                  href={`${API_BASE}/api/monitoring/${data.election.id}/result-certificate.pdf`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Download result certificate (PDF)
                </a>
                <Link href="/commitments" className="btn-outline">
                  Published commitments
                </Link>
                <Link href="/verify" className="btn-outline">
                  Verify my ballot
                </Link>
              </div>
            </Card>
          </div>
        ) : null}
      </div>
    </PublicShell>
  );
}
