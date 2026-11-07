"use client";

import { Sparkles } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { PageColumns } from "@/components/shell/PageColumns";
import { useRole } from "@/components/shell/RoleContext";
import { DEMO_MODE, DemoMissError, SAMPLES, ackChange, ask, getChanges } from "@/lib/api";
import { cx, safeStorageGet, safeStorageSet } from "@/lib/format";
import { CLIENTS, type AnswerCard, type ChangeItem, type Citation, type ClientKey, type InvoiceContext } from "@/lib/types";

import {
  ChangeBanner,
  CurrentVsOlderCard,
  DecisionRow,
  ExpertTipCard,
  NotCoveredCard,
  Related,
  StatusPill,
  WorkingCard,
} from "./AnswerBlocks";
import { CitedText } from "./CitedText";
import { Composer } from "./Composer";
import { DocGlyph } from "./DocGlyph";
import { OlderSourceItem, SourceChipStrip, SourceDrawer, SourcesRail } from "./Sources";

type Tab = "answer" | "sources" | "history";
type Failure = { kind: "demo" } | { kind: "error"; message: string };

const LAST_SEEN_KEY = "ps07.lastSeenKb";

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

function clientLabel(key: string | null): string {
  return CLIENTS.find((c) => c.key === (key ?? "all"))?.label ?? "All clients";
}

