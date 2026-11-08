"use client";

import { Check, GitCompare, Inbox, Loader2, Play, X } from "lucide-react";
import { useMemo, useState } from "react";

import { PageColumns } from "@/components/shell/PageColumns";
import { useRole } from "@/components/shell/RoleContext";
import { Button, Card, Empty, ErrorNote, PageHeader, Pill, SectionLabel, SkeletonRows, useToast } from "@/components/ui/Primitives";
import { apiSend } from "@/lib/api";
import { cx, fmtDate, fmtDateTime, humanKey } from "@/lib/format";
import type { Conflict, ConflictSide, ScanStatus } from "@/lib/types";
import { useApi } from "@/lib/useApi";

const KIND_LABEL: Record<string, string> = {
  value: "Different values",
  self_contradiction: "Contradicts itself",
  practice_vs_rule: "Practice vs rule",
  scope: "Scope",
};

/** "AP SOP v4.0 · 4.2", but "Video 1 [02:10]" when the locator already names the source. */
export function placeLabel(source: string | null, locator: string | null): string {
  if (!locator || locator === source) return source ?? "";
  if (source && locator.startsWith(source)) return locator;
  return source ? `${source} · ${locator}` : locator;
}

function Side({ side, authoritative }: { side: ConflictSide | null; authoritative: boolean }) {
  if (!side) return <div className="rounded-2xl bg-fill p-4 text-sm text-muted">Fact no longer available.</div>;
  return (
    <div
      className={cx(
        "flex h-full flex-col rounded-2xl border p-4",
        authoritative ? "border-hairline bg-surface" : "border-hairline bg-canvas",
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className={cx("font-mono text-[11px]", authoritative ? "text-ink" : "text-muted")}>
          {placeLabel(side.source, side.locator)}
        </span>
        {authoritative ? (
          <span className="inline-flex items-center rounded-full bg-rose px-2 py-0.5 text-[11px] font-medium text-surface">
            authoritative
          </span>
        ) : (
          <span className="font-mono text-[11px] text-muted">{side.status}</span>
        )}
      </div>
      <p className={cx("mt-2 text-[15px] font-semibold", authoritative ? "text-ink" : "text-muted")}>
        {authoritative ? side.value : <s>{side.value}</s>}
      </p>
      <p className={cx("mt-1.5 text-[13px] leading-relaxed", authoritative ? "text-ink" : "text-muted")}>
        {side.quote || side.statement}
      </p>
      {side.valid_from && (
        <p className="mt-auto pt-3 font-mono text-[11px] text-muted">from {fmtDate(side.valid_from)}</p>
      )}
    </div>
  );
}

function ConflictCard({ c, onDone }: { c: Conflict; onDone: (id: number) => void }) {
  const { userId } = useRole();
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const act = async (what: "resolved" | "dismissed" | "review") => {
    setBusy(what);
    try {
      if (what === "review") {
        await apiSend("POST", `/conflicts/${c.id}/review`, { by: userId });
        toast("Added to the review queue.");
      } else {
        await apiSend("POST", `/conflicts/${c.id}`, { status: what });
        toast(what === "resolved" ? "Marked resolved." : "Dismissed.");
        onDone(c.id);
      }
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  };
  return (
    <Card as="li" className="p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-display text-base font-semibold text-ink">
          {c.topic}
          {c.attribute && <span className="font-normal text-muted"> · {humanKey(c.attribute)}</span>}
        </h2>
        <div className="flex items-center gap-2">
          {c.scope?.client && c.scope.client !== "all" && <Pill tone="outline">{c.scope.client}</Pill>}
          <Pill>{KIND_LABEL[c.kind] ?? c.kind}</Pill>
        </div>
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <Side side={c.authoritative} authoritative />
        <Side side={c.conflicting} authoritative={false} />
      </div>
      {c.reason && <p className="mt-3 text-sm leading-relaxed text-ink">{c.reason}</p>}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
        <span className="font-mono text-[11px] text-muted">found {fmtDateTime(c.detected_at)}</span>
        <div className="flex flex-wrap gap-2">
          <Button variant="ghost" icon={X} busy={busy === "dismissed"} onClick={() => void act("dismissed")}>
            Dismiss
          </Button>
          <Button icon={Inbox} busy={busy === "review"} onClick={() => void act("review")}>
            Open in review
          </Button>
          <Button variant="primary" icon={Check} busy={busy === "resolved"} onClick={() => void act("resolved")}>
            Mark resolved
          </Button>
        </div>
      </div>
    </Card>
  );
}

export function ConflictsView() {
  const toast = useToast();
  const scan = useApi<ScanStatus>("/conflict-scan", 5000);
  const running = scan.data?.status === "queued" || scan.data?.status === "running";
  const list = useApi<Conflict[]>("/conflicts", running ? 5000 : 30_000);
  const [kind, setKind] = useState("all");
  const [source, setSource] = useState("all");
  const [hidden, setHidden] = useState<Set<number>>(new Set());

  const items = useMemo(() => (list.data ?? []).filter((c) => !hidden.has(c.id)), [list.data, hidden]);
  const kinds = useMemo(() => {
    const m = new Map<string, number>();
    for (const c of items) m.set(c.kind, (m.get(c.kind) ?? 0) + 1);
    return m;
  }, [items]);
  const sources = useMemo(() => {
    const m = new Map<string, number>();
    for (const c of items) if (c.conflicting?.source) m.set(c.conflicting.source, (m.get(c.conflicting.source) ?? 0) + 1);
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [items]);
  const shown = items.filter(
    (c) => (kind === "all" || c.kind === kind) && (source === "all" || c.conflicting?.source === source),
  );

  const run = async () => {
    try {
      const out = await apiSend<{ queued: boolean }>("POST", "/conflict-scan", {});
      toast(out.queued ? "Scan queued. Results appear here as it finishes." : "A scan is already waiting to run.");
      void scan.reload();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  const s = scan.data;
  const summary =
    s?.status === "done"
      ? `${items.length} open · last run ${fmtDateTime(s.finished_at)}${s.result?.cleared ? ` · ${s.result.cleared} cleared` : ""}`
      : s?.status === "failed"
        ? "last run failed"
        : running
          ? "scan running…"
          : `${items.length} open`;

  return (
    <PageColumns
      railLabel="Conflict filters"
      main={
        <>
          <PageHeader
            eyebrow="Conflicts"
            title="Where sources disagree"
            meta={<span>{summary}</span>}
            actions={
              <Button variant="primary" icon={running ? Loader2 : Play} disabled={running} onClick={() => void run()}>
                {running ? "Scanning" : "Run conflict scan"}
              </Button>
            }
          >
            Each card puts the rule that holds next to the statement that disagrees with it, and says why one wins: authority first, then dates.
          </PageHeader>
          {list.error ? (
            <ErrorNote message={list.error} onRetry={() => void list.reload()} />
          ) : list.loading && !list.data ? (
            <SkeletonRows rows={3} height="h-56" />
          ) : shown.length === 0 ? (
            <Empty icon={GitCompare} title="No open conflicts">
              Run a scan after new documents arrive. Resolved and dismissed conflicts stay on record.
            </Empty>
          ) : (
            <ul className="space-y-3">
              {shown.slice(0, 60).map((c) => (
                <ConflictCard key={c.id} c={c} onDone={(id) => setHidden((h) => new Set(h).add(id))} />
              ))}
            </ul>
          )}
          {shown.length > 60 && (
            <p className="mt-4 text-center font-mono text-[11px] text-muted">
              showing 60 of {shown.length} · narrow with the filters
            </p>
          )}
        </>
      }
      rail={
        <div className="space-y-6">
          <div>
            <SectionLabel>Kind</SectionLabel>
            <ul className="space-y-1">
              {[["all", items.length] as const, ...[...kinds.entries()]].map(([k, n]) => (
                <li key={k}>
                  <button
                    type="button"
                    onClick={() => setKind(k)}
                    aria-pressed={kind === k}
                    className={cx(
                      "flex w-full items-center justify-between rounded-xl px-3 py-2 text-left text-sm",
                      kind === k ? "bg-fill font-medium text-ink" : "text-ink hover:bg-fill",
                    )}
                  >
                    {k === "all" ? "All" : (KIND_LABEL[k] ?? k)}
                    <span className="font-mono text-[11px] text-muted">{n}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <SectionLabel>Disagreeing source</SectionLabel>
            <select
              value={source}
              onChange={(e) => setSource(e.target.value)}
              aria-label="Disagreeing source"
              className="w-full rounded-xl border border-hairline bg-surface px-3 py-2 text-sm text-ink focus:border-muted focus:outline-none"
            >
              <option value="all">All sources</option>
              {sources.map(([name, n]) => (
                <option key={name} value={name}>
                  {name} ({n})
                </option>
              ))}
            </select>
          </div>
        </div>
      }
    />
  );
}
