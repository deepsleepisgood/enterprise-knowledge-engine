"use client";

import { ArrowRight, CalendarClock, Check, ChevronDown, Paperclip, X } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { searchInvoices } from "@/lib/api";
import { cx, fmtDate, fmtInr, sessionGet, sessionSet } from "@/lib/format";
import { ALL_SCOPE, type ClientKey, type InvoiceContext, type Scope } from "@/lib/types";

function usePopover() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);
  return { open, setOpen, ref };
}

function InvoicePicker({ onPick }: { onPick: (i: InvoiceContext) => void }) {
  const { open, setOpen, ref } = usePopover();
  const [q, setQ] = useState("");
  const [items, setItems] = useState<InvoiceContext[]>([]);
  useEffect(() => {
    if (open) void searchInvoices(q).then(setItems);
  }, [open, q]);
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label="Attach an invoice"
        aria-expanded={open}
        className="flex h-9 w-9 items-center justify-center rounded-full text-muted hover:bg-fill hover:text-ink"
      >
        <Paperclip className="h-[18px] w-[18px]" aria-hidden />
      </button>
      {open && (
        <div className="absolute bottom-11 left-0 z-30 w-[min(20rem,calc(100vw-3rem))] rounded-2xl border border-hairline bg-surface p-2 shadow-card">
          <label className="block px-1.5 pb-2">
            <span className="eyebrow">Attach invoice (ERP)</span>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Invoice id or supplier"
              className="mt-1.5 w-full rounded-xl border border-hairline bg-canvas px-3 py-2 text-sm text-ink placeholder:text-muted focus:border-muted focus:outline-none"
            />
          </label>
          <ul className="max-h-60 overflow-y-auto">
            {items.map((i) => (
              <li key={i.invoice_id}>
                <button
                  type="button"
                  onClick={() => {
                    onPick(i);
                    setOpen(false);
                  }}
                  className="flex w-full items-center justify-between gap-3 rounded-xl px-2.5 py-2 text-left hover:bg-fill"
                >
                  <span className="min-w-0">
                    <span className="block font-mono text-xs text-ink">{i.invoice_id}</span>
                    <span className="block truncate text-[13px] text-muted">
                      {i.vendor_name} · {i.client}
                    </span>
                  </span>
                  <span className="shrink-0 font-mono text-xs text-ink">{fmtInr(i.total_inr)}</span>
                </button>
              </li>
            ))}
            {items.length === 0 && <li className="px-2.5 py-2 text-[13px] text-muted">No matching invoice.</li>}
          </ul>
        </div>
      )}
    </div>
  );
}

