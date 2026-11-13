"use client";

import { CalendarClock, ExternalLink, FileText, History, Network, Search, X } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { SourceDrawer } from "@/components/ask/Sources";
import { PageColumns } from "@/components/shell/PageColumns";
import { Card, Empty, ErrorNote, PageHeader, Pill, SectionLabel, SkeletonRows } from "@/components/ui/Primitives";
import { DEMO_MODE, originalUrl } from "@/lib/api";
import { cx, fmtDate, fmtDateTime, humanKey, plural, valueText } from "@/lib/format";
import type { Citation, EntitySummary, FactVersion, Timeline } from "@/lib/types";
import { useApi } from "@/lib/useApi";

const DAY = 86_400_000;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const t = (iso: string | null | undefined) => (iso ? new Date(iso).getTime() : NaN);
const isoDay = (ms: number) => new Date(ms).toISOString().slice(0, 10);
const IN_FORCE = new Set(["current", "corroborating"]);

interface Row {
  key: string;
  attribute: string;
  scope: string;
  /** The topic, when the row comes from facts scoped to this entity (a client rule). */
  topic: string | null;
  lanes: FactVersion[][];
}

/** Versions known to the engine at a transaction time (or now: live rows only). */
function known(v: FactVersion, at: number | null): boolean {
  if (at === null) return v.retracted_at === null;
  return t(v.recorded_at) <= at && (v.retracted_at === null || t(v.retracted_at) > at);
}

function inInterval(v: FactVersion, at: number): boolean {
  const from = Number.isNaN(t(v.valid_from)) ? -Infinity : t(v.valid_from);
  const to = Number.isNaN(t(v.valid_to)) ? Infinity : t(v.valid_to);
  return from <= at && at < to;
}

/** Month ticks across the domain; sparser for long spans. */
function ticks(d0: number, d1: number): { at: number; label: string }[] {
  const months = (d1 - d0) / (30 * DAY);
  const step = months > 48 ? 12 : months > 24 ? 6 : months > 12 ? 3 : 1;
  const out = [];
  const start = new Date(d0);
  const cur = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + 1, 1));
  while (cur.getTime() <= d1) {
    const m = cur.getUTCMonth();
    if (m % step === 0) {
      out.push({ at: cur.getTime(), label: m === 0 ? String(cur.getUTCFullYear()) : `${MONTHS[m]} ${String(cur.getUTCFullYear()).slice(2)}` });
    }
    cur.setUTCMonth(m + 1);
  }
  return out;
}

/** Chart zoom: how far back the chart shows (the sliders always cover all time). */
const SPANS = [
  { key: "6m", label: "6 months", months: 6 },
  { key: "1y", label: "1 year", months: 12 },
  { key: "3y", label: "3 years", months: 36 },
  { key: "all", label: "All time", months: 0 },
] as const;
type Span = (typeof SPANS)[number]["key"];

/** The part of a version's interval inside the window [v0, v1], or null when it is outside. */
function clip(v: FactVersion, v0: number, v1: number): { from: number; to: number; before: boolean } | null {
  const s = Number.isNaN(t(v.valid_from)) ? -Infinity : t(v.valid_from);
  const e = Number.isNaN(t(v.valid_to)) ? Infinity : t(v.valid_to);
  if (e <= v0 || s >= v1) return null;
  return { from: Math.max(v0, s), to: Math.min(v1, e), before: s < v0 };
}

