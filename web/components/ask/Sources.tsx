"use client";

import { Clock, ExternalLink, FileText, Plus, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { DEMO_MODE, getPassage, originalUrl } from "@/lib/api";
import { cx, fmtDate } from "@/lib/format";
import type { Citation, InvoiceContext, OlderSource, PassageDetail, SourceStatus } from "@/lib/types";

import { groupOlder } from "./AnswerBlocks";
import { DocGlyph } from "./DocGlyph";

const STATUS_LABEL: Record<SourceStatus, string> = {
  current: "current",
  superseded: "superseded",
  stale: "stale",
  draft: "draft",
  record: "record",
  provisional: "provisional",
};

const fileStem = (file: string) => file.replace(/\.[a-z0-9]{2,5}$/i, "");

const TIMED: Citation["doc_type"][] = ["training", "interview", "observation"];

/** Transcripts are best named by their timestamp ("Interview 1 [00:42]"). */
const cardTitle = (c: Citation) => (TIMED.includes(c.doc_type) ? c.short_label : c.section_title);

/** Horizontal strip of source chips under the tabs (DESIGN.md §4.5). */
export function SourceChipStrip({
  citations,
  active,
  onActivate,
  max = 4,
}: {
  citations: Citation[];
  active: number | null;
  onActivate: (n: number, scroll: boolean) => void;
  max?: number;
}) {
  const [expanded, setExpanded] = useState(false);
  if (!citations.length) return null;
  const shown = expanded ? citations : citations.slice(0, max);
  const hidden = citations.length - shown.length;
  return (
    <div className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:px-0">
      {shown.map((c) => (
        <button
          key={c.n}
          type="button"
          onMouseEnter={() => onActivate(c.n, true)}
          onFocus={() => onActivate(c.n, true)}
          onClick={() => onActivate(c.n, true)}
          aria-label={`Source ${c.n}: ${c.short_label}`}
          className={cx(
            "flex shrink-0 items-center gap-2 rounded-full border bg-surface py-1.5 pl-2 pr-2.5 text-[13px] transition-colors",
            active === c.n ? "border-rose-line" : "border-hairline hover:border-muted",
          )}
        >
          <DocGlyph type={c.doc_type} />
          <span className="whitespace-nowrap font-mono text-xs text-ink">{c.short_label}</span>
          <span className="font-mono text-[11px] font-medium text-rose">{c.n}</span>
        </button>
      ))}
      {hidden > 0 && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="flex shrink-0 items-center gap-1 rounded-full border border-hairline bg-surface px-3 py-1.5 font-mono text-xs text-muted hover:border-muted hover:text-ink"
        >
          <Plus className="h-3 w-3" aria-hidden />
          {hidden}
        </button>
      )}
    </div>
  );
}

function SourceCard({
  citation,
  active,
  onActivate,
  onOpen,
}: {
  citation: Citation;
  active: boolean;
  onActivate: (n: number, scroll: boolean) => void;
  onOpen: (c: Citation) => void;
}) {
  const ref = useRef<HTMLButtonElement>(null);
  return (
    <li>
      <button
        ref={ref}
        type="button"
        id={`source-${citation.n}`}
        data-source-card={citation.n}
        data-active={active ? "true" : "false"}
        onMouseEnter={() => onActivate(citation.n, false)}
        onFocus={() => onActivate(citation.n, false)}
        onClick={() => onOpen(citation)}
        aria-label={`Source ${citation.n}: ${citation.section_title}, ${citation.short_label}. Open full passage`}
        className={cx(
          "group flex w-full gap-3 rounded-2xl border p-3.5 text-left transition-colors",
          active ? "border-rose-line bg-rose-tint" : "border-hairline bg-surface hover:border-muted",
        )}
      >
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <DocGlyph type={citation.doc_type} />
            <span className="truncate text-sm font-semibold text-ink">{cardTitle(citation)}</span>
          </div>
          <p className="mt-1 truncate font-mono text-[11px] text-muted">
            {fileStem(citation.file)} · {STATUS_LABEL[citation.status]}
          </p>
          <p className="mt-2 line-clamp-2 text-[13px] leading-snug text-muted">{citation.quote}</p>
        </div>
        <span
          className={cx(
            "flex h-6 w-6 shrink-0 items-center justify-center rounded-full border font-mono text-[11px] font-medium",
            active ? "border-rose bg-rose text-surface" : "border-hairline bg-surface text-muted",
          )}
          aria-hidden
        >
          {citation.n}
        </span>
      </button>
    </li>
  );
}

