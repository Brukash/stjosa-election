"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { PublicShell } from "@/components/PublicShell";
import { Alert, Card, CheckRow, Loading, StatusPill } from "@/components/ui";
import { api, formatDate } from "@/lib/api";
import {
  ChallengeCheck,
  Credential,
  clearCredential,
  loadCredential,
  verifyChallenge,
} from "@/lib/credential";

type Phase = "ballot" | "review" | "prepared" | "challenged" | "cast";

export default function VotePage() {
  const [election, setElection] = useState<any | null>(null);
  const [credential, setCredential] = useState<Credential | null>(null);
  const [selections, setSelections] = useState<Record<string, string>>({});
  const [phase, setPhase] = useState<Phase>("ballot");
  const [prepared, setPrepared] = useState<any | null>(null);
  const [receipt, setReceipt] = useState<any | null>(null);
  const [checks, setChecks] = useState<ChallengeCheck[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    api("/api/public/election")
      .then((data) => {
        setElection(data.election);
        if (data.election) setCredential(loadCredential(data.election.id));
      })
      .catch((err) => setError(err.message));
  }, []);

  const positions = election?.positions ?? [];
  const selectedCount = Object.keys(selections).length;
  const complete = selectedCount === positions.length && positions.length > 0;

  const candidateById = useMemo(() => {
    const map: Record<string, any> = {};
    positions.forEach((position: any) =>
      position.candidates.forEach((candidate: any) => {
        map[candidate.id] = candidate;
      })
    );
    return map;
  }, [positions]);

  function select(positionId: string, candidateId: string) {
    if (phase !== "ballot" && phase !== "review") return;
    setSelections((prev) => ({ ...prev, [positionId]: candidateId }));
  }

  async function prepareBallot() {
    if (!election || !credential) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const data = await api("/api/voting/prepare", {
        method: "POST",
        body: JSON.stringify({
          election_id: election.id,
          token: credential.token,
          signature: credential.signature,
          selections,
        }),
      });
      setPrepared(data);
      setPhase("prepared");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function challengeBallot() {
    if (!prepared || !credential) return;
    setBusy(true);
    setError("");
    try {
      const data = await api(`/api/voting/${prepared.prepared_id}/challenge`, {
        method: "POST",
        body: JSON.stringify({ token: credential.token, signature: credential.signature }),
      });
      const material = data.verification_material;
      const verified = await verifyChallenge(material, selections);
      setChecks(verified);
      setPhase("challenged");
      setPrepared(null);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function castBallot() {
    if (!prepared || !credential) return;
    setBusy(true);
    setError("");
    try {
      const data = await api(`/api/voting/${prepared.prepared_id}/cast`, {
        method: "POST",
        body: JSON.stringify({
          token: credential.token,
          signature: credential.signature,
          turnout_token: credential.turnout_token,
        }),
      });
      setReceipt(data);
      setPhase("cast");
      clearCredential(election.id);
      setCredential(null);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  function startFreshBallot() {
    setPrepared(null);
    setChecks(null);
    setPhase("ballot");
    setNotice("Your previous ballot was challenged and is permanently excluded. Review your selections and cast a fresh ballot.");
  }

  const open = election && election.status === "voting_open";

  return (
    <PublicShell>
      <div className="mx-auto max-w-4xl">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-green">Official ballot</p>
            <h1 className="mt-2 text-3xl text-ink">{election?.title ?? "Loading ballot…"}</h1>
            <p className="mt-1 text-xs text-ink/50">
              {election ? `Reference ${election.reference} · Closes ${formatDate(election.closes_at)}` : ""}
            </p>
          </div>
          {election ? <StatusPill status={election.status} label={election.status_label} /> : null}
        </div>

        {error ? <div className="mt-5"><Alert tone="error">{error}</Alert></div> : null}
        {notice ? <div className="mt-5"><Alert tone="warn">{notice}</Alert></div> : null}

        {!election ? (
          <Loading />
        ) : phase === "cast" && receipt ? (
          <Card className="card-pad mt-6 animate-rise">
            <div className="flex items-center gap-3">
              <span className="flex h-11 w-11 items-center justify-center rounded-full bg-green/10 text-xl text-green">
                ✓
              </span>
              <div>
                <h2 className="text-xl text-ink">Your ballot has been accepted</h2>
                <p className="text-sm text-ink/55">Keep your receipt. It proves acceptance without revealing your choices.</p>
              </div>
            </div>
            <dl className="mt-6 space-y-1">
              <div className="kv">
                <dt>Receipt number</dt>
                <dd className="font-mono text-xs">{receipt.receipt_number}</dd>
              </div>
              <div className="kv">
                <dt>Verification reference</dt>
                <dd className="font-mono text-sm font-bold">{receipt.receipt_reference}</dd>
              </div>
              <div className="kv">
                <dt>Ballot commitment</dt>
                <dd className="code max-w-[70%] text-right">{receipt.ballot_commitment}</dd>
              </div>
              <div className="kv">
                <dt>Submitted</dt>
                <dd>{formatDate(receipt.issued_at)}</dd>
              </div>
            </dl>
            <Alert tone="info">
              Your ballot is encrypted and stored without your identity. Verification confirms the
              commitment is in the published record; it never reveals your selections.
            </Alert>
            <div className="mt-5 flex flex-wrap gap-3">
              <a className="btn-primary" href={receipt.pdf_url} target="_blank" rel="noreferrer">
                Download PDF receipt
              </a>
              <Link className="btn-outline" href={`/verify?ref=${encodeURIComponent(receipt.receipt_reference)}`}>
                Verify inclusion now
              </Link>
            </div>
            <p className="mt-4 text-xs text-ink/45">
              Your voting credential has now been spent. You cannot vote again in this election.
            </p>
          </Card>
        ) : !credential ? (
          <Card className="card-pad mt-6">
            <h2 className="text-lg text-ink">You need an anonymous voting credential</h2>
            <p className="mt-2 text-sm leading-relaxed text-ink/60">
              Accredited voters receive one credential per election. Complete accreditation with your
              Voter ID, then return here to open your ballot.
            </p>
            <div className="mt-5 flex flex-wrap gap-3">
              <Link href="/accredit" className="btn-primary">
                Accredit now
              </Link>
              <Link href="/verify" className="btn-outline">
                Verify a receipt
              </Link>
            </div>
          </Card>
        ) : !open ? (
          <div className="mt-6">
            <Alert tone="warn">
              Voting is not open. The ballot becomes available when the Electoral Committee opens voting.
            </Alert>
          </div>
        ) : phase === "challenged" && checks ? (
          <Card className="card-pad mt-6 animate-rise">
            <h2 className="text-xl text-ink">Your challenge was verified in this browser</h2>
            <p className="mt-1 text-sm text-ink/55">
              The system revealed the encryption key and randomisers for the prepared ballot. Your
              browser independently recomputed the encryption — this is the cast-as-intended check.
            </p>
            <div className="mt-5">
              {checks.map((check) => (
                <CheckRow key={check.label} passed={check.passed}>
                  {check.label}
                  {check.detail ? <span className="ml-2 text-xs text-ink/40">{check.detail}</span> : null}
                </CheckRow>
              ))}
            </div>
            <Alert tone={checks.every((check) => check.passed) ? "success" : "error"}>
              {checks.every((check) => check.passed)
                ? "Every check passed. Your selections were encoded exactly as you intended. That ballot is now permanently excluded and can never be counted."
                : "One or more checks did not match. Do not trust that prepared ballot. Report this to the Electoral Committee and prepare a new ballot."}
            </Alert>
            <button className="btn-primary mt-5" onClick={startFreshBallot}>
              Prepare a fresh ballot
            </button>
          </Card>
        ) : (
          <>
            {phase === "prepared" && prepared ? (
              <Card className="card-pad mt-6 animate-rise">
                <h2 className="text-xl text-ink">Your ballot is encrypted but not yet cast</h2>
                <p className="mt-1 text-sm text-ink/60">
                  Verify the encryption, or cast this ballot. Casting is final.
                </p>
                <p className="mt-3 code">{prepared.commitment}</p>
                <div className="mt-5 flex flex-col gap-2 sm:flex-row">
                  <button className="btn-dark" onClick={castBallot} disabled={busy}>
                    {busy ? "Casting…" : "Cast my ballot"}
                  </button>
                  <button className="btn-outline" onClick={challengeBallot} disabled={busy}>
                    Verify my selections (challenge this ballot)
                  </button>
                </div>
                <p className="mt-4 text-xs leading-relaxed text-ink/45">
                  Challenging reveals cryptographic proof and permanently spoils this prepared ballot.
                  You will then prepare a fresh ballot to cast. Nothing has been counted yet.
                </p>
              </Card>
            ) : null}

            <div className="mt-6 space-y-4">
              {positions.map((position: any) => (
                <Card key={position.id} className="card-pad">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <h2 className="text-lg text-ink">{position.title}</h2>
                    <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-ink/40">
                      {position.seats === 1 ? "Choose one candidate" : `Choose up to ${position.seats}`}
                    </span>
                  </div>
                  <div className="mt-4 grid gap-3">
                    {position.candidates.map((candidate: any) => {
                      const chosen = selections[position.id] === candidate.id;
                      return (
                        <label
                          key={candidate.id}
                          className={`flex cursor-pointer gap-4 rounded-xl border p-4 transition ${
                            chosen
                              ? "border-green bg-green/[0.05] ring-2 ring-green/10"
                              : "border-line hover:border-ink/25"
                          }`}
                        >
                          <input
                            type="radio"
                            name={position.id}
                            className="sr-only"
                            checked={chosen}
                            onChange={() => select(position.id, candidate.id)}
                            disabled={phase !== "ballot" && phase !== "review"}
                          />
                          <span
                            className={`mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 ${
                              chosen ? "border-green bg-green text-[10px] text-white" : "border-line"
                            }`}
                          >
                            {chosen ? "✓" : ""}
                          </span>
                          {candidate.photo_url ? (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img
                              src={candidate.photo_url}
                              alt={candidate.full_name}
                              className="h-14 w-14 rounded-full object-cover"
                            />
                          ) : (
                            <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-ink/5 font-display text-lg text-ink/40">
                              {candidate.full_name
                                .split(" ")
                                .map((part: string) => part[0])
                                .slice(-2)
                                .join("")}
                            </span>
                          )}
                          <span className="min-w-0">
                            <span className="block text-sm font-semibold text-ink">{candidate.full_name}</span>
                            <span className="mt-1 block text-[13px] leading-relaxed text-ink/55">
                              {candidate.bio}
                            </span>
                            {candidate.manifesto ? (
                              <span className="mt-1.5 block text-[13px] leading-relaxed text-ink/45">
                                {candidate.manifesto}
                              </span>
                            ) : null}
                          </span>
                        </label>
                      );
                    })}
                  </div>
                </Card>
              ))}
            </div>

            <Card className="card-pad mt-6">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                  <p className="text-sm font-semibold text-ink">
                    {selectedCount} of {positions.length} positions selected
                  </p>
                  <p className="mt-1 text-xs text-ink/50">
                    Review your review screen carefully — a cast ballot cannot be edited.
                  </p>
                </div>
                {phase === "review" ? (
                  <div className="flex gap-2">
                    <button className="btn-ghost" onClick={() => setPhase("ballot")}>
                      Change selections
                    </button>
                    <button className="btn-primary" onClick={prepareBallot} disabled={busy || !complete}>
                      {busy ? "Encrypting…" : "Prepare encrypted ballot"}
                    </button>
                  </div>
                ) : phase === "prepared" && prepared ? (
                  <div className="flex flex-wrap gap-2">
                    <button className="btn-ghost" onClick={() => setPhase("review")}>
                      Review my selections
                    </button>
                    <button className="btn-dark" onClick={castBallot} disabled={busy}>
                      {busy ? "Casting…" : "Cast my ballot"}
                    </button>
                  </div>
                ) : (
                  <button
                    className="btn-primary"
                    onClick={() => setPhase("review")}
                    disabled={selectedCount === 0}
                  >
                    Review my selections
                  </button>
                )}
              </div>
            </Card>

            {phase === "review" ? (
              <Card className="card-pad mt-4">
                <h2 className="text-lg text-ink">Review before encryption</h2>
                <div className="mt-4 space-y-2">
                  {positions.map((position: any) => (
                    <div key={position.id} className="kv">
                      <dt>{position.title}</dt>
                      <dd>{candidateById[selections[position.id]]?.full_name ?? "No selection"}</dd>
                    </div>
                  ))}
                </div>
                {!complete ? (
                  <Alert tone="warn">
                    Select a candidate for every position before preparing your ballot.
                  </Alert>
                ) : (
                  <p className="mt-3 text-xs leading-relaxed text-ink/45">
                    On the next step you can either cast this ballot or challenge it to verify that the
                    encryption contains exactly these selections.
                  </p>
                )}
              </Card>
            ) : null}
          </>
        )}
      </div>
    </PublicShell>
  );
}
