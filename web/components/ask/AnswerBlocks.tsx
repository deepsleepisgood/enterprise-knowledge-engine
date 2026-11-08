"use client";

import {
  ArrowRight,
  BookUser,
  ChevronRight,
  CircleCheck,
  CircleX,
  Clock,
  Flag,
  Layers,
  Plus,
  ShieldAlert,
  UserRound,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { fmtDate } from "@/lib/format";
import type { AnswerCard, ChangeItem, Citation, ExpertTip, OlderSource, RouteTo } from "@/lib/types";

import { CitationChip } from "./CitedText";

type Activate = (n: number, scroll: boolean) => void;

const STATUS_PILL: Partial<Record<AnswerCard["status"], { text: string; icon: typeof Clock }>> = {
  provisional: { text: "Provisional — owner confirming", icon: Clock },
  unverified: { text: "Unverified — citation could not be confirmed", icon: ShieldAlert },
  needs_specialist: { text: "Needs a specialist — see route below", icon: ShieldAlert },
};

export function StatusPill({ status }: { status: AnswerCard["status"] }) {
  const pill = STATUS_PILL[status];
  if (!pill) return null;
  const Icon = pill.icon;
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-fill px-3 py-1 text-[13px] font-medium text-muted">
      <Icon className="h-3.5 w-3.5" aria-hidden />
      {pill.text}
    </span>
  );
}

export function DecisionRow({ card }: { card: AnswerCard }) {
  if (!card.decision) return null;
  const pass = !card.exception_code;
  const Icon = pass ? CircleCheck : CircleX;
  return (
    <ul className="space-y-2.5 text-[15px] leading-snug">
      <li className="flex gap-2.5">
        <Icon className="mt-0.5 h-[18px] w-[18px] shrink-0 text-rose" aria-hidden />
        <span>
          <span className="sr-only">Decision: </span>
          <span className="font-medium text-ink">{card.decision}</span>
        </span>
      </li>
      {card.exception_code && (
        <li className="flex gap-2.5">
          <CircleCheck className="mt-0.5 h-[18px] w-[18px] shrink-0 text-rose" aria-hidden />
          <span className="text-ink">
            Exception code <code className="rounded bg-fill px-1.5 py-0.5 font-mono text-[13px]">{card.exception_code}</code>
          </span>
        </li>
      )}
      {card.next_owner && (
        <li className="flex gap-2.5">
          <CircleCheck className="mt-0.5 h-[18px] w-[18px] shrink-0 text-rose" aria-hidden />
          <span className="text-ink">
            <span className="text-muted">Next: </span>
            {card.next_owner}
          </span>
        </li>
      )}
    </ul>
  );
}

const NUMERIC = /[₹\d]/;

