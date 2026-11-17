"use client";

import { Card, SectionHeading, StatusPill } from "@/components/ui";
import { formatLongDate } from "@/lib/api";
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
      <SectionHeading eyebrow="Open now" title="Choose an election">
        More than one election is open. Pick the one you want to vote in.
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
              className={`flex w-full flex-col gap-3 rounded-[8px] border p-4 text-left transition sm:flex-row sm:items-center sm:justify-between ${
                selected
                  ? "border-forest bg-forest/[0.05]"
                  : "border-rule bg-surface hover:border-ink/25"
              }`}
            >
              <span className="min-w-0">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="text-[14.5px] font-semibold text-ink">{election.title}</span>
                  {selected ? (
                    <span className="text-[10px] font-semibold uppercase tracking-[0.1em] text-forest">
                      Selected
                    </span>
                  ) : null}
                </span>
                <span className="mt-1 block text-[12.5px] text-ink/55">
                  {election.status === "voting_open"
                    ? `Voting closes ${formatLongDate(election.closes_at)}`
                    : `Accreditation open · voting opens ${formatLongDate(election.opens_at)}`}
                </span>
              </span>
              <span className="flex shrink-0 items-center gap-3">
                <StatusPill status={election.status} label={election.status_label} />
                <span
                  className={`text-[12px] font-semibold ${selected ? "text-forest" : "text-ink/45"}`}
                >
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
