"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Alert, Loading, StatusPill } from "@/components/ui";
import { api, can, ELECTION_UPDATED_EVENT, getProfile } from "@/lib/api";

const TABS = [
  { segment: "", label: "Setup & verification", permissions: ["election.view"] },
  { segment: "/register", label: "Voter register", permissions: ["register.view"] },
  { segment: "/ballot", label: "Positions & candidates", permissions: ["election.view"] },
  { segment: "/counting", label: "Counting", permissions: ["counting.authorise"] },
  { segment: "/results", label: "Results", permissions: ["results.review", "results.review_restricted"] },
  { segment: "/audit", label: "Audit", permissions: ["audit.view", "audit.view_technical"] },
];

export default function ElectionWorkspaceLayout({ children }: { children: React.ReactNode }) {
  const params = useParams<{ id: string }>();
  const pathname = usePathname();
  const id = params?.id;
  const profile = getProfile();
  const [election, setElection] = useState<any | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!id) return;
    const refresh = () =>
      api(`/api/elections/${id}`, { auth: true })
        .then(setElection)
        .catch((err) => setError(err.message));
    refresh();
    // Pages inside the workspace report successful actions, so the header
    // status and configuration hash follow along without a full reload.
    window.addEventListener(ELECTION_UPDATED_EVENT, refresh);
    return () => window.removeEventListener(ELECTION_UPDATED_EVENT, refresh);
  }, [id]);

  if (error) return <Alert tone="error">{error}</Alert>;
  if (!election) return <Loading label="Loading election workspace…" />;

  const base = `/admin/elections/${id}`;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Link href="/admin/elections" className="text-xs font-semibold text-ink/45 hover:text-ink">
            ← All elections
          </Link>
          <h1 className="mt-1 font-display text-2xl leading-snug text-ink">{election.title}</h1>
          <p className="mt-1 text-xs text-ink/50">
            {election.reference} · {election.year} · configuration hash{" "}
            <span className="font-mono">{election.configuration_hash?.slice(0, 16) ?? "not approved"}</span>
          </p>
        </div>
        <div className="flex items-center gap-2">
          {election.locked_at ? <span className="pill-gold">Configuration locked</span> : null}
          <StatusPill status={election.status} label={election.status_label} />
        </div>
      </div>

      <nav className="flex flex-wrap gap-1 border-b border-rule pb-1">
        {TABS.filter((tab) => tab.permissions.some((permission) => can(profile, permission))).map((tab) => {
          const href = `${base}${tab.segment}`;
          const active = tab.segment === "" ? pathname === base : pathname === href;
          return (
            <Link
              key={tab.label}
              href={href}
              className={`whitespace-nowrap rounded-t-lg px-2.5 py-2 text-[12.5px] font-medium transition sm:px-3 sm:text-[13px] ${
                active ? "bg-white text-ink shadow-sm" : "text-ink/50 hover:text-ink"
              }`}
            >
              {tab.label}
            </Link>
          );
        })}
      </nav>

      {children}
    </div>
  );
}
