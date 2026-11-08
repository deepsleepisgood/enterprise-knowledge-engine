"use client";

import { CalendarClock, History, Network, Search, X } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { PageColumns } from "@/components/shell/PageColumns";
import { Card, Empty, ErrorNote, PageHeader, Pill, SectionLabel, SkeletonRows } from "@/components/ui/Primitives";
import { cx, fmtDate, fmtDateTime, humanKey, plural, valueText } from "@/lib/format";
import type { EntitySummary, FactVersion, Timeline } from "@/lib/types";
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

function Bar({ v, d0, d1, now, selected, onPick }: {
  v: FactVersion;
  d0: number;
  d1: number;
  now: number;
  selected: boolean;
  onPick: (v: FactVersion) => void;
}) {
  const from = Number.isNaN(t(v.valid_from)) ? d0 : Math.max(d0, t(v.valid_from));
  const to = Number.isNaN(t(v.valid_to)) ? d1 : Math.min(d1, t(v.valid_to));
  const left = ((from - d0) / (d1 - d0)) * 100;
  const width = Math.max(1.2, ((to - from) / (d1 - d0)) * 100);
  const current = v.status === "current" && (Number.isNaN(t(v.valid_to)) || t(v.valid_to) > now);
  const superseded = v.status === "superseded" || v.status === "overridden" || (!Number.isNaN(t(v.valid_to)) && t(v.valid_to) <= now);
  const label = valueText(v.value);
  return (
    <button
      type="button"
      onClick={() => onPick(v)}
      title={`${label} · ${v.source_label ?? ""} ${v.locator ?? ""} · ${v.status}`}
      aria-label={`${humanKey(v.attribute)}: ${label}, ${v.status}, from ${v.valid_from ? fmtDate(v.valid_from) : "the start"}${v.valid_to ? ` to ${fmtDate(v.valid_to)}` : ""}`}
      style={{ left: `${left}%`, width: `${width}%` }}
      className={cx(
        "absolute top-0 flex h-6 items-center overflow-hidden rounded-full px-2 text-left text-[11px] font-medium transition-shadow",
        current
          ? "bg-rose text-surface"
          : superseded
            ? "bg-fill text-muted line-through"
            : "border border-hairline bg-surface text-muted",
        selected && "ring-2 ring-ink ring-offset-1",
      )}
    >
      <span className="truncate">{label}</span>
    </button>
  );
}

