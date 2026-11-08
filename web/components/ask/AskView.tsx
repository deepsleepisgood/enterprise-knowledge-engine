"use client";

import { ArrowUpRight, Search, Sparkles } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { PageColumns } from "@/components/shell/PageColumns";
import { useRole } from "@/components/shell/RoleContext";
import { useSignals } from "@/components/shell/Signals";
import { useToast } from "@/components/ui/Primitives";
import {
  DEMO_MODE,
  DemoMissError,
  SAMPLES,
  ackChange,
  apiGet,
  apiSend,
  ask,
  escalate,
  getContext,
  getScopes,
  reportWrong,
} from "@/lib/api";
import { cx, fmtDate, plural } from "@/lib/format";
import {
  ALL_SCOPE,
  type AnswerCard,
  type Citation,
  type ClientKey,
  type InvoiceContext,
  type Notification,
  type Scope,
} from "@/lib/types";

import {
  AnsweredBanner,
  ChangeBanner,
  CurrentVsOlderCard,
  DecisionRow,
  ExpertReplyCard,
  ExpertTipCard,
  groupOlder,
  NotCoveredCard,
  Related,
  ReportWrong,
  StatusPill,
  WorkingCard,
} from "./AnswerBlocks";
import { CitedText } from "./CitedText";
import { Composer } from "./Composer";
import { DocGlyph } from "./DocGlyph";
import { OlderSourceItem, SourceChipStrip, SourceDrawer, SourcesRail } from "./Sources";

type Tab = "answer" | "sources" | "history";
type Failure = { kind: "demo" } | { kind: "error"; message: string };

function Skeleton() {
  return (
    <div aria-hidden className="space-y-3">
      <div className="flex gap-2">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-8 w-32 animate-pulse rounded-full bg-fill" />
        ))}
      </div>
      {[0, 1, 2].map((i) => (
        <div key={i} className="space-y-2 pt-3">
          <div className="h-3.5 w-full animate-pulse rounded bg-fill" />
          <div className="h-3.5 w-11/12 animate-pulse rounded bg-fill" />
          <div className="h-3.5 w-2/3 animate-pulse rounded bg-fill" />
        </div>
      ))}
    </div>
  );
}

/** The notification body carries its own label; the cards show the label themselves. */
const replyText = (body: string) => body.replace(/^Expert reply[^:]*:\s*/, "");

function clientLabel(scopes: Scope[], key: string | null): string {
  return scopes.find((c) => c.key === (key ?? "all"))?.label ?? key ?? ALL_SCOPE.label;
}

/** "Rule in force on 1 Mar 2026 — superseded since 1 Apr 2026" for dated answers. */
function asOfLine(card: AnswerCard): string | null {
  if (!card.as_of) return null;
  const base = `Rule in force on ${fmtDate(card.as_of)}`;
  return card.superseded_since ? `${base} — superseded since ${fmtDate(card.superseded_since)}` : base;
}

