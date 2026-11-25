"use client";

import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Alert, Card, Loading, SectionHeading, Stat } from "@/components/ui";
import { api, can, formatDate, getProfile } from "@/lib/api";

const SAMPLE = `voter_id,full_name,email,phone,whatsapp_consent,alumni_set,graduation_year
SJC/AL/2016/025,Jane Doe,jane.doe@example.com,+2348000000000,true,Lagos Chapter,2016`;

// A single click finishes the whole register: the API sends bounded batches and
// reports whatever it could not finish, and the page asks it to continue. The
// default cap is 240 voters per continuation, so a register would have to be
// enormous before this limit is reached.
const MAX_NOTICE_BATCHES = 8;

const EMPTY_VOTER = {
  voter_id: "",
  full_name: "",
  email: "",
  phone: "",
  whatsapp_consent: false,
  alumni_set: "",
  graduation_year: "",
  is_eligible: true,
};

function deliverySummary(n: any) {
  if (!n) return "";
  const deferred = n.email_deferred
    ? ` ${n.email_deferred} notice(s) are still waiting after the last batch — run this action once more to finish them.`
    : "";
  return (
    deferred +
    ` Email: ${n.email_sent ?? 0} sent, ${n.email_failed ?? 0} failed, ` +
    `${n.email_unavailable ?? 0} unavailable. ` +
    `SMS: ${n.sms_sent ?? 0} sent, ${n.sms_failed ?? 0} failed, ` +
    `${n.sms_unavailable ?? 0} unavailable. ` +
    `WhatsApp: ${n.whatsapp_sent ?? 0} sent, ${n.whatsapp_failed ?? 0} failed, ` +
    `${(n.whatsapp_unavailable ?? 0) + (n.whatsapp_no_consent ?? 0)} unavailable.`
  );
}