export function AskView() {
  const { userId } = useRole();
  const [question, setQuestion] = useState(SAMPLES[0]?.question ?? "");
  const [card, setCard] = useState<AnswerCard | null>(null);
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [active, setActive] = useState<number | null>(1);
  const [tab, setTab] = useState<Tab>("answer");
  const [client, setClient] = useState<ClientKey>("all");
  const [invoice, setInvoice] = useState<InvoiceContext | null>(null);
  const [drawer, setDrawer] = useState<Citation | null>(null);
  const [change, setChange] = useState<ChangeItem | null>(null);

  const run = useCallback(
    async (q: string) => {
      setQuestion(q);
      setLoading(true);
      setFailure(null);
      setTab("answer");
      try {
        const result = await ask({ question: q, userId, client, invoiceId: invoice?.invoice_id ?? null });
        setCard(result);
        setActive(result.rule.citations[0]?.n ?? null);
      } catch (e) {
        setCard(null);
        setFailure(e instanceof DemoMissError ? { kind: "demo" } : { kind: "error", message: (e as Error).message });
      } finally {
        setLoading(false);
      }
    },
    [userId, client, invoice],
  );

  useEffect(() => {
    void run(SAMPLES[0]?.question ?? "");
    const lastSeen = Number(safeStorageGet(LAST_SEEN_KEY) ?? "41");
    void getChanges(Number.isFinite(lastSeen) ? lastSeen : 41).then((items) => setChange(items[0] ?? null));
    // run once on mount; later questions come from the composer and Related
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const activate = useCallback((n: number, scroll: boolean) => {
    setActive(n);
    if (!scroll) return;
    if (typeof window === "undefined" || !window.matchMedia("(min-width: 1024px)").matches) return;
    // Scroll only the sticky rail, never the page.
    const card = document.getElementById(`source-${n}`);
    const rail = card?.closest("aside");
    if (!card || !rail) return;
    const c = card.getBoundingClientRect();
    const r = rail.getBoundingClientRect();
    if (c.top < r.top) rail.scrollBy({ top: c.top - r.top - 16, behavior: "smooth" });
    else if (c.bottom > r.bottom) rail.scrollBy({ top: c.bottom - r.bottom + 16, behavior: "smooth" });
  }, []);

  const ack = () => {
    if (!change) return;
    safeStorageSet(LAST_SEEN_KEY, String(change.kb_version));
    void ackChange(change.id, userId);
    setChange(null);
  };

  const citations = card?.rule.citations ?? [];
  const older = card?.older_sources ?? [];
  const unsupported = card?.status === "unsupported";

  const tabs: { key: Tab; label: string }[] = [
    { key: "answer", label: "Answer" },
    { key: "sources", label: `Sources${citations.length ? ` · ${citations.length}` : ""}` },
    { key: "history", label: "History" },
  ];

  const main = (
    <>
      {change && <ChangeBanner change={change} onAck={ack} />}

      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-1.5">
          <Sparkles className="h-4 w-4 text-rose" aria-hidden />
          <span className="eyebrow text-ink">Answer</span>
        </div>
        <div className="flex items-center gap-2 font-mono text-[11px] text-muted">
          <span className="rounded-full border border-hairline bg-surface px-2.5 py-1">
            {clientLabel(card?.client ?? client)}
          </span>
          {card && <span>kb v{card.kb_version}</span>}
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
            <p className="mb-4 text-sm text-muted">Checking SOP v4.0, client memos and transcripts…</p>
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
                  <button type="button" onClick={() => void run(s.question)} className="text-left text-sm font-medium text-rose hover:text-rose-hover">
                    {s.question}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : failure?.kind === "error" ? (
          <div role="alert" className="rounded-2xl border border-hairline bg-surface p-5 shadow-card">
            <p className="text-[15px] text-ink">We couldn&apos;t get an answer. {failure.message}</p>
            <button type="button" onClick={() => void run(question)} className="mt-3 text-sm font-medium text-rose hover:text-rose-hover">
              Try again
            </button>
          </div>
        ) : card && tab === "answer" ? (
          <div className="space-y-6">
            <SourceChipStrip citations={citations} active={active} onActivate={activate} />
            {card.status !== "answered" && !unsupported && <StatusPill status={card.status} />}
            {unsupported ? (
              <NotCoveredCard route={card.route_to} />
            ) : (
              <>
                <CitedText text={card.rule.text} citations={citations} active={active} onActivate={activate} />
                <DecisionRow card={card} />
                <WorkingCard rows={card.working} />
                <CurrentVsOlderCard items={older} firstCitation={citations[0]} active={active} onActivate={activate} />
                {card.expert_tip && <ExpertTipCard tip={card.expert_tip} onActivate={activate} />}
              </>
            )}
          </div>
        ) : card && tab === "sources" ? (
          citations.length ? (
            <ol className="space-y-3">
              {citations.map((c) => (
                <li key={c.n} className="rounded-2xl border border-hairline bg-surface p-4">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[11px] font-medium text-rose">{c.n}</span>
                    <DocGlyph type={c.doc_type} />
                    <span className="text-sm font-semibold text-ink">{c.section_title}</span>
                  </div>
                  <p className="mt-1 font-mono text-[11px] text-muted">
                    {c.file} · {c.short_label}
                  </p>
                  <p className="mt-2 text-sm leading-relaxed text-ink">{c.quote}</p>
                </li>
              ))}
            </ol>
          ) : (
            <p className="text-sm text-muted">No sources: the documents don&apos;t cover this question.</p>
          )
        ) : card ? (
          <div>
            {older.length > 0 && (
              <>
                <h2 className="eyebrow">Older sources on this topic</h2>
                <ul className="mt-3 space-y-2.5">
                  {older.map((o, i) => (
                    <OlderSourceItem key={i} item={o} />
                  ))}
                </ul>
              </>
            )}
            <p className={cx("text-sm text-muted", older.length > 0 && "mt-6")}>
              No earlier answers to this question at older knowledge-base versions.
            </p>
          </div>
        ) : null}
      </div>

      {!loading && card && <Related items={card.related} onAsk={(q) => void run(q)} />}

      <Composer
        onSubmit={(q) => void run(q)}
        client={client}
        onClientChange={setClient}
        invoice={invoice}
        onInvoiceChange={setInvoice}
        busy={loading}
      />
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
          <SourcesRail
            citations={citations}
            older={older}
            active={active}
            onActivate={activate}
            onOpen={setDrawer}
            invoice={invoice}
            loading={loading}
          />
        }
      />
      <SourceDrawer citation={drawer} onClose={() => setDrawer(null)} />
    </>
  );
}
