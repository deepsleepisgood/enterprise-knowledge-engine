"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

import { useRole } from "@/components/shell/RoleContext";
import { DEMO_MODE, apiGet, getChanges, getNotifications, markNotificationRead, streamUrl } from "@/lib/api";
import { safeStorageGet, safeStorageSet } from "@/lib/format";
import type { ChangeFeedItem, Notification, Stats } from "@/lib/types";

const LAST_SEEN_KEY = "ps07.lastSeenKb";
const POLL_MS = 10_000; // without the live stream (BUILD_PLAN Phase 8: polling every 10 s)
const POLL_LIVE_MS = 60_000; // with it: a slow safety net only

interface SignalState {
  /** Rule changes published after the version this browser last acknowledged. */
  unseen: ChangeFeedItem[];
  /** This user's unread notifications: answers recalled, expert replies. */
  notes: Notification[];
  stats: Stats | null;
  /** Episodes that are failed, held or waiting for review. */
  attention: number;
  /** True while the server-sent event stream is connected. */
  live: boolean;
  /** Bumps on every live update, so pages can refetch. */
  tick: number;
  markSeen: (kbVersion: number) => void;
  dismiss: (id: number) => void;
  refresh: () => void;
}

const SignalContext = createContext<SignalState>({
  unseen: [],
  notes: [],
  stats: null,
  attention: 0,
  live: false,
  tick: 0,
  markSeen: () => {},
  dismiss: () => {},
  refresh: () => {},
});

export function SignalProvider({ children }: { children: React.ReactNode }) {
  const { userId } = useRole();
  const [unseen, setUnseen] = useState<ChangeFeedItem[]>([]);
  const [notes, setNotes] = useState<Notification[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [live, setLive] = useState(false);
  const [tick, setTick] = useState(0);
  const userRef = useRef(userId);
  userRef.current = userId;

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
    const [items, mine] = await Promise.all([getChanges(seen), getNotifications(userRef.current)]);
    setUnseen(items.filter((c) => c.attribute || DEMO_MODE));
    setNotes(mine);
  }, []);

  // The user id is read from storage after mount: fetch again once it is known.
  useEffect(() => {
    void poll();
  }, [poll, userId]);

  // Live updates: the stream says when something moved; we refetch. The browser reconnects on
  // its own when the server ends the stream (every 90 s) or the network blips.
  useEffect(() => {
    const url = streamUrl(userId);
    if (!url || typeof EventSource === "undefined") return;
    const es = new EventSource(url);
    es.onopen = () => setLive(true);
    es.onerror = () => setLive(false);
    es.addEventListener("state", () => {
      setTick((t) => t + 1);
      void poll();
    });
    return () => {
      es.close();
      setLive(false);
    };
  }, [poll, userId]);

  useEffect(() => {
    const id = window.setInterval(
      () => {
        if (document.visibilityState === "visible") void poll();
      },
      live ? POLL_LIVE_MS : POLL_MS,
    );
    return () => window.clearInterval(id);
  }, [poll, live]);

  const markSeen = useCallback((kb: number) => {
    const prev = Number(safeStorageGet(LAST_SEEN_KEY) ?? "0");
    safeStorageSet(LAST_SEEN_KEY, String(Math.max(prev, kb)));
    setUnseen((u) => u.filter((c) => c.kb_version > kb));
  }, []);

  const dismiss = useCallback((id: number) => {
    setNotes((n) => n.filter((x) => x.id !== id));
    void markNotificationRead(id, userRef.current).catch(() => {});
  }, []);

  const by = stats?.episodes_by_status ?? {};
  const attention = (by.failed ?? 0) + (by.needs_attention ?? 0) + (by.pending_review ?? 0);

  return (
    <SignalContext.Provider
      value={{ unseen, notes, stats, attention, live, tick, markSeen, dismiss, refresh: () => void poll() }}
    >
      {children}
    </SignalContext.Provider>
  );
}

export const useSignals = () => useContext(SignalContext);
