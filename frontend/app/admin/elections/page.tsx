"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Alert, Card, Loading, SectionHeading, StatusPill } from "@/components/ui";
import { api, can, formatDate, getProfile } from "@/lib/api";

const BLANK = {
  title: "",
  year: new Date().getFullYear() + 1,
  reference: "",
  opens_at: "",
  closes_at: "",
};

export default function ElectionsAdminPage() {
  const profile = getProfile();
  const canCreate = can(profile, "election.create");
  const [elections, setElections] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [form, setForm] = useState<any>(BLANK);
  const [busy, setBusy] = useState(false);

  function load() {
    api("/api/elections", { auth: true })
      .then((data) => setElections(data.elections))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const payload = {
        title: form.title,
        year: Number(form.year),
        reference: form.reference || undefined,
        opens_at: form.opens_at ? new Date(form.opens_at).toISOString() : null,
        closes_at: form.closes_at ? new Date(form.closes_at).toISOString() : null,
      };
      await api("/api/elections", { method: "POST", auth: true, body: JSON.stringify(payload) });
      setNotice("Election created. Configure positions, candidates and verification settings next.");
      setForm(BLANK);
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <Loading />;

  return (
    <div className="space-y-6">
      <SectionHeading eyebrow="Election configuration" title="Elections">
        Each election has its own register, candidates, verification settings, ballots, results and
        audit record.
      </SectionHeading>

      {error ? <Alert tone="error">{error}</Alert> : null}
      {notice ? <Alert tone="success">{notice}</Alert> : null}

      <div className="grid gap-4 md:grid-cols-2">
        {elections.map((election) => (
          <Card key={election.id} className="card-pad">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="font-display text-lg leading-snug text-ink">{election.title}</h2>
                <p className="mt-1 text-xs text-ink/50">
                  {election.reference} · {election.year}
                </p>
              </div>
              <StatusPill status={election.status} label={election.status_label} />
            </div>
            <div className="mt-4 grid grid-cols-3 gap-2 text-center">
              <div className="rounded-lg bg-paper px-2 py-2">
                <p className="font-display text-lg text-ink">{election.totals.eligible_voters}</p>
                <p className="text-[10px] uppercase tracking-wide text-ink/40">Eligible</p>
              </div>
              <div className="rounded-lg bg-paper px-2 py-2">
                <p className="font-display text-lg text-ink">{election.totals.votes_cast}</p>
                <p className="text-[10px] uppercase tracking-wide text-ink/40">Votes</p>
              </div>
              <div className="rounded-lg bg-paper px-2 py-2">
                <p className="font-display text-lg text-ink">{election.totals.turnout_percentage}%</p>
                <p className="text-[10px] uppercase tracking-wide text-ink/40">Turnout</p>
              </div>
            </div>
            <p className="mt-3 text-[11px] text-ink/45">
              Voting {formatDate(election.opens_at)} → {formatDate(election.closes_at)}
            </p>
            <Link href={`/admin/elections/${election.id}`} className="btn-outline mt-4 w-full">
              Open workspace
            </Link>
          </Card>
        ))}
      </div>

      {canCreate ? (
      <Card className="card-pad">
        <SectionHeading eyebrow="New election" title="Create an election">
          Only the Super Administrator and Electoral Committee Chairman may create elections.
        </SectionHeading>
        <form onSubmit={create} className="grid gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label className="label">Election title</label>
            <input
              className="input"
              value={form.title}
              onChange={(event) => setForm({ ...form, title: event.target.value })}
              placeholder="St. John's College Jos Alumni Association Election 2028"
              required
            />
          </div>
          <div>
            <label className="label">Year</label>
            <input
              type="number"
              className="input"
              value={form.year}
              onChange={(event) => setForm({ ...form, year: event.target.value })}
              required
            />
          </div>
          <div>
            <label className="label">Reference (optional)</label>
            <input
              className="input"
              value={form.reference}
              onChange={(event) => setForm({ ...form, reference: event.target.value.toUpperCase() })}
              placeholder="SJCJ-ALUMNI-2028"
            />
          </div>
          <div>
            <label className="label">Voting opens</label>
            <input
              type="datetime-local"
              className="input"
              value={form.opens_at}
              onChange={(event) => setForm({ ...form, opens_at: event.target.value })}
            />
          </div>
          <div>
            <label className="label">Voting closes</label>
            <input
              type="datetime-local"
              className="input"
              value={form.closes_at}
              onChange={(event) => setForm({ ...form, closes_at: event.target.value })}
            />
          </div>
          <div className="sm:col-span-2">
            <button className="btn-primary" disabled={busy}>
              {busy ? "Creating…" : "Create election"}
            </button>
          </div>
        </form>
      </Card>
      ) : (
        <p className="text-xs text-ink/45">
          Creating elections is restricted to the Chairman and Super Administrator. You can still open
          a workspace to view the election within your role.
        </p>
      )}
    </div>
  );
}
