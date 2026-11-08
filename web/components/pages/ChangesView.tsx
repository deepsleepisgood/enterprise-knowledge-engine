"use client";

import { Bell, Check, Clock, FileText, ShieldAlert } from "lucide-react";
import { useMemo, useState } from "react";

import { PageColumns } from "@/components/shell/PageColumns";
import { useRole } from "@/components/shell/RoleContext";
import { useSignals } from "@/components/shell/Signals";
import { Button, Card, Empty, ErrorNote, PageHeader, Pill, SectionLabel, SkeletonRows } from "@/components/ui/Primitives";
import { ackChange } from "@/lib/api";
import { cx, fmtDate, humanKey } from "@/lib/format";
import type { ChangeFeedItem, Episode } from "@/lib/types";
import { useApi } from "@/lib/useApi";

const STATUS_ICON = { provisional: Clock, confirmed: Check, rejected: ShieldAlert } as const;

function AckMeter({ seen, of }: { seen: number; of: number }) {
  const pct = of ? Math.min(100, Math.round((seen / of) * 100)) : 0;
  return (
    <div className="mt-4">
      <div className="flex justify-between font-mono text-[11px] text-muted">
        <span>
          {seen} of {of || "?"} have seen this
        </span>
        <span>{pct}%</span>
      </div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-fill" role="meter" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Acknowledged">
        <div className="h-full rounded-full bg-rose" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

/** Batch records ("extraction of <episode id>: 2 new, …") in words people read. */
function readable(summary: string, names: Map<string, string>): string {
  const m = summary.match(/^extraction of ([0-9a-f]{8,}): (.*)$/i);
  if (m) return `${names.get(m[1]!) ?? "A new document"} read: ${m[2]}`;
  const r = summary.match(/^re-resolution of every group: (.*)$/i);
  if (r) return `Authority re-checked across all rules: ${r[1]}`;
  return summary.charAt(0).toUpperCase() + summary.slice(1);
}

function ChangeCard({ c, owner, users, onAck, acked, names }: {
  c: ChangeFeedItem;
  owner: boolean;
  users: number;
  onAck: () => void;
  acked: boolean;
  names: Map<string, string>;
}) {
  const Icon = STATUS_ICON[c.status] ?? Clock;
  const hasValues = Boolean(c.old_value || c.new_value);
  const rule = Boolean(c.attribute);
  return (
    <Card as="li" className="p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 font-mono text-[11px] text-muted">
          <span>kb v{c.kb_version}</span>
          <span aria-hidden>·</span>
          <span>from {fmtDate(c.effective_at)}</span>
        </div>
        <Pill icon={Icon}>{rule ? c.status : "knowledge update"}</Pill>
      </div>
      <h2 className={cx("mt-2 font-display font-semibold leading-snug text-ink", rule ? "text-lg" : "text-[15px]")}>
        {rule ? `${c.topic} · ${humanKey(c.attribute!)}` : readable(c.summary, names)}
      </h2>
      {rule && <p className="mt-1 text-sm text-muted">{c.summary}</p>}
      {hasValues && (
        <p className="mt-3 flex flex-wrap items-baseline gap-2 text-[15px]">
          {c.old_value && <s className="text-muted">{c.old_value}</s>}
          {c.old_value && <span className="text-muted" aria-hidden>→</span>}
          <span className="font-medium text-ink">{c.new_value}</span>
        </p>
      )}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        {c.source_label ? (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-hairline px-2.5 py-1 font-mono text-[11px] text-muted">
            <FileText className="h-3 w-3" aria-hidden />
            {c.source_label}
          </span>
        ) : (
          <span />
        )}
        {!owner &&
          rule &&
          (acked ? (
            <span className="inline-flex items-center gap-1 text-[13px] text-muted">
              <Check className="h-3.5 w-3.5" aria-hidden /> Seen
            </span>
          ) : (
            <Button onClick={onAck}>Got it</Button>
          ))}
      </div>
      {owner && rule && <AckMeter seen={c.acknowledged} of={users} />}
    </Card>
  );
}

export function ChangesView() {
  const { role, userId } = useRole();
  const { stats, markSeen } = useSignals();
  const { data, error, loading, reload } = useApi<ChangeFeedItem[]>("/changes?since=0&limit=200", 10_000);
  const [status, setStatus] = useState<string>("all");
  const [rulesOnly, setRulesOnly] = useState(false);
  const episodes = useApi<Episode[]>("/episodes");
  const names = useMemo(
    () => new Map((episodes.data ?? []).map((e) => [e.id, (e.source_uri ?? e.id).split(/[\\/]/).pop() ?? e.id])),
    [episodes.data],
  );
  const [topic, setTopic] = useState("all");
  const [acked, setAcked] = useState<Set<number>>(new Set());
  const owner = role === "owner";

  const items = useMemo(() => data ?? [], [data]);
  const topics = useMemo(
    () => Array.from(new Set(items.filter((c) => c.attribute).map((c) => c.topic))).sort(),
    [items],
  );
  const shown = items.filter(
    (c) =>
      (!rulesOnly || c.attribute) &&
      (status === "all" || c.status === status) &&
      (topic === "all" || c.topic === topic),
  );

  const ack = async (c: ChangeFeedItem) => {
    setAcked((s) => new Set(s).add(c.id));
    markSeen(c.kb_version);
    await ackChange(c.id, userId).catch(() => {});
    void reload();
  };

  const filterBtn = (value: string, current: string, set: (v: string) => void, label: string) => (
    <button
      key={value}
      type="button"
      onClick={() => set(value)}
      aria-pressed={current === value}
      className={cx(
        "rounded-full border px-3 py-1 text-[13px] font-medium transition-colors",
        current === value ? "border-ink bg-fill text-ink" : "border-hairline bg-surface text-ink hover:border-muted",
      )}
    >
      {label}
    </button>
  );

  return (
    <PageColumns
      railLabel="Change filters"
      main={
        <>
          <PageHeader
            eyebrow="Changes"
            title="What changed in the rules"
            meta={stats && <span>kb v{stats.kb_version}</span>}
          >
            Every published change, newest first: the old value, the new one, when it applies from and where it came from.
          </PageHeader>
          {error ? (
            <ErrorNote message={error} onRetry={() => void reload()} />
          ) : loading && !data ? (
            <SkeletonRows rows={4} height="h-32" />
          ) : shown.length === 0 ? (
            <Empty icon={Bell} title="No changes to show">
              When a new document, email or approved reply changes a rule, it appears here.
            </Empty>
          ) : (
            <ul className="space-y-3">
              {shown.map((c) => (
                <ChangeCard
                  key={c.id}
                  c={c}
                  owner={owner}
                  users={stats?.users ?? 0}
                  acked={acked.has(c.id)}
                  names={names}
                  onAck={() => void ack(c)}
                />
              ))}
            </ul>
          )}
        </>
      }
      rail={
        <div className="space-y-6">
          <div>
            <SectionLabel>Status</SectionLabel>
            <div className="flex flex-wrap gap-2">
              {["all", "provisional", "confirmed", "rejected"].map((s) =>
                filterBtn(s, status, setStatus, s === "all" ? "All" : s[0]!.toUpperCase() + s.slice(1)),
              )}
            </div>
          </div>
          <div>
            <SectionLabel>Topic</SectionLabel>
            <select
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              aria-label="Topic"
              className="w-full rounded-xl border border-hairline bg-surface px-3 py-2 text-sm text-ink focus:border-muted focus:outline-none"
            >
              <option value="all">All topics</option>
              {topics.map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </div>
          <label className="flex items-center gap-2 text-sm text-ink">
            <input type="checkbox" checked={rulesOnly} onChange={(e) => setRulesOnly(e.target.checked)} className="accent-rose" />
            Rule changes only
          </label>
          <p className="font-mono text-[11px] text-muted">
            {shown.length} of {items.length} shown · refreshes every 10 s
          </p>
        </div>
      }
    />
  );
}
