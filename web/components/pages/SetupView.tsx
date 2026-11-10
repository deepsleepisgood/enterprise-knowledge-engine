"use client";

import {
  ArrowDown,
  ArrowUp,
  Check,
  ChevronDown,
  GitMerge,
  Lock,
  PencilLine,
  Save,
  Search,
  Scissors,
  ShieldAlert,
  Snowflake,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { PageColumns } from "@/components/shell/PageColumns";
import { useRole } from "@/components/shell/RoleContext";
import { Button, Card, ErrorNote, PageHeader, Pill, SectionLabel, SkeletonRows, useToast } from "@/components/ui/Primitives";
import { apiSend } from "@/lib/api";
import { cx, fmtDateTime, plural } from "@/lib/format";
import type { Binding, EntitySummary, Ontology, Risk, SchemaState, Stats } from "@/lib/types";
import { useApi } from "@/lib/useApi";

type Tab = "schema" | "entities";
const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, "");

function Rows({ children }: { children: React.ReactNode }) {
  return <ul className="divide-y divide-hairline">{children}</ul>;
}

function CardHead({ title, hint, right }: { title: string; hint?: string; right?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-hairline px-4 py-3">
      <div>
        <h2 className="font-display text-[15px] font-semibold text-ink">{title}</h2>
        {hint && <p className="mt-0.5 text-[13px] text-muted">{hint}</p>}
      </div>
      {right}
    </div>
  );
}

