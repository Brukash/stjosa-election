"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { PublicShell } from "@/components/PublicShell";
import { Alert, Card, Loading } from "@/components/ui";
import { API_BASE, api, formatDate } from "@/lib/api";

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
      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-green">Voting receipt</p>
      <h1 className="mt-2 text-3xl text-ink">Electronic ballot receipt</h1>

      {!reference ? (
        <div className="mt-6">
          <Alert tone="info">
            Enter your reference on the verification portal to open a receipt, or use the QR code on
            your downloaded PDF receipt.
          </Alert>
          <Link href="/verify" className="btn-primary mt-4">
            Go to verification portal
          </Link>
        </div>
      ) : null}

      {error ? <div className="mt-6"><Alert tone="error">{error}</Alert></div> : null}
      {!receipt && !error && reference ? <Loading /> : null}

      {receipt ? (
        <Card className="card-pad mt-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-ink/45">
                {receipt.election.title}
              </p>
              <h2 className="mt-1 font-display text-xl text-ink">{receipt.receipt_number}</h2>
            </div>
            <span className="pill-green">Ballot accepted</span>
          </div>

          <dl className="mt-5 space-y-1">
            <div className="kv">
              <dt>Election reference</dt>
              <dd className="font-mono text-xs">{receipt.election.reference}</dd>
            </div>
            <div className="kv">
              <dt>Verification reference</dt>
              <dd className="font-mono text-sm font-bold">{receipt.receipt_reference}</dd>
            </div>
            <div className="kv">
              <dt>Submitted</dt>
              <dd>{formatDate(receipt.issued_at)}</dd>
            </div>
            <div className="kv">
              <dt>Ballot commitment</dt>
              <dd className="code max-w-[70%] text-right">{receipt.ballot_commitment}</dd>
            </div>
          </dl>

          <Alert tone="info">{receipt.note}</Alert>

          <div className="mt-5 flex flex-wrap gap-2">
            <a
              className="btn-primary"
              href={`${API_BASE}/api/receipts/${encodeURIComponent(receipt.receipt_reference)}/pdf`}
              target="_blank"
              rel="noreferrer"
            >
              Download PDF
            </a>
            <Link
              className="btn-outline"
              href={`/verify?ref=${encodeURIComponent(receipt.receipt_reference)}`}
            >
              Verify inclusion
            </Link>
          </div>
        </Card>
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
