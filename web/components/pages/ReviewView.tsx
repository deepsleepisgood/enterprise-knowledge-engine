"use client";

import { Check, Clock, FileWarning, GitCompare, Inbox, MessageSquareReply, Send, ShieldAlert, Trash2, X } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { placeLabel } from "@/components/pages/ConflictsView";
import { PageColumns } from "@/components/shell/PageColumns";
import { useRole } from "@/components/shell/RoleContext";
import { Button, Card, Empty, ErrorNote, PageHeader, Pill, SectionLabel, SkeletonRows, useToast } from "@/components/ui/Primitives";
import { ApiError, apiSend } from "@/lib/api";
import { cx, fmtAgo, fmtDate, plural } from "@/lib/format";
import type { ConflictSide, Escalation, ReviewItem } from "@/lib/types";
import { useApi } from "@/lib/useApi";

const KIND: Record<string, { label: string; icon: typeof Inbox }> = {
  change: { label: "Rule change", icon: ShieldAlert },
  conflict: { label: "Conflict", icon: GitCompare },
  tacit: { label: "Expert practice", icon: MessageSquareReply },
  schema: { label: "Schema proposal", icon: FileWarning },
  metadata: { label: "Low-confidence metadata", icon: FileWarning },
  report: { label: "Reported answer", icon: ShieldAlert },
  retire: { label: "Retire passages", icon: Trash2 },
  question: { label: "Escalated question", icon: MessageSquareReply },
};

const str = (v: unknown) => (typeof v === "string" ? v : v === null || v === undefined ? "" : JSON.stringify(v));

function Sides({ a, b }: { a: ConflictSide | null; b: ConflictSide | null }) {
  return (
    <div className="mt-3 grid gap-2 sm:grid-cols-2">
      {[a, b].map((s, i) =>
        s ? (
          <div key={i} className={cx("rounded-xl border border-hairline p-3", i ? "bg-canvas" : "bg-surface")}>
            <p className="font-mono text-[11px] text-muted">
              {placeLabel(s.source, s.locator)}
            </p>
            <p className={cx("mt-1 text-sm font-medium", i ? "text-muted" : "text-ink")}>{i ? <s>{s.value}</s> : s.value}</p>
          </div>
        ) : null,
      )}
    </div>
  );
}

/** What changed, rendered for each kind of item. Removed text struck through, added underlined. */
function ItemBody({ item }: { item: ReviewItem }) {
  const p = item.payload;
  switch (item.kind) {
    case "metadata": {
      const values = (p.values ?? {}) as Record<string, unknown>;
      return (
        <div className="mt-2 text-sm text-ink">
          <p>
            The engine is unsure of the {((p.fields as string[]) ?? []).join(", ").replace(/_/g, " ")} of{" "}
            <span className="font-semibold">{str(p.label)}</span>.
          </p>
          <p className="mt-1.5 font-mono text-[11px] text-muted">
            {Object.entries(values)
              .map(([k, v]) => `${k.replace(/_/g, " ")}: ${str(v) || "unknown"}`)
              .join(" · ")}
          </p>
          <Link href="/sources" className="mt-2 inline-block text-[13px] font-medium text-rose hover:text-rose-hover">
            Correct it on Sources
          </Link>
        </div>
      );
    }
    case "retire":
      return (
        <p className="mt-2 text-sm text-ink">
          {str(p.summary)}{" "}
          <span className="font-mono text-[11px] text-muted">{plural(((p.passage_ids as string[]) ?? []).length, "passage")}</span>
        </p>
      );
    case "conflict":
      return (
        <div className="mt-2 text-sm text-ink">
          <p>{str(p.summary)}</p>
          <Sides a={p.authoritative as ConflictSide} b={p.conflicting as ConflictSide} />
        </div>
      );
    case "report":
      return (
        <div className="mt-2 text-sm text-ink">
          <p className="font-medium">&ldquo;{str(p.question)}&rdquo;</p>
          <p className="mt-1 font-mono text-[11px] text-muted">reported by {str(p.reported_by)} · answer {str(p.answer_id)}</p>
        </div>
      );
    case "change": {
      const before = str(p.old_value ?? p.before);
      const after = str(p.new_value ?? p.after);
      return (
        <div className="mt-2 text-sm text-ink">
          <p>{str(p.summary)}</p>
          {(before || after) && (
            <p className="mt-2 rounded-xl bg-canvas p-3 leading-relaxed">
              {before && <s className="text-muted">{before}</s>} {after && <span className="underline decoration-ink underline-offset-2">{after}</span>}
            </p>
          )}
          {Boolean(p.sender || p.channel) && (
            <p className="mt-1.5 font-mono text-[11px] text-muted">
              {[str(p.sender), str(p.channel), p.effective ? `from ${fmtDate(str(p.effective))}` : ""].filter(Boolean).join(" · ")}
            </p>
          )}
        </div>
      );
    }
    default:
      return <p className="mt-2 text-sm text-ink">{str(p.summary) || str(p).slice(0, 240)}</p>;
  }
}

