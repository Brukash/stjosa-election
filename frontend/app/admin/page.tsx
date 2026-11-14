"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Alert, Card, Loading, SectionHeading, Stat, StatusPill } from "@/components/ui";
import { api, can, formatDate, getProfile, shortHash } from "@/lib/api";

export default function AdminDashboardPage() {
  const profile = getProfile();
  const [elections, setElections] = useState<any[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [overview, setOverview] = useState<any | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api("/api/elections", { auth: true })
      .then((data) => {
        setElections(data.elections);
        const preferred =
          data.elections.find((election: any) => election.status === "voting_open") ??
          data.elections.find((election: any) => !["draft", "archived"].includes(election.status)) ??
          data.elections[0];
        setSelected(preferred?.id ?? "");
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selected) return;
    setOverview(null);
    api(`/api/monitoring/${selected}/overview`, { auth: true })
      .then(setOverview)
      .catch((err) => setError(err.message));
  }, [selected]);

  const maxHourly = useMemo(
    () => Math.max(1, ...(overview?.live?.hourly_ballots ?? []).map((point: any) => point.ballots)),
    [overview]
  );

  if (loading) return <Loading label="Loading election monitoring…" />;
  if (error && !elections.length) return <Alert tone="error">{error}</Alert>;

  if (!elections.length) {
    return (
      <Card className="card-pad">
        <h1 className="font-display text-xl text-ink">No elections configured</h1>
        <p className="mt-2 text-sm text-ink/60">
          Create the first election to begin configuring positions, candidates and the voter register.
        </p>
        <Link href="/admin/elections" className="btn-primary mt-4">
          Go to elections
        </Link>
      </Card>
    );
  }

  const stats = overview?.stats;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-green">Monitoring dashboard</p>
          <h1 className="mt-1 text-2xl text-ink sm:text-3xl">
            {overview?.election?.title ?? "Election monitoring"}
          </h1>
          <p className="mt-1 text-xs text-ink/50">
            {overview
              ? `${overview.election.reference} · ${formatDate(overview.election.opens_at)} → ${formatDate(
                  overview.election.closes_at
                )}`
              : ""}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            className="input !w-auto !py-2 text-sm"
            value={selected}
            onChange={(event) => setSelected(event.target.value)}
            aria-label="Select election"
          >
            {elections.map((election) => (
              <option key={election.id} value={election.id}>
                {election.title}
              </option>
            ))}
          </select>
          {overview ? <StatusPill status={overview.election.status} label={overview.status_label} /> : null}
          {selected ? (
            <Link href={`/admin/elections/${selected}`} className="btn-dark !py-2 text-xs">
              Election workspace
            </Link>
          ) : null}
        </div>
      </div>

      {error ? <Alert tone="error">{error}</Alert> : null}
      {!overview ? <Loading label="Loading monitoring data…" /> : null}

      {overview && stats ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <Stat label="Eligible voters" value={stats.eligible_voters} />
            <Stat label="Accredited" value={stats.accredited_voters} hint={`${stats.accreditation_rate}% of register`} />
            <Stat label="Votes cast" value={stats.votes_cast} hint={`${stats.turnout_percentage}% turnout`} />
            <Stat label="Yet to vote" value={stats.yet_to_vote} />
            <Stat label="Challenged ballots" value={stats.challenged_ballots} hint="excluded from count" />
          </div>

          <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">
            <Card className="card-pad">
              <SectionHeading eyebrow="Live monitoring" title="Ballot submissions, last 24 hours">
                Aggregated hourly activity. Individual voters are never associated with ballots.
              </SectionHeading>
              <div className="flex h-40 items-end gap-[3px]">
                {(overview.live.hourly_ballots ?? []).map((point: any) => (
                  <div key={point.hour} className="group relative flex-1">
                    <div
                      className="w-full rounded-t bg-ink/15 transition group-hover:bg-green"
                      style={{ height: `${Math.max(2, (point.ballots / maxHourly) * 150)}px` }}
                      title={`${new Date(point.hour).toLocaleTimeString("en-GB", {
                        hour: "2-digit",
                        minute: "2-digit",
                      })}: ${point.ballots} ballot(s)`}
                    />
                  </div>
                ))}
              </div>
              <div className="mt-2 flex justify-between text-[10px] text-ink/35">
                <span>24h ago</span>
                <span>now</span>
              </div>
              <div className="mt-5 grid gap-3 sm:grid-cols-3">
                <Stat label="Accreditations (1h)" value={overview.live.accreditations_last_hour} />
                <Stat label="Failed OTP attempts" value={overview.live.failed_otp_attempts} />
                <Stat label="Rejected duplicates" value={overview.live.rejected_duplicate_attempts} />
              </div>
            </Card>

            <div className="space-y-5">
              <Card className="card-pad">
                <SectionHeading eyebrow="Availability" title="Service status" />
                <dl className="space-y-1">
                  {Object.entries(overview.availability).map(([key, value]) => (
                    <div key={key} className="kv">
                      <dt className="capitalize">{key.replace(/_/g, " ")}</dt>
                      <dd className="text-xs">{String(value)}</dd>
                    </div>
                  ))}
                </dl>
              </Card>
              <Card className="card-pad">
                <SectionHeading eyebrow="Security" title="Recent alerts" />
                {overview.live.security_alerts.length === 0 ? (
                  <p className="text-sm text-ink/50">No failed or unauthorised attempts recorded.</p>
                ) : (
                  <ul className="space-y-2">
                    {overview.live.security_alerts.map((alert: any, index: number) => (
                      <li key={index} className="rounded-lg border border-line px-3 py-2 text-xs">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-semibold text-ink">{alert.action}</span>
                          <span className="text-ink/40">{formatDate(alert.at)}</span>
                        </div>
                        <p className="mt-1 text-ink/50">
                          {alert.ip ?? "unknown IP"} · {JSON.stringify(alert.detail ?? {}).slice(0, 120)}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
            </div>
          </div>

          <div className="grid gap-5 lg:grid-cols-2">
            <Card className="card-pad">
              <SectionHeading eyebrow="Counting" title="Counting dashboard" />
              {overview.counting.hidden ? (
                <p className="text-sm text-ink/55">{overview.counting.message}</p>
              ) : (
                <>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Stat label="Accepted ballots" value={overview.counting.accepted_ballots} />
                    <Stat label="Valid ballots" value={overview.counting.valid_ballots} />
                    <Stat label="Invalid ballots" value={overview.counting.invalid_ballots} />
                    <Stat label="Reconciliation" value={overview.counting.reconciliation?.balanced ? "Balanced" : "Pending"} />
                  </div>
                  <div className="mt-4 space-y-1">
                    <div className="kv">
                      <dt>Counting status</dt>
                      <dd className="capitalize">{overview.counting.counting_status}</dd>
                    </div>
                    <div className="kv">
                      <dt>Evidence hash</dt>
                      <dd className="code">{shortHash(overview.counting.evidence_hash, 14)}</dd>
                    </div>
                  </div>
                  {can(profile, "counting.authorise") ? (
                    <Link href={`/admin/elections/${selected}/counting`} className="btn-outline mt-4 w-full">
                      Open counting module
                    </Link>
                  ) : null}
                </>
              )}
            </Card>

            <Card className="card-pad">
              <SectionHeading eyebrow="Verification settings" title="Locked configuration" />
              <dl className="space-y-1">
                {[
                  ["Ballot inclusion verification", overview.verification_settings.ballot_inclusion_enabled],
                  ["Private selection verification", overview.verification_settings.private_selection_enabled],
                  ["Public commitment list", overview.verification_settings.public_commitment_list_enabled],
                  ["PDF voting receipt", overview.verification_settings.pdf_receipt_enabled],
                ].map(([label, enabled]) => (
                  <div key={String(label)} className="kv">
                    <dt>{label}</dt>
                    <dd>
                      <span className={enabled ? "pill-green" : "pill-grey"}>
                        {enabled ? "Enabled" : "Disabled"}
                      </span>
                    </dd>
                  </div>
                ))}
                <div className="kv">
                  <dt>Locked at</dt>
                  <dd className="text-xs">{formatDate(overview.verification_settings.locked_at)}</dd>
                </div>
                <div className="kv">
                  <dt>Results</dt>
                  <dd className="text-xs">
                    {overview.results.declared
                      ? `Declared v${overview.results.version}`
                      : "Not declared"}
                  </dd>
                </div>
              </dl>
              {can(profile, "audit.view") || can(profile, "audit.view_technical") ? (
                <Link href={`/admin/elections/${selected}/audit`} className="btn-outline mt-4 w-full">
                  Audit reports
                </Link>
              ) : null}
            </Card>
          </div>
        </>
      ) : null}
    </div>
  );
}