function ClientChip({
  value,
  onChange,
  scopes,
}: {
  value: ClientKey;
  onChange: (c: ClientKey) => void;
  scopes: Scope[];
}) {
  const { open, setOpen, ref } = usePopover();
  const label = scopes.find((c) => c.key === value)?.label ?? ALL_SCOPE.label;
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`Client: ${label}`}
        className="flex h-9 items-center gap-2 rounded-full border border-hairline px-3 text-[13px] font-medium text-ink hover:border-muted"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-rose" aria-hidden />
        {label}
        <ChevronDown className="h-3.5 w-3.5 text-muted" aria-hidden />
      </button>
      {open && (
        <ul role="listbox" className="absolute bottom-11 left-0 z-30 w-48 rounded-2xl border border-hairline bg-surface p-1.5 shadow-card">
          {scopes.map((c) => (
            <li key={c.key} role="option" aria-selected={c.key === value}>
              <button
                type="button"
                onClick={() => {
                  onChange(c.key);
                  setOpen(false);
                }}
                className="flex w-full items-center justify-between rounded-xl px-2.5 py-2 text-left text-sm text-ink hover:bg-fill"
              >
                {c.label}
                {c.key === value && <Check className="h-4 w-4" aria-hidden />}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function AsOfPill({ value, onChange }: { value: string | null; onChange: (d: string | null) => void }) {
  const { open, setOpen, ref } = usePopover();
  const label = value ? fmtDate(value) : "Today";
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={`Rules as of: ${label}`}
        className="flex h-9 items-center gap-2 rounded-full border border-hairline px-3 text-[13px] font-medium text-ink hover:border-muted"
      >
        <CalendarClock className="h-3.5 w-3.5 text-muted" aria-hidden />
        {label}
      </button>
      {open && (
        <div className="absolute bottom-11 right-0 z-30 w-[min(15rem,calc(100vw-3rem))] rounded-2xl border border-hairline bg-surface p-3 shadow-card sm:left-0 sm:right-auto">
          <label className="block">
            <span className="eyebrow">Rules in force on</span>
            <input
              type="date"
              value={value ?? ""}
              onChange={(e) => onChange(e.target.value || null)}
              className="mt-1.5 w-full rounded-xl border border-hairline bg-canvas px-3 py-2 font-mono text-sm text-ink focus:border-muted focus:outline-none"
            />
          </label>
          <button
            type="button"
            onClick={() => {
              onChange(null);
              setOpen(false);
            }}
            className="mt-2 text-[13px] font-medium text-rose hover:text-rose-hover"
          >
            Back to today
          </button>
        </div>
      )}
    </div>
  );
}

const DRAFT_KEY = "ps07.askDraft";

export function Composer({
  onSubmit,
  client,
  onClientChange,
  invoice,
  onInvoiceChange,
  busy,
  scopes,
  asOf,
  onAsOfChange,
}: {
  onSubmit: (q: string) => void;
  client: ClientKey;
  onClientChange: (c: ClientKey) => void;
  scopes: Scope[];
  asOf: string | null;
  onAsOfChange: (d: string | null) => void;
  invoice: InvoiceContext | null;
  onInvoiceChange: (i: InvoiceContext | null) => void;
  busy: boolean;
}) {
  const [text, setText] = useState("");
  const ta = useRef<HTMLTextAreaElement>(null);

  // The unsent question survives a trip to another page (per tab). Restored after mount so the
  // server render and the first client render match; saved as it is typed, cleared on send.
  useEffect(() => {
    const saved = sessionGet<string>(DRAFT_KEY);
    if (saved) setText(saved);
  }, []);
  const edit = (v: string) => {
    setText(v);
    sessionSet(DRAFT_KEY, v);
  };

  useLayoutEffect(() => {
    const el = ta.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 240)}px`;
  }, [text]);

  const submit = () => {
    const q = text.trim();
    if (!q || busy) return;
    onSubmit(q);
    edit("");
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      className="mt-10 rounded-2xl border border-hairline bg-surface p-3 shadow-card"
    >
      {invoice && (
        <div className="mb-2 flex">
          <span className="inline-flex items-center gap-2 rounded-full bg-fill py-1 pl-3 pr-1 font-mono text-xs text-ink">
            {invoice.invoice_id} · {invoice.vendor_name}
            <button
              type="button"
              onClick={() => onInvoiceChange(null)}
              aria-label="Remove attached invoice"
              className="flex h-5 w-5 items-center justify-center rounded-full text-muted hover:bg-surface hover:text-ink"
            >
              <X className="h-3 w-3" aria-hidden />
            </button>
          </span>
        </div>
      )}
      <label htmlFor="ask-input" className="sr-only">
        Ask a question
      </label>
      <textarea
        id="ask-input"
        ref={ta}
        rows={2}
        value={text}
        onChange={(e) => edit(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
        placeholder="Ask about a rule, a document or an entity…"
        className="block w-full resize-none bg-transparent px-1.5 py-1 text-[15px] leading-relaxed text-ink placeholder:text-muted focus:outline-none"
      />
      <div className="mt-2 flex items-center gap-2">
        <InvoicePicker onPick={onInvoiceChange} />
        <ClientChip value={client} onChange={onClientChange} scopes={scopes} />
        <AsOfPill value={asOf} onChange={onAsOfChange} />
        <button
          type="submit"
          disabled={!text.trim() || busy}
          aria-label="Send question"
          className={cx(
            "ml-auto flex h-9 w-9 items-center justify-center rounded-full bg-rose text-surface transition-colors hover:bg-rose-hover",
            (!text.trim() || busy) && "cursor-not-allowed opacity-40 hover:bg-rose",
          )}
        >
          <ArrowRight className="h-[18px] w-[18px]" aria-hidden />
        </button>
      </div>
    </form>
  );
}
