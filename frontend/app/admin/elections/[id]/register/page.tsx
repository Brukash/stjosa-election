"use client";

import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Alert, Card, Loading, SectionHeading, Stat } from "@/components/ui";
import { api, can, getProfile } from "@/lib/api";

const SAMPLE = `voter_id,full_name,email,phone,alumni_set,graduation_year
SJC/AL/2016/025,Jane Doe,jane.doe@example.com,+2348000000000,Lagos Chapter,2016`;

export default function RegisterPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const profile = getProfile();
  const [data, setData] = useState<any | null>(null);
  const [csv, setCsv] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");

  function load() {
    api(`/api/register/${id}`, { auth: true })
      .then(setData)
      .catch((err) => setError(err.message));
  }

  useEffect(load, [id]);

  async function importCsv(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api(`/api/register/${id}/import`, {
        method: "POST",
        auth: true,
        body: JSON.stringify({ csv_text: csv }),
      });
      setNotice(
        `${result.added} record(s) imported, ${result.skipped_duplicates} duplicate(s) skipped. ` +
          (result.errors?.length ? `${result.errors.length} row error(s).` : "")
      );
      setCsv("");
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function approveRegister() {
    setBusy(true);
    setError("");
    try {
      const result = await api(`/api/register/${id}/approve`, { method: "POST", auth: true });
      setNotice(`${result.approved} voter(s) approved; ${result.excluded} excluded.`);
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function toggleEligibility(voter: any) {
    setBusy(true);
    try {
      await api(`/api/register/voters/${voter.id}`, {
        method: "PATCH",
        auth: true,
        body: JSON.stringify({ is_eligible: !voter.is_eligible, note: "Register maintained by committee" }),
      });
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const voters = useMemo(() => {
    if (!data) return [];
    const needle = query.trim().toLowerCase();
    if (!needle) return data.voters;
    return data.voters.filter(
      (voter: any) =>
        voter.voter_id.toLowerCase().includes(needle) ||
        voter.full_name.toLowerCase().includes(needle) ||
        (voter.alumni_set ?? "").toLowerCase().includes(needle)
    );
  }, [data, query]);

  if (!data) return <Loading label="Loading electoral register…" />;

  const approved = data.election.register_approved;
  const canImport = can(profile, "register.import");
  const canApprove = can(profile, "register.approve");

  return (
    <div className="space-y-5">
      {error ? <Alert tone="error">{error}</Alert> : null}
      {notice ? <Alert tone="success">{notice}</Alert> : null}

      <div className="grid gap-3 sm:grid-cols-4">
        <Stat label="Registered" value={data.stats.registered_voters} />
        <Stat label="Eligible" value={data.stats.eligible_voters} />
        <Stat label="Accredited" value={data.stats.accredited_voters} />
        <Stat label="Register status" value={approved ? "Approved" : "Pending"} />
      </div>

      <div className="grid gap-5 lg:grid-cols-[1fr_0.8fr]">
        <Card className="card-pad">
          <SectionHeading eyebrow="Import" title="Approved voter register">
            Paste the CSV exported by the Electoral Committee. Voter identity records never contain
            ballot information.
          </SectionHeading>
          {canImport ? (
          <form onSubmit={importCsv} className="space-y-3">
            <textarea
              className="input min-h-[150px] font-mono text-xs"
              placeholder={SAMPLE}
              value={csv}
              onChange={(event) => setCsv(event.target.value)}
            />
            <div className="flex flex-wrap gap-2">
              <button className="btn-primary" disabled={busy || !csv.trim() || !can(profile, "register.import")}>
                Import register
              </button>
              <label className="btn-outline cursor-pointer">
                Choose CSV file
                <input
                  type="file"
                  accept=".csv,text/csv"
                  className="hidden"
                  onChange={async (event) => {
                    const file = event.target.files?.[0];
                    if (file) setCsv(await file.text());
                  }}
                />
              </label>
            </div>
            <p className="text-xs text-ink/45">
              Required columns: <span className="font-mono">voter_id, full_name</span>. Optional:{" "}
              <span className="font-mono">email, phone, alumni_set, graduation_year</span>.
            </p>
          </form>
          ) : (
            <Alert tone="info">
              Read-only register view. Your role can inspect voter records but cannot import changes.
            </Alert>
          )}
        </Card>

        <Card className="card-pad">
          <SectionHeading eyebrow="Approval" title="Register approval" />
          <p className="text-sm leading-relaxed text-ink/60">
            Only the Chairman can approve the register. Approved voters become eligible for
            accreditation; changes are locked once the first ballot is cast.
          </p>
          {canApprove ? (
            <button className="btn-dark mt-4 w-full" onClick={approveRegister} disabled={busy}>
              Approve register
            </button>
          ) : null}
          <div className="mt-5">
            <label className="label">Search voters</label>
            <input
              className="input"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Voter ID, name or alumni set"
            />
          </div>
        </Card>
      </div>

      <Card className="card-pad">
        <SectionHeading eyebrow="Electoral register" title={`${voters.length} voter record(s)`} />
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Voter ID</th>
                <th>Name</th>
                <th>Alumni set</th>
                <th>Status</th>
                <th>Accredited</th>
                {canApprove ? <th /> : null}
              </tr>
            </thead>
            <tbody>
              {voters.map((voter: any) => (
                <tr key={voter.id}>
                  <td className="font-mono text-xs">{voter.voter_id}</td>
                  <td>
                    <span className="font-medium text-ink">{voter.full_name}</span>
                    <span className="mt-0.5 block text-[11px] text-ink/45">{voter.email ?? voter.phone}</span>
                  </td>
                  <td className="text-xs">{voter.alumni_set}</td>
                  <td>
                    <span className={voter.register_status === "approved" ? "pill-green" : "pill-grey"}>
                      {voter.register_status}
                    </span>
                    {!voter.is_eligible ? <span className="pill-red ml-1">ineligible</span> : null}
                  </td>
                  <td>{voter.accredited ? <span className="pill-green">yes</span> : <span className="text-xs text-ink/35">no</span>}</td>
                  {canApprove ? (
                    <td className="text-right">
                      <button
                        className="text-xs font-semibold text-ink/50 underline hover:text-ink"
                        onClick={() => toggleEligibility(voter)}
                        disabled={busy}
                      >
                        {voter.is_eligible ? "Exclude" : "Include"}
                      </button>
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
