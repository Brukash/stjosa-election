"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PublicShell } from "@/components/PublicShell";
import { Alert, Card, Loading, StatusPill } from "@/components/ui";
import { api, formatDate } from "@/lib/api";
import { issueCredential, storeCredential } from "@/lib/credential";

type Step = "identify" | "otp" | "credential" | "ready";

const maskName = (fullName: string) =>
  fullName
    .split(" ")
    .map((part) => (part.length > 1 ? part[0] + "•".repeat(Math.min(part.length - 1, 5)) : part))
    .join(" ");

export default function AccreditPage() {
  const [election, setElection] = useState<any | null>(null);
  const [loadError, setLoadError] = useState("");
  const [step, setStep] = useState<Step>("identify");
  const [voterId, setVoterId] = useState("");
  const [otp, setOtp] = useState("");
  const [challenge, setChallenge] = useState<any | null>(null);
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

  async function requestOtp(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const data = await api("/api/accreditation/request-otp", {
        method: "POST",
        body: JSON.stringify({ election_id: election.id, voter_id: voterId.trim() }),
      });
      setChallenge(data);
      setStep("otp");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function verifyOtp(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const data = await api("/api/accreditation/verify-otp", {
        method: "POST",
        body: JSON.stringify({
          election_id: election.id,
          voter_id: voterId.trim(),
          challenge_id: challenge.challenge_id,
          otp: otp.trim(),
        }),
      });
      setSession(data);
      setStep("credential");
    } catch (err: any) {
      setError(err.message);
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

  return (
    <PublicShell>
      <div className="mx-auto max-w-3xl">
        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-green">Voter accreditation</p>
        <h1 className="mt-2 text-3xl text-ink">Verify your identity, then vote anonymously</h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink/60">
          Accreditation confirms you are on the approved alumni register. A single anonymous voting
          credential is issued to your Voter ID — the system cannot tell which ballot that credential
          later submits.
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
              <ol className="mt-5 grid grid-cols-4 gap-2 text-center text-[11px] font-semibold uppercase tracking-wide">
                {["Identify", "OTP", "Credential", "Ballot"].map((label, index) => {
                  const order = ["identify", "otp", "credential", "ready"];
                  const active = order.indexOf(step) >= index;
                  return (
                    <li
                      key={label}
                      className={`rounded-lg border px-2 py-2 ${
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
                <form onSubmit={requestOtp} className="space-y-5">
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
                    <p className="mt-2 text-xs text-ink/45">
                      Use the Voter ID exactly as it appears on the Electoral Committee register. A
                      one-time password is sent by email (or SMS) to the contact on file.
                    </p>
                  </div>
                  <button className="btn-primary w-full sm:w-auto" disabled={busy || !accreditationOpen}>
                    {busy ? "Sending OTP…" : "Send one-time password"}
                  </button>
                </form>
              ) : null}

              {step === "otp" ? (
                <form onSubmit={verifyOtp} className="space-y-5">
                  <Alert tone="info">
                    {challenge?.message ? (
                      challenge.message
                    ) : (
                      <>
                        An OTP was sent to <strong>{challenge?.delivery}</strong>.
                      </>
                    )}{" "}
                    It expires in {Math.round((challenge?.expires_in ?? 300) / 60)} minutes and can
                    be used once.
                  </Alert>
                  {challenge?.dev_otp ? (
                    <div className="rounded-xl border border-dashed border-gold/50 bg-gold/[0.07] px-4 py-3 text-sm">
                      <p className="font-semibold text-[#5C4A00]">Local development delivery</p>
                      <p className="mt-1 text-[#5C4A00]/80">
                        Your OTP is{" "}
                        <span className="font-mono text-base font-bold tracking-[0.2em]">
                          {challenge.dev_otp}
                        </span>
                      </p>
                      <p className="mt-2 text-[11px] leading-relaxed text-[#5C4A00]/70">
                        Shown only because the backend is in local development on a loopback origin.
                        Production sends a real email or SMS and never displays the code.
                      </p>
                    </div>
                  ) : null}
                  <div>
                    <label className="label" htmlFor="otp">
                      6-digit one-time password
                    </label>
                    <input
                      id="otp"
                      className="input max-w-[240px] text-center font-mono text-xl tracking-[0.4em]"
                      inputMode="numeric"
                      pattern="[0-9]*"
                      maxLength={6}
                      value={otp}
                      onChange={(event) => setOtp(event.target.value.replace(/\D/g, ""))}
                      required
                    />
                  </div>
                  <div className="flex flex-wrap gap-3">
                    <button className="btn-primary" disabled={busy || otp.length !== 6}>
                      {busy ? "Verifying…" : "Verify OTP"}
                    </button>
                    <button
                      type="button"
                      className="btn-ghost"
                      onClick={() => {
                        setStep("identify");
                        setChallenge(null);
                        setOtp("");
                        setError("");
                      }}
                    >
                      Use a different Voter ID
                    </button>
                  </div>
                </form>
              ) : null}

              {step === "credential" && session ? (
                <div className="space-y-5">
                  <Alert tone="success">
                    Identity verified. Welcome, {session.voter?.full_name}. You are accredited for{" "}
                    {session.election_reference}.
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
                      Your browser generates a random secret, blinds it, and asks the accreditation
                      service to sign it. The service never sees the secret, so the signed credential
                      cannot be linked back to your Voter ID or to your ballot.
                    </p>
                  </div>
                  <button className="btn-primary" onClick={createCredential} disabled={busy || session.already_issued}>
                    {busy ? "Creating credential…" : "Create my anonymous voting credential"}
                  </button>
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
