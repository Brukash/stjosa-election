"use client";

import { Card, SectionHeading, StatusPill } from "@/components/ui";
import { formatDate } from "@/lib/api";
import type { PublicElectionOption } from "@/lib/publicElections";

export function ElectionChooser({
  elections,
  selectedId,
  onSelect,
}: {
  elections: PublicElectionOption[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <Card className="card-pad mt-6">
      <SectionHeading eyebrow="Active elections" title="Choose an election">
        More than one election is open. Select the election you want to accredit or vote in.
      </SectionHeading>
      <div className="grid gap-3">
        {elections.map((election) => {
          const selected = election.id === selectedId;
          return (
            <button
              key={election.id}
              type="button"
              aria-pressed={selected}
              onClick={() => onSelect(election.id)}
              className={`flex w-full flex-col gap-3 rounded-xl border p-4 text-left transition sm:flex-row sm:items-center sm:justify-between ${
                selected
                  ? "border-green bg-green/[0.06] ring-2 ring-green/15"
                  : "border-line hover:border-ink/25 hover:bg-cream/40"
              }`}
            >
              <span className="min-w-0">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold text-ink">{election.title}</span>
                  {selected ? <span className="pill-green">Selected</span> : null}
                </span>
                <span className="mt-1 block text-xs text-ink/50">
                  Reference {election.reference} · {election.year}
                </span>
                <span className="mt-1 block text-xs text-ink/40">
                  {election.status === "voting_open"
                    ? `Voting closes ${formatDate(election.closes_at)}`
                    : `Accreditation open · Voting opens ${formatDate(election.opens_at)}`}
                </span>
              </span>
              <span className="flex shrink-0 items-center gap-3">
                <StatusPill status={election.status} label={election.status_label} />
                <span className={`text-xs font-semibold ${selected ? "text-green" : "text-ink/45"}`}>
                  {selected ? "Chosen" : "Choose"}
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </Card>
  );
}