export function WorkingCard({ rows }: { rows: AnswerCard["working"] }) {
  if (!rows?.length) return null;
  return (
    <section aria-label="Working" className="overflow-hidden rounded-2xl border border-hairline bg-surface shadow-card">
      <div className="flex justify-between border-b border-hairline px-4 py-2.5">
        <span className="eyebrow">Step</span>
        <span className="eyebrow">Value</span>
      </div>
      <dl className="divide-y divide-hairline">
        {rows.map((r) => (
          <div key={r.label} className="flex items-baseline justify-between gap-4 px-4 py-2.5 text-sm">
            <dt className="text-muted">{r.label}</dt>
            <dd className={NUMERIC.test(r.value) ? "font-mono text-[13px] text-ink" : "font-medium text-ink"}>
              {r.value}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/** One row per distinct change: several older documents saying the same old value share it. */
export function groupOlder(items: OlderSource[]): OlderSource[] {
  const by = new Map<string, OlderSource>();
  for (const o of items) {
    const key = `${o.topic}|${o.current_value}|${o.older_value}`;
    const seen = by.get(key);
    if (!seen) by.set(key, { ...o });
    else if (!seen.locator.split(", ").includes(o.locator)) seen.locator = `${seen.locator}, ${o.locator}`;
  }
  return [...by.values()];
}

export function CurrentVsOlderCard({
  items,
  firstCitation,
  active,
  onActivate,
}: {
  items: OlderSource[];
  firstCitation: Citation | undefined;
  active: number | null;
  onActivate: Activate;
}) {
  if (!items.length) return null;
  const rows = groupOlder(items);
  return (
    <section aria-label="Current rule versus older sources" className="overflow-hidden rounded-2xl border border-hairline bg-surface shadow-card">
      <div className="hidden grid-cols-[1fr_1.3fr_1.3fr] gap-4 border-b border-hairline px-4 py-2.5 sm:grid">
        <span className="eyebrow">Topic</span>
        <span className="eyebrow">Current rule</span>
        <span className="eyebrow">Older sources say</span>
      </div>
      <ul className="divide-y divide-hairline">
        {rows.map((o, i) => (
          <li key={i} className="grid gap-1.5 px-4 py-3 text-sm sm:grid-cols-[1fr_1.3fr_1.3fr] sm:gap-4">
            <span className="font-medium text-ink">{o.topic}</span>
            <span className="text-ink">
              <span className="eyebrow mr-2 sm:hidden">Now</span>
              {o.current_value}
              {firstCitation && <CitationChip citation={firstCitation} active={active === firstCitation.n} onActivate={onActivate} />}
            </span>
            <span className="text-muted">
              <span className="eyebrow mr-2 sm:hidden">Before</span>
              <s>{o.older_value}</s>
              <span className="mt-1 block font-mono text-[11px] leading-relaxed">
                {o.locator} · superseded {fmtDate(o.superseded_on)}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function ExpertTipCard({ tip, onActivate }: { tip: ExpertTip; onActivate: Activate }) {
  return (
    <section aria-label="Expert practice" className="rounded-2xl border border-hairline bg-surface p-4 shadow-card">
      <div className="flex items-center gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-fill text-muted">
          <BookUser className="h-4 w-4" aria-hidden />
        </span>
        <h3 className="eyebrow">Expert practice</h3>
      </div>
      <p className="mt-3 text-[15px] leading-[1.6] text-ink">{tip.text}</p>
      <button
        type="button"
        onClick={() => onActivate(tip.citation.n, true)}
        className="mt-3 text-left font-mono text-[11px] leading-relaxed text-muted hover:text-ink"
      >
        {tip.author} · {tip.citation.short_label}
        {tip.approved_by ? ` · approved by ${tip.approved_by}` : " · pending review"}
      </button>
    </section>
  );
}

export function NotCoveredCard({
  route,
  sent,
  sending,
  onSend,
}: {
  route: RouteTo | null;
  sent: string | null;
  sending: boolean;
  onSend: () => void;
}) {
  const role = route?.role || "the process owner";
  return (
    <div className="space-y-4">
      <p className="text-base leading-[1.65] text-ink">The documents don&apos;t cover this.</p>
      <section aria-label="Who to ask" className="rounded-2xl border border-hairline bg-surface p-4 shadow-card">
        <div className="flex items-start gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-fill text-muted">
            <UserRound className="h-[18px] w-[18px]" aria-hidden />
          </span>
          <div className="min-w-0 flex-1">
            <p className="eyebrow">Route to</p>
            <p className="mt-0.5 font-display text-lg font-semibold text-ink">{route?.role || "Process owner"}</p>
            <p className="mt-1 text-sm leading-relaxed text-muted">
              {route?.reason || "Nobody owns this topic yet, so the process owner decides who answers."}
            </p>
            {sent ? (
              <span className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-fill px-3 py-1 text-[13px] font-medium text-muted">
                <Clock className="h-3.5 w-3.5" aria-hidden />
                Sent to {sent} · waiting
              </span>
            ) : (
              <button
                type="button"
                onClick={onSend}
                disabled={sending}
                className="mt-3 inline-flex h-9 items-center gap-1.5 rounded-full border border-rose bg-surface px-4 text-sm font-medium text-rose transition-colors hover:bg-rose-tint disabled:opacity-50"
              >
                Send to {role}
                <ArrowRight className="h-4 w-4" aria-hidden />
              </button>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}

/** An expert's reply to an escalated question: shown, but clearly not yet a rule. */
export function ExpertReplyCard({ text, onDismiss }: { text: string; onDismiss: () => void }) {
  return (
    <section aria-label="Expert reply" className="rounded-2xl border border-hairline bg-surface p-4 shadow-card">
      <div className="flex items-center gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-fill text-muted">
          <BookUser className="h-4 w-4" aria-hidden />
        </span>
        <h3 className="eyebrow">Expert reply — not yet part of the knowledge base</h3>
      </div>
      <p className="mt-3 whitespace-pre-line text-[15px] leading-[1.6] text-ink">{text}</p>
      <div className="mt-3 flex items-center justify-between gap-3">
        <span className="inline-flex items-center gap-1.5 rounded-full bg-fill px-2.5 py-0.5 text-xs font-medium text-muted">
          <Clock className="h-3.5 w-3.5" aria-hidden />
          Pending owner review
        </span>
        <button type="button" onClick={onDismiss} className="text-[13px] font-medium text-muted hover:text-ink">
          Dismiss
        </button>
      </div>
    </section>
  );
}

/** "Report a wrong answer" in every card's footer: a short note to the process owner. */
export function ReportWrong({ onSend }: { onSend: (note: string) => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent">("idle");
  if (state === "sent") {
    return <p className="font-mono text-[11px] text-muted">Reported · the process owner will check this answer</p>;
  }
  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1.5 text-[13px] text-muted hover:text-ink"
      >
        <Flag className="h-3.5 w-3.5" aria-hidden />
        Report a wrong answer
      </button>
    );
  }
  return (
    <form
      className="rounded-2xl border border-hairline bg-surface p-3"
      onSubmit={async (e) => {
        e.preventDefault();
        setState("sending");
        try {
          await onSend(note.trim());
          setState("sent");
        } catch {
          setState("idle");
        }
      }}
    >
      <label htmlFor="report-note" className="eyebrow">
        What is wrong?
      </label>
      <textarea
        id="report-note"
        rows={2}
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="For example: the memo for this client says 5%, not 10%."
        className="mt-1.5 block w-full resize-none rounded-xl border border-hairline bg-canvas px-3 py-2 text-sm text-ink placeholder:text-muted focus:border-muted focus:outline-none"
      />
      <div className="mt-2 flex justify-end gap-2">
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="h-8 rounded-full px-3 text-[13px] font-medium text-muted hover:bg-fill hover:text-ink"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={state === "sending"}
          className="h-8 rounded-full border border-hairline bg-surface px-3.5 text-[13px] font-medium text-ink hover:border-muted disabled:opacity-50"
        >
          Send to the process owner
        </button>
      </div>
    </form>
  );
}

export function Related({ items, onAsk }: { items: string[]; onAsk: (q: string) => void }) {
  if (!items.length) return null;
  return (
    <section aria-labelledby="related-h" className="mt-10">
      <div className="flex items-center gap-2">
        <Layers className="h-4 w-4 text-muted" aria-hidden />
        <h2 id="related-h" className="eyebrow">
          Related
        </h2>
      </div>
      <ul className="mt-2 divide-y divide-hairline border-y border-hairline">
        {items.slice(0, 4).map((q) => (
          <li key={q}>
            <button
              type="button"
              onClick={() => onAsk(q)}
              className="group flex w-full items-center gap-3 py-3 text-left text-[15px] text-ink"
            >
              <Plus className="h-4 w-4 shrink-0 text-muted transition-colors group-hover:text-rose" aria-hidden />
              <span className="flex-1">{q}</span>
              <ChevronRight className="h-4 w-4 shrink-0 text-muted" aria-hidden />
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** "Your question was answered": an expert replied to something this user escalated. */
export function AnsweredBanner({ body, onDismiss }: { body: string; onDismiss: () => void }) {
  return (
    <div className="mb-6 flex flex-col gap-3 rounded-2xl border border-l-[3px] border-hairline border-l-rose bg-surface p-4 shadow-card sm:flex-row sm:items-center">
      <p className="flex-1 text-sm leading-relaxed text-ink">
        <span className="font-semibold">Your question was answered</span>
        <span className="text-muted"> · </span>
        <span className="whitespace-pre-line">{body}</span>
        <span className="mt-1 block font-mono text-[11px] text-muted">
          Expert reply · not yet part of the knowledge base until the owner confirms it
        </span>
      </p>
      <button
        type="button"
        onClick={onDismiss}
        className="shrink-0 self-start rounded-full border border-hairline px-3.5 py-1.5 text-sm font-medium text-ink hover:border-muted sm:self-center"
      >
        Got it
      </button>
    </div>
  );
}

export function ChangeBanner({ change, count, onAck }: { change: ChangeItem; count: number; onAck: () => void }) {
  return (
    <div className="mb-6 flex flex-col gap-3 rounded-2xl border border-l-[3px] border-hairline border-l-rose bg-surface p-4 shadow-card sm:flex-row sm:items-center">
      <p className="flex-1 text-sm leading-relaxed text-ink">
        <span className="font-semibold">
          {count === 1 ? "1 rule changed" : `${count} rules changed`} since you last looked
        </span>
        <span className="text-muted"> · </span>
        {change.topic || change.summary}{" "}
        {change.old_value && (
          <>
            <s className="text-muted">{change.old_value}</s> →{" "}
          </>
        )}
        {change.new_value} from {fmtDate(change.effective_at)}
        <span className="text-muted"> · {change.status}</span>
      </p>
      <div className="flex shrink-0 items-center gap-3">
        <Link href="/changes" className="text-sm font-medium text-rose hover:text-rose-hover">
          View change
        </Link>
        <button
          type="button"
          onClick={onAck}
          className="rounded-full border border-hairline px-3.5 py-1.5 text-sm font-medium text-ink hover:border-muted"
        >
          Got it
        </button>
      </div>
    </div>
  );
}
