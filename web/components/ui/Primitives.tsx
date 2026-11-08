"use client";

import { AlertCircle, CheckCircle2, Loader2, X, type LucideIcon } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useState } from "react";

import { cx } from "@/lib/format";

/* ---------------------------------------------------------------- buttons */

type ButtonVariant = "primary" | "outline" | "ghost" | "rose-outline";

const BUTTON: Record<ButtonVariant, string> = {
  primary: "bg-rose text-surface hover:bg-rose-hover border border-rose hover:border-rose-hover",
  outline: "border border-hairline bg-surface text-ink hover:border-muted",
  ghost: "text-muted hover:bg-fill hover:text-ink",
  "rose-outline": "border border-rose bg-surface text-rose hover:bg-rose-tint",
};

export function Button({
  variant = "outline",
  busy = false,
  icon: Icon,
  className,
  children,
  disabled,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  busy?: boolean;
  icon?: LucideIcon;
}) {
  return (
    <button
      type="button"
      disabled={disabled || busy}
      className={cx(
        "inline-flex h-9 items-center justify-center gap-1.5 whitespace-nowrap rounded-full px-4 text-[13px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        BUTTON[variant],
        className,
      )}
      {...rest}
    >
      {busy ? (
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
      ) : Icon ? (
        <Icon className="h-4 w-4" aria-hidden />
      ) : null}
      {children}
    </button>
  );
}

/* ---------------------------------------------------------------- pills and cards */

/** Neutral status pill (DESIGN.md §2): fill background, muted text, optional icon or rose dot. */
export function Pill({
  children,
  icon: Icon,
  dot = false,
  tone = "neutral",
  className,
}: {
  children: React.ReactNode;
  icon?: LucideIcon;
  dot?: boolean;
  tone?: "neutral" | "outline" | "ink";
  className?: string;
}) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium",
        tone === "neutral" && "bg-fill text-muted",
        tone === "outline" && "border border-hairline bg-surface text-muted",
        tone === "ink" && "bg-fill text-ink",
        className,
      )}
    >
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-rose" aria-hidden />}
      {Icon && <Icon className="h-3.5 w-3.5" aria-hidden />}
      {children}
    </span>
  );
}

export function Card({
  children,
  className,
  as: Tag = "section",
  ...rest
}: React.HTMLAttributes<HTMLElement> & { as?: "section" | "div" | "li" | "article" }) {
  return (
    <Tag className={cx("rounded-2xl border border-hairline bg-surface shadow-card", className)} {...rest}>
      {children}
    </Tag>
  );
}

export function PageHeader({
  eyebrow,
  title,
  meta,
  actions,
  children,
}: {
  eyebrow: string;
  title: string;
  meta?: React.ReactNode;
  actions?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <header className="mb-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="eyebrow">{eyebrow}</p>
        {meta && <div className="flex flex-wrap items-center gap-2 font-mono text-[11px] text-muted">{meta}</div>}
      </div>
      <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
        <h1 className="font-display text-2xl font-bold leading-tight tracking-tight text-ink md:text-[30px] md:leading-[1.15]">
          {title}
        </h1>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {children && <div className="mt-3 max-w-prose text-[15px] leading-[1.65] text-muted">{children}</div>}
    </header>
  );
}

export function SectionLabel({ children, icon: Icon, count }: { children: React.ReactNode; icon?: LucideIcon; count?: number }) {
  return (
    <div className="mb-3 flex items-center gap-2">
      {Icon && <Icon className="h-4 w-4 text-muted" aria-hidden />}
      <h2 className="eyebrow">{children}</h2>
      {count !== undefined && <span className="font-mono text-[11px] text-muted">{count}</span>}
    </div>
  );
}

export function Empty({ icon: Icon, title, children }: { icon: LucideIcon; title: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center rounded-2xl border border-dashed border-hairline px-6 py-12 text-center">
      <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-fill text-muted">
        <Icon className="h-5 w-5" aria-hidden />
      </span>
      <p className="mt-3 font-display text-base font-semibold text-ink">{title}</p>
      {children && <div className="mt-1 max-w-sm text-sm leading-relaxed text-muted">{children}</div>}
    </div>
  );
}

export function SkeletonRows({ rows = 4, height = "h-16" }: { rows?: number; height?: string }) {
  return (
    <ul aria-hidden className="space-y-2.5">
      {Array.from({ length: rows }, (_, i) => (
        <li key={i} className={cx(height, "animate-pulse rounded-2xl bg-fill")} />
      ))}
    </ul>
  );
}

export function ErrorNote({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-2xl border border-hairline bg-surface p-4 shadow-card">
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose" aria-hidden />
      <p className="flex-1 text-sm text-ink">{message}</p>
      {onRetry && (
        <button type="button" onClick={onRetry} className="text-sm font-medium text-rose hover:text-rose-hover">
          Try again
        </button>
      )}
    </div>
  );
}

/** A labelled number for rails and summaries. */
export function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="rounded-2xl border border-hairline bg-surface p-3.5">
      <p className="eyebrow">{label}</p>
      <p className="mt-1 font-display text-2xl font-bold leading-none text-ink">{value}</p>
      {hint && <p className="mt-1.5 font-mono text-[11px] text-muted">{hint}</p>}
    </div>
  );
}

/* ---------------------------------------------------------------- toasts */

interface Toast {
  id: number;
  text: string;
  kind: "ok" | "error";
}

const ToastContext = createContext<(text: string, kind?: Toast["kind"]) => void>(() => {});

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, kind: Toast["kind"] = "ok") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-2), { id, text, kind }]);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2">
        {toasts.map((t) => (
          <ToastItem key={t.id} toast={t} onDone={() => setToasts((all) => all.filter((x) => x.id !== t.id))} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function ToastItem({ toast, onDone }: { toast: Toast; onDone: () => void }) {
  useEffect(() => {
    const id = window.setTimeout(onDone, 4500);
    return () => window.clearTimeout(id);
  }, [onDone]);
  const Icon = toast.kind === "ok" ? CheckCircle2 : AlertCircle;
  return (
    <div className="pointer-events-auto flex items-start gap-2.5 rounded-2xl border border-hairline bg-surface p-3.5 shadow-card">
      <Icon className={cx("mt-0.5 h-4 w-4 shrink-0", toast.kind === "ok" ? "text-ink" : "text-rose")} aria-hidden />
      <p className="flex-1 text-sm text-ink">{toast.text}</p>
      <button type="button" onClick={onDone} aria-label="Dismiss" className="text-muted hover:text-ink">
        <X className="h-4 w-4" aria-hidden />
      </button>
    </div>
  );
}

export const useToast = () => useContext(ToastContext);