function Bar({ v, v0, v1, now, selected, onPick }: {
  v: FactVersion;
  v0: number;
  v1: number;
  now: number;
  selected: boolean;
  onPick: (v: FactVersion) => void;
}) {
  const c = clip(v, v0, v1);
  if (!c) return null;
  const left = ((c.from - v0) / (v1 - v0)) * 100;
  const width = Math.max(1.5, ((c.to - c.from) / (v1 - v0)) * 100);
  const ongoing = Number.isNaN(t(v.valid_to));
  const current = v.status === "current" && (ongoing || t(v.valid_to) > now);
  const superseded = v.status === "superseded" || v.status === "overridden" || (!ongoing && t(v.valid_to) <= now);
  const label = valueText(v.value);
  const span = `${v.valid_from ? fmtDate(v.valid_from) : "the start"} – ${v.valid_to ? fmtDate(v.valid_to) : "ongoing"}`;
  return (
    <button
      type="button"
      onClick={() => onPick(v)}
      title={`${label}\n${span}\n${v.source_label ?? ""} ${v.locator ?? ""} · ${v.status}`}
      aria-label={`${humanKey(v.attribute)}: ${label}, ${v.status}, ${span}`}
      style={{ left: `${left}%`, width: `${width}%` }}
      className={cx(
        "absolute inset-y-0 flex items-center gap-1 overflow-hidden px-2.5 text-left text-[12px] font-medium transition-shadow hover:shadow-card",
        c.before ? "rounded-r-lg rounded-l-sm" : "rounded-lg",
        ongoing && "rounded-r-sm",
        current
          ? "bg-rose text-surface"
          : superseded
            ? "bg-fill text-muted line-through decoration-muted/60"
            : "border border-hairline bg-surface text-muted",
        selected && "ring-2 ring-ink ring-offset-1",
      )}
    >
      {c.before && (
        <span className="inline-block shrink-0 font-mono text-[10px] opacity-70" aria-hidden>
          ‹
        </span>
      )}
      <span className="truncate">{label}</span>
    </button>
  );
}

const sourceText = (v: FactVersion) =>
  `${v.source_label ?? "Source"}${v.locator && v.locator !== v.source_label ? ` · ${v.locator}` : ""}`;

/** A fact's passage as a citation, for the source drawer (which loads the rest). */
function factCitation(v: FactVersion): Citation | null {
  if (!v.passage_id) return null;
  return {
    n: 0,
    passage_id: v.passage_id,
    file: "",
    short_label: sourceText(v),
    locator: v.locator ?? "",
    section_title: "",
    doc_type: "other",
    status: "current",
    quote: v.quote ?? "",
  };
}

/** "Read the passage" (drawer) and "Open original" (the file as received). */
function SourceLinks({ v, onSource }: { v: FactVersion; onSource: (c: Citation) => void }) {
  const cite = factCitation(v);
  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5">
      {cite && (
        <button
          type="button"
          onClick={() => onSource(cite)}
          className="inline-flex items-center gap-1.5 text-[13px] font-medium text-rose hover:text-rose-hover"
        >
          <FileText className="h-3.5 w-3.5" aria-hidden />
          Read {sourceText(v)}
        </button>
      )}
      {v.episode_id && !DEMO_MODE && (
        <a
          href={originalUrl(v.episode_id)}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1.5 text-[13px] font-medium text-rose hover:text-rose-hover"
        >
          <ExternalLink className="h-3.5 w-3.5" aria-hidden />
          Open original
        </a>
      )}
    </div>
  );
}

function FactDetail({ v, onClose, onSource }: { v: FactVersion; onClose: () => void; onSource: (c: Citation) => void }) {
  const rows: [string, string][] = [
    ["Value", valueText(v.value)],
    ["Status", v.status],
    ["Kind", v.kind],
    ["Scope", v.scope?.client ?? "all"],
    ["Valid from", v.valid_from ? fmtDate(v.valid_from) : "–"],
    ["Valid to", v.valid_to ? fmtDate(v.valid_to) : "open"],
    ["Recorded", fmtDateTime(v.recorded_at)],
    ["Retracted", v.retracted_at ? fmtDateTime(v.retracted_at) : "–"],
    ["Authority rank", String(v.authority_rank)],
  ];
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="eyebrow">Fact #{v.id}</p>
          <p className="mt-1 text-sm font-semibold text-ink">{humanKey(v.attribute)}</p>
        </div>
        <button type="button" onClick={onClose} aria-label="Close fact" className="rounded-full p-1 text-muted hover:bg-fill hover:text-ink">
          <X className="h-4 w-4" aria-hidden />
        </button>
      </div>
      <p className="mt-2 text-[13px] leading-relaxed text-ink">{v.statement}</p>
      <SourceLinks v={v} onSource={onSource} />
      <dl className="mt-3 divide-y divide-hairline text-[13px]">
        {rows.map(([k, val]) => (
          <div key={k} className="flex justify-between gap-3 py-1.5">
            <dt className="text-muted">{k}</dt>
            <dd className="text-right font-mono text-[12px] text-ink">{val}</dd>
          </div>
        ))}
      </dl>
      {v.quote && <p className="mt-3 border-l-[3px] border-rose pl-3 text-[13px] leading-relaxed text-ink">{v.quote}</p>}
    </Card>
  );
}

