"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PublicShell } from "@/components/PublicShell";
import { Alert, Loading, StatusPill } from "@/components/ui";
import { api, formatLongDate } from "@/lib/api";

type Position = { id: string; title: string; seats?: number };
type Election = {
  id: string;
  title: string;
  reference: string;
  year: number;
  status: string;
  closes_at: string;
  opens_at: string;
  can_vote?: boolean;
  can_accredit?: boolean;
  positions?: Position[];
};

const STEPS = [
  {
    n: "01",
    title: "Find your Voter ID",
    body: "It is in the email the Electoral Committee sent when your registration was approved. It looks like SJC/AL/2004/001.",
  },
  {
    n: "02",
    title: "Mark your ballot",
    body: "Choose one candidate for each position. You will see a summary of your choices before anything is submitted.",
  },
  {
    n: "03",
    title: "Keep your receipt",
    body: "A reference number is issued when your ballot is accepted, and a confirmation is emailed to you. Use either to check your ballot was recorded.",
  },
];

function seatLabel(seats?: number) {
  return seats && seats > 1 ? `${seats} seats` : "1 seat";
}

function BallotCard({ election, statusLabel }: { election: Election; statusLabel?: string }) {
  const positions = election.positions ?? [];
  const shown = positions.slice(0, 6);
  const extra = positions.length - shown.length;

  return (
    <div className="ballot-enter relative">
      <p className="absolute -top-3 left-5 z-10 rounded-[3px] bg-ochre px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-white">
        Official ballot
      </p>

      <div className="rounded-[10px] border border-rule bg-surface p-5 shadow-ballot sm:p-7">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="eyebrow">St. John&apos;s College Jos</p>
            <h2 className="mt-1.5 font-display text-[22px] leading-tight text-ink sm:text-[25px]">
              {election.title}
            </h2>
          </div>
          <span
            aria-hidden="true"
            className="stamp hidden shrink-0 -rotate-6 rounded-[3px] border-2 border-ochre/70 px-2 py-1 text-[9px] font-bold uppercase tracking-[0.14em] text-ochre sm:block"
          >
            {statusLabel ?? "Voting open"}
          </span>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 text-[12px] text-ink/60">
          <span>Closes {formatLongDate(election.closes_at)}</span>
          <span aria-hidden="true" className="text-ink/25">/</span>
          <span className="tabular">{positions.length} positions</span>
          <span className="basis-full pt-1 sm:hidden">
            <StatusPill status={election.status} label={statusLabel} />
          </span>
        </div>

        <ol className="mt-4 divide-y divide-rule/80 border-t border-dashed border-rule">
          {shown.length === 0 ? (
            <li className="py-3 text-[13px] text-ink/55">
              The list of positions is published here once the committee opens the ballot.
            </li>
          ) : (
            shown.map((position, index) => (
              <li key={position.id} className="flex items-baseline gap-3 py-2.5">
                <span className="tabular w-6 shrink-0 text-[11px] font-semibold text-ochre">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span className="min-w-0 flex-1 text-[14px] leading-snug text-ink">{position.title}</span>
                <span className="shrink-0 text-[11px] text-ink/45">{seatLabel(position.seats)}</span>
              </li>
            ))
          )}
        </ol>

        {extra > 0 ? (
          <p className="mt-3 text-[11px] text-ink/50">and {extra} more on your ballot</p>
        ) : null}

        <p className="mt-5 border-t border-rule pt-3 text-[10px] uppercase tracking-[0.14em] text-ink/45">
          One vote per position
        </p>
      </div>
    </div>
  );
}

