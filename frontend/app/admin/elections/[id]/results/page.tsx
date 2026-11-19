"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Alert, Card, Loading, SectionHeading, Stat } from "@/components/ui";
import {
  API_BASE,
  api,
  can,
  downloadWithAuth,
  formatDate,
  getProfile,
  notifyElectionUpdated,
  shortHash,
} from "@/lib/api";

export default function ResultsAdminPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const profile = getProfile();
  const [data, setData] = useState<any | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");

  function load() {
    api(`/api/results/${id}`, { auth: true })
      .then(setData)
      .catch((err) => setError(err.message));
  }

  useEffect(load, [id]);

  async function submit() {
    setBusy(true);
    setError("");
    try {
      await api(`/api/results/${id}/submit`, {
        method: "POST",
        auth: true,
        body: JSON.stringify({ comments: "Provisional figures reviewed and reconciled" }),
      });
      setNotice("Provisional results submitted to the Chairman for approval.");
      notifyElectionUpdated();
      load();
    } catch (err: any) {
      setError(err.message);
      // Another tab may already have moved the election on; show what is true now.
      if (err?.status === 409) load();
    } finally {
      setBusy(false);
    }
  }

  async function approve() {
    setBusy(true);
    setError("");
    try {
      const declaration = await api(`/api/results/${id}/approve`, { method: "POST", auth: true });
      const delivered = declaration?.voter_notifications;
      const emails =
        delivered && typeof delivered.email_sent === "number"
          ? ` Voter result notices — Email: ${delivered.email_sent} sent, ${delivered.email_failed} failed,` +
            ` ${delivered.email_unavailable} unavailable.` +
            ` SMS: ${delivered.sms_sent ?? 0} sent, ${delivered.sms_failed ?? 0} failed,` +
            ` ${delivered.sms_unavailable ?? 0} unavailable.` +
            ` WhatsApp: ${delivered.whatsapp_sent ?? 0} sent, ${delivered.whatsapp_failed ?? 0} failed,` +
            ` ${(delivered.whatsapp_unavailable ?? 0) + (delivered.whatsapp_no_consent ?? 0)} unavailable.`
          : "";
      const solo = declaration?.single_official_declaration
        ? " Recorded as a single-official declaration: the same account submitted and declared."
        : "";
      setNotice(`Official results declared (version ${declaration.version}) and digitally signed.${solo}${emails}`);
      notifyElectionUpdated();
      load();
    } catch (err: any) {
      setError(err.message);
      if (err?.status === 409) load();
    } finally {
      setBusy(false);
    }
  }

  async function correct(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const declaration = await api(`/api/results/${id}/corrections`, {
        method: "POST",
        auth: true,
        body: JSON.stringify({ reason }),
      });
      setNotice(`Correction declared as version ${declaration.version}; earlier versions preserved.`);
      setReason("");
      notifyElectionUpdated();
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (!data) return <Loading label="Loading results module…" />;

  const provisional = data.provisional;
  const declarations = data.declarations ?? [];
  const current = declarations.find((declaration: any) => declaration.is_current) ?? declarations[0];
  const status = data.election.status;
  const restricted =
    Boolean(profile) && !can(profile, "results.review") && can(profile, "results.review_restricted");

  return (
    <div className="space-y-5">
      {error ? <Alert tone="error">{error}</Alert> : null}
      {notice ? <Alert tone="success">{notice}</Alert> : null}
      {restricted ? (
        <Alert tone="info">
          Observer access: provisional counts and internal approval comments are hidden. Signed,
          declared results appear here after the Chairman declares them.
        </Alert>
      ) : null}

      <Card className="card-pad">
        <SectionHeading eyebrow="Declaration workflow" title="Provisional → approval → declaration">
          The Chairman submits the provisional results, approves them and declares the result. Every
          version is preserved with signatures, and the approval trail records which official carried
          out each step.
        </SectionHeading>
        <div className="grid gap-2 sm:grid-cols-3">
          {[
            ["Counting complete", Boolean(provisional)],
            ["Submitted for review", ["under_review", "declared"].includes(status)],
            ["Declared", declarations.length > 0],
          ].map(([label, done]) => (
            <div key={String(label)} className="flex items-center justify-between rounded-lg border border-rule px-3 py-2">
              <span className="text-sm text-ink/70">{label}</span>
              <span className={done ? "pill-green" : "pill-grey"}>{done ? "Done" : "Pending"}</span>
            </div>
          ))}
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {can(profile, "results.submit") ? (
            <button
              className="btn-outline"
              onClick={submit}
              disabled={busy || status !== "provisional_results"}
            >
              Submit provisional results
            </button>
          ) : null}
          {can(profile, "results.approve") ? (
            <button
              className="btn-primary"
              onClick={approve}
              disabled={busy || status !== "under_review"}
              title={
                status === "under_review"
                  ? undefined
                  : "Submit the provisional results first; approval opens once they are in review."
              }
            >
              Approve and declare results
            </button>
          ) : null}
          {current ? (
            <a
              className="btn-outline"
              href={`${API_BASE}/api/monitoring/${id}/result-certificate.pdf`}
              target="_blank"
              rel="noreferrer"
            >
              Result certificate
            </a>
          ) : null}
        </div>
        {can(profile, "results.approve") && status === "provisional_results" ? (
          <p className="mt-3 text-xs text-ink/60">
            You can complete both steps yourself: submit the provisional figures, then declare them. The
            approval trail, election events and audit log record that one official did both.
          </p>
        ) : null}
        {can(profile, "results.approve") && status === "under_review" ? (
          <p className="mt-3 text-xs text-ink/60">
            The provisional figures are in review. Declaring them publishes the signed result and emails
            every approved voter.
          </p>
        ) : null}
      </Card>

      {provisional ? (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Votes cast" value={provisional.totals.votes_cast} />
            <Stat label="Valid ballots" value={provisional.totals.valid_ballots} />
            <Stat label="Invalid ballots" value={provisional.totals.invalid_ballots} />
            <Stat label="Turnout" value={`${provisional.totals.turnout_percentage}%`} />
          </div>
          <Card className="card-pad">
            <SectionHeading eyebrow="Provisional figures" title="Candidate totals" />
            <div className="space-y-4">
              {provisional.positions.map((position: any) => (
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
                            <td>{candidateRow.is_winner ? <span className="pill-green">Elected</span> : "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </>
      ) : (
        <Card className="card-pad">
          <p className="text-sm text-ink/60">
            No provisional results yet. Complete counting first; totals are hidden during voting.
          </p>
        </Card>
      )}

      <Card className="card-pad">
        <SectionHeading eyebrow="Declarations" title={`${declarations.length} declared version(s)`} />
        {declarations.length === 0 ? (
          <p className="text-sm text-ink/50">Results have not been declared.</p>
        ) : (
          <div className="space-y-3">
            {declarations.map((declaration: any) => (
              <div key={declaration.id} className="rounded-xl border border-rule p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="font-semibold text-ink">Version {declaration.version}</p>
                    <p className="mt-0.5 text-xs text-ink/50">
                      {formatDate(declaration.declared_at)} · {declaration.declared_by}
                    </p>
                  </div>
                  <span className={declaration.signature_valid ? "pill-green" : "pill-red"}>
                    {declaration.signature_valid ? "Signature valid" : "Signature invalid"}
                  </span>
                </div>
                {declaration.correction_reason ? (
                  <p className="mt-2 text-xs text-ink/60">Reason: {declaration.correction_reason}</p>
                ) : null}
                <p className="mt-2 font-mono text-[11px] text-ink/45">
                  {shortHash(declaration.signed_payload_hash, 20)}
                </p>
              </div>
            ))}
          </div>
        )}

        {status === "declared" && can(profile, "results.approve") ? (
          <form onSubmit={correct} className="mt-5 space-y-3 rounded-xl border border-dashed border-rule p-4">
            <label className="label">Authorised correction (creates a new version)</label>
            <textarea
              className="input min-h-[70px]"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Reason for correcting the declared result"
              required
              minLength={10}
            />
            <button className="btn-danger" disabled={busy || reason.trim().length < 10}>
              Declare corrected version
            </button>
          </form>
        ) : null}
      </Card>

      {!restricted ? (
      <Card className="card-pad">
        <SectionHeading eyebrow="Approval trail" title="Result approvals" />
        {data.approvals.length === 0 ? (
          <p className="text-sm text-ink/50">No approvals recorded.</p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Stage</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Comments</th>
                  <th>Time</th>
                </tr>
              </thead>
              <tbody>
                {data.approvals.map((approval: any, index: number) => (
                  <tr key={index}>
                    <td className="capitalize">{approval.stage.replace(/_/g, " ")}</td>
                    <td className="capitalize">{approval.approver_role.replace(/_/g, " ")}</td>
                    <td>{approval.status}</td>
                    <td className="text-xs">{approval.comments ?? "—"}</td>
                    <td className="text-xs">{formatDate(approval.at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <button
          className="btn-outline mt-4"
          onClick={() => downloadWithAuth(`/api/monitoring/${id}/audit-report.pdf`, `audit-${id}.pdf`)}
        >
          Download audit report (PDF)
        </button>
      </Card>
      ) : null}
    </div>
  );
}
