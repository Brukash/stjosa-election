"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PublicShell } from "@/components/PublicShell";
import { Alert, Card, Empty, Loading } from "@/components/ui";
import { API_BASE, api, formatLongDate } from "@/lib/api";

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
      <div className="mx-auto max-w-3xl">
        <p className="eyebrow">Election record</p>
        <h1 className="page-title mt-2">
          Published ballot record
        </h1>
        <p className="mt-2 max-w-xl text-[13.5px] leading-relaxed text-ink/65">
          Every accepted ballot is listed here as a random fingerprint. The list holds no names and no
          choices — it exists so anyone can confirm the record was not altered after the fact.
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
                <div className="min-w-0">
                  <p className="eyebrow">{data.election.title}</p>
                  {data.batches.length > 0 ? (
                    <p className="mt-1 text-[12.5px] text-ink/55">
                      {data.batches.length === 1
                        ? "1 published list"
                        : `${data.batches.length} published lists`}
                    </p>
                  ) : null}
                </div>
                <Link href="/verify" className="btn-outline w-full sm:w-auto">
                  Check my receipt
                </Link>
              </div>
            </Card>

            <div className="mt-5 space-y-4">
              {data.batches.length === 0 ? (
                <Empty title="Nothing published yet">
                  The Electoral Committee publishes this list after voting closes. You can check your
                  own receipt at any time.
                </Empty>
              ) : (
                data.batches.map((batch: any) => (
                  <div
                    key={batch.batch_reference}
                    className="rounded-[10px] border border-rule bg-surface shadow-card"
                  >
                    <div className="flex items-start justify-between gap-4 border-b border-rule px-5 py-4">
                      <div className="min-w-0">
                        <p className="font-display text-[18px] leading-tight text-ink">
                          {batch.commitment_count} ballot{batch.commitment_count === 1 ? "" : "s"}
                        </p>
                        <p className="mt-1 text-[12px] text-ink/55">
                          Published {formatLongDate(batch.published_at)} · {batch.batch_reference}
                        </p>
                      </div>
                      <span
                        className={`shrink-0 rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.08em] ${
                          batch.signature_verified
                            ? "border-forest/25 bg-forest/[0.06] text-forest"
                            : "border-clay/40 bg-clay/[0.07] text-clay"
                        }`}
                      >
                        {batch.signature_verified ? "Signature verified" : "Signature failed"}
                      </span>
                    </div>

                    <div className="px-5 py-4">
                      <div className="flex flex-col gap-3 sm:flex-row">
                        <a
                          href={`${API_BASE}${batch.download_url}`}
                          target="_blank"
                          rel="noreferrer"
                          className="btn-primary w-full sm:w-auto"
                        >
                          Download the list
                        </a>
                        <Link href="/verify" className="btn-outline w-full sm:w-auto">
                          Check my ballot in it
                        </Link>
                      </div>

                      <details className="mt-4 border-t border-rule pt-3">
                        <summary className="cursor-pointer text-[12px] font-medium text-ink/55">
                          Material for an independent check
                        </summary>
                        <dl className="mt-3">
                          <div className="kv">
                            <dt>Batch fingerprint (root)</dt>
                            <dd className="code max-w-[60%] text-right">{batch.merkle_root}</dd>
                          </div>
                          <div className="kv">
                            <dt>Batch signature</dt>
                            <dd className="code max-w-[60%] text-right">{batch.digital_signature}</dd>
                          </div>
                        </dl>
                      </details>
                    </div>
                  </div>
                ))
              )}
            </div>

            <details className="mt-6 border-t border-rule pt-3">
              <summary className="cursor-pointer text-[12px] font-medium text-ink/55">
                How to check this record yourself
              </summary>
              <div className="mt-2 space-y-2 text-[12.5px] leading-relaxed text-ink/60">
                <p>
                  Download a list and recompute its fingerprint using SHA-256 with the domain prefixes{" "}
                  <span className="font-mono text-[11.5px]">SJC-LEAF|</span> and{" "}
                  <span className="font-mono text-[11.5px]">SJC-NODE|</span>, then compare it with the
                  batch fingerprint above.
                </p>
                <p>
                  The signature over the list header uses the election signing key, published at{" "}
                  <span className="font-mono text-[11.5px]">/api/crypto/{"{election_id}"}</span>.
                </p>
              </div>
            </details>
          </>
        ) : null}
      </div>
    </PublicShell>
  );
}
