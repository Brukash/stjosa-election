"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ElectionChooser } from "@/components/ElectionChooser";
import { PublicShell } from "@/components/PublicShell";
import { Alert, Card, Loading, StatusPill } from "@/components/ui";
import { api, formatLongDate } from "@/lib/api";
import { issueCredential, storeCredential } from "@/lib/credential";
import { usePublicElectionChoice } from "@/lib/publicElections";

type Step = "identify" | "credential" | "ready";

const STEP_LABELS = ["Voter ID", "Credential", "Ballot"];

export default function AccreditPage() {
  const { options, selectedId, election, choose, loading, error: choiceError } = usePublicElectionChoice();
  const [step, setStep] = useState<Step>("identify");
  const [voterId, setVoterId] = useState("");
  const [session, setSession] = useState<any | null>(null);
  const [credential, setCredential] = useState<any | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setStep("identify");
    setSession(null);
    setCredential(null);
    setVoterId("");
    setError("");
  }, [selectedId]);

  const accreditationOpen = ["accreditation_open", "voting_open"].includes(election?.status ?? "");

  async function verifyVoter(event: React.FormEvent) {
    event.preventDefault();
    if (!election) return;
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
    if (!election) return;
    setBusy(true);
    setError("");
    try {
      const issued = await issueCredential(
        election.id,
        election.reference,
        session.accreditation_token,
        session.turnout_token
      );
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

  const stepIndex = ["identify", "credential", "ready"].indexOf(step);

  return (
    <PublicShell>
      <div className="mx-auto max-w-2xl">
        <p className="eyebrow">Accreditation</p>
        <h1 className="page-title mt-2">
          Enter your Voter ID
        </h1>
        <p className="measure mt-3 text-[14.5px] leading-relaxed text-ink/70">
          Your Voter ID is in the email the Electoral Committee sent when your registration was
          approved. It looks like <span className="tabular">SJC/AL/2004/001</span>. You do not need a
          password or a one-time code.
        </p>

        {choiceError ? <div className="mt-6"><Alert tone="error">{choiceError}</Alert></div> : null}
        {loading ? <Loading label="Checking which election is open…" /> : null}

        {!loading && options?.length === 0 ? (
          <div className="mt-6">
            <Alert tone="info">
              No election is open for accreditation right now. When the committee opens the ballot,
              it will appear here.
            </Alert>
          </div>
        ) : null}

        {options && options.length > 1 ? (
          <ElectionChooser elections={options} selectedId={selectedId} onSelect={choose} />
        ) : null}

        {!loading && options && options.length > 0 && !selectedId ? (
          <div className="mt-5">
            <Alert tone="info">Choose an election above to continue.</Alert>
          </div>
        ) : null}

        {selectedId && !election && !choiceError ? <Loading label="Loading election…" /> : null}

        {election ? (
          <>
            <div className="mt-7 border-y border-rule py-3">
              <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                <p className="min-w-0 text-[13.5px] leading-snug text-ink">
                  {election.title}
                  <span className="mt-0.5 block text-[12px] text-ink/55">
                    Closes {formatLongDate(election.closes_at)}
                  </span>
                </p>
                <StatusPill status={election.status} label={election.status_label} />
              </div>

              <ol className="mt-3 flex items-center gap-2 text-[10.5px] font-semibold uppercase tracking-[0.1em]">
                {STEP_LABELS.map((label, index) => {
                  const active = stepIndex >= index;
                  return (
                    <li
                      key={label}
                      className={`flex flex-1 items-center gap-1.5 border-t-2 pt-2 ${
                        active ? "border-ochre text-ink" : "border-rule text-ink/40"
                      }`}
                    >
                      <span className="tabular">{index + 1}</span>
                      <span className="truncate">{label}</span>
                    </li>
                  );
                })}
              </ol>
            </div>

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
                      className="input tabular"
                      placeholder="SJC/AL/2004/001"
                      value={voterId}
                      onChange={(event) => setVoterId(event.target.value)}
                      autoComplete="off"
                      autoCapitalize="characters"
                      spellCheck={false}
                      required
                      disabled={!accreditationOpen}
                    />
                    <p className="mt-2 text-[12.5px] leading-relaxed text-ink/55">
                      Type it exactly as it appears in your email. If it matches the approved register,
                      you continue straight to your ballot.
                    </p>
                  </div>
                  <button className="btn-primary w-full sm:w-auto" disabled={busy || !accreditationOpen}>
                    {busy ? "Checking…" : "Continue"}
                  </button>
                </form>
              ) : null}

              {step === "credential" && session ? (
                <div className="space-y-5">
                  <div>
                    <p className="eyebrow">Voter ID confirmed</p>
                    <p className="mt-1.5 font-display text-[20px] leading-snug text-ink">
                      Welcome, {session.voter?.full_name}.
                    </p>
                  </div>

                  {session.already_issued ? (
                    <Alert tone="warn">
                      A voting credential has already been issued to this Voter ID. If you lost it,
                      contact the Accreditation Officer for help.
                    </Alert>
                  ) : null}

                  <p className="text-[13.5px] leading-relaxed text-ink/70">
                    Next, this browser creates a private code that the committee signs without seeing.
                    Your ballot is submitted with that code, not with your name, so no one can trace the
                    ballot back to you.
                  </p>

                  <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap">
                    <button
                      className="btn-primary w-full sm:w-auto"
                      onClick={createCredential}
                      disabled={busy || session.already_issued}
                    >
                      {busy ? "Preparing…" : "Get my ballot"}
                    </button>
                    <button type="button" className="btn-ghost w-full sm:w-auto" onClick={startOver}>
                      Use a different Voter ID
                    </button>
                  </div>
                </div>
              ) : null}

              {step === "ready" && credential ? (
                <div className="space-y-5">
                  <div>
                    <p className="eyebrow">Ready to vote</p>
                    <p className="mt-1.5 font-display text-[20px] leading-snug text-ink">
                      Your ballot is unlocked in this browser.
                    </p>
                  </div>
                  <dl className="space-y-0">
                    <div className="kv">
                      <dt>Positions on the ballot</dt>
                      <dd className="tabular">{election.positions?.length ?? 0}</dd>
                    </div>
                    <div className="kv">
                      <dt>Held in</dt>
                      <dd>This tab only</dd>
                    </div>
                  </dl>
                  <p className="text-[12.5px] leading-relaxed text-ink/55">
                    Keep this tab open until you have submitted. If you close it, come back and enter
                    your Voter ID again.
                  </p>
                  <div className="flex flex-col gap-3 sm:flex-row">
                    <Link
                      href={`/vote?election=${encodeURIComponent(election.id)}`}
                      className="btn-primary w-full sm:w-auto"
                    >
                      Open my ballot
                    </Link>
                    <Link href="/verify" className="btn-outline w-full sm:w-auto">
                      How verification works
                    </Link>
                  </div>
                </div>
              ) : null}
            </Card>

            <p className="mt-6 text-center text-[12px] leading-relaxed text-ink/50">
              Having trouble? Contact the Accreditation Officer at{" "}
              <a className="font-medium text-forest underline decoration-rule underline-offset-2" href="mailto:accreditation@sjcjos-alumni.org">
                accreditation@sjcjos-alumni.org
              </a>
              .
            </p>
          </>
        ) : null}
      </div>
    </PublicShell>
  );
}