export function OlderSourceItem({ item }: { item: OlderSource }) {
  return (
    <li className="rounded-2xl border border-hairline bg-surface p-3.5">
      <div className="flex items-center gap-2">
        <Clock className="h-3.5 w-3.5 text-muted" aria-hidden />
        <span className="truncate text-sm font-semibold text-muted">{item.topic}</span>
      </div>
      <p className="mt-1.5 text-[13px] text-muted">
        <s>{item.older_value}</s>
      </p>
      <p className="mt-1.5 font-mono text-[11px] leading-relaxed text-muted">
        {item.locator} · superseded {fmtDate(item.superseded_on)} by {item.superseded_by}
      </p>
    </li>
  );
}

export function InvoiceContextCard({ invoice }: { invoice: InvoiceContext }) {
  const rows: [string, string][] = [
    ["Client", invoice.client],
    ["PO-backed", invoice.po_backed ? "Yes" : "No — non-PO"],
    ["MSME", invoice.msme_category],
    ["E-invoice", invoice.einvoice_required ? "Required (IRN)" : "Not required"],
    ["Due date", invoice.due_date ? fmtDate(invoice.due_date) : ""],
    ["Payment run", invoice.payment_run],
  ].filter(([, v]) => v) as [string, string][];
  return (
    <section aria-labelledby="invoice-ctx" className="mb-6 rounded-2xl border border-hairline bg-surface p-4 shadow-card">
      <div className="flex items-center gap-2">
        <FileText className="h-4 w-4 text-muted" aria-hidden />
        <h2 id="invoice-ctx" className="eyebrow">
          Invoice context
        </h2>
      </div>
      <p className="mt-2 font-mono text-[13px] text-ink">
        {invoice.invoice_id} · {invoice.vendor_id}
      </p>
      <p className="text-sm font-medium text-ink">{invoice.vendor_name}</p>
      <dl className="mt-3 divide-y divide-hairline text-[13px]">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-3 py-1.5">
            <dt className="text-muted">{k}</dt>
            <dd className="text-right text-ink">{v}</dd>
          </div>
        ))}
      </dl>
      {invoice.habits.length > 0 && (
        <div className="mt-3 rounded-xl bg-fill p-2.5">
          <p className="eyebrow">Supplier habit</p>
          {invoice.habits.map((h) => (
            <p key={h} className="mt-1 text-[13px] text-ink">
              {h}
            </p>
          ))}
        </div>
      )}
    </section>
  );
}

export function SourcesRail({
  citations,
  older,
  active,
  onActivate,
  onOpen,
  invoice,
  loading,
}: {
  citations: Citation[];
  older: OlderSource[];
  active: number | null;
  onActivate: (n: number, scroll: boolean) => void;
  onOpen: (c: Citation) => void;
  invoice: InvoiceContext | null;
  loading: boolean;
}) {
  const [showAll, setShowAll] = useState(false);
  useEffect(() => setShowAll(false), [citations]);
  const visible = showAll ? citations : citations.slice(0, 4);

  return (
    <div>
      {invoice && <InvoiceContextCard invoice={invoice} />}
      <div className="flex items-baseline justify-between">
        <h2 className="eyebrow">Sources</h2>
        {!loading && <span className="font-mono text-[11px] text-muted">{citations.length}</span>}
      </div>
      {loading ? (
        <ul className="mt-3 space-y-2.5" aria-hidden>
          {[0, 1, 2].map((i) => (
            <li key={i} className="h-[92px] animate-pulse rounded-2xl bg-fill" />
          ))}
        </ul>
      ) : citations.length === 0 ? (
        <p className="mt-3 text-[13px] text-muted">No source in the knowledge base covers this question.</p>
      ) : (
        <ul className="mt-3 space-y-2.5">
          {visible.map((c) => (
            <SourceCard key={c.n} citation={c} active={active === c.n} onActivate={onActivate} onOpen={onOpen} />
          ))}
        </ul>
      )}
      {!loading && older.length > 0 && (
        <>
          <h2 className="eyebrow mt-7">Older sources</h2>
          <ul className="mt-3 space-y-2.5">
            {groupOlder(older).map((o, i) => (
              <OlderSourceItem key={i} item={o} />
            ))}
          </ul>
        </>
      )}
      {!loading && citations.length > 4 && !showAll && (
        <button
          type="button"
          onClick={() => setShowAll(true)}
          className="mt-4 w-full rounded-full border border-hairline bg-surface py-2 text-[13px] font-medium text-ink hover:border-muted"
        >
          Show all {citations.length} sources
        </button>
      )}
    </div>
  );
}

/** The passage text with the cited quote marked (whitespace-insensitive match). */
function Highlighted({ text, quote }: { text: string; quote: string }) {
  const norm = (s: string) => s.replace(/\s+/g, " ").trim();
  const flat = norm(text);
  const q = norm(quote).replace(/[.…]+$/, "");
  const at = q.length > 8 ? flat.toLowerCase().indexOf(q.toLowerCase()) : -1;
  if (at < 0) return <p className="whitespace-pre-line">{text}</p>;
  return (
    <p>
      {flat.slice(0, at)}
      <mark className="rounded bg-rose-tint px-0.5 text-ink ring-1 ring-rose-line">{flat.slice(at, at + q.length)}</mark>
      {flat.slice(at + q.length)}
    </p>
  );
}

