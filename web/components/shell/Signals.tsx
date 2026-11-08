"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

import { DEMO_MODE, apiGet, getChanges } from "@/lib/api";
import { safeStorageGet, safeStorageSet } from "@/lib/format";
import type { ChangeFeedItem, Stats } from "@/lib/types";

const LAST_SEEN_KEY = "ps07.lastSeenKb";
const POLL_MS = 10_000; // BUILD_PLAN Phase 8: change polling every 10 s

interface SignalState {
  /** Rule changes published after the version this browser last acknowledged. */
  unseen: ChangeFeedItem[];
  stats: Stats | null;
  /** Episodes that are failed, held or waiting for review. */
  attention: number;
  markSeen: (kbVersion: number) => void;
  refresh: () => void;
}

const SignalContext = createContext<SignalState>({
  unseen: [],
  stats: null,
  attention: 0,
  markSeen: () => {},
  refresh: () => {},
});

export function SignalProvider({ children }: { children: React.ReactNode }) {
  const [unseen, setUnseen] = useState<ChangeFeedItem[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);

  const poll = useCallback(async () => {
    let s: Stats | null = null;
    try {
      s = await apiGet<Stats>("/stats");
      setStats(s);
    } catch {
      /* the API is down: keep the last values */
    }
    let seen = Number(safeStorageGet(LAST_SEEN_KEY));
    if (!Number.isFinite(seen) || safeStorageGet(LAST_SEEN_KEY) === null) {
      // First visit: only changes from now on are news. The demo starts one version back.
      seen = DEMO_MODE ? 41 : (s?.kb_version ?? 0);
      safeStorageSet(LAST_SEEN_KEY, String(seen));
    }
    const items = await getChanges(seen);
    setUnseen(items.filter((c) => c.attribute || DEMO_MODE));
  }, []);

  useEffect(() => {
    void poll();
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") void poll();
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [poll]);

  const markSeen = useCallback(
    (kb: number) => {
      const prev = Number(safeStorageGet(LAST_SEEN_KEY) ?? "0");
      safeStorageSet(LAST_SEEN_KEY, String(Math.max(prev, kb)));
      setUnseen((u) => u.filter((c) => c.kb_version > kb));
    },
    [],
  );

  const by = stats?.episodes_by_status ?? {};
  const attention = (by.failed ?? 0) + (by.needs_attention ?? 0) + (by.pending_review ?? 0);

  return (
    <SignalContext.Provider value={{ unseen, stats, attention, markSeen, refresh: () => void poll() }}>
      {children}
    </SignalContext.Provider>
  );
}

export const useSignals = () => useContext(SignalContext);
