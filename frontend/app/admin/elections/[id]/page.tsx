"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Alert, Card, Loading, SectionHeading, Stat } from "@/components/ui";
import {
  api,
  can,
  formatDate,
  fromDateTimeInput,
  getProfile,
  shortHash,
  toDateTimeInput,
} from "@/lib/api";

const SETTINGS_FIELDS = [
  ["ballot_inclusion_enabled", "Ballot inclusion verification", "Voters confirm their ballot is in the published record."],
  ["private_selection_enabled", "Private selection verification", "Voters can challenge a prepared ballot before casting."],
  ["public_commitment_list_enabled", "Public commitment list", "Publish signed anonymous commitments after closure."],
  ["pdf_receipt_enabled", "PDF voting receipt", "Download an electronic receipt with QR verification."],
] as const;

const LIFECYCLE_ACTIONS: Record<string, { status: string; label: string }[]> = {
  draft: [],
  configured: [],
  approved: [{ status: "accreditation_open", label: "Open accreditation" }],
  accreditation_open: [{ status: "voting_open", label: "Open voting" }],
  voting_open: [{ status: "voting_closed", label: "Close voting" }],
  voting_closed: [],
  counting: [],
  provisional_results: [],
  under_review: [],
  declared: [{ status: "archived", label: "Archive election" }],
  archived: [],
};

