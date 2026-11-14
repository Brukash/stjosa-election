"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PublicShell } from "@/components/PublicShell";
import { Alert, Card, Empty, Loading } from "@/components/ui";
import { API_BASE, api, formatDate } from "@/lib/api";

export default function CommitmentsPage() {
  const [data, setData] = useState<any | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api("/api/public/election")
      .then((payload) => {
        if (!payload.election) throw new Error("No election is available");
        return api(`/api/commitments/${payload.election.id}`);
      })
      .then(setData)
      .catch((err) => setError(err.message));
  }, []);

  return (
    <PublicShell>
      <div className="mx-auto max-w-4xl">
        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-green">Election record</p>
        <h1 className="mt-2 text-3xl text-ink">Public anonymous ballot commitments</h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink/60">
          Every accepted ballot produces a unique cryptographic commitment. After voting closes these
          commitments are published in a Merkle tree, digitally signed, and preserved so anyone can
          verify that the published record was not altered. The list contains no voter identity and no
          candidate selections.
        </p>

        {error ? (
          <div className="mt-6">
            <Alert tone="warn">{error}</Alert>
          </div>
        ) : null}
        {!data && !error ? <Loading /> : null}

        {data ? (
          <>
            <Card className="card-pad mt-6">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-ink/45">
                    {data.election.title}
                  </p>
                  <p className="mt-1 text-xs text-ink/50">
                    Reference {data.election.reference} · {data.batches.length} published batch(es)
                  </p>
                </div>
                <Link href="/verify" className="btn-outline">
                  Search by receipt
                </Link>
              </div>
            </Card>

            <div className="mt-5 space-y-4">
              {data.batches.length === 0 ? (
                <Empty title="No commitments published yet">
                  The Electoral Committee publishes the anonymous commitment list after voting closes.
                  Check back then, or verify your receipt at any time.
                </Empty>
              ) : (
                data.batches.map((batch: any) => (
                  <Card key={batch.batch_reference} className="card-pad">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <h2 className="font-display text-lg text-ink">{batch.batch_reference}</h2>
                        <p className="mt-1 text-xs text-ink/50">
                          Published {formatDate(batch.published_at)} · {batch.commitment_count} commitments
                        </p>
                      </div>
                      <span className={batch.signature_verified ? "pill-green" : "pill-red"}>
                        {batch.signature_verified ? "Signature valid" : "Signature invalid"}
                      </span>
                    </div>
                    <dl className="mt-4 space-y-1">
                      <div className="kv">
                        <dt>Merkle root</dt>
                        <dd className="code max-w-[72%] text-right">{batch.merkle_root}</dd>
                      </div>
                      <div className="kv">
                        <dt>Ed25519 signature</dt>
                        <dd className="code max-w-[72%] text-right">{batch.digital_signature}</dd>
                      </div>
                    </dl>
                    <div className="mt-4 flex flex-wrap gap-2">
                      <a
                        href={`${API_BASE}${batch.download_url}`}
                        target="_blank"
                        rel="noreferrer"
                        className="btn-primary"
                      >
                        Download signed list (JSON)
                      </a>
                      <Link href="/verify" className="btn-outline">
                        Verify my commitment
                      </Link>
                    </div>
                  </Card>
                ))
              )}
            </div>

            <p className="mt-6 text-xs leading-relaxed text-ink/45">
              Independent verification: recompute the Merkle root from the downloaded commitments using
              SHA-256 (domain prefixes <span className="font-mono">SJC-LEAF|</span> and{" "}
              <span className="font-mono">SJC-NODE|</span>), then check the Ed25519 signature over the
              canonical JSON header and compare the root. The signing public key is published at{" "}
              <span className="font-mono">/api/crypto/{"{election_id}"}</span>.
            </p>
          </>
        ) : null}
      </div>
    </PublicShell>
  );
}
