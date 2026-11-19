"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Alert, Card, Empty, Loading, SectionHeading } from "@/components/ui";
import { api, can, getProfile, notifyElectionUpdated } from "@/lib/api";

export default function BallotSetupPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const profile = getProfile();
  const [election, setElection] = useState<any | null>(null);
  const [position, setPosition] = useState({ title: "", description: "", seats: 1 });
  const [candidate, setCandidate] = useState({
    position_id: "",
    full_name: "",
    bio: "",
    manifesto: "",
    photo_url: "",
  });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  function load() {
    api(`/api/elections/${id}`, { auth: true })
      .then(setElection)
      .catch((err) => setError(err.message));
  }

  useEffect(load, [id]);

  const locked = Boolean(election?.locked_at);
  const canEdit = can(profile, "election.edit");
  const editable = canEdit && !locked;

  async function addPosition(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api(`/api/elections/${id}/positions`, {
        method: "POST",
        auth: true,
        body: JSON.stringify({ ...position, seats: Number(position.seats) }),
      });
      setNotice(`Position "${position.title}" added.`);
      notifyElectionUpdated();
      setPosition({ title: "", description: "", seats: 1 });
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function addCandidate(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api(`/api/elections/${id}/candidates`, {
        method: "POST",
        auth: true,
        body: JSON.stringify({
          ...candidate,
          photo_url: candidate.photo_url || null,
        }),
      });
      setNotice(`Candidate "${candidate.full_name}" added.`);
      notifyElectionUpdated();
      setCandidate({ ...candidate, full_name: "", bio: "", manifesto: "", photo_url: "" });
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(kind: "positions" | "candidates", itemId: string) {
    setBusy(true);
    try {
      await api(`/api/elections/${kind}/${itemId}`, { method: "DELETE", auth: true });
      setNotice("Record removed and configuration hash recomputed.");
      notifyElectionUpdated();
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (!election) return <Loading label="Loading ballot configuration…" />;

  return (
    <div className="space-y-5">
      {error ? <Alert tone="error">{error}</Alert> : null}
      {notice ? <Alert tone="success">{notice}</Alert> : null}
      {locked ? (
        <Alert tone="warn">
          Positions and candidates are locked because the first ballot has been accepted. They cannot be
          changed without an approved exceptional change.
        </Alert>
      ) : null}

      {canEdit ? (
      <div className="grid gap-5 md:grid-cols-2">
        <Card className="card-pad">
          <SectionHeading eyebrow="Elective positions" title="Add a position" />
          <form onSubmit={addPosition} className="space-y-3">
            <div>
              <label className="label">Position title</label>
              <input
                className="input"
                value={position.title}
                onChange={(event) => setPosition({ ...position, title: event.target.value })}
                placeholder="General Secretary"
                required
                disabled={!editable}
              />
            </div>
            <div>
              <label className="label">Description</label>
              <input
                className="input"
                value={position.description}
                onChange={(event) => setPosition({ ...position, description: event.target.value })}
                disabled={!editable}
              />
            </div>
            <div>
              <label className="label">Seats</label>
              <input
                type="number"
                min={1}
                className="input max-w-[120px]"
                value={position.seats}
                onChange={(event) => setPosition({ ...position, seats: Number(event.target.value) })}
                disabled={!editable}
              />
            </div>
            <button className="btn-primary" disabled={busy || !editable}>
              Add position
            </button>
          </form>
        </Card>

        <Card className="card-pad">
          <SectionHeading eyebrow="Approved candidates" title="Add a candidate" />
          <form onSubmit={addCandidate} className="space-y-3">
            <div>
              <label className="label">Position</label>
              <select
                className="input"
                value={candidate.position_id}
                onChange={(event) => setCandidate({ ...candidate, position_id: event.target.value })}
                required
                disabled={!editable}
              >
                <option value="">Select position…</option>
                {(election.positions ?? []).map((item: any) => (
                  <option key={item.id} value={item.id}>
                    {item.title}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">Candidate name</label>
              <input
                className="input"
                value={candidate.full_name}
                onChange={(event) => setCandidate({ ...candidate, full_name: event.target.value })}
                required
                disabled={!editable}
              />
            </div>
            <div>
              <label className="label">Profile</label>
              <input
                className="input"
                value={candidate.bio}
                onChange={(event) => setCandidate({ ...candidate, bio: event.target.value })}
                placeholder="Short biography"
                disabled={!editable}
              />
            </div>
            <div>
              <label className="label">Manifesto</label>
              <textarea
                className="input min-h-[70px]"
                value={candidate.manifesto}
                onChange={(event) => setCandidate({ ...candidate, manifesto: event.target.value })}
                disabled={!editable}
              />
            </div>
            <div>
              <label className="label">Photograph URL (optional)</label>
              <input
                className="input"
                value={candidate.photo_url}
                onChange={(event) => setCandidate({ ...candidate, photo_url: event.target.value })}
                placeholder="https://…"
                disabled={!editable}
              />
            </div>
            <button className="btn-primary" disabled={busy || !editable}>
              Add candidate
            </button>
          </form>
        </Card>
      </div>
      ) : (
        <Alert tone="info">
          Read-only view. Your role can inspect positions and candidates but cannot change the ballot.
        </Alert>
      )}

      <div className="space-y-4">
        {(election.positions ?? []).length === 0 ? (
          <Empty title="No elective positions yet">
            {canEdit
              ? "Add the positions that will appear on the ballot."
              : "No positions have been configured for this election."}
          </Empty>
        ) : null}
        {(election.positions ?? []).map((item: any) => (
          <Card key={item.id} className="card-pad">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <h2 className="font-display text-lg text-ink">{item.title}</h2>
                <p className="text-xs text-ink/50">
                  {item.candidates.length} candidate(s) · {item.seats} seat(s)
                </p>
              </div>
              <div className="flex items-center gap-2">
                <span className={item.approved ? "pill-green" : "pill-grey"}>
                  {item.approved ? "Approved" : "Draft"}
                </span>
                {editable ? (
                  <button
                    className="text-xs font-semibold text-red-600 underline"
                    onClick={() => remove("positions", item.id)}
                    disabled={busy}
                  >
                    Delete
                  </button>
                ) : null}
              </div>
            </div>
            <div className="table-wrap mt-3">
              <table className="table">
                <thead>
                  <tr>
                    <th>Candidate</th>
                    <th>Profile</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {item.candidates.map((candidateRow: any) => (
                    <tr key={candidateRow.id}>
                      <td className="font-medium text-ink">{candidateRow.full_name}</td>
                      <td className="text-xs text-ink/55">
                        {candidateRow.bio}
                        {candidateRow.manifesto ? (
                          <span className="mt-1 block italic text-ink/40">{candidateRow.manifesto}</span>
                        ) : null}
                      </td>
                      <td className="text-right">
                        {editable ? (
                          <button
                            className="text-xs font-semibold text-red-600 underline"
                            onClick={() => remove("candidates", candidateRow.id)}
                            disabled={busy}
                          >
                            Remove
                          </button>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