export default function ElectionSetupPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const profile = getProfile();
  const [election, setElection] = useState<any | null>(null);
  const [form, setForm] = useState<any>({});
  const [settings, setSettings] = useState<any>({});
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [changeReason, setChangeReason] = useState("");
  const [changeCloses, setChangeCloses] = useState("");

  function load() {
    api(`/api/elections/${id}`, { auth: true })
      .then((data) => {
        setElection(data);
        setForm({
          title: data.title,
          description: data.description,
          opens_at: toDateTimeInput(data.opens_at),
          closes_at: toDateTimeInput(data.closes_at),
          timezone: data.timezone,
          eligibility_rules: data.eligibility_rules,
          voting_rules: data.voting_rules,
        });
        setSettings({
          ballot_inclusion_enabled: data.verification.ballot_inclusion_enabled,
          private_selection_enabled: data.verification.private_selection_enabled,
          public_commitment_list_enabled: data.verification.public_commitment_list_enabled,
          pdf_receipt_enabled: data.verification.pdf_receipt_enabled,
        });
      })
      .catch((err) => setError(err.message));
  }

  useEffect(load, [id]);

  async function saveDetails(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api(`/api/elections/${id}`, {
        method: "PATCH",
        auth: true,
        body: JSON.stringify({
          title: form.title,
          description: form.description,
          opens_at: fromDateTimeInput(form.opens_at),
          closes_at: fromDateTimeInput(form.closes_at),
          timezone: form.timezone,
          eligibility_rules: form.eligibility_rules,
          voting_rules: form.voting_rules,
        }),
      });
      setNotice("Election details saved and configuration hash recomputed.");
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function saveSettings() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api(`/api/elections/${id}/verification-settings`, {
        method: "PUT",
        auth: true,
        body: JSON.stringify(settings),
      });
      setNotice("Verification settings saved. A different authorised official must approve them before voting can open.");
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function approveSettings() {
    setBusy(true);
    try {
      await api(`/api/elections/${id}/verification-settings/approve`, { method: "POST", auth: true });
      setNotice("Verification settings approved. They are now locked in for this election.");
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function approveConfiguration() {
    setBusy(true);
    try {
      const data = await api(`/api/elections/${id}/configuration/approve`, {
        method: "POST",
        auth: true,
      });
      setNotice(data.message);
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function transition(status: string) {
    setBusy(true);
    try {
      await api(`/api/elections/${id}/status`, {
        method: "POST",
        auth: true,
        body: JSON.stringify({ status }),
      });
      setNotice(`Election status changed to ${status.replace(/_/g, " ")}.`);
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function requestChange(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      const changes = changeCloses
        ? { closes_at: fromDateTimeInput(changeCloses) }
        : {};
      await api(`/api/elections/${id}/changes`, {
        method: "POST",
        auth: true,
        body: JSON.stringify({ changes, reason: changeReason }),
      });
      setNotice("Exceptional change recorded. A second authorised official must approve it.");
      setChangeReason("");
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function approveChange(changeId: string) {
    setBusy(true);
    try {
      await api(`/api/elections/changes/${changeId}/approve`, { method: "POST", auth: true });
      setNotice("Change approved and applied with a new configuration hash.");
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (!election) return <Loading label="Loading configuration…" />;

  const locked = Boolean(election.locked_at) || ["voting_closed", "counting", "provisional_results", "under_review", "declared", "archived"].includes(election.status);
  const approvals = election.configuration_approvals ?? [];
  const approvalRoles = new Set(approvals.map((approval: any) => approval.approver_role));
  const myRoles = new Set<string>(profile?.roles ?? []);
  const canEdit = can(profile, "election.edit");
  const canConfigure = can(profile, "verification.configure");
  const canApproveSettings =
    can(profile, "verification.approve") &&
    election.verification.configured_by !== profile?.id;
  const myApprovalRole = myRoles.has("chairman")
    ? "chairman"
    : myRoles.has("returning_officer")
    ? "returning_officer"
    : null;
  const canRecordConfigurationApproval =
    Boolean(myApprovalRole) &&
    !approvalRoles.has(myApprovalRole as string) &&
    ["draft", "configured", "approved"].includes(election.status);
  const canRequestChange = can(profile, "verification.approve");
  const lifecycleActions = (LIFECYCLE_ACTIONS[election.status] ?? []).filter((action) =>
    action.status === "voting_closed"
      ? myRoles.has("chairman") || myRoles.has("returning_officer")
      : myRoles.has("chairman")
  );

  return (
    <div className="space-y-5">
      {error ? <Alert tone="error">{error}</Alert> : null}
      {notice ? <Alert tone="success">{notice}</Alert> : null}
      {!canEdit ? (
        <Alert tone="info">
          Read-only configuration view. Your role can inspect election details and verification
          settings, but cannot edit them.
        </Alert>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-4">
        <Stat label="Eligible voters" value={election.totals.eligible_voters} />
        <Stat label="Accredited" value={election.totals.accredited_voters} />
        <Stat label="Votes cast" value={election.totals.votes_cast} />
        <Stat label="Turnout" value={`${election.totals.turnout_percentage}%`} />
      </div>

      <div className="grid gap-5 lg:grid-cols-[1.25fr_0.75fr]">
        <Card className="card-pad">
          <SectionHeading eyebrow="Election details" title="Configuration">
            {!canEdit
              ? "Read-only view of the configuration covered by the election hash."
              : locked
              ? "Configuration is frozen because voting has begun. Use the exceptional change process for emergency amendments."
              : "Opening/closing times, eligibility and voting rules are covered by the configuration hash."}
          </SectionHeading>
          {canEdit ? (
          <form onSubmit={saveDetails} className="grid gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <label className="label">Title</label>
              <input
                className="input"
                value={form.title ?? ""}
                onChange={(event) => setForm({ ...form, title: event.target.value })}
                disabled={locked}
              />
            </div>
            <div className="sm:col-span-2">
              <label className="label">Description</label>
              <textarea
                className="input min-h-[80px]"
                value={form.description ?? ""}
                onChange={(event) => setForm({ ...form, description: event.target.value })}
                disabled={locked}
              />
            </div>
            <div>
              <label className="label">Voting opens</label>
              <input
                type="datetime-local"
                className="input"
                value={form.opens_at ?? ""}
                onChange={(event) => setForm({ ...form, opens_at: event.target.value })}
                disabled={locked}
              />
            </div>
            <div>
              <label className="label">Voting closes</label>
              <input
                type="datetime-local"
                className="input"
                value={form.closes_at ?? ""}
                onChange={(event) => setForm({ ...form, closes_at: event.target.value })}
                disabled={locked}
              />
            </div>
            <div>
              <label className="label">Time zone</label>
              <input
                className="input"
                value={form.timezone ?? ""}
                onChange={(event) => setForm({ ...form, timezone: event.target.value })}
                disabled={locked}
              />
            </div>
            <div>
              <label className="label">Eligibility rules</label>
              <input
                className="input"
                value={form.eligibility_rules ?? ""}
                onChange={(event) => setForm({ ...form, eligibility_rules: event.target.value })}
                disabled={locked}
              />
            </div>
            <div className="sm:col-span-2">
              <label className="label">Voting rules</label>
              <textarea
                className="input min-h-[70px]"
                value={form.voting_rules ?? ""}
                onChange={(event) => setForm({ ...form, voting_rules: event.target.value })}
                disabled={locked}
              />
            </div>
            <div className="sm:col-span-2 flex flex-wrap gap-2">
              <button className="btn-primary" disabled={busy || locked || !can(profile, "election.edit")}>
                Save configuration
              </button>
              <span className="self-center text-[11px] text-ink/40">
                Hash {election.configuration_hash_now?.slice(0, 20)}…
              </span>
            </div>
          </form>
          ) : (
            <dl className="space-y-3 text-sm">
              <div className="kv"><dt>Title</dt><dd>{election.title}</dd></div>
              <div className="kv"><dt>Description</dt><dd>{election.description || "—"}</dd></div>
              <div className="kv"><dt>Voting opens</dt><dd>{formatDate(election.opens_at)}</dd></div>
              <div className="kv"><dt>Voting closes</dt><dd>{formatDate(election.closes_at)}</dd></div>
              <div className="kv"><dt>Time zone</dt><dd>{election.timezone}</dd></div>
              <div className="kv"><dt>Eligibility rules</dt><dd>{election.eligibility_rules}</dd></div>
              <div className="kv"><dt>Voting rules</dt><dd>{election.voting_rules}</dd></div>
              <div className="kv">
                <dt>Configuration hash</dt>
                <dd className="code max-w-[65%] text-right">{shortHash(election.configuration_hash_now, 18)}</dd>
              </div>
            </dl>
          )}
        </Card>

        <div className="space-y-5">
          <Card className="card-pad">
            <SectionHeading eyebrow="Two-person approval" title="Configuration approvals" />
            <div className="space-y-2">
              {["chairman", "returning_officer"].map((role) => (
                <div key={role} className="flex items-center justify-between rounded-lg border border-rule px-3 py-2">
                  <span className="text-sm capitalize text-ink/70">{role.replace("_", " ")}</span>
                  <span className={approvalRoles.has(role) ? "pill-green" : "pill-grey"}>
                    {approvalRoles.has(role) ? "Approved" : "Pending"}
                  </span>
                </div>
              ))}
            </div>
            <p className="mt-3 text-xs text-ink/45">
              The Chairman approves the settings and a second authorised official independently confirms
              them. Approval provisions the election's tally and signing keys.
            </p>
            {canRecordConfigurationApproval ? (
              <button className="btn-dark mt-4 w-full" onClick={approveConfiguration} disabled={busy}>
                Record my approval
              </button>
            ) : (
              <p className="mt-3 text-xs text-ink/45">
                Configuration approval is reserved for the Chairman and Returning Officer. Each may
                record one approval.
              </p>
            )}
            {election.approved_at ? (
              <p className="mt-2 text-[11px] text-ink/40">Approved {formatDate(election.approved_at)}</p>
            ) : null}
          </Card>

          <Card className="card-pad">
            <SectionHeading eyebrow="Lifecycle" title="Election status" />
            <p className="text-sm text-ink/60">
              Current status: <strong className="capitalize">{election.status.replace(/_/g, " ")}</strong>
            </p>
            <div className="mt-3 flex flex-col gap-2">
              {lifecycleActions.map((action) => (
                <button
                  key={action.status}
                  className="btn-outline"
                  onClick={() => transition(action.status)}
                  disabled={busy}
                >
                  {action.label}
                </button>
              ))}
              {["voting_closed", "counting", "provisional_results", "under_review"].includes(election.status) ? (
                <p className="text-xs text-ink/45">
                  Continue in the Counting and Results tabs to maintain the audit trail.
                </p>
              ) : null}
              {election.status === "approved" ? (
                <p className="text-xs text-ink/45">Open accreditation when the register is approved.</p>
              ) : null}
            </div>
          </Card>
        </div>
      </div>

      <Card className="card-pad">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <SectionHeading eyebrow="Voter verification and receipt settings" title="Verification controls">
            These four controls are enabled by default and lock permanently once the first ballot is accepted.
          </SectionHeading>
          {election.verification.locked_at ? (
            <span className="pill-gold">Locked {formatDate(election.verification.locked_at)}</span>
          ) : null}
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          {SETTINGS_FIELDS.map(([key, title, description]) => (
            <div
              key={key}
              className={`flex items-start gap-3 rounded-xl border p-4 ${
                settings[key] ? "border-green/30 bg-green/[0.03]" : "border-rule"
              }`}
            >
              {canConfigure ? (
                <input
                  type="checkbox"
                  className="mt-1 h-4 w-4 accent-green"
                  checked={Boolean(settings[key])}
                  onChange={(event) => setSettings({ ...settings, [key]: event.target.checked })}
                  disabled={locked}
                />
              ) : (
                <span className={`mt-0.5 ${settings[key] ? "pill-green" : "pill-grey"}`}>
                  {settings[key] ? "Enabled" : "Disabled"}
                </span>
              )}
              <span>
                <span className="block text-sm font-semibold text-ink">{title}</span>
                <span className="mt-0.5 block text-[13px] leading-relaxed text-ink/55">{description}</span>
              </span>
            </div>
          ))}
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          {canConfigure ? (
            <button className="btn-primary" onClick={saveSettings} disabled={busy || locked}>
              Save verification settings
            </button>
          ) : null}
          {canApproveSettings ? (
            <button className="btn-outline" onClick={approveSettings} disabled={busy || locked}>
              {election.verification.approved_at ? "Re-approve settings" : "Approve settings"}
            </button>
          ) : null}
          <span className="text-[11px] text-ink/40">
            {election.verification.approved_at
              ? `Approved ${formatDate(election.verification.approved_at)}`
              : "Awaiting approval by a second official"}
          </span>
        </div>
      </Card>

      {locked && canRequestChange ? (
        <Card className="card-pad">
          <SectionHeading eyebrow="Exceptional changes" title="Emergency configuration amendment">
            Voting integrity settings cannot be changed. Emergency changes are documented, require two
            approvals, preserve the previous configuration and are published to voters.
          </SectionHeading>
          <form onSubmit={requestChange} className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="label">New closing time (optional)</label>
              <input
                type="datetime-local"
                className="input"
                value={changeCloses}
                onChange={(event) => setChangeCloses(event.target.value)}
              />
            </div>
            <div className="sm:col-span-2">
              <label className="label">Reason (required, recorded permanently)</label>
              <textarea
                className="input min-h-[70px]"
                value={changeReason}
                onChange={(event) => setChangeReason(event.target.value)}
                required
                minLength={10}
              />
            </div>
            <div className="sm:col-span-2">
              <button className="btn-danger" disabled={busy || !changeReason.trim()}>
                Record change request
              </button>
            </div>
          </form>
          <div className="mt-5 space-y-2">
            {(election.change_history ?? []).map((change: any) => (
              <div key={change.id} className="rounded-xl border border-rule p-3 text-xs">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-semibold text-ink">{change.reason}</span>
                  <span className={change.status === "approved" ? "pill-green" : "pill-gold"}>
                    {change.status}
                  </span>
                </div>
                <p className="mt-1 text-ink/50">
                  {change.approvals?.length ?? 0} approval(s) · {formatDate(change.created_at)}
                </p>
                {change.status === "pending" &&
                !(change.approvals ?? []).some((approval: any) => approval.profile_id === profile?.id) ? (
                  <button className="btn-outline mt-2 !py-1.5 text-xs" onClick={() => approveChange(change.id)}>
                    Approve change
                  </button>
                ) : null}
              </div>
            ))}
          </div>
        </Card>
      ) : null}

      <Card className="card-pad">
        <SectionHeading eyebrow="Configuration history" title="Election events" />
        <ol className="space-y-2">
          {(election.events ?? []).map((event: any) => (
            <li key={event.id} className="flex gap-3 text-sm">
              <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-green" />
              <span>
                <span className="text-ink/75">{event.message}</span>
                <span className="ml-2 text-[11px] text-ink/40">{formatDate(event.created_at)}</span>
              </span>
            </li>
          ))}
        </ol>
      </Card>
    </div>
  );
}
