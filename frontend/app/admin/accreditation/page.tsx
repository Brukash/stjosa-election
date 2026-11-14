"use client";

import { useEffect, useMemo, useState } from "react";
import { Alert, Card, Loading, SectionHeading, Stat, StatusPill } from "@/components/ui";
import { api, can, formatDate, getProfile } from "@/lib/api";

export default function AccreditationConsolePage() {
  const profile = getProfile();
  const canReset = can(profile, "accreditation.manage");
  const [elections, setElections] = useState<any[]>([]);
  const [selected, setSelected] = useState("");
  const [overview, setOverview] = useState<any | null>(null);
  const [rows, setRows] = useState<any[]>([]);
  const [search, setSearch] = useState("");
  const [voterId, setVoterId] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    api("/api/elections", { auth: true })
      .then((data) => {
        setElections(data.elections);
        const preferred =
          data.elections.find((election: any) => election.status === "voting_open") ??
          data.elections.find((election: any) => election.status === "accreditation_open") ??
          data.elections[0];
        setSelected(preferred?.id ?? "");
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  function load(electionId: string) {
    if (!electionId) return;
    Promise.all([
      api(`/api/monitoring/${electionId}/overview`, { auth: true }),
      api(`/api/accreditation/exceptions/accreditations?election_id=${electionId}`, { auth: true }),
    ])
      .then(([monitoring, accreditations]) => {
        setOverview(monitoring);
        setRows(accreditations.accreditations);
      })
      .catch((err) => setError(err.message));
  }

  useEffect(() => {
    if (!selected) return;
    setOverview(null);
    setRows([]);
    load(selected);
  }, [selected]);

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return rows;
    return rows.filter(
      (row) =>
        (row.voter_id ?? "").toLowerCase().includes(term) ||
        (row.full_name ?? "").toLowerCase().includes(term)
    );
  }, [rows, search]);

  async function resetCredential(event: React.FormEvent) {
    event.preventDefault();
    if (!selected) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const query = new URLSearchParams({
        election_id: selected,
        voter_id: voterId.trim(),
        reason: reason.trim(),
      });
      await api(`/api/accreditation/exceptions/reset-issuance?${query.toString()}`, {
        method: "POST",
        auth: true,
      });
      setNotice(
        `Credential for ${voterId.trim()} revoked. The voter can now accredit again with a fresh OTP; the old issuance remains in the audit trail.`
      );
      setVoterId("");
      setReason("");
      load(selected);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <Loading label="Loading accreditation console…" />;

  const election = elections.find((item) => item.id === selected);

  return (
    <div className="space-y-5">
      <SectionHeading eyebrow="Accreditation" title="Voter accreditation console">
        Monitor who has accredited and handle controlled credential exceptions. Revoking an issuance
        never deletes it; the action is audited with your reason.
      </SectionHeading>

      {error ? <Alert tone="error">{error}</Alert> : null}
      {notice ? <Alert tone="success">{notice}</Alert> : null}

      <Card className="card-pad">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="min-w-[260px] flex-1">
            <label className="label">Election</label>
            <select
              className="input"
              value={selected}
              onChange={(event) => setSelected(event.target.value)}
            >
              {elections.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.title}
                </option>
              ))}
            </select>
          </div>
          {election ? (
            <div className="flex items-center gap-2 pb-1">
              <StatusPill status={election.status} label={election.status_label} />
              <span className="text-[11px] text-ink/45">{election.reference}</span>
            </div>
          ) : null}
        </div>
      </Card>

      {overview ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Eligible voters" value={overview.stats.eligible_voters} />
          <Stat label="Accredited" value={overview.stats.accredited_voters} />
          <Stat
            label="Yet to accredit"
            value={Math.max(0, overview.stats.eligible_voters - overview.stats.accredited_voters)}
          />
          <Stat label="Failed OTP attempts" value={overview.live.failed_otp_attempts} />
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[1.4fr_0.6fr]">
        <Card className="card-pad">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="font-display text-lg text-ink">Accredited voters</h2>
            <input
              className="input max-w-[240px] !py-2 text-sm"
              placeholder="Search Voter ID or name"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </div>
          <p className="mt-1 text-xs text-ink/45">
            Showing {filtered.length} of {rows.length} accreditation records (latest 500).
          </p>

          <div className="table-wrap mt-4">
            <table className="table">
              <thead>
                <tr>
                  <th>Voter ID</th>
                  <th>Name</th>
                  <th>Accredited</th>
                  <th>Method</th>
                  <th>Credential</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((row) => (
                  <tr key={row.id}>
                    <td className="font-mono text-xs">{row.voter_id ?? "—"}</td>
                    <td>{row.full_name ?? "—"}</td>
                    <td className="text-xs text-ink/60">{formatDate(row.accredited_at)}</td>
                    <td>
                      <span className="pill-green">{row.method}</span>
                    </td>
                    <td>
                      <span
                        className={
                          row.credential_status === "active"
                            ? "pill-green"
                            : row.credential_status === "revoked"
                            ? "pill-red"
                            : "pill-grey"
                        }
                      >
                        {row.credential_status === "active"
                          ? "Active"
                          : row.credential_status === "revoked"
                          ? "Revoked"
                          : "Not issued"}
                      </span>
                      {row.credential_issuance_count > 1 ? (
                        <span className="ml-1.5 text-[10px] text-ink/40">
                          {row.credential_issuance_count} issuances
                        </span>
                      ) : null}
                    </td>
                  </tr>
                ))}
                {!filtered.length ? (
                  <tr>
                    <td colSpan={5} className="py-6 text-center text-sm text-ink/45">
                      No accreditation records match.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </Card>

        <Card className="card-pad">
          <h2 className="font-display text-lg text-ink">Credential exception</h2>
          {canReset ? (
            <>
              <p className="mt-1 text-sm text-ink/55">
                Use only when a voter has lost their anonymous credential and cannot complete voting.
                The voter will need a fresh OTP and will receive a new credential.
              </p>
              <form onSubmit={resetCredential} className="mt-4 space-y-3">
                <div>
                  <label className="label">Voter ID</label>
                  <input
                    className="input font-mono"
                    placeholder="SJC/AL/2004/001"
                    value={voterId}
                    onChange={(event) => setVoterId(event.target.value)}
                    required
                  />
                </div>
                <div>
                  <label className="label">Reason (recorded in the audit trail)</label>
                  <textarea
                    className="input min-h-[90px]"
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                    placeholder="Lost device; verified in person by the accreditation desk"
                    minLength={10}
                    required
                  />
                </div>
                <button
                  className="btn-danger w-full"
                  disabled={busy || voterId.trim().length < 5 || reason.trim().length < 10}
                >
                  {busy ? "Revoking…" : "Revoke credential issuance"}
                </button>
              </form>
            </>
          ) : (
            <Alert tone="info">
              Your role can review accreditation records but cannot reset credentials. Ask the
              Accreditation Officer to perform an exception.
            </Alert>
          )}
        </Card>
      </div>
    </div>
  );
}