function FactDetail({ v, onClose }: { v: FactVersion; onClose: () => void }) {
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
      {v.source_label && (
        <span className="mt-2 inline-flex rounded-full border border-hairline px-2.5 py-0.5 font-mono text-[11px] text-muted">
          {v.source_label}
          {v.locator && v.locator !== v.source_label ? ` · ${v.locator}` : ""}
        </span>
      )}
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
        return { key, attribute, scope, lanes: lanes.slice(0, 4) };
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
        const before = r.lanes.flat().filter((v) => inInterval(v, asOf) && v.kind !== "practice").sort((a, b) => a.authority_rank - b.authority_rank)[0];
        return { r, v: hit ?? before ?? null };
      }),
    [rows, asOf],
  );

  const pct = (ms: number) => ((ms - d0) / (d1 - d0)) * 100;
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
                <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
                  <label className="flex min-w-[240px] flex-1 items-center gap-3 text-[13px] text-ink">
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
                      className="flex-1 accent-ink"
                    />
                    <input
                      type="date"
                      value={isoDay(asOf)}
                      onChange={(e) => e.target.value && setAsOf(new Date(e.target.value).getTime())}
                      aria-label="As-of date (exact)"
                      className="rounded-lg border border-hairline bg-surface px-2 py-1 font-mono text-[12px] text-ink focus:border-muted focus:outline-none"
                    />
                  </label>
                  <div className="flex min-w-[240px] flex-1 items-center gap-3 text-[13px] text-ink">
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
                      className="flex-1 accent-ink disabled:opacity-40"
                    />
                    <span className="w-28 shrink-0 text-right font-mono text-[11px] text-muted">
                      {knownMode ? fmtDateTime(new Date(knownAt).toISOString()) : "now"}
                    </span>
                  </div>
                </div>
              </Card>

              <Card className="mt-4 overflow-x-auto p-4">
                <div className="min-w-[560px]">
                  {/* axis */}
                  <div className="relative ml-0 h-6 sm:ml-[200px]">
                    {ticks(d0, d1).map((tk) => (
                      <span
                        key={tk.at}
                        className="absolute -translate-x-1/2 whitespace-nowrap font-mono text-[10px] text-muted"
                        style={{ left: `${pct(tk.at)}%` }}
                      >
                        {tk.label}
                      </span>
                    ))}
                  </div>
                  <div className="relative">
                    {/* now and as-of lines over the tracks */}
                    <div className="pointer-events-none absolute inset-y-0 left-0 right-0 sm:left-[200px]">
                      <span className="absolute inset-y-0 w-px bg-rose" style={{ left: `${pct(now)}%` }} aria-hidden />
                      <span
                        className="absolute -top-1 -translate-x-1/2 rounded-full bg-rose px-1.5 font-mono text-[9px] leading-4 text-surface"
                        style={{ left: `${pct(now)}%` }}
                        aria-hidden
                      >
                        now
                      </span>
                      {Math.abs(asOf - now) > DAY && (
                        <span className="absolute inset-y-0 border-l border-dashed border-ink" style={{ left: `${pct(asOf)}%` }} aria-hidden />
                      )}
                    </div>
                    <ul className="divide-y divide-hairline">
                      {rows.map((r) => (
                        <li key={r.key} className="py-2.5 sm:flex sm:items-start">
                          <div className="mb-1.5 pr-3 sm:mb-0 sm:w-[200px] sm:shrink-0">
                            <p className="truncate text-[13px] font-medium text-ink" title={r.attribute}>
                              {humanKey(r.attribute)}
                            </p>
                            {r.scope !== "all" && <p className="truncate font-mono text-[10px] text-muted">{r.scope}</p>}
                          </div>
                          <div className="relative flex-1 space-y-1">
                            {r.lanes.map((lane, i) => (
                              <div key={i} className="relative h-6">
                                {lane.map((v) => (
                                  <Bar key={v.id} v={v} d0={d0} d1={d1} now={now} selected={picked?.id === v.id} onPick={setPicked} />
                                ))}
                              </div>
                            ))}
                          </div>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              </Card>
              <div className="mt-2 flex flex-wrap gap-4 font-mono text-[11px] text-muted">
                <span className="flex items-center gap-1.5">
                  <span className="h-2.5 w-5 rounded-full bg-rose" aria-hidden /> current
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="h-2.5 w-5 rounded-full border border-hairline bg-surface" aria-hidden /> also stated / pending
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="h-2.5 w-5 rounded-full bg-fill" aria-hidden /> superseded
                </span>
              </div>

              <section className="mt-8">
                <SectionLabel icon={CalendarClock}>In force on {fmtDate(isoDay(asOf))}</SectionLabel>
                <Card className="overflow-hidden">
                  <ul className="divide-y divide-hairline">
                    {inForce.map(({ r, v }) => (
                      <li key={r.key} className="flex items-baseline justify-between gap-4 px-4 py-2.5 text-sm">
                        <span className="text-muted">
                          {humanKey(r.attribute)}
                          {r.scope !== "all" && <span className="font-mono text-[11px]"> · {r.scope}</span>}
                        </span>
                        {v ? (
                          <button type="button" onClick={() => setPicked(v)} className="text-right font-medium text-ink hover:underline">
                            {valueText(v.value)}
                            <span className="ml-2 font-mono text-[11px] font-normal text-muted">{v.source_label}</span>
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
          {picked && <FactDetail v={picked} onClose={() => setPicked(null)} />}
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