function ReviewRow({ item, onDecided }: { item: ReviewItem; onDecided: () => void }) {
  const { userId } = useRole();
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const meta = KIND[item.kind] ?? { label: item.kind, icon: Inbox };
  const decide = async (decision: "approve" | "reject") => {
    setBusy(decision);
    try {
      await apiSend("POST", `/review/${item.id}`, { decision, by: userId, row_version: item.row_version });
      toast(decision === "approve" ? "Approved." : "Rejected.");
      onDecided();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        toast("Someone else just decided this item. The list has been refreshed.", "error");
        onDecided();
      } else toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  };
  return (
    <Card as="li" className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Pill icon={meta.icon} tone="ink">
          {meta.label}
        </Pill>
        <span className="font-mono text-[11px] text-muted">
          #{item.id} · {fmtAgo(item.created_at)}
        </span>
      </div>
      <ItemBody item={item} />
      <div className="mt-4 flex justify-end gap-2">
        <Button icon={X} busy={busy === "reject"} onClick={() => void decide("reject")}>
          Reject
        </Button>
        <Button variant="primary" icon={Check} busy={busy === "approve"} onClick={() => void decide("approve")}>
          Approve
        </Button>
      </div>
    </Card>
  );
}

/** An escalated question: the expert's reply box replaces Approve and Reject. */
function QuestionRow({ e, onDone }: { e: Escalation; onDone: () => void }) {
  const { userId } = useRole();
  const toast = useToast();
  const [text, setText] = useState("");
  const [effective, setEffective] = useState("");
  const [scope, setScope] = useState(e.client ?? "");
  const [busy, setBusy] = useState<string | null>(null);
  const found = e.found as { reason?: string; passages?: { label?: string; locator?: string; score?: number }[]; note?: string };
  const closest = (found.passages ?? [])
    .slice(0, 3)
    .map((x) => x.label ?? x.locator)
    .filter((x): x is string => Boolean(x));
  const send = async () => {
    setBusy("send");
    try {
      await apiSend("POST", `/escalations/${e.id}/reply`, {
        expert_id: userId,
        text: text.trim(),
        expert_role: e.routed_to_role,
        effective: effective || null,
        scope: scope || null,
      });
      toast("Reply sent to the asker. It enters the knowledge base only after review.");
      onDone();
    } catch (err) {
      toast((err as Error).message, "error");
    } finally {
      setBusy(null);
    }
  };
  const close = async () => {
    setBusy("close");
    try {
      await apiSend("POST", `/escalations/${e.id}/close`, { by: userId });
      onDone();
    } catch (err) {
      toast((err as Error).message, "error");
    } finally {
      setBusy(null);
    }
  };
  return (
    <Card as="li" className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Pill icon={MessageSquareReply} tone="ink">
          {e.kind === "report" ? "Reported answer" : "Escalated question"}
        </Pill>
        <span className="flex items-center gap-1.5 font-mono text-[11px] text-muted">
          <Clock className="h-3 w-3" aria-hidden /> waiting {fmtAgo(e.created_at).replace(" ago", "")}
        </span>
      </div>
      <p className="mt-3 font-display text-base font-semibold leading-snug text-ink">&ldquo;{e.question}&rdquo;</p>
      <p className="mt-1 font-mono text-[11px] text-muted">
        {[e.asked_by, e.client, `to ${e.routed_to_role}`].filter(Boolean).join(" · ")}
      </p>
      {(found.reason || found.note || found.passages?.length) && (
        <div className="mt-3 rounded-xl bg-canvas p-3 text-[13px] text-muted">
          {found.note && <p className="text-ink">Note: {found.note}</p>}
          {found.reason && <p>Why the engine did not answer: {found.reason}</p>}
          {closest.length > 0 && <p className="mt-1 font-mono text-[11px]">closest passages: {closest.join(" · ")}</p>}
        </div>
      )}
      <label htmlFor={`reply-${e.id}`} className="eyebrow mt-4 block">
        Your answer
      </label>
      <textarea
        id={`reply-${e.id}`}
        rows={3}
        value={text}
        onChange={(ev) => setText(ev.target.value)}
        placeholder="Answer in plain words, and say where the rule comes from if you know."
        className="mt-1.5 block w-full resize-y rounded-xl border border-hairline bg-surface px-3 py-2 text-sm text-ink placeholder:text-muted focus:border-muted focus:outline-none"
      />
      <div className="mt-2 flex flex-wrap items-end gap-2">
        <label className="text-[12px] text-muted">
          Effective from
          <input
            type="date"
            value={effective}
            onChange={(ev) => setEffective(ev.target.value)}
            className="mt-1 block rounded-xl border border-hairline bg-surface px-2.5 py-1.5 font-mono text-[12px] text-ink focus:border-muted focus:outline-none"
          />
        </label>
        <label className="text-[12px] text-muted">
          Scope
          <input
            value={scope}
            onChange={(ev) => setScope(ev.target.value)}
            placeholder="all clients"
            className="mt-1 block w-40 rounded-xl border border-hairline bg-surface px-2.5 py-1.5 text-[13px] text-ink placeholder:text-muted focus:border-muted focus:outline-none"
          />
        </label>
        <div className="ml-auto flex gap-2">
          <Button variant="ghost" busy={busy === "close"} onClick={() => void close()}>
            Close without reply
          </Button>
          <Button variant="primary" icon={Send} busy={busy === "send"} disabled={!text.trim()} onClick={() => void send()}>
            Send
          </Button>
        </div>
      </div>
    </Card>
  );
}

