"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Crest, PublicShell } from "@/components/PublicShell";
import { Card, Loading, StatusPill, Alert } from "@/components/ui";
import { api, formatDate } from "@/lib/api";

const FEATURES = [
  {
    title: "Accreditation with your Voter ID",
    body: "Only alumni on the approved electoral register can accredit. Your Voter ID is checked against the register, and only one anonymous credential is issued per voter.",
  },
  {
    title: "Encrypted anonymous ballots",
    body: "Your selections are encrypted to the election's tally key and stored without any voter identifier. Administrators cannot see how you voted.",
  },
  {
    title: "Cast-as-intended verification",
    body: "Before casting, challenge the prepared ballot. The system reveals cryptographic proof that the encryption holds exactly your selections — and that challenged ballot is destroyed.",
  },
  {
    title: "Signed public commitment list",
    body: "After voting closes, every accepted ballot commitment is published in a Merkle tree and digitally signed for independent checking.",
  },
  {
    title: "Verifiable counting",
    body: "The count is performed under dual control with signed evidence and a per-ballot proof that each accepted ballot was included.",
  },
  {
    title: "Authorised declaration",
    body: "Provisional results are submitted by the Returning Officer and only declared after Electoral Committee approval, with a signed certificate.",
  },
];

export default function HomePage() {
  const [data, setData] = useState<any | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api("/api/public/election")
      .then(setData)
      .catch((err) => setError(err.message));
  }, []);

  const election = data?.election;

  return (
    <PublicShell>
      <section className="grid gap-8 rounded-3xl border border-line bg-white p-7 shadow-card sm:p-10 lg:grid-cols-[1.15fr_0.85fr]">
        <div>
          <div className="flex items-center gap-3">
            <Crest size={54} />
            <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-green">
              Alumni Association · Electoral Committee
            </p>
          </div>
          <h1 className="mt-3 text-3xl leading-tight text-ink sm:text-[42px]">
            One alumnus. One vote. <span className="text-green">Independently verifiable.</span>
          </h1>
          <p className="mt-4 max-w-xl text-[15px] leading-relaxed text-ink/65">
            The official remote electronic voting platform for the St. John&apos;s College Jos Alumni
            Association. Cast your ballot from anywhere, then verify that it was recorded, appears in
            the published election record, and was included in the final count.
          </p>
          <div className="mt-7 flex flex-wrap gap-3">
            <Link href="/accredit" className="btn-primary">
              Accredit and vote
            </Link>
            <Link href="/verify" className="btn-outline">
              Verify my ballot
            </Link>
          </div>
          <p className="mt-4 text-xs text-ink/45">
            You will need the Voter ID sent to the email address on your approved registration.
          </p>
        </div>

        <div className="rounded-2xl border border-line bg-cream/70 p-5">
          {error ? <Alert tone="error">{error}</Alert> : null}
          {!data && !error ? <Loading /> : null}
          {election ? (
            <div className="space-y-4">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-ink/45">
                  Current election
                </span>
                <StatusPill status={election.status} label={data.status_label} />
              </div>
              <div>
                <h2 className="text-lg leading-snug text-ink">{election.title}</h2>
                <p className="mt-1 text-xs text-ink/50">
                  Reference {election.reference} · {election.year}
                </p>
              </div>
              <dl className="space-y-2 text-sm">
                <div className="kv">
                  <dt>Voting opens</dt>
                  <dd>{formatDate(election.opens_at)}</dd>
                </div>
                <div className="kv">
                  <dt>Voting closes</dt>
                  <dd>{formatDate(election.closes_at)}</dd>
                </div>
                <div className="kv">
                  <dt>Positions</dt>
                  <dd>{election.positions?.length ?? 0}</dd>
                </div>
                <div className="kv">
                  <dt>Verification</dt>
                  <dd className="text-right text-xs text-green">All four controls enabled</dd>
                </div>
              </dl>
              <div className="flex gap-2">
                {election.verification?.private_selection_enabled ? (
                  <span className="pill-green">Challenge verification</span>
                ) : null}
                {election.verification?.ballot_inclusion_enabled ? (
                  <span className="pill-green">Inclusion check</span>
                ) : null}
              </div>
            </div>
          ) : null}
        </div>
      </section>

      <section className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {FEATURES.map((feature) => (
          <Card key={feature.title} className="card-pad">
            <h3 className="text-[15px] font-semibold text-ink">{feature.title}</h3>
            <p className="mt-2 text-sm leading-relaxed text-ink/60">{feature.body}</p>
          </Card>
        ))}
      </section>

      <section className="mt-10 grid gap-4 lg:grid-cols-3">
        <Card className="card-pad lg:col-span-2">
          <h3 className="font-display text-lg text-ink">How voting works</h3>
          <ol className="mt-4 grid gap-3 sm:grid-cols-2">
            {[
              ["1", "Verify your identity", "Enter your Voter ID. We check it against the approved register; no OTP is required."],
              ["2", "Receive your anonymous credential", "Your browser blinds a secret token; the system signs it without seeing it."],
              ["3", "Review and verify your ballot", "Check your selections, optionally challenge the encryption, then cast."],
              ["4", "Keep your receipt and verify", "Use the receipt reference or QR code to confirm inclusion any time."],
            ].map(([step, title, body]) => (
              <li key={step} className="flex gap-3">
                <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-ink text-xs font-bold text-white">
                  {step}
                </span>
                <span>
                  <span className="block text-sm font-semibold text-ink">{title}</span>
                  <span className="mt-0.5 block text-[13px] leading-relaxed text-ink/55">{body}</span>
                </span>
              </li>
            ))}
          </ol>
        </Card>
        <Card className="card-pad">
          <h3 className="font-display text-lg text-ink">Election integrity</h3>
          <p className="mt-2 text-sm leading-relaxed text-ink/60">
            Verification settings are locked as soon as the first ballot is accepted. Administrators
            cannot disable verification, alter a submitted ballot, or declare a result without
            authorised approval.
          </p>
          <div className="mt-5 space-y-2 text-xs text-ink/50">
            <p className="font-mono">SHA-256 commitments · RSA blind credentials</p>
            <p className="font-mono">AES-256-GCM ballots · Ed25519 signed records</p>
          </div>
          <Link href="/results" className="btn-outline mt-5 w-full">
            View declared results
          </Link>
        </Card>
      </section>
    </PublicShell>
  );
}
