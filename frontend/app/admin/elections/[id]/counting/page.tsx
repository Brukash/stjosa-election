"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Alert, Card, Loading, SectionHeading, Stat } from "@/components/ui";
import { api, can, formatDate, getProfile, notifyElectionUpdated, shortHash } from "@/lib/api";

export default function CountingPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const profile = getProfile();
  const [data, setData] = useState<any | null>(null);
  const [runs, setRuns] = useState<any[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  function load() {
    api(`/api/tally/${id}`, { auth: true })
      .then(setData)
      .catch((err) => setError(err.message));
    api(`/api/tally/${id}/runs`, { auth: true })
      .then((payload) => setRuns(payload.runs))
      .catch(() => setRuns([]));
  }

  useEffect(load, [id]);

  async function authorise() {
    setBusy(true);
    setError("");
    try {
      const result = await api(`/api/tally/${id}/authorise`, { method: "POST", auth: true });
      setNotice(result.message);
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function closeVoting() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api(`/api/elections/${id}/status`, {
        method: "POST",
        auth: true,
        body: JSON.stringify({ status: "voting_closed", note: "Voting closed from the counting console" }),
      });
      window.location.reload();
    } catch (err: any) {
      setError(err.message);
      setBusy(false);
    }
  }

  async function runCount() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api(`/api/tally/${id}/run`, { method: "POST", auth: true });
      setNotice("Automated count completed. Provisional results are ready for review.");
      notifyElectionUpdated();
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (!data) return <Loading label="Loading counting dashboard…" />;

  const tally = data.tally;
  // Without private key material nothing on this page can ever succeed, so the
  // console says so once instead of offering buttons that return an error.
  const keysAvailable = data.keys_available !== false;
  // Keys that were never created yet (configuration not approved) are not the
  // same as keys that were created and lost; only the second is fatal.
  const keysProvisioned = data.keys_provisioned !== false;
  const roles = new Set((data.authorisations ?? []).map((row: any) => row.role));
  const myRoles = new Set<string>(profile?.roles ?? []);
  const canCloseVoting = can(profile, "election.view") && myRoles.has("chairman");
  const statusBlocksResults = ["draft", "configured", "approved", "accreditation_open", "voting_open"].includes(
    data.status
  );

  return (
    <div className="space-y-5">
      {error ? <Alert tone="error">{error}</Alert> : null}
      {notice ? <Alert tone="success">{notice}</Alert> : null}

      {keysAvailable ? null : !keysProvisioned ? (
        <Card className="card-pad">
          <SectionHeading eyebrow="Keys pending" title="Keys are created when configuration is approved">
            The tally key and the record-signing key are generated when the Chairman approves the
            configuration. Until that approval completes there are no keys to count with.
          </SectionHeading>
          <p className="mt-3 text-sm leading-relaxed text-ink/60">
            The keys are saved with the election the moment they are created, so counting works on
            whichever server handles it — not only the one that created them.
          </p>
          <div className="mt-4">
            <Link href={`/admin/elections/${id}`} className="btn-outline">
              Open setup &amp; verification
            </Link>
          </div>
        </Card>
      ) : (
        <Card className="card-pad">
          <SectionHeading eyebrow="Keys missing" title="This election cannot be counted">
            The private keys for this election were never saved with it, and the machine that
            generated them no longer holds a copy. Ballots already cast were encrypted to that key,
            so they cannot be decrypted now — and a new key cannot open them without making the
            record untrue.
          </SectionHeading>
          <p className="mt-3 text-sm leading-relaxed text-ink/60">
            Create a fresh election for this ballot. Elections created now keep their keys with the
            election, so counting works even after the server is replaced. This one stays on record
            with its ballots unreadable.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Link href="/admin/elections" className="btn-primary">
              Create a replacement election
            </Link>
            <Link href={`/admin/elections/${id}`} className="btn-outline">
              Review this election
            </Link>
          </div>
        </Card>
      )}

      {keysAvailable ? (
      <Card className="card-pad">
        <SectionHeading eyebrow="Authorisation" title="Authorise counting">
          The Chairman authorises counting, and one authorisation is enough. Tally keys remain
          encrypted and are only used by the counting service.
        </SectionHeading>
        <div className="grid gap-2 sm:grid-cols-2">
          <div className="flex items-center justify-between rounded-lg border border-rule px-3 py-2">
            <span className="text-sm text-ink/70">Chairman</span>
            <span className={roles.has("chairman") ? "pill-green" : "pill-grey"}>
              {roles.has("chairman") ? "Authorised" : "Pending"}
            </span>
          </div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <button
            className="btn-outline"
            onClick={authorise}
            disabled={
              busy ||
              data.authorised ||
              !can(profile, "counting.authorise") ||
              !["voting_closed", "provisional_results"].includes(data.status)
            }
          >
            {data.authorised ? "Counting authorised" : "Authorise counting"}
          </button>
          {can(profile, "counting.run") ? (
            <button
              className="btn-primary"
              onClick={runCount}
              disabled={
                busy ||
                !data.authorised ||
                !["voting_closed", "provisional_results", "under_review"].includes(data.status)
              }
            >
              {busy ? "Counting…" : "Run automated count"}
            </button>
          ) : (
            <p className="self-center text-xs text-ink/45">
              Only an official with counting permission can run the automated count.
            </p>
          )}
        </div>
        {data.status === "voting_open" ? (
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <p className="text-xs text-ink/45">
              Voting is still open. Close voting before authorising the count.
            </p>
            {canCloseVoting ? (
              <button className="btn-outline !py-1.5 text-xs" onClick={closeVoting} disabled={busy}>
                Close voting now
              </button>
            ) : (
              <span className="text-xs text-ink/45">
                The Chairman closes voting in the Setup &amp; verification tab.
              </span>
            )}
          </div>
        ) : null}
      </Card>
      ) : null}

      {statusBlocksResults ? (
        <Card className="card-pad">
          <p className="text-sm text-ink/60">
            Candidate results remain hidden during the voting period and are only available once
            counting has been authorised and completed.
          </p>
        </Card>
      ) : null}

      {tally ? (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Accepted ballots" value={tally.totals.accepted_ballots} />
            <Stat label="Valid ballots" value={tally.totals.valid_ballots} />
            <Stat label="Invalid ballots" value={tally.totals.invalid_ballots} />
            <Stat label="Challenged (excluded)" value={tally.totals.challenged_ballots} />
          </div>

          <Card className="card-pad">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <SectionHeading eyebrow="Counting dashboard" title="Candidate totals">
                Completed {formatDate(tally.finished_at)}
              </SectionHeading>
              <span className={tally.reconciliation?.balanced ? "pill-green" : "pill-red"}>
                {tally.reconciliation?.balanced ? "Reconciled" : "Not reconciled"}
              </span>
            </div>
            <div className="space-y-4">
              {tally.positions.map((position: any) => (
                <div key={position.id}>
                  <h3 className="text-sm font-semibold text-ink">{position.title}</h3>
                  <div className="table-wrap mt-2">
                    <table className="table">
                      <thead>
                        <tr>
                          <th>Candidate</th>
                          <th className="text-right">Votes</th>
                          <th className="text-right">Share</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {position.candidates.map((candidateRow: any) => (
                          <tr key={candidateRow.id}>
                            <td className="font-medium text-ink">{candidateRow.full_name}</td>
                            <td className="text-right font-mono">{candidateRow.votes}</td>
                            <td className="text-right">{candidateRow.percentage}%</td>
                            <td>
                              {candidateRow.is_winner ? (
                                <span className="pill-green">Winner</span>
                              ) : (
                                <span className="text-xs text-ink/35">—</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ))}
            </div>
          </Card>

          <Card className="card-pad">
            <SectionHeading eyebrow="Evidence" title="Verifiable tally record" />
            <dl className="space-y-1">
              <div className="kv">
                <dt>Tally run</dt>
                <dd className="font-mono text-xs">{tally.tally_run_id}</dd>
              </div>
              <div className="kv">
                <dt>Evidence hash</dt>
                <dd className="code max-w-[70%] text-right">{tally.evidence_hash}</dd>
              </div>
              <div className="kv">
                <dt>Signature</dt>
                <dd className="code max-w-[70%] text-right">{shortHash(tally.signature, 18)}</dd>
              </div>
              {(tally.reconciliation ?? null) ? (
                <div className="kv">
                  <dt>Reconciliation</dt>
                  <dd className="text-xs">
                    accepted {tally.reconciliation.accepted_ballots} · valid + invalid{" "}
                    {tally.reconciliation.valid_plus_invalid} · receipts {tally.reconciliation.receipts_issued} ·
                    credentials spent {tally.reconciliation.spent_credentials}
                  </dd>
                </div>
              ) : null}
            </dl>
            <p className="mt-3 text-xs leading-relaxed text-ink/45">
              Each accepted ballot has a stored proof: its commitment, a Merkle inclusion proof against
              the published root, and a hash-chained position in the decrypted tally sequence.
            </p>
          </Card>
        </>
      ) : !statusBlocksResults && keysAvailable ? (
        <Card className="card-pad">
          <p className="text-sm text-ink/60">
            No completed count yet. Authorise counting, then run the automated count.
          </p>
        </Card>
      ) : null}

      {runs.length ? (
        <Card className="card-pad">
          <SectionHeading eyebrow="History" title="Counting sessions" />
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Started</th>
                  <th>Status</th>
                  <th className="text-right">Accepted</th>
                  <th className="text-right">Valid</th>
                  <th className="text-right">Invalid</th>
                  <th>Evidence</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id}>
                    <td className="text-xs">{formatDate(run.started_at)}</td>
                    <td className="capitalize">{run.status}</td>
                    <td className="text-right font-mono">{run.accepted_ballots}</td>
                    <td className="text-right font-mono">{run.valid_ballots}</td>
                    <td className="text-right font-mono">{run.invalid_ballots}</td>
                    <td className="font-mono text-[11px]">{shortHash(run.evidence_hash, 10)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}
    </div>
  );
}
