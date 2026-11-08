"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { apiGet } from "@/lib/api";

export interface ApiState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => Promise<void>;
  setData: (d: T | null) => void;
}

/**
 * GET a path and keep it fresh. `interval` (ms) polls while the tab is visible; `path = null`
 * waits. Native fetch only (AGENTS.md: no utility packages for what the platform does).
 */
export function useApi<T>(path: string | null, interval?: number): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(path !== null);
  const current = useRef(path);
  current.current = path;

  const load = useCallback(async () => {
    const p = current.current;
    if (p === null) return;
    try {
      const d = await apiGet<T>(p);
      if (current.current === p) {
        setData(d);
        setError(null);
      }
    } catch (e) {
      if (current.current === p) setError((e as Error).message);
    } finally {
      if (current.current === p) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (path === null) return;
    setLoading(true);
    void load();
    if (!interval) return;
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, interval);
    return () => window.clearInterval(id);
  }, [path, interval, load]);

  return { data, error, loading, reload: load, setData };
}
