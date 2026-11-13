"use client";

import {
  Archive,
  Bell,
  CalendarDays,
  Check,
  ChevronLeft,
  ChevronRight,
  Clock,
  Copy,
  FilePen,
  FileText,
  MessageSquareReply,
  RotateCcw,
  ShieldAlert,
  X,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { PageColumns } from "@/components/shell/PageColumns";
import { useRole } from "@/components/shell/RoleContext";
import { useSignals } from "@/components/shell/Signals";
import { Button, Card, Empty, ErrorNote, PageHeader, Pill, SectionLabel, SkeletonRows } from "@/components/ui/Primitives";
import { ackChange, draftDocumentEdit } from "@/lib/api";
import { cx, fmtDate, humanKey } from "@/lib/format";
import type { ChangeFeedItem, Digest, DocumentEdit, Episode, Notification } from "@/lib/types";
import { useApi } from "@/lib/useApi";

const STATUS_ICON = { provisional: Clock, confirmed: Check, rejected: ShieldAlert, retired: Archive } as const;

const NOTE_KIND: Record<string, { icon: typeof Bell; label: string }> = {
  recall: { icon: RotateCcw, label: "An answer you got has changed" },
  expert_reply: { icon: MessageSquareReply, label: "An expert replied" },
  reanswered: { icon: Check, label: "Your question has a new answer" },
};

/** Notifications for this user: answers recalled because a rule they cited changed, replies. */
function ForYou({ notes, onDismiss }: { notes: Notification[]; onDismiss: (id: number) => void }) {
  if (notes.length === 0) return null;
  return (
    <section className="mb-8" aria-label="For you">
      <SectionLabel icon={Bell}>For you</SectionLabel>
      <ul className="space-y-3">
        {notes.map((n) => {
          const kind = NOTE_KIND[n.kind] ?? { icon: Bell, label: "Update" };
          const Icon = kind.icon;
          const detail = n.question ? n.body.replace(/\s*You asked: ".*"$/, "") : n.body;
          return (
            <Card as="li" key={n.id} className="border-l-4 border-l-rose p-4">
              <div className="flex items-start gap-3">
                <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-rose/10 text-rose" aria-hidden>
                  <Icon className="h-4 w-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                    <p className="text-[15px] font-semibold text-ink">{kind.label}</p>
                    <span className="font-mono text-[11px] text-muted">{fmtDate(n.at)}</span>
                  </div>
                  {n.question && (
                    <p className="mt-1 text-sm text-ink">
                      You asked: <span className="italic">“{n.question}”</span>
                    </p>
                  )}
                  <p className="mt-1 text-sm text-muted">{detail}</p>
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    {n.question && (
                      <Link
                        href={`/?q=${encodeURIComponent(n.question)}`}
                        onClick={() => onDismiss(n.id)}
                        className="inline-flex items-center gap-1.5 rounded-full bg-ink px-3 py-1.5 text-[13px] font-medium text-surface hover:bg-ink/90"
                      >
                        <RotateCcw className="h-3.5 w-3.5" aria-hidden /> Ask again
                      </Link>
                    )}
                    {n.change_id !== null && (
                      <a
                        href={`#change-${n.change_id}`}
                        className="rounded-full border border-hairline px-3 py-1.5 text-[13px] font-medium text-ink hover:border-muted"
                      >
                        See the change
                      </a>
                    )}
                    <button
                      type="button"
                      onClick={() => onDismiss(n.id)}
                      className="ml-auto inline-flex items-center gap-1 rounded-full px-2 py-1 text-[13px] text-muted hover:text-ink"
                    >
                      <X className="h-3.5 w-3.5" aria-hidden /> Dismiss
                    </button>
                  </div>
                </div>
              </div>
            </Card>
          );
        })}
      </ul>
    </section>
  );
}

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

const isoDay = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const shiftDay = (iso: string, days: number) => {
  const [y, m, d] = iso.split("-").map(Number);
  return isoDay(new Date(y!, m! - 1, d! + days));
};

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

const DIGEST_SHOWN = 6;

/** One day's changes in one summary, with a plain-text copy for email or chat. */
function DigestCard({ userId, owner, tick }: { userId: string; owner: boolean; tick: number }) {
  const today = useMemo(() => isoDay(new Date()), []);
  const [day, setDay] = useState(today);
  const [copied, setCopied] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const offset = -new Date().getTimezoneOffset();
  const { data, error, reload } = useApi<Digest>(
    `/digest?day=${day}&utc_offset_minutes=${offset}&user_id=${encodeURIComponent(userId)}`,
  );
  useEffect(() => {
    if (tick > 0) void reload();
  }, [tick, reload]);
  const copy = async () => {
    if (data && (await copyText(data.text))) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    }
  };
  return (
    <section className="mb-8" aria-label="Daily digest">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <SectionLabel icon={CalendarDays}>Daily digest</SectionLabel>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setDay((d) => shiftDay(d, -1))}
            aria-label="Previous day"
            className="grid h-8 w-8 place-items-center rounded-full text-muted hover:bg-fill hover:text-ink"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span className="min-w-[96px] text-center font-mono text-[12px] text-ink">{fmtDate(day)}</span>
          <button
            type="button"
            onClick={() => setDay((d) => shiftDay(d, 1))}
            disabled={day >= today}
            aria-label="Next day"
            className="grid h-8 w-8 place-items-center rounded-full text-muted hover:bg-fill hover:text-ink disabled:opacity-30"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>
      <Card className="p-5">
        {error ? (
          <ErrorNote message={error} onRetry={() => void reload()} />
        ) : !data ? (
          <SkeletonRows rows={2} height="h-6" />
        ) : data.empty ? (
          <p className="text-sm text-muted">No changes to the knowledge base on this day.</p>
        ) : (
          <>
            <ul className="space-y-3">
              {(showAll ? data.rules : data.rules.slice(0, DIGEST_SHOWN)).map((r) => (
                <li key={r.id} className="text-sm leading-snug">
                  <a href={`#change-${r.id}`} className="font-medium text-ink hover:underline">
                    {r.topic ? `${r.topic} · ${humanKey(r.attribute ?? "")}` : r.summary}
                  </a>
                  {r.old_value && r.new_value ? (
                    <span className="mt-0.5 block break-words">
                      <s className="text-muted">{r.old_value}</s> <span className="text-muted">→</span>{" "}
                      <span className="font-medium text-ink">{r.new_value}</span>
                    </span>
                  ) : (
                    r.new_value && <span className="mt-0.5 block break-words font-medium text-ink">{r.new_value}</span>
                  )}
                  <span className="mt-0.5 block font-mono text-[11px] text-muted">
                    from {fmtDate(r.effective_at)}
                    {r.source_label && ` · ${r.source_label}`}
                    {r.status === "provisional" && " · provisional"}
                    {data.users > 0 && ` · seen by ${r.acknowledged} of ${data.users}`}
                    {data.to_acknowledge.includes(r.id) && !owner && " · not acknowledged by you"}
                  </span>
                </li>
              ))}
              {data.withdrawn.map((r) => (
                <li key={r.id} className="break-words text-sm text-muted">
                  {r.status === "rejected" ? "Withdrawn" : "No longer in force"}: {r.topic} · <s>{r.old_value || r.summary}</s>
                </li>
              ))}
            </ul>
            {data.rules.length > DIGEST_SHOWN && (
              <button
                type="button"
                onClick={() => setShowAll((v) => !v)}
                className="mt-3 text-[13px] font-medium text-ink underline decoration-hairline underline-offset-2 hover:decoration-ink"
              >
                {showAll ? "Show fewer" : `Show all ${data.rules.length} changes`}
              </button>
            )}
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-hairline pt-3">
              <p className="font-mono text-[11px] text-muted">
                {[
                  data.updates > 0 && `${data.updates} other knowledge updates`,
                  owner && data.document_edits.length > 0 && `${data.document_edits.length} document edit(s) to make`,
                  owner && data.waiting_review > 0 && `${data.waiting_review} waiting for review`,
                ]
                  .filter(Boolean)
                  .join(" · ") || " "}
              </p>
              <Button icon={copied ? Check : Copy} onClick={() => void copy()}>
                {copied ? "Copied" : "Copy as text"}
              </Button>
            </div>
          </>
        )}
      </Card>
    </section>
  );
}

