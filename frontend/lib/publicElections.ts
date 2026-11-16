"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

export type PublicElectionOption = {
  id: string;
  title: string;
  reference: string;
  year: number;
  status: string;
  status_label: string;
  opens_at: string | null;
  closes_at: string | null;
  can_accredit: boolean;
  can_vote: boolean;
};

export type PublicElectionDetail = PublicElectionOption & {
  description?: string | null;
  timezone?: string;
  voting_rules?: string | null;
  verification?: Record<string, boolean>;
  positions?: any[];
};

/**
 * Resolve the public election a member is acting on.
 *
 * If the URL carries ?election=<id> and that election is active, it wins.
 * If only one election is active, it is selected automatically. When several
 * are active and none was chosen, selectedId stays null so the page can show
 * the chooser instead of silently guessing.
 */
export function usePublicElectionChoice() {
  const [options, setOptions] = useState<PublicElectionOption[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [election, setElection] = useState<PublicElectionDetail | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api<{ elections: PublicElectionOption[] }>("/api/public/active-elections")
      .then((data) => {
        if (cancelled) return;
        const list = data.elections ?? [];
        const requested = new URLSearchParams(window.location.search).get("election");
        const requestedMatch = requested ? list.find((item) => item.id === requested) : undefined;
        setOptions(list);
        setSelectedId(requestedMatch?.id ?? (list.length === 1 ? list[0].id : null));
      })
      .catch((err: any) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setElection(null);
      return;
    }
    let cancelled = false;
    setElection(null);
    setError("");
    api<PublicElectionDetail>(`/api/public/elections/${selectedId}`)
      .then((data) => {
        if (!cancelled) setElection(data);
      })
      .catch((err: any) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const choose = useCallback((id: string) => {
    const url = new URL(window.location.href);
    url.searchParams.set("election", id);
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
    setElection(null);
    setSelectedId(id);
  }, []);

  return { options, selectedId, election, choose, loading, error };
}
