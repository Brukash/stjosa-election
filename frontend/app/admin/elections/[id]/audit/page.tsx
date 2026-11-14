"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Alert, Card, Loading, SectionHeading } from "@/components/ui";
import { api, downloadWithAuth, formatDate, shortHash } from "@/lib/api";

export default function AuditPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const [report, setReport] = useState<any | null>(null);
  const [logs, setLogs] = useState<any[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api(`/api/monitoring/${id}/audit-report`, { auth: true })
      .then(setReport)
      .catch((err) => setError(err.message));
    api(`/api/monitoring/${id}/audit-logs?limit=60`, { auth: true })
      .then((payload) => setLogs(payload.logs))
      .catch(() => setLogs([]));
  }, [id]);

  async function download(kind: "pdf" | "xlsx") {
    setBusy(true);
    try {
      await downloadWithAuth(
        `/api/monitoring/${id}/audit-report.${kind}`,
        `audit-report-${id}.${kind}`
      );
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (error) return <Alert tone="error">{error}</Alert>;
  if (!report) return <Loading label="Generating audit report…" />;

  const failedChecks = report.checks.filter((check: any) => !check.passed);

  return (
    <div className="space-y-5">
      <Card className="card-pad">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <SectionHeading eyebrow="Post-election auditing" title="Comprehensive audit report">
            Generated {formatDate(report.generated_at)} from append-only election records. No voter
            identity is linked to any ballot or selection.
          </SectionHeading>
          <div className="flex gap-2">
            <button className="btn-outline" onClick={() => download("pdf")} disabled={busy}>
              PDF
            </button>
            <button className="btn-outline" onClick={() => download("xlsx")} disabled={busy}>
              Excel
            </button>
          </div>
        </div>

        <div className="rounded-xl border border-line">
          {report.checks.map((check: any) => (
            <div
              key={check.check}
              className="flex flex-col gap-1 border-b border-line/70 px-4 py-3 last:border-0 sm:flex-row sm:items-start sm:justify-between"
            >
              <div className="flex items-start gap-3">
                <span
                  className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold ${
                    check.passed ? "bg-green/12 text-green" : "bg-red-100 text-red-700"
                  }`}
                >
                  {check.passed ? "✓" : "!"}
                </span>
                <div>
                  <p className="text-sm font-medium text-ink">{check.check}</p>
                  <p className="mt-0.5 text-xs text-ink/50">{check.evidence}</p>
                </div>
              </div>
              <span className={check.passed ? "pill-green" : "pill-red"}>
                {check.passed ? "Pass" : "Review"}
              </span>
            </div>
          ))}
        </div>

        {failedChecks.length ? (
          <Alert tone="warn">
            {failedChecks.length} finding(s) require committee review before the report is signed.
          </Alert>
        ) : (
          <Alert tone="success">All audit checks passed.</Alert>
        )}
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card className="card-pad">
          <SectionHeading eyebrow="Evidence" title="Audit areas" />
          <dl className="space-y-1">
            {Object.entries(report.areas).map(([area, values]: [string, any]) => (
              <div key={area} className="kv">
                <dt className="capitalize">{area.replace(/_/g, " ")}</dt>
                <dd className="max-w-[62%] text-right text-xs">
                  {Object.entries(values)
                    .filter(([, value]) => value !== null && typeof value !== "object")
                    .map(([key, value]) => `${key.replace(/_/g, " ")}: ${value}`)
                    .join(" · ") || "see records"}
                </dd>
              </div>
            ))}
            <div className="kv">
              <dt>Configuration hash</dt>
              <dd className="code">{shortHash(report.election.configuration_hash, 14)}</dd>
            </div>
          </dl>
        </Card>

        <Card className="card-pad">
          <SectionHeading eyebrow="Security" title="Rejected and failed attempts" />
          {report.failed_attempts.length === 0 ? (
            <p className="text-sm text-ink/50">No failed attempts recorded for this election.</p>
          ) : (
            <ul className="space-y-2">
              {report.failed_attempts.slice(0, 12).map((attempt: any, index: number) => (
                <li key={index} className="rounded-lg border border-line px-3 py-2 text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-semibold text-ink">{attempt.action}</span>
                    <span className="text-ink/40">{formatDate(attempt.at)}</span>
                  </div>
                  <p className="mt-0.5 text-ink/50">
                    {attempt.ip ?? "unknown"} · {JSON.stringify(attempt.detail ?? {}).slice(0, 110)}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card className="card-pad">
        <SectionHeading eyebrow="Audit log" title="Administrative activity" />
        <div className="table-wrap max-h-[420px] overflow-y-auto">
          <table className="table">
            <thead>
              <tr>
                <th>Action</th>
                <th>Role</th>
                <th>Entity</th>
                <th>Outcome</th>
                <th>IP</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => (
                <tr key={log.id}>
                  <td className="font-mono text-[11px]">{log.action}</td>
                  <td className="text-xs capitalize">{log.actor_role ?? "—"}</td>
                  <td className="text-xs">{log.entity ?? "—"}</td>
                  <td>
                    <span className={log.outcome === "success" ? "pill-green" : "pill-red"}>
                      {log.outcome}
                    </span>
                  </td>
                  <td className="font-mono text-[11px]">{log.ip_address ?? "—"}</td>
                  <td className="text-xs">{formatDate(log.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card className="card-pad">
        <SectionHeading eyebrow="Administrative actions" title="Recorded activities" />
        <div className="table-wrap max-h-[300px] overflow-y-auto">
          <table className="table">
            <thead>
              <tr>
                <th>Action</th>
                <th>Role</th>
                <th>Entity</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {report.administrative_activities.map((activity: any, index: number) => (
                <tr key={index}>
                  <td className="font-mono text-[11px]">{activity.action}</td>
                  <td className="text-xs capitalize">{activity.role ?? "—"}</td>
                  <td className="text-xs">{activity.entity ?? "—"}</td>
                  <td className="text-xs">{formatDate(activity.at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