/** The drafted edit to the document that still states the old rule: a word diff to review. */
function DocumentEditPanel({ c }: { c: ChangeFeedItem }) {
  const [busy, setBusy] = useState(false);
  const [edit, setEdit] = useState<DocumentEdit | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const target = c.document_edit!;
  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      setEdit(await draftDocumentEdit(c.id));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  if (!edit) {
    return (
      <div className="mt-4 flex flex-wrap items-center gap-3 rounded-xl bg-fill/60 px-3 py-2.5">
        <p className="min-w-0 flex-1 text-[13px] text-ink">
          <span className="font-medium">{target.document}</span>
          {target.locator && ` §${target.locator}`} still states the old rule.
        </p>
        <Button icon={FilePen} busy={busy} onClick={() => void run()}>
          {busy ? "Drafting…" : "Draft document edit"}
        </Button>
        {err && <p className="w-full text-[13px] text-rose">{err}</p>}
      </div>
    );
  }
  return (
    <div className="mt-4 rounded-xl border border-hairline">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-hairline px-4 py-2.5">
        <p className="text-[13px] font-medium text-ink">
          Suggested edit · {edit.document}
          {edit.locator && ` §${edit.locator}`}
        </p>
        <Pill icon={edit.verified ? Check : ShieldAlert}>{edit.verified ? "checked" : "check this"}</Pill>
      </div>
      <div className="px-4 py-3">
        {edit.summary && <p className="mb-2 text-[13px] text-muted">{edit.summary}</p>}
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink">
          {edit.diff.map((r, i) =>
            r.op === "equal" ? (
              <span key={i}>{r.text}</span>
            ) : r.op === "delete" ? (
              <del key={i} className="rounded bg-fill text-muted decoration-muted">
                {r.text}
              </del>
            ) : (
              <ins key={i} className="rounded bg-rose/10 font-medium text-ink no-underline">
                {r.text}
              </ins>
            ),
          )}
        </p>
        {edit.problems.length > 0 && (
          <ul className="mt-3 space-y-1 text-[13px] text-rose">
            {edit.problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        )}
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
          <span className="font-mono text-[11px] text-muted">
            Draft only: copy it into {edit.document_title || edit.document}. Nothing is changed here.
          </span>
          <Button
            icon={copied ? Check : Copy}
            onClick={() =>
              void copyText(edit.suggested_text).then((ok) => {
                if (ok) {
                  setCopied(true);
                  window.setTimeout(() => setCopied(false), 2000);
                }
              })
            }
          >
            {copied ? "Copied" : "Copy suggested text"}
          </Button>
        </div>
      </div>
    </div>
  );
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
    <Card as="li" id={`change-${c.id}`} className="scroll-mt-20 p-5 target:ring-2 target:ring-rose">
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
          {c.new_value ? (
            <span className="font-medium text-ink">{c.new_value}</span>
          ) : (
            <span className="text-muted">{c.status === "rejected" ? "withdrawn" : "no longer in force"}</span>
          )}
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
      {owner && rule && c.document_edit && <DocumentEditPanel c={c} />}
      {owner && rule && <AckMeter seen={c.acknowledged} of={users} />}
    </Card>
  );
}

export function ChangesView() {
  const { role, userId } = useRole();
  const { stats, markSeen, notes, dismiss, live, tick } = useSignals();
  // With the user's id, each change says whether this user already acknowledged it (server-side).
  const { data, error, loading, reload } = useApi<ChangeFeedItem[]>(
    `/changes?since=0&limit=200&user_id=${encodeURIComponent(userId)}`,
    live ? 0 : 10_000,
  );
  // The live stream says something moved: refetch now rather than at the next poll.
  useEffect(() => {
    if (tick > 0) void reload();
  }, [tick, reload]);
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
          <ForYou notes={notes} onDismiss={dismiss} />
          <DigestCard userId={userId} owner={owner} tick={tick} />
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
                  acked={acked.has(c.id) || Boolean(c.seen)}
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
              {["all", "provisional", "confirmed", "rejected", "retired"].map((s) =>
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
            {shown.length} of {items.length} shown · {live ? "live" : "refreshes every 10 s"}
          </p>
        </div>
      }
    />
  );
}