function EntityPicker({ entities, value, onPick }: { entities: EntitySummary[]; value: string | null; onPick: (id: string) => void }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const needle = q.trim().toLowerCase();
  const hits = entities
    .filter((e) => e.facts > 0 && (!needle || `${e.name} ${e.aliases.join(" ")} ${e.type}`.toLowerCase().includes(needle)))
    .sort((a, b) => b.facts - a.facts)
    .slice(0, 12);
  const cur = entities.find((e) => e.id === value);
  return (
    <div className="relative">
      <label className="relative block">
        <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted" aria-hidden />
        <input
          value={open ? q : (cur?.name ?? q)}
          onFocus={() => {
            setOpen(true);
            setQ("");
          }}
          onBlur={() => window.setTimeout(() => setOpen(false), 150)}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Find an entity: a rule topic, a supplier, a role…"
          aria-label="Find an entity"
          className="w-full rounded-full border border-hairline bg-surface py-2 pl-9 pr-3 text-sm text-ink placeholder:text-muted focus:border-muted focus:outline-none"
        />
      </label>
      {open && hits.length > 0 && (
        <ul className="absolute z-30 mt-1.5 max-h-80 w-full overflow-y-auto rounded-2xl border border-hairline bg-surface p-1.5 shadow-card">
          {hits.map((e) => (
            <li key={e.id}>
              <button
                type="button"
                onMouseDown={(ev) => ev.preventDefault()}
                onClick={() => {
                  onPick(e.id);
                  setOpen(false);
                }}
                className="flex w-full items-center justify-between gap-3 rounded-xl px-3 py-2 text-left hover:bg-fill"
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm text-ink">{e.name}</span>
                  <span className="font-mono text-[11px] text-muted">{e.type}</span>
                </span>
                <span className="shrink-0 font-mono text-[11px] text-muted">{plural(e.facts, "fact")}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function EntitiesView() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const entities = useApi<EntitySummary[]>("/entities");
  const [id, setId] = useState<string | null>(params.get("id"));
  useEffect(() => {
    if (id || !entities.data) return;
    const best = [...entities.data].filter((e) => e.type === "topic").sort((a, b) => b.facts - a.facts)[0];
    if (best) setId(best.id);
  }, [entities.data, id]);
  const tl = useApi<Timeline>(id ? `/entities/${id}/timeline` : null);

  const now = useMemo(() => Date.now(), []);
  const [asOf, setAsOf] = useState<number>(now);
  const [knownMode, setKnownMode] = useState(false);
  const [knownAt, setKnownAt] = useState<number>(now);
  const [picked, setPicked] = useState<FactVersion | null>(null);
  const [source, setSource] = useState<Citation | null>(null);
  const [span, setSpan] = useState<Span>("1y");
  // On a narrow screen the chart scrolls sideways: open it at the "now" end, where the current bars are.
  const chartRef = useRef<HTMLDivElement>(null);
  const chartReady = Boolean(tl.data);
  useEffect(() => {
    const el = chartRef.current;
    if (chartReady && el && el.scrollWidth > el.clientWidth) el.scrollLeft = el.scrollWidth;
  }, [chartReady, id, span]);
  const [attrFilter, setAttrFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");

  const pick = (eid: string) => {
    setId(eid);
    setPicked(null);
    setAttrFilter("all");
    router.replace(`${pathname}?id=${eid}`, { scroll: false });
  };

  const all = useMemo(() => tl.data?.attributes.flatMap((a) => a.versions) ?? [], [tl.data]);
  const visible = useMemo(() => all.filter((v) => known(v, knownMode ? knownAt : null)), [all, knownMode, knownAt]);

  const [d0, d1] = useMemo(() => {
    const starts = all.map((v) => t(v.valid_from)).filter((x) => !Number.isNaN(x));
    const ends = all.map((v) => t(v.valid_to)).filter((x) => !Number.isNaN(x));
    const lo = Math.min(now - 365 * DAY, ...starts);
    const hi = Math.max(now + 60 * DAY, ...ends);
    const pad = (hi - lo) * 0.03;
    return [lo - pad, hi + pad];
  }, [all, now]);
  const [r0, r1] = useMemo(() => {
    const rec = all.map((v) => t(v.recorded_at)).filter((x) => !Number.isNaN(x));
    return [rec.length ? Math.min(...rec) : now - 30 * DAY, now];
  }, [all, now]);

  const rows: Row[] = useMemo(() => {
    const by = new Map<string, FactVersion[]>();
    for (const v of visible) {
      const scope = v.scope?.client ?? "all";
      const key = `${v.attribute}|${scope}`;
      by.set(key, [...(by.get(key) ?? []), v]);
    }
    return [...by.entries()]
      .map(([key, vs]) => {
        // Overlapping versions (the same rule stated in several documents) stack in lanes.
        const lanes: FactVersion[][] = [];
        for (const v of [...vs].sort((a, b) => (t(a.valid_from) || 0) - (t(b.valid_from) || 0))) {
          const s = Number.isNaN(t(v.valid_from)) ? -Infinity : t(v.valid_from);
          const lane = lanes.find((l) => {
            const last = l[l.length - 1]!;
            const e = Number.isNaN(t(last.valid_to)) ? Infinity : t(last.valid_to);
            return e <= s;
          });
          if (lane) lane.push(v);
          else lanes.push([v]);
        }
        const [attribute = "", scope = "all"] = key.split("|");
        const viaScope = vs.every((v) => v.via === "scope");
        return { key, attribute, scope, topic: viaScope ? (vs[0]?.subject_name ?? null) : null, lanes: lanes.slice(0, 4) };
      })
      .filter((r) => attrFilter === "all" || r.attribute === attrFilter)
      .sort((a, b) => a.attribute.localeCompare(b.attribute));
  }, [visible, attrFilter]);

  const inForce = useMemo(
    () =>
      rows.map((r) => {
        const hit = r.lanes
          .flat()
          .filter((v) => IN_FORCE.has(v.status) && v.kind !== "practice" && inInterval(v, asOf))
          .sort((a, b) => a.authority_rank - b.authority_rank || Number(b.status === "current") - Number(a.status === "current"))[0];
        // Nothing in force: a pending or provisional statement is shown as such, never as the rule.
        const held = r.lanes
          .flat()
          .filter((v) => (v.status === "pending" || v.status === "provisional") && v.kind !== "practice" && inInterval(v, asOf))
          .sort((a, b) => a.authority_rank - b.authority_rank)[0];
        // An expert habit is shown as practice: it is not a rule, so it is never "in force".
        const practice = r.lanes
          .flat()
          .filter((v) => v.kind === "practice" && IN_FORCE.has(v.status) && inInterval(v, asOf))
          .sort((a, b) => a.authority_rank - b.authority_rank)[0];
        return { r, v: hit ?? null, held: hit ? null : (held ?? null), practice: hit || held ? null : (practice ?? null) };
      }),
    [rows, asOf],
  );

  // The chart's window: the chosen span back from now, plus room after now so ongoing rules
  // read as long bars rather than slivers at the edge.
  const [v0, v1] = useMemo(() => {
    const months = SPANS.find((s) => s.key === span)?.months ?? 0;
    if (!months) return [d0, d1];
    const back = months * 30.4 * DAY;
    return [Math.max(d0, now - back), now + back * 0.25];
  }, [span, d0, d1, now]);
  const pct = (ms: number) => ((ms - v0) / (v1 - v0)) * 100;
  const asOfShown = asOf >= v0 && asOf <= v1;
  const entity = tl.data?.entity;
  const facts = visible.filter(
    (v) => (attrFilter === "all" || v.attribute === attrFilter) && (statusFilter === "all" || v.status === statusFilter),
  );
  const statuses = Array.from(new Set(all.map((v) => v.status))).sort();
  const attributes = Array.from(new Set(all.map((v) => v.attribute))).sort();

  return (
    <PageColumns
      railLabel="Facts"
      main={
        <>
          <PageHeader eyebrow="Entities" title={entity?.name ?? "Entity timeline"} meta={entity && <span>{entity.type}</span>}>
            Each bar is a fact across the dates it was true. Drag the as-of marker to see what was in force on a day; switch on Known at to replay what the engine believed then.
          </PageHeader>
          {entities.data && <EntityPicker entities={entities.data} value={id} onPick={pick} />}
          {entity && (tl.data?.scoped_facts ?? 0) > 0 && (
            <p className="mt-3 text-[13px] text-muted">
              Includes {plural(tl.data?.scoped_facts ?? 0, "fact version")} that apply only to {entity.name}, stated under their topics (shown under each row).
            </p>
          )}
          {entity && entity.aliases.filter((a) => a !== entity.name).length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {entity.aliases
                .filter((a) => a !== entity.name)
                .map((a) => (
                  <span key={a} className="rounded-full bg-fill px-2.5 py-0.5 text-[12px] text-muted">
                    {a}
                  </span>
                ))}
            </div>
          )}

          {tl.error ? (
            <div className="mt-6">
              <ErrorNote message={tl.error} onRetry={() => void tl.reload()} />
            </div>
          ) : tl.loading || !tl.data ? (
            <div className="mt-6">
              <SkeletonRows rows={5} height="h-12" />
            </div>
          ) : rows.length === 0 ? (
            <div className="mt-6">
              <Empty icon={Network} title="No facts to show">
                {knownMode ? "The engine knew nothing about this entity yet at that time." : "This entity has no facts yet."}
              </Empty>
            </div>
          ) : (
            <>
              <Card className="mt-6 p-4">
                <div className="grid gap-3">
                  <label className="flex min-w-0 items-center gap-3 text-[13px] text-ink">
                    <CalendarClock className="h-4 w-4 shrink-0 text-muted" aria-hidden />
                    <span className="shrink-0 font-medium">As of</span>
                    <input
                      type="range"
                      min={d0}
                      max={d1}
                      step={DAY}
                      value={asOf}
                      onChange={(e) => setAsOf(Number(e.target.value))}
                      aria-label="As-of date"
                      aria-valuetext={fmtDate(isoDay(asOf))}
                      className="min-w-0 flex-1 accent-ink"
                    />
                    <input
                      type="date"
                      value={isoDay(asOf)}
                      onChange={(e) => e.target.value && setAsOf(new Date(e.target.value).getTime())}
                      aria-label="As-of date (exact)"
                      className="rounded-lg border border-hairline bg-surface px-2 py-1 font-mono text-[12px] text-ink focus:border-muted focus:outline-none"
                    />
                  </label>
                  <div className="flex min-w-0 items-center gap-3 text-[13px] text-ink">
                    <label className="flex shrink-0 cursor-pointer items-center gap-2 font-medium">
                      <input type="checkbox" checked={knownMode} onChange={(e) => setKnownMode(e.target.checked)} className="accent-ink" />
                      <History className="h-4 w-4 text-muted" aria-hidden />
                      Known at
                    </label>
                    <input
                      type="range"
                      min={r0}
                      max={r1}
                      step={3_600_000}
                      value={knownAt}
                      disabled={!knownMode}
                      onChange={(e) => setKnownAt(Number(e.target.value))}
                      aria-label="Known-at time"
                      aria-valuetext={fmtDateTime(new Date(knownAt).toISOString())}
                      className="min-w-0 flex-1 accent-ink disabled:opacity-40"
                    />
                    <span className="w-28 shrink-0 text-right font-mono text-[11px] text-muted">
                      {knownMode ? fmtDateTime(new Date(knownAt).toISOString()) : "now"}
                    </span>
                  </div>
                </div>
              </Card>

              <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
                <div role="group" aria-label="Chart range" className="flex rounded-full border border-hairline bg-surface p-0.5">
                  {SPANS.map((s) => (
                    <button
                      key={s.key}
                      type="button"
                      onClick={() => setSpan(s.key)}
                      aria-pressed={span === s.key}
                      className={cx(
                        "rounded-full px-3 py-1 text-[12px] font-medium transition-colors",
                        span === s.key ? "bg-ink text-surface" : "text-muted hover:text-ink",
                      )}
                    >
                      {s.label}
                    </button>
                  ))}
                </div>
                {!asOfShown && (
                  <button
                    type="button"
                    onClick={() => setSpan("all")}
                    className="font-mono text-[11px] text-muted underline decoration-hairline underline-offset-2 hover:text-ink"
                  >
                    As of {fmtDate(isoDay(asOf))} is outside this range · show all time
                  </button>
                )}
              </div>
              <div ref={chartRef} className="mt-3 overflow-x-auto rounded-2xl border border-hairline bg-surface p-4 shadow-card">
                <div className="min-w-[560px]">
                  {/* axis */}
                  <div className="relative ml-0 h-7 border-b border-hairline sm:ml-[220px]">
                    {ticks(v0, v1).map((tk) => (
                      <span key={tk.at} className="absolute bottom-0 h-1.5 w-px bg-hairline" style={{ left: `${pct(tk.at)}%` }} aria-hidden />
                    ))}
                    {ticks(v0, v1).map((tk) => (
                      <span
                        key={`l${tk.at}`}
                        className="absolute top-0 -translate-x-1/2 whitespace-nowrap font-mono text-[10px] text-muted"
                        style={{ left: `${pct(tk.at)}%` }}
                      >
                        {tk.label}
                      </span>
                    ))}
                  </div>
                  <div className="relative">
                    {/* gridlines, then the now and as-of lines, over the tracks */}
                    <div className="pointer-events-none absolute inset-y-0 left-0 right-0 sm:left-[220px]">
                      {ticks(v0, v1).map((tk) => (
                        <span key={tk.at} className="absolute inset-y-0 w-px bg-hairline/60" style={{ left: `${pct(tk.at)}%` }} aria-hidden />
                      ))}
                      <span className="absolute inset-y-0 right-0 bg-fill/40" style={{ left: `${pct(now)}%` }} aria-hidden />
                      {/* behind the bars (they paint later), so it never cuts through a label */}
                      <span className="absolute inset-y-0 w-0.5 -translate-x-1/2 bg-rose/70" style={{ left: `${pct(now)}%` }} aria-hidden />
                      <span
                        className="absolute -top-2 z-20 -translate-x-1/2 rounded-full bg-rose px-2 font-mono text-[10px] leading-5 text-surface"
                        style={{ left: `${pct(now)}%` }}
                        aria-hidden
                      >
                        now
                      </span>
                      {Math.abs(asOf - now) > DAY && asOfShown && (
                        <span className="absolute inset-y-0 z-20 border-l-2 border-dashed border-ink" style={{ left: `${pct(asOf)}%` }} aria-hidden />
                      )}
                    </div>
                    <ul className="divide-y divide-hairline">
                      {rows.map((r) => (
                        <li key={r.key} className="py-3 sm:flex sm:items-start">
                          <div className="sticky left-0 z-10 mb-1.5 w-fit max-w-[280px] rounded-md bg-surface/90 pr-3 sm:static sm:mb-0 sm:w-[220px] sm:max-w-none sm:shrink-0 sm:bg-transparent sm:pt-1">
                            <p className="line-clamp-2 text-[13px] font-medium leading-snug text-ink" title={r.attribute}>
                              {humanKey(r.attribute)}
                            </p>
                            {r.topic ? (
                              <p className="truncate font-mono text-[10px] text-muted">{r.topic}</p>
                            ) : (
                              r.scope !== "all" && <p className="truncate font-mono text-[10px] text-muted">{r.scope}</p>
                            )}
                          </div>
                          <div className="relative flex-1 space-y-1.5">
                            {(() => {
                              const lanes = r.lanes.filter((lane) => lane.some((v) => clip(v, v0, v1)));
                              if (lanes.length === 0) {
                                const last = Math.max(...r.lanes.flat().map((v) => t(v.valid_to)).filter((x) => !Number.isNaN(x)));
                                return (
                                  <p className="flex h-8 items-center font-mono text-[11px] text-muted">
                                    {Number.isFinite(last) && last < v0 ? `No change in this range · ended ${fmtDate(isoDay(last))}` : "Outside this range"}
                                  </p>
                                );
                              }
                              return lanes.map((lane, i) => (
                                <div key={i} className="relative h-8">
                                  {lane.map((v) => (
                                    <Bar key={v.id} v={v} v0={v0} v1={v1} now={now} selected={picked?.id === v.id} onPick={setPicked} />
                                  ))}
                                </div>
                              ));
                            })()}
                          </div>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              </div>
              <div className="mt-2 flex flex-wrap gap-4 font-mono text-[11px] text-muted">
                <span className="flex items-center gap-1.5">
                  <span className="h-2.5 w-5 rounded bg-rose" aria-hidden /> current
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="h-2.5 w-5 rounded border border-hairline bg-surface" aria-hidden /> also stated / pending
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="h-2.5 w-5 rounded bg-fill" aria-hidden /> superseded
                </span>
                <span className="flex items-center gap-1.5">
                  <span aria-hidden>‹</span> began before this range
                </span>
              </div>

              <section className="mt-8">
                <SectionLabel icon={CalendarClock}>In force on {fmtDate(isoDay(asOf))}</SectionLabel>
                <Card className="overflow-hidden">
                  <ul className="divide-y divide-hairline">
                    {inForce.map(({ r, v, held, practice }) => (
                      <li key={r.key} className="flex items-baseline justify-between gap-4 px-4 py-2.5 text-sm">
                        <span className="text-muted">
                          {humanKey(r.attribute)}
                          {r.scope !== "all" && <span className="font-mono text-[11px]"> · {r.scope}</span>}
                        </span>
                        {v ? (
                          <span className="text-right">
                            <button type="button" onClick={() => setPicked(v)} className="font-medium text-ink hover:underline">
                              {valueText(v.value)}
                            </button>
                            {factCitation(v) ? (
                              <button
                                type="button"
                                onClick={() => setSource(factCitation(v))}
                                title="Read the source passage"
                                className="ml-2 font-mono text-[11px] text-rose hover:text-rose-hover hover:underline"
                              >
                                {sourceText(v)}
                              </button>
                            ) : (
                              <span className="ml-2 font-mono text-[11px] text-muted">{v.source_label}</span>
                            )}
                          </span>
                        ) : held ? (
                          <button type="button" onClick={() => setPicked(held)} className="text-right text-muted hover:underline">
                            not in force
                            <span className="ml-2 font-mono text-[11px]">
                              {held.status === "pending" ? "held for review" : "provisional"}: {valueText(held.value)} ({held.source_label})
                            </span>
                          </button>
                        ) : practice ? (
                          <button type="button" onClick={() => setPicked(practice)} className="text-right text-ink hover:underline">
                            {valueText(practice.value)}
                            <span className="ml-2 font-mono text-[11px] text-muted">practice · {practice.source_label}</span>
                          </button>
                        ) : (
                          <span className="text-muted">not in force</span>
                        )}
                      </li>
                    ))}
                  </ul>
                </Card>
              </section>
            </>
          )}
        </>
      }
      rail={
        <div className="space-y-5">
          {picked && <FactDetail v={picked} onClose={() => setPicked(null)} onSource={setSource} />}
          <SourceDrawer citation={source} onClose={() => setSource(null)} eyebrow="Source of this fact" />
          <div>
            <SectionLabel count={facts.length}>Facts</SectionLabel>
            <div className="grid grid-cols-2 gap-2">
              <select
                value={attrFilter}
                onChange={(e) => setAttrFilter(e.target.value)}
                aria-label="Attribute"
                className="min-w-0 rounded-xl border border-hairline bg-surface px-2.5 py-1.5 text-[13px] text-ink focus:border-muted focus:outline-none"
              >
                <option value="all">All attributes</option>
                {attributes.map((a) => (
                  <option key={a} value={a}>
                    {humanKey(a)}
                  </option>
                ))}
              </select>
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                aria-label="Status"
                className="min-w-0 rounded-xl border border-hairline bg-surface px-2.5 py-1.5 text-[13px] text-ink focus:border-muted focus:outline-none"
              >
                <option value="all">All statuses</option>
                {statuses.map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </div>
          </div>
          <ul className="space-y-2">
            {facts.slice(0, 80).map((v) => (
              <li key={v.id}>
                <button
                  type="button"
                  onClick={() => setPicked(v)}
                  className={cx(
                    "w-full rounded-2xl border p-3 text-left transition-colors",
                    picked?.id === v.id ? "border-rose-line bg-rose-tint" : "border-hairline bg-surface hover:border-muted",
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-[13px] font-medium text-ink">{humanKey(v.attribute)}</span>
                    <Pill>{v.status}</Pill>
                  </div>
                  <p className={cx("mt-1 text-[13px]", v.status === "superseded" ? "text-muted line-through" : "text-ink")}>
                    {valueText(v.value)}
                  </p>
                  <p className="mt-1 font-mono text-[11px] text-muted">
                    {v.source_label} · {v.valid_from ? fmtDate(v.valid_from) : "–"}
                  </p>
                </button>
              </li>
            ))}
          </ul>
        </div>
      }
    />
  );
}