/** First screen: what the engine can do, with sample questions to start from. */
function Welcome({ onAsk }: { onAsk: (q: string) => void }) {
  const { stats } = useSignals();
  return (
    <div>
      <div className="flex items-center gap-1.5">
        <Sparkles className="h-4 w-4 text-rose" aria-hidden />
        <span className="eyebrow text-ink">Ask</span>
      </div>
      <h1 className="mt-3 font-display text-[28px] font-bold leading-[1.15] tracking-tight text-ink md:text-[34px]">
        What do you need to check?
      </h1>
      <p className="mt-3 max-w-prose text-[15px] leading-[1.65] text-muted">
        Answers come only from your documents, with the exact section, timestamp or row they rest on.
        Set a date to see the rule that was in force then.
      </p>
      {stats && (
        <p className="mt-4 font-mono text-[11px] text-muted">
          {plural(stats.documents, "document")} · {plural(stats.facts, "fact")} · kb v{stats.kb_version}
        </p>
      )}
      <section aria-labelledby="try-h" className="mt-8">
        <h2 id="try-h" className="eyebrow">
          Try
        </h2>
        <ul className="mt-2 divide-y divide-hairline border-y border-hairline">
          {SAMPLES.map((s) => (
            <li key={s.question}>
              <button
                type="button"
                onClick={() => onAsk(s.question)}
                className="group flex w-full items-center gap-3 py-3 text-left text-[15px] text-ink"
              >
                <Search className="h-4 w-4 shrink-0 text-muted transition-colors group-hover:text-rose" aria-hidden />
                <span className="flex-1">{s.question}</span>
                <ArrowUpRight className="h-4 w-4 shrink-0 text-muted" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

export function AskView() {
  const { userId, role } = useRole();
  const { unseen, markSeen } = useSignals();
  const toast = useToast();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const [question, setQuestion] = useState<string | null>(null);
  const [card, setCard] = useState<AnswerCard | null>(null);
  const [loading, setLoading] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [active, setActive] = useState<number | null>(1);
  const [tab, setTab] = useState<Tab>("answer");
  const [client, setClient] = useState<ClientKey>("all");
  const [invoice, setInvoice] = useState<InvoiceContext | null>(null);
  const [drawer, setDrawer] = useState<Citation | null>(null);
  const [scopes, setScopes] = useState<Scope[]>([ALL_SCOPE]);
  const [asOf, setAsOf] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [replies, setReplies] = useState<Notification[]>([]);
  const [shownReply, setShownReply] = useState<Notification | null>(null);
  const started = useRef(false);

  const run = useCallback(
    async (q: string, opts: { asOf?: string | null } = {}) => {
      const when = opts.asOf !== undefined ? opts.asOf : asOf;
      setQuestion(q);
      setLoading(true);
      setFailure(null);
      setTab("answer");
      setSentTo(null);
      setShownReply(null);
      const next = new URLSearchParams({ q });
      if (when) next.set("as_of", when);
      router.replace(`${pathname}?${next.toString()}`, { scroll: false });
      try {
        const result = await ask({
          question: q,
          userId,
          client,
          invoiceId: invoice?.invoice_id ?? null,
          asOf: when,
          viewer: role === "owner" ? "owner" : "processor",
        });
        setCard(result);
        setActive(result.rule.citations[0]?.n ?? result.draft?.rule.citations[0]?.n ?? null);
      } catch (e) {
        setCard(null);
        setFailure(e instanceof DemoMissError ? { kind: "demo" } : { kind: "error", message: (e as Error).message });
      } finally {
        setLoading(false);
      }
    },
    [userId, role, client, invoice, asOf, router, pathname],
  );

  // A question in the URL (shared link, Related, reload) is asked on arrival; the demo opens on T1.
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void getScopes().then((s) => setScopes(s.length ? s : [ALL_SCOPE]));
    const q = params.get("q");
    const when = params.get("as_of");
    if (when) setAsOf(when);
    if (q) void run(q, { asOf: when });
    else if (DEMO_MODE) void run(SAMPLES[0]?.question ?? "", { asOf: null });
  }, [params, run]);

  // Expert replies to this user's escalated questions.
  useEffect(() => {
    if (DEMO_MODE) return;
    let alive = true; // the user id settles after mount; a stale response must not win
    const load = () =>
      void apiGet<Notification[]>(`/notifications?user_id=${encodeURIComponent(userId)}`)
        .then((n) => {
          if (alive) setReplies(n.filter((x) => x.kind === "expert_reply"));
        })
        .catch(() => {});
    load();
    const id = window.setInterval(load, 10_000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [userId]);

  const activate = useCallback((n: number, scroll: boolean) => {
    setActive(n);
    if (!scroll) return;
    if (typeof window === "undefined" || !window.matchMedia("(min-width: 1024px)").matches) return;
    // Scroll only the sticky rail, never the page.
    const el = document.getElementById(`source-${n}`);
    const rail = el?.closest("aside");
    if (!el || !rail) return;
    const c = el.getBoundingClientRect();
    const r = rail.getBoundingClientRect();
    if (c.top < r.top) rail.scrollBy({ top: c.top - r.top - 16, behavior: "smooth" });
    else if (c.bottom > r.bottom) rail.scrollBy({ top: c.bottom - r.bottom + 16, behavior: "smooth" });
  }, []);

  const change = unseen[0] ?? null;
  const ack = () => {
    if (!change) return;
    markSeen(Math.max(...unseen.map((c) => c.kb_version)));
    for (const c of unseen) void ackChange(c.id, userId).catch(() => {});
  };

  const reply = replies[0] ?? null;
  const dismissReply = (n: Notification) => {
    setReplies((r) => r.filter((x) => x.id !== n.id));
    setShownReply(null);
    if (!DEMO_MODE) void apiSend("POST", `/notifications/${n.id}/read`, { user_id: userId }).catch(() => {});
  };

  const attachInvoice = (inv: InvoiceContext | null) => {
    setInvoice(inv);
    if (!inv) return;
    void getContext(inv.invoice_id).then((ctx) => {
      if (ctx?.tips?.length) setInvoice((cur) => (cur?.invoice_id === inv.invoice_id ? { ...cur, habits: ctx.tips } : cur));
    });
  };

  const sendToExpert = async () => {
    if (!card) return;
    setSending(true);
    try {
      const out = await escalate(card.answer_id, userId);
      setSentTo(out.routed_to || card.route_to?.role || "the process owner");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSending(false);
    }
  };

  const ownerDraft = role === "owner" && card?.status === "unverified" && card.draft ? card.draft : null;
  const rule = ownerDraft ? ownerDraft.rule : card?.rule;
  const citations = rule?.citations ?? [];
  const older = card?.older_sources ?? [];
  const unsupported =
    card?.status === "unsupported" || card?.status === "needs_specialist" || (card?.status === "unverified" && !ownerDraft);
  const replyForCard = card ? replies.find((r) => String(r.answer_id) === card.answer_id) : undefined;

  const tabs: { key: Tab; label: string }[] = [
    { key: "answer", label: "Answer" },
    { key: "sources", label: `Sources${citations.length ? ` · ${citations.length}` : ""}` },
    { key: "history", label: "History" },
  ];

  const banners = (
    <>
      {reply && !replyForCard && (
        <AnsweredBanner body={replyText(reply.body)} onDismiss={() => dismissReply(reply)} />
      )}
      {change && <ChangeBanner change={change} count={unseen.length} onAck={ack} />}
    </>
  );

  const composer = (
    <Composer
      onSubmit={(q) => void run(q)}
      client={client}
      onClientChange={setClient}
      invoice={invoice}
      onInvoiceChange={attachInvoice}
      busy={loading}
      scopes={scopes}
      asOf={asOf}
      onAsOfChange={(d) => {
        setAsOf(d);
        if (question) void run(question, { asOf: d });
      }}
    />
  );

  const main =
    question === null ? (
      <>
        {banners}
        <Welcome onAsk={(q) => void run(q)} />
        {composer}
      </>
    ) : (
      <>
        {banners}

        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-1.5">
            <Sparkles className="h-4 w-4 text-rose" aria-hidden />
            <span className="eyebrow text-ink">Answer</span>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2 font-mono text-[11px] text-muted">
            <span className="whitespace-nowrap rounded-full border border-hairline bg-surface px-2.5 py-1">
              {clientLabel(scopes, card?.client ?? client)}
            </span>
            {card?.as_of && (
              <span className="whitespace-nowrap rounded-full border border-hairline bg-surface px-2.5 py-1">
                as of {fmtDate(card.as_of)}
              </span>
            )}
            {card && <span className="whitespace-nowrap">kb v{card.kb_version}</span>}
          </div>
        </div>

        <h1 className="mt-3 font-display text-2xl font-bold leading-tight tracking-tight text-ink md:text-[30px] md:leading-[1.15]">
          {question}
        </h1>

        <div role="tablist" aria-label="Answer views" className="mt-6 flex gap-6 border-b border-hairline">
          {tabs.map((t) => (
            <button
              key={t.key}
              role="tab"
              type="button"
              id={`tab-${t.key}`}
              aria-selected={tab === t.key}
              aria-controls={`panel-${t.key}`}
              onClick={() => setTab(t.key)}
              className={cx(
                "-mb-px border-b-2 pb-2.5 text-sm font-medium transition-colors",
                tab === t.key ? "border-rose text-ink" : "border-transparent text-muted hover:text-ink",
              )}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} className="pt-5">
          {loading ? (
            <div aria-live="polite">
              <p className="mb-4 text-sm text-muted">Checking the documents and the rules in force…</p>
              <Skeleton />
            </div>
          ) : failure?.kind === "demo" ? (
            <div className="rounded-2xl border border-hairline bg-surface p-5 shadow-card">
              <p className="text-[15px] text-ink">
                Demo mode answers four sample questions until the API is connected. Try one of these:
              </p>
              <ul className="mt-3 space-y-1.5">
                {SAMPLES.map((s) => (
                  <li key={s.question}>
                    <button
                      type="button"
                      onClick={() => void run(s.question)}
                      className="text-left text-sm font-medium text-rose hover:text-rose-hover"
                    >
                      {s.question}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ) : failure?.kind === "error" ? (
            <div role="alert" className="rounded-2xl border border-hairline bg-surface p-5 shadow-card">
              <p className="text-[15px] text-ink">We couldn&apos;t get an answer. {failure.message}</p>
              <button
                type="button"
                onClick={() => void run(question)}
                className="mt-3 text-sm font-medium text-rose hover:text-rose-hover"
              >
                Try again
              </button>
            </div>
          ) : card && tab === "answer" ? (
            <div className="space-y-6">
              <SourceChipStrip citations={citations} active={active} onActivate={activate} />
              {ownerDraft ? (
                <StatusPill status="unverified" />
              ) : (
                card.status !== "answered" && !unsupported && <StatusPill status={card.status} />
              )}
              {asOfLine(card) && (
                <span className="inline-flex items-center rounded-full bg-fill px-3 py-1 text-[13px] font-medium text-muted">
                  {asOfLine(card)}
                </span>
              )}
              {unsupported ? (
                <NotCoveredCard route={card.route_to} sent={sentTo} sending={sending} onSend={() => void sendToExpert()} />
              ) : (
                <>
                  <CitedText text={rule?.text ?? ""} citations={citations} active={active} onActivate={activate} />
                  {ownerDraft && ownerDraft.problems.length > 0 && (
                    <ul className="space-y-1 rounded-2xl bg-fill p-3 font-mono text-[11px] text-muted">
                      {ownerDraft.problems.map((p) => (
                        <li key={p}>{p}</li>
                      ))}
                    </ul>
                  )}
                  <DecisionRow card={card} />
                  <WorkingCard rows={card.working} />
                  <CurrentVsOlderCard items={older} firstCitation={citations[0]} active={active} onActivate={activate} />
                  {card.expert_tip && <ExpertTipCard tip={card.expert_tip} onActivate={activate} />}
                </>
              )}
              {(replyForCard || shownReply) && (
                <ExpertReplyCard
                  text={replyText((replyForCard ?? shownReply)!.body)}
                  onDismiss={() => dismissReply((replyForCard ?? shownReply)!)}
                />
              )}
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-hairline pt-4">
                <ReportWrong onSend={(note) => reportWrong(card.answer_id, userId, note)} />
                {card.latency_ms > 0 && (
                  <span className="font-mono text-[11px] text-muted">{(card.latency_ms / 1000).toFixed(1)} s</span>
                )}
              </div>
            </div>
          ) : card && tab === "sources" ? (
            citations.length ? (
              <ol className="space-y-3">
                {citations.map((c) => (
                  <li key={c.n}>
                    <button
                      type="button"
                      onClick={() => setDrawer(c)}
                      className="w-full rounded-2xl border border-hairline bg-surface p-4 text-left hover:border-muted"
                    >
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[11px] font-medium text-rose">{c.n}</span>
                        <DocGlyph type={c.doc_type} />
                        <span className="text-sm font-semibold text-ink">{c.section_title}</span>
                      </div>
                      <p className="mt-1 font-mono text-[11px] text-muted">
                        {c.file} · {c.short_label} · {c.status}
                      </p>
                      <p className="mt-2 text-sm leading-relaxed text-ink">{c.quote}</p>
                    </button>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="text-sm text-muted">No sources: the documents don&apos;t cover this question.</p>
            )
          ) : card ? (
            <div>
              {older.length > 0 ? (
                <>
                  <h2 className="eyebrow">Older sources on this topic</h2>
                  <ul className="mt-3 space-y-2.5">
                    {groupOlder(older).map((o, i) => (
                      <OlderSourceItem key={i} item={o} />
                    ))}
                  </ul>
                </>
              ) : (
                <p className="text-sm text-muted">No older version of this rule is on record.</p>
              )}
              <p className="mt-6 text-sm text-muted">
                Set a date with the{" "}
                <span className="font-medium text-ink">as of</span> pill to see the rule that applied on that day.
              </p>
            </div>
          ) : null}
        </div>

        {!loading && card && <Related items={card.related} onAsk={(q) => void run(q)} />}

        {composer}
        {DEMO_MODE && (
          <p className="mt-3 text-center font-mono text-[11px] text-muted">
            Demo mode · answers come from sample fixtures until the API is connected
          </p>
        )}
      </>
    );

  return (
    <>
      <PageColumns
        main={main}
        railLabel="Sources"
        rail={
          question === null ? (
            <div>
              <h2 className="eyebrow">Sources</h2>
              <p className="mt-3 text-[13px] leading-relaxed text-muted">
                Every answer lists the passages it rests on here. Hover a citation number to find its source;
                click a source to read the full passage in its document.
              </p>
            </div>
          ) : (
            <SourcesRail
              citations={citations}
              older={older}
              active={active}
              onActivate={activate}
              onOpen={setDrawer}
              invoice={invoice}
              loading={loading}
            />
          )
        }
      />
      <SourceDrawer citation={drawer} onClose={() => setDrawer(null)} />
    </>
  );
}
