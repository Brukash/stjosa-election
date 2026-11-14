"use client";

import Link from "next/link";
import { ReactNode } from "react";

export function StatusPill({ status, label }: { status: string; label?: string }) {
  const tone =
    status === "voting_open" || status === "declared"
      ? "pill-green"
      : status === "accreditation_open" || status === "under_review"
      ? "pill-gold"
      : status === "voting_closed" || status === "counting"
      ? "pill-grey"
      : "pill-grey";
  return <span className={tone}>{label ?? status.replace(/_/g, " ")}</span>;
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`card ${className}`}>{children}</div>;
}

export function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
}) {
  return (
    <div className="rounded-xl border border-line bg-white px-4 py-3.5">
      <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-ink/45">{label}</p>
      <p className="mt-1 font-display text-2xl text-ink">{value}</p>
      {hint ? <p className="mt-0.5 text-[11px] text-ink/45">{hint}</p> : null}
    </div>
  );
}

export function CheckRow({ passed, children }: { passed: boolean; children: ReactNode }) {
  return (
    <div className="flex items-start gap-3 border-b border-line/70 py-2.5 last:border-0">
      <span
        className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold ${
          passed ? "bg-green/12 text-green" : "bg-red-100 text-red-700"
        }`}
      >
        {passed ? "✓" : "✕"}
      </span>
      <span className="text-sm text-ink/80">{children}</span>
    </div>
  );
}

export function SectionHeading({
  eyebrow,
  title,
  children,
}: {
  eyebrow?: string;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="mb-5">
      {eyebrow ? (
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-green">{eyebrow}</p>
      ) : null}
      <h2 className="mt-1 text-xl text-ink sm:text-2xl">{title}</h2>
      {children ? <div className="mt-1.5 max-w-2xl text-sm text-ink/60">{children}</div> : null}
    </div>
  );
}

export function Alert({
  tone = "info",
  children,
}: {
  tone?: "info" | "error" | "success" | "warn";
  children: ReactNode;
}) {
  const tones: Record<string, string> = {
    info: "border-ink/10 bg-ink/[0.03] text-ink/75",
    error: "border-red-200 bg-red-50 text-red-800",
    success: "border-green/20 bg-green/[0.06] text-green",
    warn: "border-gold/40 bg-gold/[0.12] text-[#5C4A00]",
  };
  return (
    <div className={`rounded-xl border px-4 py-3 text-sm leading-relaxed ${tones[tone]}`}>{children}</div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <div className="py-16 text-center text-sm text-ink/45">{label}</div>;
}

export function NotAuthorized({
  roleNames = [],
  backHref = "/admin",
}: {
  roleNames?: string[];
  backHref?: string;
}) {
  return (
    <div className="mx-auto max-w-xl py-12">
      <Card className="card-pad text-center">
        <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-ink/[0.04] text-xl text-ink/45">
          ⛨
        </span>
        <h1 className="mt-4 font-display text-2xl text-ink">Not available for your role</h1>
        <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-ink/60">
          {roleNames.length
            ? `${roleNames.join(" · ")} does not have access to this page.`
            : "Your account does not have access to this page."}{" "}
          The page is hidden from your workspace, and the server enforces the same restriction.
        </p>
        <LinkButton href={backHref} variant="dark">
          Back to my workspace
        </LinkButton>
      </Card>
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-line px-6 py-10 text-center">
      <p className="font-display text-lg text-ink/70">{title}</p>
      {children ? <div className="mx-auto mt-2 max-w-md text-sm text-ink/50">{children}</div> : null}
    </div>
  );
}

export function LinkButton({
  href,
  children,
  variant = "primary",
}: {
  href: string;
  children: ReactNode;
  variant?: "primary" | "dark" | "outline";
}) {
  const cls =
    variant === "primary" ? "btn-primary" : variant === "dark" ? "btn-dark" : "btn-outline";
  return (
    <Link href={href} className={cls}>
      {children}
    </Link>
  );
}