/** Side drawer with the full passage, its version, date and status, and the original. */
export function SourceDrawer({
  citation,
  onClose,
  eyebrow,
}: {
  citation: Citation | null;
  onClose: () => void;
  /** Heading above the title; default "Source {n}". */
  eyebrow?: string;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const [detail, setDetail] = useState<PassageDetail | null>(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!citation) return;
    closeRef.current?.focus();
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [citation, onClose]);
  useEffect(() => {
    setDetail(null);
    if (!citation || DEMO_MODE) return;
    setLoading(true);
    void getPassage(citation.passage_id)
      .then(setDetail)
      .finally(() => setLoading(false));
  }, [citation]);
  if (!citation) return null;
  const src = detail?.source;
  const pos = detail?.position_in_source;
  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-labelledby="drawer-title">
      <button type="button" aria-label="Close" className="absolute inset-0 bg-ink/20" onClick={onClose} />
      <div className="relative flex h-full w-full max-w-md flex-col overflow-y-auto border-l border-hairline bg-surface p-6 shadow-card">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="eyebrow">{eyebrow ?? `Source ${citation.n}`}</p>
            <h2 id="drawer-title" className="mt-1 font-display text-xl font-bold leading-tight text-ink">
              {citation.section_title || detail?.section_title || src?.title || citation.short_label}
            </h2>
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="Close passage"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-muted hover:bg-fill hover:text-ink"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </div>
        <dl className="mt-4 space-y-1 font-mono text-xs text-muted">
          <div>
            <dt className="sr-only">File</dt>
            <dd>{citation.file || src?.title}</dd>
          </div>
          <div className="flex items-center gap-2">
            <dt className="sr-only">Locator</dt>
            <DocGlyph type={src?.doc_type ?? citation.doc_type} />
            <dd>
              {citation.short_label} · {src ? (STATUS_LABEL[src.status as SourceStatus] ?? src.status) : STATUS_LABEL[citation.status]}
            </dd>
          </div>
        </dl>
        {src && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {src.version && <span className="rounded-full bg-fill px-2.5 py-0.5 font-mono text-[11px] text-muted">v{src.version}</span>}
            {src.dated && <span className="rounded-full bg-fill px-2.5 py-0.5 font-mono text-[11px] text-muted">{fmtDate(src.dated)}</span>}
            <span className="rounded-full bg-fill px-2.5 py-0.5 font-mono text-[11px] text-muted">{src.status}</span>
            {src.client_scope !== "all" && (
              <span className="rounded-full bg-fill px-2.5 py-0.5 font-mono text-[11px] text-muted">{src.client_scope}</span>
            )}
          </div>
        )}
        <h3 className="eyebrow mt-6">{detail ? "Passage, cited words marked" : "Cited words"}</h3>
        {loading ? (
          <div className="mt-3 space-y-2" aria-hidden>
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="h-3.5 animate-pulse rounded bg-fill" />
            ))}
          </div>
        ) : detail ? (
          <div className="mt-3 rounded-2xl border border-hairline bg-canvas p-4 text-[15px] leading-[1.7] text-ink">
            {detail.speaker && <p className="mb-1 font-mono text-[11px] text-muted">{detail.speaker}</p>}
            <Highlighted text={detail.text} quote={citation.quote} />
          </div>
        ) : (
          <blockquote className="mt-3 border-l-[3px] border-rose pl-4 text-[15px] leading-[1.65] text-ink">
            {citation.quote}
          </blockquote>
        )}
        {pos && (
          <div className="mt-4 space-y-1.5 font-mono text-[11px] text-muted">
            <p>
              part {(pos.index ?? 0) + 1} of {pos.of} in {src?.short_label}
            </p>
            {pos.previous && <p>before: {pos.previous.locator} {pos.previous.section_title}</p>}
            {pos.next && <p>after: {pos.next.locator} {pos.next.section_title}</p>}
          </div>
        )}
        <div className="mt-auto flex items-center justify-between gap-3 pt-6">
          <p className="truncate font-mono text-[11px] text-muted">passage {citation.passage_id}</p>
          {detail && (
            <a
              href={originalUrl(detail.episode_id)}
              target="_blank"
              rel="noreferrer"
              className="inline-flex shrink-0 items-center gap-1.5 text-[13px] font-medium text-rose hover:text-rose-hover"
            >
              <ExternalLink className="h-3.5 w-3.5" aria-hidden />
              Open original
            </a>
          )}
        </div>
      </div>
    </div>
  );
}
