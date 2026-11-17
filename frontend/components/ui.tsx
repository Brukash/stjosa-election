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
    <div className="rounded-[8px] border border-rule bg-surface px-4 py-3.5">
      <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-ink/45">{label}</p>
      <p className="mt-1 font-display text-[24px] leading-none tabular text-ink">{value}</p>
      {hint ? <p className="mt-1 text-[11px] text-ink/45">{hint}</p> : null}
    </div>
  );
}

export function CheckRow({ passed, children }: { passed: boolean; children: ReactNode }) {
  return (
    <div className="flex items-start gap-3 border-b border-rule/70 py-2.5 last:border-0">
      <span
        aria-hidden="true"
        className={`mt-0.5 flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${
          passed ? "bg-forest/10 text-forest" : "bg-clay/10 text-clay"
        }`}
      >
        {passed ? "✓" : "✕"}
      </span>
      <span className="text-[13.5px] leading-relaxed text-ink/80">{children}</span>
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
      {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
      <h2 className="mt-1.5 font-display text-[21px] leading-snug text-ink sm:text-[24px]">{title}</h2>
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
    info: "border-rule bg-ink/[0.03] text-ink/75",
    error: "border-clay/40 bg-clay/[0.07] text-[#7A2E1E]",
    success: "border-forest/25 bg-forest/[0.06] text-forest",
    warn: "border-ochre/40 bg-ochre/[0.09] text-[#6B4611]",
  };
  return (
    <div className={`rounded-[6px] border px-4 py-3 text-[13.5px] leading-relaxed ${tones[tone]}`}>
      {children}
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <div className="py-16 text-center text-[13px] text-ink/45">{label}</div>;
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
    <div className="rounded-[10px] border border-dashed border-rule px-6 py-10 text-center">
      <p className="font-display text-[18px] text-ink/75">{title}</p>
      {children ? (
        <div className="mx-auto mt-2 max-w-md text-[13px] leading-relaxed text-ink/55">{children}</div>
      ) : null}
    </div>
  );
}

function LinkButton({
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
