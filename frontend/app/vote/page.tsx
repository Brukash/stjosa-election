"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ElectionChooser } from "@/components/ElectionChooser";
import { PublicShell } from "@/components/PublicShell";
import { Alert, Card, CheckRow, Loading, StatusPill } from "@/components/ui";
import { api, formatDate, formatLongDate } from "@/lib/api";
import {
  ChallengeCheck,
  Credential,
  loadCredential,
  verifyChallenge,
} from "@/lib/credential";
import { usePublicElectionChoice } from "@/lib/publicElections";

type Phase = "ballot" | "review" | "prepared" | "challenged" | "cast";

export default function VotePage() {
  const { options, selectedId, election, choose, loading, error: choiceError } = usePublicElectionChoice();
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
    setSelections({});
    setPhase("ballot");
    setPrepared(null);
    setReceipt(null);
    setChecks(null);
    setNotice("");
    setError("");
    setCredential(selectedId ? loadCredential(selectedId) : null);
  }, [selectedId]);

  const positions = election?.positions ?? [];
  const selectedCount = Object.keys(selections).length;
  const complete = selectedCount === positions.length && positions.length > 0;
  const progress = positions.length ? Math.round((selectedCount / positions.length) * 100) : 0;

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
    if (!election || !prepared || !credential) return;
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
    setNotice(
      "That ballot was spoiled on purpose and can never be counted. Check your choices and cast a fresh one."
    );
  }

  const open = election && election.status === "voting_open";

  return (
    <PublicShell>
      <div className="mx-auto max-w-3xl">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="eyebrow">Official ballot</p>
            <h1 className="page-title mt-2">
              {election?.title ?? "Choose an election"}
            </h1>
            <p className="mt-1.5 text-[12.5px] text-ink/55">
              {election ? `Closes ${formatLongDate(election.closes_at)}` : ""}
            </p>
          </div>
          {election ? <StatusPill status={election.status} label={election.status_label} /> : null}
        </div>

        {error ? <div className="mt-5"><Alert tone="error">{error}</Alert></div> : null}
        {choiceError ? <div className="mt-5"><Alert tone="error">{choiceError}</Alert></div> : null}
        {notice ? <div className="mt-5"><Alert tone="warn">{notice}</Alert></div> : null}
        {loading ? <Loading label="Checking which election is open…" /> : null}

        {!loading && options?.length === 0 ? (
          <div className="mt-5">
            <Alert tone="info">No election is open for voting right now.</Alert>
          </div>
        ) : null}

        {options && options.length > 1 ? (
          <ElectionChooser elections={options} selectedId={selectedId} onSelect={choose} />
        ) : null}

        {!loading && options && options.length > 0 && !selectedId ? (
          <div className="mt-5">
            <Alert tone="info">Choose an election above to open its ballot.</Alert>
          </div>
        ) : null}

        {selectedId && !election && !choiceError ? <Loading label="Loading election…" /> : null}

        {!election ? null : phase === "cast" && receipt ? (
          /* ── Accepted ballot ─────────────────────────────────────────── */
          <div className="mt-6 animate-rise">
            <div className="rounded-[10px] border border-rule bg-surface shadow-ballot">
              <div className="flex items-start justify-between gap-4 border-b border-rule px-5 py-5 sm:px-7">
                <div>
                  <p className="eyebrow">Ballot accepted</p>
                  <p className="mt-1.5 font-display text-[24px] leading-tight text-ink">
                    Your vote is in.
                  </p>
                  <p className="mt-1 text-[13px] text-ink/60">
                    Submitted {formatDate(receipt.issued_at)}
                  </p>
                </div>
                <span
                  aria-hidden="true"
                  className="hidden shrink-0 -rotate-6 rounded-[3px] border-2 border-forest/60 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-[0.14em] text-forest sm:block"
                >
                  Accepted
                </span>
              </div>

              <div className="px-5 py-5 sm:px-7">
                <p className="text-[13px] leading-relaxed text-ink/70">
                  A confirmation may be emailed to you. Either way, keep the reference below; it is the
                  thing you need to check that this ballot appears in the published record.
                </p>

                <dl className="mt-5">
                  <div className="kv">
                    <dt>Receipt number</dt>
                    <dd className="tabular">{receipt.receipt_number}</dd>
                  </div>
                  <div className="kv">
                    <dt>Reference for checking</dt>
                    <dd className="tabular break-all text-right text-[13px]">
                      {receipt.receipt_reference}
                    </dd>
                  </div>
                  <div className="kv">
                    <dt>Election</dt>
                    <dd className="text-right text-[13px]">{election.reference}</dd>
                  </div>
                </dl>

                <div className="mt-5 flex flex-col gap-3 sm:flex-row">
                  <Link
                    className="btn-primary w-full sm:w-auto"
                    href={`/verify?ref=${encodeURIComponent(receipt.receipt_reference)}`}
                  >
                    Check my ballot now
                  </Link>
                  <a
                    className="btn-outline w-full sm:w-auto"
                    href={receipt.pdf_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Download receipt (PDF)
                  </a>
                </div>

                <p className="mt-4 text-[12px] leading-relaxed text-ink/50">
                  You cannot vote again in this election. Your choices are not stored anywhere with
                  your name.
                </p>
              </div>
            </div>
          </div>
        ) : !credential ? (
          /* ── Not accredited ──────────────────────────────────────────── */
          <Card className="card-pad mt-6">
            <h2 className="font-display text-[20px] leading-snug text-ink">
              Your ballot is not unlocked yet
            </h2>
            <p className="mt-2 text-[13.5px] leading-relaxed text-ink/65">
              Enter your Voter ID once on the accreditation page. That unlocks your ballot in this
              browser for this election.
            </p>
            <div className="mt-5 flex flex-col gap-3 sm:flex-row">
              <Link
                href={`/accredit?election=${encodeURIComponent(election.id)}`}
                className="btn-primary w-full sm:w-auto"
              >
                Enter my Voter ID
              </Link>
              <Link href="/verify" className="btn-outline w-full sm:w-auto">
                Verify a receipt
              </Link>
            </div>
          </Card>
        ) : !open ? (
          <div className="mt-6">
            <Alert tone="warn">
              Voting is not open. The ballot becomes available when the Electoral Committee opens
              voting.
            </Alert>
          </div>
        ) : phase === "challenged" && checks ? (
          /* ── Spoiled ballot, proof checked ───────────────────────────── */
          <div className="mt-6 animate-rise">
            <Card className="card-pad">
              <p className="eyebrow">Check complete</p>
              <h2 className="mt-1.5 font-display text-[22px] leading-snug text-ink">
                This ballot held exactly what you chose
              </h2>
              <p className="mt-2 text-[13.5px] leading-relaxed text-ink/65">
                Your browser decrypted the sealed ballot and compared it with your selections. That
                ballot is now spoiled on purpose and can never be counted, so you can vote again with
                confidence.
              </p>
              <div className="mt-5">
                {checks.map((check) => (
                  <CheckRow key={check.label} passed={check.passed}>
                    {check.label}
                    {check.detail ? (
                      <span className="ml-2 text-[11px] text-ink/45">{check.detail}</span>
                    ) : null}
                  </CheckRow>
                ))}
              </div>
              {!checks.every((check) => check.passed) ? (
                <div className="mt-4">
                  <Alert tone="error">
                    A check did not match. Do not trust that ballot — report this to the Electoral
                    Committee before continuing.
                  </Alert>
                </div>
              ) : null}
              <button className="btn-primary mt-5 w-full sm:w-auto" onClick={startFreshBallot}>
                Cast a fresh ballot
              </button>
            </Card>
          </div>
        ) : (
          <>
            {/* ── Sealed ballot waiting for a decision ─────────────────── */}
            {phase === "prepared" && prepared ? (
              <div className="mt-6 animate-rise">
                <div className="rounded-[10px] border border-rule bg-surface p-5 shadow-card sm:p-7">
                  <p className="eyebrow">Step 2 of 3</p>
                  <h2 className="mt-1.5 font-display text-[22px] leading-snug text-ink">
                    Your ballot is sealed
                  </h2>
                  <p className="mt-2 text-[13.5px] leading-relaxed text-ink/65">
                    Nothing has been counted yet. Cast it now, or check the sealed ballot first — the
                    check spoils this one and you mark a fresh ballot.
                  </p>
                  <div className="mt-5 flex flex-col gap-3 sm:flex-row">
                    <button className="btn-primary w-full sm:w-auto" onClick={castBallot} disabled={busy}>
                      {busy ? "Submitting…" : "Cast my ballot"}
                    </button>
                    <button
                      className="btn-outline w-full sm:w-auto"
                      onClick={challengeBallot}
                      disabled={busy}
                    >
                      Check it first
                    </button>
                  </div>
                  <details className="mt-5 border-t border-rule pt-3">
                    <summary className="cursor-pointer text-[12px] font-medium text-ink/55">
                      Ballot fingerprint
                    </summary>
                    <p className="code mt-2">{prepared.commitment}</p>
                  </details>
                </div>
              </div>
            ) : null}

            {/* ── Review ──────────────────────────────────────────────── */}
            {phase === "review" ? (
              <div className="mt-6 animate-rise">
                <Card className="card-pad">
                  <p className="eyebrow">Check before submitting</p>
                  <h2 className="mt-1.5 font-display text-[22px] leading-snug text-ink">
                    This is your ballot
                  </h2>
                  <dl className="mt-4">
                    {positions.map((position: any) => (
                      <div key={position.id} className="kv">
                        <dt className="min-w-[45%]">{position.title}</dt>
                        <dd className="text-right">
                          {candidateById[selections[position.id]]?.full_name ?? (
                            <span className="text-ink/40">No choice</span>
                          )}
                        </dd>
                      </div>
                    ))}
                  </dl>

                  {!complete ? (
                    <div className="mt-4">
                      <Alert tone="warn">
                        Choose a candidate for every position before submitting.
                      </Alert>
                    </div>
                  ) : (
                    <p className="mt-4 text-[12.5px] leading-relaxed text-ink/55">
                      Once cast, a ballot cannot be edited or withdrawn.
                    </p>
                  )}

                  <div className="mt-5 flex flex-col gap-3 sm:flex-row">
                    <button className="btn-primary w-full sm:w-auto" onClick={prepareBallot} disabled={busy || !complete}>
                      {busy ? "Sealing…" : "Submit my ballot"}
                    </button>
                    <button
                      type="button"
                      className="btn-ghost w-full sm:w-auto"
                      onClick={() => setPhase("ballot")}
                    >
                      Change my choices
                    </button>
                  </div>
                </Card>
              </div>
            ) : null}

            {/* ── Ballot sheet ────────────────────────────────────────── */}
            {phase === "ballot" ? (
              <>
                <div className="mt-6 border-t border-rule pt-5">
                  <p className="text-[13px] leading-relaxed text-ink/65">
                    Choose one candidate for each position. Your choices are highlighted as you go.
                  </p>
                </div>

                {positions.map((position: any, index: number) => (
                  <section key={position.id} className="mt-7" aria-labelledby={`pos-${position.id}`}>
                    <div className="flex items-baseline justify-between gap-3 border-b-2 border-ink/80 pb-2">
                      <h2 id={`pos-${position.id}`} className="flex items-baseline gap-3">
                        <span className="tabular text-[12px] font-semibold text-ochre">
                          {String(index + 1).padStart(2, "0")}
                        </span>
                        <span className="font-display text-[19px] leading-tight text-ink sm:text-[21px]">
                          {position.title}
                        </span>
                      </h2>
                      <span className="shrink-0 text-[10.5px] font-semibold uppercase tracking-[0.1em] text-ink/45">
                        {position.seats === 1 ? "Choose one" : `Choose up to ${position.seats}`}
                      </span>
                    </div>

                    <div className="divide-y divide-rule/80 border-b border-rule">
                      {position.candidates.map((candidate: any) => {
                        const chosen = selections[position.id] === candidate.id;
                        return (
                          <label
                            key={candidate.id}
                            className={`option-row flex cursor-pointer items-start gap-4 px-1 py-4 transition sm:px-3 ${
                              chosen ? "bg-forest/[0.05]" : "hover:bg-ink/[0.025]"
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
                              aria-hidden="true"
                              className={`mt-0.5 flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full border-2 text-[11px] transition ${
                                chosen
                                  ? "mark-pop border-forest bg-forest text-white"
                                  : "border-ink/25 bg-white"
                              }`}
                            >
                              {chosen ? "✓" : ""}
                            </span>

                            {candidate.photo_url ? (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img
                                src={candidate.photo_url}
                                alt=""
                                className="h-12 w-12 shrink-0 rounded-[3px] object-cover"
                              />
                            ) : null}

                            <span className="min-w-0">
                              <span
                                className={`block text-[15px] leading-snug ${
                                  chosen ? "font-semibold text-forest" : "font-medium text-ink"
                                }`}
                              >
                                {candidate.full_name}
                              </span>
                              {candidate.bio ? (
                                <span className="mt-1 block max-w-[72ch] text-[13.5px] leading-relaxed text-ink/60">
                                  {candidate.bio}
                                </span>
                              ) : null}
                              {candidate.manifesto ? (
                                <span className="mt-1 block max-w-[72ch] text-[13px] leading-relaxed text-ink/45">
                                  {candidate.manifesto}
                                </span>
                              ) : null}
                            </span>
                          </label>
                        );
                      })}
                    </div>
                  </section>
                ))}

                {/* Progress + action, pinned to the bottom on small screens. */}
                <div className="fixed inset-x-0 bottom-0 z-30 border-t border-rule bg-paper/95 px-4 py-3 backdrop-blur sm:static sm:mt-8 sm:rounded-[10px] sm:border sm:bg-surface sm:px-5">
                  <div
                    className="mb-2.5 h-[3px] w-full overflow-hidden rounded-full bg-ink/10"
                    role="progressbar"
                    aria-valuenow={selectedCount}
                    aria-valuemin={0}
                    aria-valuemax={positions.length}
                    aria-label="Positions chosen"
                  >
                    <div
                      className="h-full rounded-full bg-ochre transition-[width] duration-300 ease-out"
                      style={{ width: `${progress}%` }}
                    />
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-[13.5px] font-semibold text-ink">
                        {selectedCount} of {positions.length} chosen
                      </p>
                      <p className="mt-0.5 text-[11.5px] text-ink/55">
                        {complete ? "Ready to review" : "Choose one for each position"}
                      </p>
                    </div>
                    <button
                      className="btn-primary shrink-0"
                      onClick={() => setPhase("review")}
                      disabled={selectedCount === 0}
                    >
                      Review
                    </button>
                  </div>
                </div>
                {/* Space so the pinned bar never covers the last candidate. */}
                <div className="h-24 sm:hidden" aria-hidden="true" />
              </>
            ) : null}
          </>
        )}
      </div>
    </PublicShell>
  );
}