export default function RegisterPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const profile = getProfile();
  const isChairman = (profile?.roles ?? []).includes("chairman");
  const [data, setData] = useState<any | null>(null);
  const [csv, setCsv] = useState("");
  const [error, setError] = useState("");
  const [popup, setPopup] = useState<{ title: string; message: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [resendTarget, setResendTarget] = useState("");
  const [fixTarget, setFixTarget] = useState("");
  const [fixEmail, setFixEmail] = useState("");
  const [fixNote, setFixNote] = useState("");
  const [voterForm, setVoterForm] = useState({ ...EMPTY_VOTER });
  const [consentSelection, setConsentSelection] = useState<Set<string>>(new Set());
  const [consentSource, setConsentSource] = useState("");
  const [consentDate, setConsentDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [consentNote, setConsentNote] = useState("");

  function load() {
    api(`/api/register/${id}`, { auth: true })
      .then(setData)
      .catch((err) => setError(err.message));
  }

  useEffect(load, [id]);

  useEffect(() => {
    if (!popup) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPopup(null);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [popup]);

  async function importCsv(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setPopup(null);
    try {
      const result = await api(`/api/register/${id}/import`, {
        method: "POST",
        auth: true,
        body: JSON.stringify({ csv_text: csv }),
      });
      const rejected = (result.errors ?? []) as { line: number; error: string }[];
      const listed = rejected
        .slice(0, 8)
        .map((row) => `Line ${row.line}: ${row.error}`)
        .join(" ");
      setPopup({
        title: "Register imported",
        message:
          `${result.added} record(s) imported, ${result.skipped_duplicates} duplicate(s) skipped. ` +
          (rejected.length
            ? `${rejected.length} row(s) were rejected, including bad email addresses — ` +
              `${listed}${rejected.length > 8 ? " …" : ""} These rows are not on the register; fix them and import the file again.`
            : "No rows were rejected."),
      });
      setCsv("");
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function addVoter(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setPopup(null);
    try {
      const created = await api(`/api/register/${id}/voters`, {
        method: "POST",
        auth: true,
        body: JSON.stringify({
          voter_id: voterForm.voter_id.trim(),
          full_name: voterForm.full_name.trim(),
          email: voterForm.email.trim() || null,
          phone: voterForm.phone.trim() || null,
          whatsapp_consent: voterForm.whatsapp_consent,
          alumni_set: voterForm.alumni_set.trim() || "General",
          graduation_year: voterForm.graduation_year.trim()
            ? Number(voterForm.graduation_year)
            : null,
          is_eligible: voterForm.is_eligible,
        }),
      });
      setPopup({
        title: "Voter added",
        message:
          `${created.full_name} (${created.voter_id}) was added to the register. ` +
          "New records require register approval before accreditation.",
      });
      setVoterForm({ ...EMPTY_VOTER });
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function correctEmail(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setPopup(null);
    try {
      const result = await api(`/api/register/${id}/voters/email`, {
        method: "POST",
        auth: true,
        body: JSON.stringify({
          voter: fixTarget.trim(),
          email: fixEmail.trim(),
          note: fixNote.trim() || null,
        }),
      });
      setPopup({
        title: "Email address corrected",
        message:
          `${result.voter.full_name} (${result.voter.voter_id}) now has ${result.voter.email}. ` +
          "The previous and new address are recorded in the audit log. Send the notice to the " +
          "new address with Resend to one member.",
      });
      setFixTarget("");
      setFixEmail("");
      setFixNote("");
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  // The API works through as many paced batches as one invocation can safely
  // hold and reports the rest as deferred. This asks it to carry on until
  // nothing is left, so an approval of a large register never leaves voters
  // waiting for someone to remember to press "Resend unsent notices".
  async function finishDeferredNotices(start: any) {
    const summary: any = { ...(start ?? {}) };
    let batches = 1;
    while (!summary.error && (summary.email_deferred ?? 0) > 0 && batches < MAX_NOTICE_BATCHES) {
      let next: any;
      try {
        next = await api(`/api/register/${id}/notifications/retry`, {
          method: "POST",
          auth: true,
        });
      } catch (err: any) {
        // The approval (or the first batch) already happened: report the
        // notices that are still waiting instead of hiding that behind an error.
        summary.continuation_error = err.message;
        break;
      }
      const more = next.notifications ?? {};
      for (const [key, value] of Object.entries(more)) {
        if (typeof value !== "number" || key === "voters") continue;
        // Sent and failed counts describe one run, so they add up across the
        // batches; everything else describes where the register stands now.
        const perRun =
          (key.endsWith("_sent") || key.endsWith("_failed")) && !key.endsWith("_already_sent");
        summary[key] = perRun ? (summary[key] ?? 0) + value : value;
      }
      summary.voters = more.voters ?? summary.voters;
      batches += 1;
    }
    return { summary, batches };
  }

  async function approveRegister() {
    setBusy(true);
    setError("");
    try {
      const result = await api(`/api/register/${id}/approve`, { method: "POST", auth: true });
      const { summary: n, batches } = await finishDeferredNotices(result.notifications);
      const delivery = deliverySummary(n);
      if (n?.error) setError(`Register approved, but ${n.error}.`);
      else if (n?.continuation_error)
        setError(
          `Register approved, but the remaining notices could not be sent: ${n.continuation_error}. ` +
            `Run Resend unsent notices to finish them.`,
        );
      setPopup({
        title: "Register approved",
        message:
          `${result.approved} voter(s) approved; ${result.excluded} excluded.` +
          (batches > 1 ? ` Notices went out in ${batches} batches.` : "") +
          delivery,
      });
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function resendNotices() {
    setBusy(true);
    setError("");
    setPopup(null);
    try {
      const result = await api(`/api/register/${id}/notifications/retry`, {
        method: "POST",
        auth: true,
      });
      const { summary: n, batches } = await finishDeferredNotices(result.notifications);
      if (n?.error) setError(`Registration notices were not sent: ${n.error}.`);
      else if (n?.continuation_error)
        setError(
          `Some notices could not be sent: ${n.continuation_error}. ` +
            `Run this action again to finish them.`,
        );
      setPopup({
        title: "Registration notices retried",
        message:
          `${result.voters} approved voter(s) checked.` +
          (result.register_locked
            ? " The register is locked, so only notices that had not been delivered were sent."
            : " Notices that had already been delivered were skipped.") +
          (batches > 1 ? ` Sent in ${batches} batches.` : "") +
          deliverySummary(n),
      });
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function resendOne(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setPopup(null);
    try {
      const result = await api(`/api/register/${id}/notifications/resend`, {
        method: "POST",
        auth: true,
        body: JSON.stringify({ voter: resendTarget.trim() }),
      });
      if (result.delivery?.status === "sent") {
        setPopup({
          title: "Registration email resent",
          message: `${result.voter.full_name} (${result.voter.voter_id}) — sent to ${result.voter.email}.`,
        });
        setResendTarget("");
      } else {
        setError(
          `The email to ${result.voter.full_name} (${result.voter.voter_id}) was not delivered: ` +
            `${result.delivery?.error ?? "unknown error"}. Try again in a few minutes.`,
        );
      }
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

  async function toggleWhatsappConsent(voter: any) {
    setBusy(true);
    setError("");
    try {
      await api(`/api/register/voters/${voter.id}`, {
        method: "PATCH",
        auth: true,
        body: JSON.stringify({
          whatsapp_consent: !voter.whatsapp_consent,
          note: "WhatsApp consent recorded by the Electoral Committee",
        }),
      });
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  function toggleConsentSelection(voterId: string, checked: boolean) {
    setConsentSelection((current) => {
      const next = new Set(current);
      if (checked) next.add(voterId);
      else next.delete(voterId);
      return next;
    });
  }

  function selectAllUnconsented() {
    if (!data) return;
    setConsentSelection(
      new Set(
        data.voters
          .filter((voter: any) => voter.phone && !voter.whatsapp_consent)
          .map((voter: any) => voter.id)
      )
    );
  }

  async function recordBulkConsent() {
    if (!data || !consentSelection.size || !consentSource.trim() || !consentDate) return;
    setBusy(true);
    setError("");
    setPopup(null);
    try {
      const result = await api(`/api/register/${id}/whatsapp-consent`, {
        method: "POST",
        auth: true,
        body: JSON.stringify({
          voter_ids: Array.from(consentSelection),
          source: consentSource.trim(),
          consent_date: consentDate,
          note: consentNote.trim() || null,
        }),
      });
      const skipped =
        (result.skipped_already_consented ?? 0) +
        (result.skipped_no_phone ?? 0) +
        (result.skipped_unknown ?? 0);
      setPopup({
        title: "WhatsApp consent recorded",
        message:
          `${result.recorded} voter(s) now have WhatsApp consent recorded.` +
          (skipped ? ` ${skipped} selected voter(s) were skipped.` : "") +
          " No messages were sent.",
      });
      setConsentSelection(new Set<string>());
      setConsentNote("");
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
  const registerLocked = Boolean(data.election.locked_at);
  const unconsentedWithPhone = data.voters.filter(
    (voter: any) => voter.phone && !voter.whatsapp_consent
  );

  return (
    <div className="space-y-5">
      {error ? <Alert tone="error">{error}</Alert> : null}

      {popup ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4 backdrop-blur-sm"
          role="presentation"
          onClick={() => setPopup(null)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="register-result-title"
            className="w-full max-w-lg rounded-2xl border border-rule bg-white p-6 shadow-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-green">
                  Completed
                </p>
                <h2 id="register-result-title" className="mt-1 font-display text-2xl text-ink">
                  {popup.title}
                </h2>
              </div>
              <button
                type="button"
                className="rounded-full p-1 text-2xl leading-none text-ink/40 transition hover:bg-ink/[0.05] hover:text-ink"
                onClick={() => setPopup(null)}
                aria-label="Close popup"
                autoFocus
              >
                ×
              </button>
            </div>
            <p className="mt-3 text-sm leading-relaxed text-ink/70">{popup.message}</p>
            <button type="button" className="btn-dark mt-6 w-full" onClick={() => setPopup(null)}>
              Done
            </button>
          </div>
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
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
              <a className="btn-ghost" href="/voter_register_template.csv" download>
                Download CSV template
              </a>
            </div>
            <p className="text-xs text-ink/45">
              Required columns: <span className="font-mono">voter_id, full_name</span>. Optional:{" "}
              <span className="font-mono">email, phone, whatsapp_consent, alumni_set, graduation_year</span>.
              Use the template to keep the header row exact.
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
            accreditation; changes are locked once the first ballot is cast. Approval also sends
            a registration notice by email, SMS and WhatsApp where a contact, consent and provider
            are available.
          </p>
          {canApprove ? (
            <button className="btn-dark mt-4 w-full" onClick={approveRegister} disabled={busy}>
              Approve register
            </button>
          ) : null}
          {canApprove && data.election.register_approved ? (
            <>
              <button className="btn-ghost mt-3 w-full" onClick={resendNotices} disabled={busy}>
                {busy ? "Sending…" : "Resend unsent notices"}
              </button>
              <p className="mt-2 text-xs text-ink/45">
                Sends only to voters whose registration notice was not delivered. Safe after the
                register locks, because it never changes who is registered.
              </p>
            </>
          ) : null}
          {canApprove ? (
            <form onSubmit={resendOne} className="mt-5 rounded-lg border border-rule p-4">
              <label className="label" htmlFor="resend-voter">
                Resend to one member
              </label>
              <div className="flex flex-wrap gap-2">
                <input
                  id="resend-voter"
                  className="input min-w-[180px] flex-1"
                  value={resendTarget}
                  onChange={(event) => setResendTarget(event.target.value)}
                  placeholder="Voter ID or email address"
                />
                <button className="btn-outline" disabled={busy || !resendTarget.trim()}>
                  {busy ? "Sending…" : "Resend email"}
                </button>
              </div>
              <p className="mt-2 text-xs text-ink/45">
                Sends only this voter&apos;s registration email. Use it when a member reports the
                notice never arrived or a send failed. Safe after the register locks.
              </p>
            </form>
          ) : null}
          {canApprove ? (
            <form onSubmit={correctEmail} className="mt-4 rounded-lg border border-rule p-4">
              <label className="label" htmlFor="fix-email-voter">
                Correct a member&apos;s email
              </label>
              <div className="grid gap-2 sm:grid-cols-2">
                <input
                  id="fix-email-voter"
                  className="input"
                  value={fixTarget}
                  onChange={(event) => setFixTarget(event.target.value)}
                  placeholder="Voter ID or current email"
                />
                <input
                  type="email"
                  className="input"
                  value={fixEmail}
                  onChange={(event) => setFixEmail(event.target.value)}
                  placeholder="Correct email address"
                />
              </div>
              <div className="mt-2 flex flex-wrap gap-2">
                <input
                  className="input min-w-[180px] flex-1"
                  value={fixNote}
                  onChange={(event) => setFixNote(event.target.value)}
                  placeholder="Reason (optional, e.g. member's written request)"
                />
                <button
                  className="btn-outline"
                  disabled={busy || !fixTarget.trim() || !fixEmail.trim()}
                >
                  {busy ? "Saving…" : "Correct email"}
                </button>
              </div>
              <p className="mt-2 text-xs text-ink/45">
                Changes only this voter&apos;s address, and records the old and new values in the
                audit log. Allowed after the register locks, because an address cannot change
                eligibility. An address that cannot receive mail is refused with the reason.
              </p>
            </form>
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

      {isChairman && !registerLocked ? (
        <Card className="card-pad">
          <SectionHeading eyebrow="WhatsApp consent" title="Record consent for existing voters">
            Select voters in the table, then record the source and date of their WhatsApp opt-in.
            Each selected voter receives an individual audit entry.
          </SectionHeading>
          <div className="grid gap-4 sm:grid-cols-3">
            <div>
              <label className="label">Consent source *</label>
              <input
                className="input"
                value={consentSource}
                onChange={(event) => setConsentSource(event.target.value)}
                placeholder="Email reply, phone call, signed form"
              />
            </div>
            <div>
              <label className="label">Consent date *</label>
              <input
                type="date"
                className="input"
                value={consentDate}
                max={new Date().toISOString().slice(0, 10)}
                onChange={(event) => setConsentDate(event.target.value)}
              />
            </div>
            <div>
              <label className="label">Audit note (optional)</label>
              <input
                className="input"
                value={consentNote}
                onChange={(event) => setConsentNote(event.target.value)}
                placeholder="Reference or committee note"
              />
            </div>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <button
              type="button"
              className="btn-primary"
              onClick={recordBulkConsent}
              disabled={busy || !consentSelection.size || !consentSource.trim() || !consentDate}
            >
              {busy
                ? "Recording…"
                : `Record consent for ${consentSelection.size} voter(s)`}
            </button>
            <button
              type="button"
              className="btn-outline"
              onClick={selectAllUnconsented}
              disabled={busy || unconsentedWithPhone.length === 0}
            >
              Select all unconsented ({unconsentedWithPhone.length})
            </button>
            <button
              type="button"
              className="btn-ghost"
              onClick={() => setConsentSelection(new Set<string>())}
              disabled={busy || !consentSelection.size}
            >
              Clear selection
            </button>
          </div>
          <p className="mt-3 text-xs text-ink/45">
            This records consent only. It does not approve the register or send messages. Use a
            source and date you can evidence if the consent is challenged.
          </p>
        </Card>
      ) : null}

      {canImport ? (
        <Card className="card-pad">
          <SectionHeading eyebrow="Single registration" title="Register one voter">
            Add an alumnus individually when they are not part of a batch file. New records are
            marked as imported and must be approved before they can accredit.
          </SectionHeading>
          <form onSubmit={addVoter} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div>
              <label className="label">Voter ID *</label>
              <input
                className="input font-mono"
                value={voterForm.voter_id}
                onChange={(event) => setVoterForm({ ...voterForm, voter_id: event.target.value })}
                placeholder="SJC/AL/2016/025"
                required
              />
            </div>
            <div>
              <label className="label">Full name *</label>
              <input
                className="input"
                value={voterForm.full_name}
                onChange={(event) => setVoterForm({ ...voterForm, full_name: event.target.value })}
                placeholder="Jane Doe"
                required
              />
            </div>
            <div>
              <label className="label">Alumni set</label>
              <input
                className="input"
                value={voterForm.alumni_set}
                onChange={(event) => setVoterForm({ ...voterForm, alumni_set: event.target.value })}
                placeholder="Lagos Chapter"
              />
            </div>
            <div>
              <label className="label">Email</label>
              <input
                type="email"
                className="input"
                value={voterForm.email}
                onChange={(event) => setVoterForm({ ...voterForm, email: event.target.value })}
                placeholder="jane.doe@example.com"
              />
            </div>
            <div>
              <label className="label">Phone</label>
              <input
                className="input"
                value={voterForm.phone}
                onChange={(event) => setVoterForm({ ...voterForm, phone: event.target.value })}
                placeholder="+2348000000000"
              />
            </div>
            <div>
              <label className="label">Graduation year</label>
              <input
                type="number"
                min={1900}
                max={2100}
                className="input"
                value={voterForm.graduation_year}
                onChange={(event) =>
                  setVoterForm({ ...voterForm, graduation_year: event.target.value })
                }
                placeholder="2016"
              />
            </div>
            <label className="flex items-center gap-2 self-end pb-2 text-sm text-ink/70">
              <input
                type="checkbox"
                className="h-4 w-4 accent-green"
                checked={voterForm.is_eligible}
                onChange={(event) =>
                  setVoterForm({ ...voterForm, is_eligible: event.target.checked })
                }
              />
              Eligible to vote
            </label>
            <label className="flex items-center gap-2 self-end pb-2 text-sm text-ink/70">
              <input
                type="checkbox"
                className="h-4 w-4 accent-green"
                checked={voterForm.whatsapp_consent}
                onChange={(event) =>
                  setVoterForm({ ...voterForm, whatsapp_consent: event.target.checked })
                }
              />
              WhatsApp consent recorded
            </label>
            <div className="flex flex-wrap items-center gap-3 sm:col-span-2 lg:col-span-2">
              <button
                className="btn-primary"
                disabled={busy || !voterForm.voter_id.trim() || !voterForm.full_name.trim()}
              >
                {busy ? "Adding…" : "Add voter"}
              </button>
              <span className="text-[11px] text-ink/45">
                Email is required for the registration notice; phone plus WhatsApp consent enables WhatsApp.
              </span>
            </div>
          </form>
        </Card>
      ) : null}

      <Card className="card-pad">
        <SectionHeading eyebrow="Electoral register" title={`${voters.length} voter record(s)`} />
        {/* Phones: the same records as stacked cards, so no voter's status or
            action sits off-screen behind a sideways scroll. */}
        <div className="space-y-2 sm:hidden">
          {voters.map((voter: any) => (
            <div key={voter.id} className="rounded-[8px] border border-rule bg-surface p-3">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="font-mono text-[11px] text-ink/50">{voter.voter_id}</p>
                  <p className="mt-0.5 text-[14px] font-medium leading-snug text-ink">{voter.full_name}</p>
                  <p className="mt-0.5 break-all text-[11px] text-ink/45">
                    {voter.email ?? voter.phone ?? "—"}
                  </p>
                  {voter.email_problem ? (
                    <span className="pill-red mt-1 inline-block" title={voter.email_problem}>
                      invalid email
                    </span>
                  ) : null}
                </div>
                <span className={voter.register_status === "approved" ? "pill-green" : "pill-grey"}>
                  {voter.register_status}
                </span>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-rule/70 pt-2 text-[11px] text-ink/55">
                <span>Set <span className="font-medium text-ink/75">{voter.alumni_set}</span></span>
                <span>
                  WhatsApp <span className="font-medium text-ink/75">{voter.whatsapp_consent ? "opted in" : "no consent"}</span>
                </span>
                <span>
                  Accredited <span className="font-medium text-ink/75">{voter.accredited ? "yes" : "no"}</span>
                </span>
                {!voter.is_eligible ? <span className="pill-red">ineligible</span> : null}
              </div>
              <div className="mt-2 break-words text-[11px] leading-relaxed text-ink/50">
                {voter.last_notice ? (
                  <>
                    <span
                      className={
                        voter.last_notice.status === "sent" ? "pill-green" : "pill-red"
                      }
                    >
                      notice {voter.last_notice.status}
                    </span>{" "}
                    {formatDate(voter.last_notice.at)} · {voter.last_notice.attempts} attempt(s)
                    · <span className="font-mono text-[10.5px]">{voter.last_notice.recipient_masked}</span>
                    {voter.last_notice.error ? (
                      <span className="mt-1 block text-red-700">{voter.last_notice.error}</span>
                    ) : null}
                  </>
                ) : (
                  <span className="text-ink/35">No registration email attempt recorded</span>
                )}
              </div>
              {(canApprove || (isChairman && !registerLocked)) ? (
                <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2">
                  {canApprove && !registerLocked && voter.phone ? (
                    <button
                      className="text-[11px] font-semibold text-ink/50 underline hover:text-ink"
                      onClick={() => toggleWhatsappConsent(voter)}
                      disabled={busy}
                    >
                      {voter.whatsapp_consent ? "Withdraw WhatsApp consent" : "Record WhatsApp consent"}
                    </button>
                  ) : null}
                  {canApprove ? (
                    <button
                      className="text-[11px] font-semibold text-ink/50 underline hover:text-ink"
                      onClick={() => toggleEligibility(voter)}
                      disabled={busy}
                    >
                      {voter.is_eligible ? "Exclude" : "Include"}
                    </button>
                  ) : null}
                  {isChairman && !registerLocked && voter.phone && !voter.whatsapp_consent ? (
                    <label className="flex items-center gap-1.5 text-[11px] text-ink/55">
                      <input
                        type="checkbox"
                        className="h-4 w-4 accent-green"
                        checked={consentSelection.has(voter.id)}
                        onChange={(event) =>
                          toggleConsentSelection(voter.id, event.target.checked)
                        }
                      />
                      Select for bulk consent
                    </label>
                  ) : null}
                </div>
              ) : null}
            </div>
          ))}
        </div>
        <div className="table-wrap hidden sm:block">
          <table className="table">
            <thead>
              <tr>
                {isChairman && !registerLocked ? <th>Select</th> : null}
                <th>Voter ID</th>
                <th>Name</th>
                <th>Alumni set</th>
                <th>Status</th>
                <th>WhatsApp</th>
                <th>Accredited</th>
                <th>Last notice</th>
                {canApprove ? <th /> : null}
              </tr>
            </thead>
            <tbody>
              {voters.map((voter: any) => (
                <tr key={voter.id}>
                  {isChairman && !registerLocked ? (
                    <td>
                      {voter.phone && !voter.whatsapp_consent ? (
                        <input
                          type="checkbox"
                          className="h-4 w-4 accent-green"
                          checked={consentSelection.has(voter.id)}
                          onChange={(event) =>
                            toggleConsentSelection(voter.id, event.target.checked)
                          }
                          aria-label={`Select ${voter.full_name} for WhatsApp consent`}
                        />
                      ) : null}
                    </td>
                  ) : null}
                  <td className="font-mono text-xs">{voter.voter_id}</td>
                  <td>
                    <span className="font-medium text-ink">{voter.full_name}</span>
                    <span className="mt-0.5 block text-[11px] text-ink/45">{voter.email ?? voter.phone}</span>
                    {voter.email_problem ? (
                      <span className="pill-red mt-1 inline-block" title={voter.email_problem}>
                        invalid email
                      </span>
                    ) : null}
                  </td>
                  <td className="text-xs">{voter.alumni_set}</td>
                  <td>
                    <span className={voter.register_status === "approved" ? "pill-green" : "pill-grey"}>
                      {voter.register_status}
                    </span>
                    {!voter.is_eligible ? <span className="pill-red ml-1">ineligible</span> : null}
                  </td>
                  <td>
                    {voter.whatsapp_consent ? (
                      <span className="pill-green">Opted in</span>
                    ) : (
                      <span className="pill-grey">No consent</span>
                    )}
                    {canApprove && !registerLocked && voter.phone ? (
                      <button
                        className="ml-2 text-[10px] font-semibold text-ink/45 underline hover:text-ink"
                        onClick={() => toggleWhatsappConsent(voter)}
                        disabled={busy}
                      >
                        {voter.whatsapp_consent ? "Withdraw" : "Record"}
                      </button>
                    ) : null}
                  </td>
                  <td>{voter.accredited ? <span className="pill-green">yes</span> : <span className="text-xs text-ink/35">no</span>}</td>
                  <td className="text-xs">
                    {voter.last_notice ? (
                      <div className="max-w-[200px]">
                        <span
                          className={
                            voter.last_notice.status === "sent" ? "pill-green" : "pill-red"
                          }
                        >
                          {voter.last_notice.status}
                        </span>
                        <span className="mt-1 block text-[11px] text-ink/50">
                          {formatDate(voter.last_notice.at)} · {voter.last_notice.attempts} attempt(s)
                        </span>
                        <span className="mt-0.5 block break-all font-mono text-[10.5px] text-ink/45">
                          {voter.last_notice.recipient_masked}
                        </span>
                        {voter.last_notice.error ? (
                          <span
                            className="mt-0.5 block text-[11px] leading-snug text-red-700"
                            title={voter.last_notice.error}
                          >
                            {voter.last_notice.error}
                          </span>
                        ) : null}
                      </div>
                    ) : (
                      <span className="text-ink/35">no attempt</span>
                    )}
                  </td>
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