function SchemaTab({ onto, editable, onChange, stats, bindings, onBindingsChanged }: {
  onto: Ontology;
  editable: boolean;
  onChange: (o: Ontology) => void;
  stats: Stats | null;
  bindings: Binding[];
  onBindingsChanged: () => void;
}) {
  const { userId } = useRole();
  const toast = useToast();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<Set<string>>(new Set());
  const counts = useMemo(() => {
    const m = new Map<string, number>();
    for (const [k, v] of Object.entries(stats?.entities_by_type ?? {})) m.set(norm(k), v);
    return m;
  }, [stats]);

  const needle = q.trim().toLowerCase();
  const topics = onto.topics
    .map((t) => ({
      t,
      attrs: onto.attributes.filter(
        (a) =>
          a.topic === t.key &&
          (!needle || `${a.key} ${a.label} ${a.synonyms.join(" ")} ${t.label}`.toLowerCase().includes(needle)),
      ),
    }))
    .filter((x) => x.attrs.length > 0 || !needle);

  const setTopic = (key: string, patch: Partial<Ontology["topics"][number]>) =>
    onChange({ ...onto, topics: onto.topics.map((t) => (t.key === key ? { ...t, ...patch } : t)) });
  const setAttr = (key: string, patch: Partial<Ontology["attributes"][number]>) =>
    onChange({ ...onto, attributes: onto.attributes.map((a) => (a.key === key ? { ...a, ...patch } : a)) });
  const ranks = [...onto.source_ranking].sort((a, b) => a.rank - b.rank);
  const move = (i: number, d: -1 | 1) => {
    const j = i + d;
    if (j < 0 || j >= ranks.length) return;
    const next = [...ranks];
    [next[i], next[j]] = [next[j]!, next[i]!];
    onChange({ ...onto, source_ranking: next.map((r, k) => ({ ...r, rank: k + 1 })) });
  };
  const confirm = async (b: Binding) => {
    if (!b.attribute_key) return;
    try {
      await apiSend("PUT", `/bindings/${b.id}`, {
        attribute_key: b.attribute_key,
        subject_entity_id: b.subject_entity_id,
        confirmed_by: userId,
      });
      toast(`${b.param} confirmed.`);
      onBindingsChanged();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  const sortedBindings = [...bindings].sort(
    (a, b) => Number(Boolean(a.attribute_key)) - Number(Boolean(b.attribute_key)) || (a.confidence ?? 0) - (b.confidence ?? 0),
  );
  const input =
    "w-full rounded-lg border border-transparent bg-transparent px-1.5 py-0.5 text-sm text-ink hover:border-hairline focus:border-muted focus:bg-surface focus:outline-none disabled:hover:border-transparent";

  return (
    <div className="space-y-5">
      <Card className="overflow-hidden">
        <CardHead title="Entity types" hint="The kinds of things the engine found in your documents." />
        <Rows>
          {onto.entity_types.map((e, i) => (
            <li key={`${e.name}-${i}`} className="flex items-start justify-between gap-4 px-4 py-2.5">
              <div className="min-w-0">
                <p className="text-sm font-medium text-ink">{e.name}</p>
                {e.description && <p className="mt-0.5 text-[13px] text-muted">{e.description}</p>}
              </div>
              <span className="shrink-0 font-mono text-[12px] text-muted">{counts.get(norm(e.name)) ?? 0}</span>
            </li>
          ))}
        </Rows>
      </Card>

      <Card className="overflow-hidden">
        <CardHead
          title="Topics and attributes"
          hint={`${plural(onto.topics.length, "topic")} · ${plural(onto.attributes.length, "attribute")}`}
          right={
            <label className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-2 h-4 w-4 text-muted" aria-hidden />
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Find an attribute"
                aria-label="Find an attribute"
                className="w-52 rounded-full border border-hairline bg-canvas py-1.5 pl-8 pr-3 text-[13px] text-ink placeholder:text-muted focus:border-muted focus:outline-none"
              />
            </label>
          }
        />
        <Rows>
          {topics.map(({ t, attrs }) => {
            const expanded = open.has(t.key) || Boolean(needle);
            return (
              <li key={t.key}>
                <div className="flex items-center gap-3 px-4 py-2.5">
                  <button
                    type="button"
                    onClick={() =>
                      setOpen((s) => {
                        const n = new Set(s);
                        if (n.has(t.key)) n.delete(t.key);
                        else n.add(t.key);
                        return n;
                      })
                    }
                    aria-expanded={expanded}
                    className="flex min-w-0 flex-1 items-center gap-2 text-left"
                  >
                    <ChevronDown className={cx("h-4 w-4 shrink-0 text-muted transition-transform", !expanded && "-rotate-90")} aria-hidden />
                    <span className="truncate text-sm font-semibold text-ink">{t.label}</span>
                    <span className="font-mono text-[11px] text-muted">{attrs.length}</span>
                  </button>
                  <label className="flex items-center gap-1.5 text-[12px] text-muted">
                    risk
                    <select
                      value={t.risk}
                      disabled={!editable}
                      onChange={(e) => setTopic(t.key, { risk: e.target.value as Risk })}
                      className="rounded-full border border-hairline bg-surface px-2 py-0.5 text-[12px] text-ink disabled:border-transparent disabled:bg-transparent"
                    >
                      <option value="low">low</option>
                      <option value="medium">medium</option>
                      <option value="high">high</option>
                    </select>
                  </label>
                </div>
                {expanded && (
                  <ul className="divide-y divide-hairline border-t border-hairline bg-canvas">
                    {attrs.map((a) => (
                      <li key={a.key} className="grid gap-1 px-4 py-2.5 sm:grid-cols-[1.1fr_1fr_auto] sm:items-center sm:gap-3">
                        <span className="truncate font-mono text-[11px] text-muted" title={a.key}>
                          {a.key}
                        </span>
                        <input
                          value={a.label}
                          disabled={!editable}
                          onChange={(e) => setAttr(a.key, { label: e.target.value })}
                          aria-label={`Label for ${a.key}`}
                          className={input}
                        />
                        <span className="flex flex-wrap items-center gap-1.5">
                          <Pill tone="outline">{a.value_type}</Pill>
                          {a.unit && <Pill tone="outline">{a.unit}</Pill>}
                        </span>
                        {a.synonyms.length > 0 && (
                          <span className="flex flex-wrap gap-1 sm:col-span-3">
                            {a.synonyms.slice(0, 6).map((s, i) => (
                              <span key={`${s}-${i}`} className="rounded-full bg-fill px-2 py-0.5 text-[11px] text-muted">
                                {s}
                              </span>
                            ))}
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </Rows>
      </Card>

      <Card className="overflow-hidden">
        <CardHead title="Source authority" hint="Higher beats lower; a newer document never overrides a more authoritative one." />
        <ol className="divide-y divide-hairline">
          {ranks.map((r, i) => (
            <li key={`${r.doc_type}-${i}`} className="flex items-start gap-3 px-4 py-2.5">
              <span className="mt-0.5 w-5 shrink-0 font-mono text-[12px] text-muted">{r.rank}</span>
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-2 text-sm font-medium text-ink">
                  {r.doc_type.replace(/_/g, " ")}
                  {r.practice && <Pill>practice only</Pill>}
                </p>
                {r.reason && <p className="mt-0.5 text-[13px] text-muted">{r.reason}</p>}
              </div>
              {editable && (
                <span className="flex shrink-0 gap-1">
                  <button type="button" onClick={() => move(i, -1)} disabled={i === 0} aria-label={`Move ${r.doc_type} up`} className="rounded-lg p-1 text-muted hover:bg-fill hover:text-ink disabled:opacity-30">
                    <ArrowUp className="h-4 w-4" aria-hidden />
                  </button>
                  <button type="button" onClick={() => move(i, 1)} disabled={i === ranks.length - 1} aria-label={`Move ${r.doc_type} down`} className="rounded-lg p-1 text-muted hover:bg-fill hover:text-ink disabled:opacity-30">
                    <ArrowDown className="h-4 w-4" aria-hidden />
                  </button>
                </span>
              )}
            </li>
          ))}
        </ol>
      </Card>

      <div className="grid gap-5 md:grid-cols-2">
        <Card className="overflow-hidden">
          <CardHead title="High-risk topics" hint="Changes here always wait for the process owner." />
          <div className="flex flex-wrap gap-1.5 p-4">
            {onto.topics.filter((t) => t.risk === "high").length === 0 ? (
              <p className="text-[13px] text-muted">None marked yet.</p>
            ) : (
              onto.topics
                .filter((t) => t.risk === "high")
                .map((t) => (
                  <Pill key={t.key} icon={ShieldAlert} tone="ink">
                    {t.label}
                  </Pill>
                ))
            )}
          </div>
        </Card>
        <Card className="overflow-hidden">
          <CardHead title="Who may change what" hint="Anyone else's change is held for review." />
          {onto.sender_authority.length === 0 ? (
            <p className="p-4 text-[13px] text-muted">No owners registered: every change is reviewed.</p>
          ) : (
            <Rows>
              {onto.sender_authority.map((s, i) => (
                <li key={i} className="px-4 py-2.5 text-sm">
                  <span className="font-medium text-ink">{s.who}</span>
                  <span className="text-muted"> → {s.topics.join(", ") || "all topics"}</span>
                  <span className="font-mono text-[11px] text-muted"> · {s.client}</span>
                </li>
              ))}
            </Rows>
          )}
        </Card>
      </div>

      <Card className="overflow-hidden">
        <CardHead title="Plug-in bindings" hint="Where each calculator parameter reads its rule. Unresolved and least certain first." />
        <Rows>
          {sortedBindings.map((b) => (
            <li key={b.id} className="grid gap-1 px-4 py-2.5 sm:grid-cols-[1fr_1.3fr_auto] sm:items-center sm:gap-3">
              <span className="text-sm text-ink">
                <span className="font-mono text-[11px] text-muted">{b.plugin} · </span>
                {b.param}
              </span>
              <span className={cx("truncate font-mono text-[12px]", b.attribute_key ? "text-ink" : "italic text-muted")} title={b.attribute_key ?? ""}>
                {b.attribute_key ?? "unresolved"}
                {b.confidence !== null && <span className="text-muted"> · {b.confidence.toFixed(2)}</span>}
              </span>
              {b.confirmed_by ? (
                <Pill icon={Check}>confirmed</Pill>
              ) : b.attribute_key ? (
                <Button className="h-8" onClick={() => void confirm(b)}>
                  Confirm
                </Button>
              ) : (
                <Pill>needs a binding</Pill>
              )}
            </li>
          ))}
        </Rows>
      </Card>
    </div>
  );
}

function EntitiesTab() {
  const { userId } = useRole();
  const toast = useToast();
  const { data, loading, reload } = useApi<EntitySummary[]>("/entities");
  const [q, setQ] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [moving, setMoving] = useState<string[]>([]);
  const list = (data ?? []).filter((e) =>
    `${e.name} ${e.type} ${e.aliases.join(" ")}`.toLowerCase().includes(q.trim().toLowerCase()),
  );
  const byId = new Map((data ?? []).map((e) => [e.id, e]));
  const toggle = (id: string) => {
    setMoving([]);
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p.slice(-1), id]));
  };
  const one = picked.length === 1 ? byId.get(picked[0]!) : undefined;
  const flip = (alias: string) => setMoving((m) => (m.includes(alias) ? m.filter((x) => x !== alias) : [...m, alias]));
  const split = async () => {
    if (!one || !moving.length) return;
    try {
      const out = await apiSend<{ moved_facts: number }>("POST", `/entities/${one.id}/split`, {
        name: moving[0],
        aliases: moving,
        by: userId,
      });
      toast(`${moving[0]} is now its own entity; ${plural(out.moved_facts, "fact")} moved with it.`);
      setPicked([]);
      setMoving([]);
      void reload();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  const merge = async () => {
    const [keep, drop] = picked;
    if (!keep || !drop) return;
    try {
      await apiSend("POST", "/entities/merge", { keep_id: keep, drop_id: drop, by: userId });
      toast(`${byId.get(drop)?.name} merged into ${byId.get(keep)?.name}.`);
      setPicked([]);
      void reload();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <label className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted" aria-hidden />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search entities and aliases"
            aria-label="Search entities"
            className="w-full rounded-full border border-hairline bg-surface py-2 pl-9 pr-3 text-sm text-ink placeholder:text-muted focus:border-muted focus:outline-none"
          />
        </label>
        <Button icon={GitMerge} disabled={picked.length !== 2} onClick={() => void merge()}>
          Merge {picked.length === 2 ? `${byId.get(picked[1]!)?.name} into ${byId.get(picked[0]!)?.name}` : "two"}
        </Button>
        <Button variant="ghost" icon={Scissors} disabled={!one || moving.length === 0} onClick={() => void split()}>
          {one && moving.length ? `Split ${moving[0]} out of ${one.name}` : "Split"}
        </Button>
      </div>
      <p className="mt-2 font-mono text-[11px] text-muted">
        Merge: pick the entity to keep, then the one to merge into it. Split: pick one entity, then click the names that
        are really a different entity. Facts that name them move with them; nothing is deleted.
      </p>
      {loading && !data ? (
        <div className="mt-4">
          <SkeletonRows rows={6} height="h-12" />
        </div>
      ) : (
        <Card className="mt-4 overflow-hidden">
          <Rows>
            {list.slice(0, 200).map((e) => {
              const n = picked.indexOf(e.id);
              return (
                <li key={e.id}>
                  <label className="flex cursor-pointer items-start gap-3 px-4 py-2.5 hover:bg-canvas">
                    <input type="checkbox" checked={n >= 0} onChange={() => toggle(e.id)} className="mt-1 accent-rose" />
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium text-ink">{e.name}</span>
                        <span className="font-mono text-[11px] text-muted">{e.type}</span>
                        {n === 0 && <Pill tone="ink">keep</Pill>}
                        {n === 1 && <Pill>merge in</Pill>}
                      </span>
                      {e.aliases.filter((a) => a !== e.name).length > 0 && (
                        <span className="mt-1 flex flex-wrap gap-1">
                          {e.aliases
                            .filter((a) => a !== e.name)
                            .slice(0, one?.id === e.id ? 50 : 6)
                            .map((a) =>
                              one?.id === e.id ? (
                                <button
                                  key={a}
                                  type="button"
                                  aria-pressed={moving.includes(a)}
                                  onClick={(ev) => {
                                    ev.preventDefault();
                                    flip(a);
                                  }}
                                  className={cx(
                                    "rounded-full border px-2 py-0.5 text-[11px]",
                                    moving.includes(a) ? "border-rose bg-rose-tint text-rose" : "border-hairline bg-fill text-muted hover:text-ink",
                                  )}
                                >
                                  {a}
                                </button>
                              ) : (
                                <span key={a} className="rounded-full bg-fill px-2 py-0.5 text-[11px] text-muted">
                                  {a}
                                </span>
                              ),
                            )}
                        </span>
                      )}
                    </span>
                    <span className="shrink-0 font-mono text-[11px] text-muted">{plural(e.facts, "fact")}</span>
                  </label>
                </li>
              );
            })}
          </Rows>
        </Card>
      )}
    </div>
  );
}

export function SetupView() {
  const { userId } = useRole();
  const toast = useToast();
  const schema = useApi<SchemaState>("/schema");
  const stats = useApi<Stats>("/stats");
  const bindings = useApi<Binding[]>("/bindings");
  const [tab, setTab] = useState<Tab>("schema");
  const [edit, setEdit] = useState<Ontology | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const draft = schema.data?.draft ?? null;
  const active = schema.data?.active ?? null;
  useEffect(() => {
    if (draft) setEdit(draft.ontology);
    else setEdit(null);
    setDirty(false);
  }, [draft]);

  const shown = edit ?? draft?.ontology ?? active?.ontology ?? null;
  const version = draft?.version ?? active?.version;

  const startDraft = async () => {
    setBusy("draft");
    try {
      await apiSend("POST", "/schema/draft", { by: userId });
      toast("Draft created. Edit below, then freeze it to apply.");
      await schema.reload();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  };
  const save = async () => {
    if (!draft || !edit) return false;
    setBusy("save");
    try {
      await apiSend("PUT", "/schema", { version: draft.version, ontology: edit });
      setDirty(false);
      toast("Draft saved.");
      return true;
    } catch (e) {
      toast((e as Error).message, "error");
      return false;
    } finally {
      setBusy(null);
    }
  };
  const freeze = async () => {
    if (!draft) return;
    if (dirty && !(await save())) return;
    setBusy("freeze");
    try {
      const out = await apiSend<{ version: number; rekeyed: number }>("POST", "/schema/freeze", {
        version: draft.version,
        by: userId,
      });
      toast(`Schema v${out.version} frozen. ${plural(out.rekeyed, "fact")} re-keyed.`);
      await schema.reload();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  };

  return (
    <PageColumns
      railLabel="Proposed by the engine"
      main={
        <>
          <PageHeader
            eyebrow="Setup"
            title="What the engine learned"
            meta={
              version !== undefined && (
                <>
                  <span>schema v{version}</span>
                  <Pill icon={draft ? PencilLine : Lock}>{draft ? "Draft" : "Frozen"}</Pill>
                </>
              )
            }
            actions={
              draft ? (
                <>
                  <Button icon={Save} busy={busy === "save"} disabled={!dirty} onClick={() => void save()}>
                    Save draft
                  </Button>
                  <Button variant="primary" icon={Snowflake} busy={busy === "freeze"} onClick={() => void freeze()}>
                    Freeze schema
                  </Button>
                </>
              ) : (
                <Button icon={PencilLine} busy={busy === "draft"} disabled={!active} onClick={() => void startDraft()}>
                  Edit schema
                </Button>
              )
            }
          >
            The engine read your documents and proposed this vocabulary, the authority of each kind of document and which rules are high-risk. Frozen versions never change; edits go into a draft.
          </PageHeader>

          <div role="tablist" aria-label="Setup sections" className="mb-6 flex gap-6 border-b border-hairline">
            {(["schema", "entities"] as Tab[]).map((t) => (
              <button
                key={t}
                role="tab"
                type="button"
                aria-selected={tab === t}
                onClick={() => setTab(t)}
                className={cx(
                  "-mb-px border-b-2 pb-2.5 text-sm font-medium capitalize transition-colors",
                  tab === t ? "border-rose text-ink" : "border-transparent text-muted hover:text-ink",
                )}
              >
                {t}
              </button>
            ))}
          </div>

          {tab === "entities" ? (
            <EntitiesTab />
          ) : schema.error ? (
            <ErrorNote message={schema.error} onRetry={() => void schema.reload()} />
          ) : !shown ? (
            <SkeletonRows rows={4} height="h-40" />
          ) : (
            <SchemaTab
              onto={shown}
              editable={Boolean(draft)}
              onChange={(o) => {
                setEdit(o);
                setDirty(true);
              }}
              stats={stats.data}
              bindings={bindings.data ?? []}
              onBindingsChanged={() => void bindings.reload()}
            />
          )}
        </>
      }
      rail={
        <div className="space-y-6">
          <div>
            <SectionLabel>Proposed by the engine</SectionLabel>
            <dl className="divide-y divide-hairline rounded-2xl border border-hairline bg-surface text-sm">
              {[
                ["Mode", (draft ?? active)?.mode ?? "–"],
                ["Learned from", (draft ?? active) ? plural((draft ?? active)!.sample.length, "passage") : "–"],
                ["Frozen", active?.frozen_at ? fmtDateTime(active.frozen_at) : "–"],
                ["Frozen by", active?.frozen_by ?? "–"],
                ["Currency", shown?.base_currency ?? "–"],
                ["Scope keys", shown?.scope_keys.join(", ") ?? "–"],
              ].map(([k, v]) => (
                <div key={k} className="flex justify-between gap-3 px-3.5 py-2">
                  <dt className="text-muted">{k}</dt>
                  <dd className="truncate text-right font-mono text-[12px] text-ink">{v}</dd>
                </div>
              ))}
            </dl>
          </div>
          {shown && Object.keys(shown.units).length > 0 && (
            <div>
              <SectionLabel>Units</SectionLabel>
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(shown.units).map(([u, m]) => (
                  <span key={u} className="rounded-full border border-hairline bg-surface px-2.5 py-0.5 font-mono text-[11px] text-muted">
                    {u} ×{m.toLocaleString("en-IN")}
                  </span>
                ))}
              </div>
            </div>
          )}
          {dirty && <p className="font-mono text-[11px] text-muted">unsaved edits</p>}
        </div>
      }
    />
  );
}
