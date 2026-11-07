"use client";

import { Fragment } from "react";

import { cx } from "@/lib/format";
import type { Citation } from "@/lib/types";

export function CitationChip({
  citation,
  active,
  onActivate,
}: {
  citation: Citation;
  active: boolean;
  onActivate: (n: number, scroll: boolean) => void;
}) {
  return (
    <sup className="relative -top-[0.45em] ml-px align-baseline text-[11px] leading-none">
      <button
        type="button"
        data-citation={citation.n}
        aria-label={`Source ${citation.n}: ${citation.short_label}`}
        onMouseEnter={() => onActivate(citation.n, true)}
        onFocus={() => onActivate(citation.n, true)}
        onClick={() => onActivate(citation.n, true)}
        className={cx(
          "rounded px-[2px] font-mono text-[11px] font-medium leading-none text-rose transition-colors hover:bg-rose-tint",
          active && "bg-rose-tint",
        )}
      >
        {citation.n}
      </button>
    </sup>
  );
}

/** Renders rule.text: paragraphs split on blank lines, `[n]` markers as citation chips. */
export function CitedText({
  text,
  citations,
  active,
  onActivate,
}: {
  text: string;
  citations: Citation[];
  active: number | null;
  onActivate: (n: number, scroll: boolean) => void;
}) {
  const byN = new Map(citations.map((c) => [c.n, c]));
  // "₹500 [1]" -> "₹500[1]" so the superscript hugs the word it supports.
  const paragraphs = text
    .replace(/[ \t]+(\[\d+\])/g, "$1")
    .split(/\n\s*\n/)
    .filter((p) => p.trim());
  return (
    <div className="space-y-4 text-[15px] leading-[1.65] text-ink sm:text-base">
      {paragraphs.map((para, i) => (
        <p key={i}>
          {para.split(/(\[\d+\])/g).map((part, j) => {
            const m = part.match(/^\[(\d+)\]$/);
            const c = m ? byN.get(Number(m[1])) : undefined;
            if (c) return <CitationChip key={j} citation={c} active={active === c.n} onActivate={onActivate} />;
            return <Fragment key={j}>{part}</Fragment>;
          })}
        </p>
      ))}
    </div>
  );
}
