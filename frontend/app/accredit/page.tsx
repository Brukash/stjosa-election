"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PublicShell } from "@/components/PublicShell";
import { Alert, Card, Loading, StatusPill } from "@/components/ui";
import { api, formatDate } from "@/lib/api";
import { issueCredential, storeCredential } from "@/lib/credential";

type Step = "identify" | "credential" | "ready";

export default function AccreditPage() {
  const [election, setElection] = useState<any | null>(null);
  const [loadError, setLoadError] = useState("");
  const [step, setStep] = useState<Step>("identify");
  const [voterId, setVoterId] = useState("");
  const [session, setSession] = useState<any | null>(null);
  const [credential, setCredential] = useState<any | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api("/api/public/election")
      .then((data) => setElection(data.election))
      .catch((err) => setLoadError(err.message));
  }, []);

  const accreditationOpen = ["accreditation_open", "voting_open"].includes(election?.status);

  async function verifyVoter(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const data = await api("/api/accreditation/verify-voter", {
        method: "POST",
        body: JSON.stringify({ election_id: election.id, voter_id: voterId.trim() }),
      });
      setSession(data);
      setStep("credential");
    } catch (err: any) {
      setError(err.message);
      setSession(null);
      setStep("identify");
    } finally {
      setBusy(false);
    }
  }

  async function createCredential() {
    setBusy(true);
    setError("");
    try {
      const issued = await issueCredential(election.id, election.reference, session.accreditation_token);
      storeCredential(election.id, issued);
      setCredential(issued);
      setStep("ready");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  function startOver() {
    setStep("identify");
    setSession(null);
    setCredential(null);
    setError("");
  }

  return (
    <PublicShell>
      <div className="mx-auto max-w-3xl">
        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-green">Voter accreditation</p>
        <h1 className="mt-2 text-3xl text-ink">Verify your Voter ID, then vote anonymously</h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink/60">
          Accreditation confirms you are on the approved alumni register. Enter your Voter ID once; if it
          matches the register, you can create a single anonymous voting credential. The system cannot tell
          which ballot that credential later submits.
        </p>

        {loadError ? <div className="mt-6"><Alert tone="error">{loadError}</Alert></div> : null}
        {!election && !loadError ? <Loading /> : null}

        {election ? (
          <>
            <Card className="card-pad mt-6">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-ink/45">
                    {election.title}
                  </p>
                  <p className="mt-1 text-xs text-ink/50">
                    Closes {formatDate(election.closes_at)} · Reference {election.reference}
                  </p>
                </div>
                <StatusPill status={election.status} label={election.status_label} />
              </div>
              <ol className="mt-5 grid grid-cols-3 gap-2 text-center text-[10px] font-semibold uppercase tracking-wide sm:text-[11px]">
                {["Voter ID", "Credential", "Ballot"].map((label, index) => {
                  const order = ["identify", "credential", "ready"];
                  const active = order.indexOf(step) >= index;
                  return (
                    <li
                      key={label}
                      className={`rounded-lg border px-1 py-2 ${
                        active ? "border-green/30 bg-green/[0.06] text-green" : "border-line text-ink/35"
                      }`}
                    >
                      {index + 1}. {label}
                    </li>
                  );
                })}
              </ol>
            </Card>

            {!accreditationOpen ? (
              <div className="mt-5">
                <Alert tone="warn">
                  Accreditation is not open for this election. Current status:{" "}
                  <strong>{election.status_label}</strong>.
                </Alert>
              </div>
            ) : null}

            {error ? <div className="mt-5"><Alert tone="error">{error}</Alert></div> : null}

            <Card className="card-pad mt-5">
              {step === "identify" ? (
                <form onSubmit={verifyVoter} className="space-y-5">
                  <div>
                    <label className="label" htmlFor="voter-id">
                      Voter ID
                    </label>
                    <input
                      id="voter-id"
                      className="input"
                      placeholder="e.g. SJC/AL/2004/001"
                      value={voterId}
                      onChange={(event) => setVoterId(event.target.value)}
                      autoComplete="off"
                      required
                      disabled={!accreditationOpen}
                    />
                    <p className="mt-2 text-xs leading-relaxed text-ink/45">
                      Enter the Voter ID from the approved Electoral Committee register. Your Voter ID is
                      included in the registration email sent when your entry was approved.
                    </p>
                    <p className="mt-2 text-xs leading-relaxed text-ink/45">
                      If the Voter ID matches the register, you can proceed directly. No OTP is required.
                      Contact details cannot be entered or changed here.
                    </p>
                  </div>
                  <button className="btn-primary w-full sm:w-auto" disabled={busy || !accreditationOpen}>
                    {busy ? "Checking Voter ID…" : "Verify my Voter ID"}
                  </button>
                </form>
              ) : null}

              {step === "credential" && session ? (
                <div className="space-y-5">
                  <Alert tone="success">
                    Voter ID matched the approved register. Welcome, {session.voter?.full_name}. You are
                    accredited for {session.election_reference}.
                  </Alert>
                  {session.already_issued ? (
                    <Alert tone="warn">
                      A credential has already been issued to this Voter ID. If you lost it, contact the
                      Accreditation Officer for a controlled exception.
                    </Alert>
                  ) : null}
                  <div className="rounded-xl border border-line bg-cream/60 p-4 text-sm text-ink/70">
                    <p className="font-semibold text-ink">How your anonymity is protected</p>
                    <p className="mt-1.5 leading-relaxed">
                      Your browser generates a random secret, blinds it, and asks the accreditation service
                      to sign it. The service never sees the secret, so the signed credential cannot be
                      linked back to your Voter ID or to your ballot.
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-3">
                    <button className="btn-primary" onClick={createCredential} disabled={busy || session.already_issued}>
                      {busy ? "Creating credential…" : "Create my anonymous voting credential"}
                    </button>
                    <button type="button" className="btn-ghost" onClick={startOver}>
                      Use a different Voter ID
                    </button>
                  </div>
                </div>
              ) : null}

              {step === "ready" && credential ? (
                <div className="space-y-5">
                  <Alert tone="success">
                    Your anonymous voting credential is ready and verified in this browser. It is held
                    only in this tab and will be spent when you cast your ballot.
                  </Alert>
                  <dl className="space-y-1">
                    <div className="kv">
                      <dt>Credential fingerprint</dt>
                      <dd className="font-mono text-xs">
                        {credential.signature.slice(0, 20)}…{credential.signature.slice(-8)}
                      </dd>
                    </div>
                    <div className="kv">
                      <dt>Ballot</dt>
                      <dd>{election.positions?.length ?? 0} positions</dd>
                    </div>
                  </dl>
                  <div className="flex flex-wrap gap-3">
                    <Link href="/vote" className="btn-primary">
                      Open my ballot
                    </Link>
                    <Link href="/verify" className="btn-outline">
                      Verification portal
                    </Link>
                  </div>
                </div>
              ) : null}
            </Card>

            <p className="mt-5 text-center text-xs text-ink/40">
              Having trouble? Contact the Accreditation Officer at{" "}
              <span className="font-mono">accreditation@sjcjos-alumni.org</span>.
            </p>
          </>
        ) : null}
      </div>
    </PublicShell>
  );
}