const TIER_ORDER = ["high", "medium", "normal", "low"];

export function ReviewView() {
  const items = useApi<ReviewItem[]>("/review-queue", 15_000);
  const questions = useApi<Escalation[]>("/escalations?status=open", 15_000);
  const [kind, setKind] = useState("all");

  const list = useMemo(() => items.data ?? [], [items.data]);
  // Reports also arrive as review items; this list is the questions experts answer.
  const qs = useMemo(() => (questions.data ?? []).filter((e) => e.kind !== "report"), [questions.data]);
  const counts = useMemo(() => {
    const m = new Map<string, number>();
    for (const i of list) m.set(i.kind, (m.get(i.kind) ?? 0) + 1);
    if (qs.length) m.set("question", qs.length);
    return m;
  }, [list, qs]);

  const tiers = useMemo(() => {
    const shown = list.filter((i) => kind === "all" || i.kind === kind);
    const by = new Map<string, ReviewItem[]>();
    for (const i of shown) by.set(i.risk_tier, [...(by.get(i.risk_tier) ?? []), i]);
    return [...by.entries()].sort((a, b) => TIER_ORDER.indexOf(a[0]) - TIER_ORDER.indexOf(b[0]));
  }, [list, kind]);
  const showQuestions = (kind === "all" || kind === "question") && qs.length > 0;
  const total = list.length + qs.length;
  const reload = () => {
    void items.reload();
    void questions.reload();
  };

  return (
    <PageColumns
      railLabel="Review filters"
      main={
        <>
          <PageHeader eyebrow="Review queue" title="Decisions waiting for you" meta={<span>{plural(total, "item")}</span>}>
            Nothing changes the rules until it is approved here. High-risk items come first; questions experts can answer have a reply box.
          </PageHeader>
          {items.error ? (
            <ErrorNote message={items.error} onRetry={reload} />
          ) : items.loading && !items.data ? (
            <SkeletonRows rows={3} height="h-36" />
          ) : total === 0 ? (
            <Empty icon={Inbox} title="All clear">
              New rule changes, conflicts, schema proposals and escalated questions land here.
            </Empty>
          ) : (
            <div className="space-y-8">
              {showQuestions && (
                <section>
                  <SectionLabel icon={MessageSquareReply} count={qs.length}>
                    Questions for experts
                  </SectionLabel>
                  <ul className="space-y-3">
                    {qs.map((e) => (
                      <QuestionRow key={e.id} e={e} onDone={reload} />
                    ))}
                  </ul>
                </section>
              )}
              {kind !== "question" &&
                tiers.map(([tier, rows]) => (
                  <section key={tier}>
                    <SectionLabel icon={tier === "high" ? ShieldAlert : undefined} count={rows.length}>
                      {tier === "high" ? "High risk" : tier === "normal" ? "Normal" : tier}
                    </SectionLabel>
                    <ul className="space-y-3">
                      {rows.map((i) => (
                        <ReviewRow key={`${i.id}-${i.row_version}`} item={i} onDecided={reload} />
                      ))}
                    </ul>
                  </section>
                ))}
            </div>
          )}
        </>
      }
      rail={
        <div>
          <SectionLabel>Kind</SectionLabel>
          <ul className="space-y-1">
            {[["all", total] as const, ...[...counts.entries()]].map(([k, n]) => (
              <li key={k}>
                <button
                  type="button"
                  onClick={() => setKind(k)}
                  aria-pressed={kind === k}
                  className={cx(
                    "flex w-full items-center justify-between rounded-xl px-3 py-2 text-left text-sm text-ink",
                    kind === k ? "bg-fill font-medium" : "hover:bg-fill",
                  )}
                >
                  {k === "all" ? "Everything" : (KIND[k]?.label ?? k)}
                  <span className="font-mono text-[11px] text-muted">{n}</span>
                </button>
              </li>
            ))}
          </ul>
          <p className="mt-6 text-[13px] leading-relaxed text-muted">
            Approving records your decision. Publishing approved changes to the live rules arrives with governance (Phase 9).
          </p>
        </div>
      }
    />
  );
}
