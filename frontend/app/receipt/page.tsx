"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { PublicShell } from "@/components/PublicShell";
import { Alert, Loading } from "@/components/ui";
import { API_BASE, api, formatLongDate } from "@/lib/api";

function ReceiptInner() {
  const params = useSearchParams();
  const reference = params.get("ref") ?? "";
  const [receipt, setReceipt] = useState<any | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!reference) return;
    api(`/api/receipts/${encodeURIComponent(reference)}`)
      .then(setReceipt)
      .catch((err) => setError(err.message));
  }, [reference]);

  return (
    <div className="mx-auto max-w-2xl">
      <p className="eyebrow">Voting receipt</p>
      <h1 className="page-title mt-2">
        Your ballot receipt
      </h1>

      {!reference ? (
        <div className="mt-6">
          <Alert tone="info">
            Open this page from the reference on your receipt, or from the QR code on your downloaded
            PDF.
          </Alert>
          <Link href="/verify" className="btn-primary mt-4 w-full sm:w-auto">
            Check a ballot instead
          </Link>
        </div>
      ) : null}

      {error ? <div className="mt-6"><Alert tone="error">{error}</Alert></div> : null}
      {!receipt && !error && reference ? <Loading /> : null}

      {receipt ? (
        <div className="mt-6 animate-rise">
          <div className="rounded-[10px] border border-rule bg-surface shadow-ballot">
            <div className="flex items-start justify-between gap-4 border-b border-rule px-5 py-5 sm:px-6">
              <div className="min-w-0">
                <p className="eyebrow">{receipt.election.title}</p>
                <p className="mt-1.5 font-display text-[24px] leading-tight text-ink">
                  {receipt.receipt_number}
                </p>
                <p className="mt-1 text-[12.5px] text-ink/55">
                  Submitted {formatLongDate(receipt.issued_at)}
                </p>
              </div>
              <span
                aria-hidden="true"
                className="hidden shrink-0 -rotate-6 rounded-[3px] border-2 border-forest/60 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-[0.14em] text-forest sm:block"
              >
                Accepted
              </span>
            </div>

            <div className="px-5 py-5 sm:px-6">
              <dl>
                <div className="kv">
                  <dt>Election</dt>
                  <dd className="text-right text-[13px]">{receipt.election.reference}</dd>
                </div>
                <div className="kv">
                  <dt>Reference for checking</dt>
                  <dd className="tabular break-all text-right text-[13px]">
                    {receipt.receipt_reference}
                  </dd>
                </div>
                <div className="kv">
                  <dt>Ballot fingerprint</dt>
                  <dd className="code max-w-[62%] text-right">{receipt.ballot_commitment}</dd>
                </div>
              </dl>

              <div className="mt-4">
                <Alert tone="info">{receipt.note}</Alert>
              </div>

              <div className="mt-5 flex flex-col gap-3 sm:flex-row">
                <a
                  className="btn-primary w-full sm:w-auto"
                  href={`${API_BASE}/api/receipts/${encodeURIComponent(receipt.receipt_reference)}/pdf`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Download PDF
                </a>
                <Link
                  className="btn-outline w-full sm:w-auto"
                  href={`/verify?ref=${encodeURIComponent(receipt.receipt_reference)}`}
                >
                  Check this ballot
                </Link>
              </div>
            </div>
          </div>

          <p className="mt-4 text-[12px] leading-relaxed text-ink/50">
            Keep this receipt. It proves your ballot was accepted without revealing your choices.
          </p>
        </div>
      ) : null}
    </div>
  );
}

export default function ReceiptPage() {
  return (
    <PublicShell>
      <Suspense fallback={<Loading />}>
        <ReceiptInner />
      </Suspense>
    </PublicShell>
  );
}