export default function HomePage() {
  const [data, setData] = useState<any | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api("/api/public/election")
      .then(setData)
      .catch((err) => setError(err.message));
  }, []);

  const election: Election | undefined = data?.election;
  // Once the ballot is closed the hero must not invite a vote in it.
  const ballotOpen = Boolean(election?.can_vote || election?.can_accredit);

  return (
    <PublicShell>
      {/* Hero */}
      <section className="grid items-start gap-10 lg:grid-cols-[1.02fr_0.98fr] lg:gap-12">
        <div className="enter">
          <p className="eyebrow">St. John&apos;s College Jos Alumni Association</p>
          <h1 className="mt-3 font-display text-[36px] leading-[1.04] tracking-[-0.01em] text-ink sm:text-[46px] lg:text-[56px]">
            Vote for your alumni executives,{" "}
            <em className="mt-1 block italic text-forest">from wherever you are.</em>
          </h1>
          <p className="measure mt-5 text-[15px] leading-relaxed text-ink/75 sm:text-[16px]">
            This is the official ballot of the St. John&apos;s College Jos Alumni Association. Enter the
            Voter ID we emailed you, mark your choices, and submit. Afterwards you can confirm that your
            ballot was recorded and included in the count.
          </p>

          <div className="mt-7 flex flex-col gap-3 sm:flex-row sm:items-center">
            {data && !ballotOpen ? (
              <Link href="/results" className="btn-primary w-full sm:w-auto">
                Read the declared results
              </Link>
            ) : (
              <Link href="/accredit" className="btn-primary w-full sm:w-auto">
                Start voting
              </Link>
            )}
            <Link href="/verify" className="btn-outline w-full sm:w-auto">
              Check my ballot
            </Link>
          </div>

          <p className="mt-4 text-[12.5px] leading-relaxed text-ink/55">
            Your Voter ID is in the email from the Electoral Committee. You do not need a password.
          </p>

          {error ? (
            <div className="mt-6">
              <Alert tone="error">
                We could not load the election just now. {error}
              </Alert>
            </div>
          ) : null}
        </div>

        <div>
          {!data && !error ? (
            <div className="rounded-[10px] border border-rule bg-surface p-6">
              <Loading label="Loading the ballot…" />
            </div>
          ) : null}

          {election ? <BallotCard election={election} statusLabel={data?.status_label} /> : null}

          {data && !election ? (
            <div className="rounded-[10px] border border-rule bg-surface p-6">
              <StatusPill status="voting_closed" label="Ballot closed" />
              <p className="mt-3 font-display text-[20px] leading-snug text-ink">
                No election is open at the moment.
              </p>
              <p className="mt-2 text-[13.5px] leading-relaxed text-ink/65">
                When the committee opens the next ballot, it will appear here with its closing date.
                Declared results from previous elections stay available.
              </p>
              <Link href="/results" className="btn-outline mt-4 w-full sm:w-auto">
                Read declared results
              </Link>
            </div>
          ) : null}
        </div>
      </section>

      {/* What you need */}
      <section className="reveal mt-14 border-y border-rule py-5">
        <ul className="grid gap-4 text-[13px] text-ink/70 sm:grid-cols-3 sm:gap-0 sm:divide-x sm:divide-rule">
          <li className="sm:px-5 sm:first:pl-0">
            <span className="block text-[10px] font-semibold uppercase tracking-[0.16em] text-ochre">
              You need
            </span>
            <span className="mt-1 block text-ink">The Voter ID sent to your email</span>
          </li>
          <li className="sm:px-5">
            <span className="block text-[10px] font-semibold uppercase tracking-[0.16em] text-ochre">
              It takes
            </span>
            <span className="mt-1 block text-ink">About five minutes</span>
          </li>
          <li className="sm:px-5">
            <span className="block text-[10px] font-semibold uppercase tracking-[0.16em] text-ochre">
              Works on
            </span>
            <span className="mt-1 block text-ink">Any phone, tablet or computer</span>
          </li>
        </ul>
      </section>

      {/* How it works */}
      <section className="reveal mt-14">
        <div className="max-w-xl">
          <p className="eyebrow">How it works</p>
          <h2 className="mt-2 text-balance font-display text-[28px] leading-tight text-ink sm:text-[34px]">
            Three steps, one ballot.
          </h2>
        </div>

        <ol className="mt-8 grid gap-8 sm:grid-cols-3 sm:gap-6">
          {STEPS.map((step) => (
            <li key={step.n} className="border-t border-ink/15 pt-4">
              <span className="tabular block font-display text-[30px] leading-none text-ochre">
                {step.n}
              </span>
              <h3 className="mt-3 text-[16px] font-semibold text-ink">{step.title}</h3>
              <p className="mt-1.5 text-[13.5px] leading-relaxed text-ink/65">{step.body}</p>
            </li>
          ))}
        </ol>
      </section>

      {/* Secrecy */}
      <section className="reveal mt-16 grid gap-8 border-t border-rule pt-10 lg:grid-cols-[0.9fr_1.1fr] lg:gap-12">
        <h2 className="text-balance font-display text-[28px] leading-tight text-ink sm:text-[34px]">
          Your name is checked once. Your ballot is never attached to it.
        </h2>
        <div className="space-y-4 text-[14.5px] leading-relaxed text-ink/75">
          <p>
            The register confirms that you are an eligible alumnus and that you have not voted yet.
            After that check, the ballot you submit carries no name, email or Voter ID. The system
            records that one alumnus voted and stores the choices, but nothing joins the two.
          </p>
          <p>
            The committee can see turnout. It cannot see how you voted, and no official can edit a
            ballot after it is submitted.
          </p>
          <Link
            href="/commitments"
            className="link-rule inline-flex items-center gap-1.5 text-[13.5px] font-semibold text-forest hover:text-greenlight"
          >
            See the public ballot record
            <span aria-hidden="true">→</span>
          </Link>
        </div>
      </section>

      {/* Closing */}
      <section className="reveal mt-16 border-t border-rule pt-10">
        <div className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="eyebrow">Ready when you are</p>
            <p className="mt-2 max-w-md font-display text-[26px] leading-tight text-ink sm:text-[30px]">
              {election
                ? `Voting closes ${formatLongDate(election.closes_at)}.`
                : "The ballot opens when the committee says so."}
            </p>
          </div>
          <Link
            href={data && !ballotOpen ? "/results" : "/accredit"}
            className="btn-primary w-full sm:w-auto"
          >
            {data && !ballotOpen ? "Read the declared results" : "Start voting"}
          </Link>
        </div>
      </section>
    </PublicShell>
  );
}
