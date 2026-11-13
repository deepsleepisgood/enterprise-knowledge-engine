"use client";

import {
  Check,
  ChevronDown,
  ExternalLink,
  FileWarning,
  FolderOpen,
  Globe,
  History,
  Mail,
  MailX,
  MessageSquare,
  Pencil,
  RotateCw,
  ShieldAlert,
  Upload,
  UploadCloud,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { DocGlyph } from "@/components/ask/DocGlyph";
import { PageColumns } from "@/components/shell/PageColumns";
import { useRole } from "@/components/shell/RoleContext";
import { useSignals } from "@/components/shell/Signals";
import { Button, Card, Empty, ErrorNote, PageHeader, Pill, SectionLabel, SkeletonRows, Stat, useToast } from "@/components/ui/Primitives";
import { API_URL, DEMO_MODE, apiSend, originalUrl, uploadFiles } from "@/lib/api";
import { cx, fmtAgo, fmtDate, fmtDateTime, plural } from "@/lib/format";
import type { Episode, EpisodeStatus, SourceBrief, UnsureField } from "@/lib/types";
import { useApi } from "@/lib/useApi";

const STEPS: EpisodeStatus[] = ["queued", "parsed", "extracted", "published"];
const HELD: Partial<Record<EpisodeStatus, { label: string; icon: typeof ShieldAlert }>> = {
  needs_attention: { label: "Needs attention", icon: FileWarning },
  pending_review: { label: "Pending review", icon: ShieldAlert },
  failed: { label: "Failed", icon: FileWarning },
  ignored: { label: "Ignored: no knowledge in it", icon: MailX },
  answered: { label: "Question: answered", icon: MessageSquare },
};
const TYPES = "docx pdf xlsx csv pptx html md txt eml vtt srt json zip";

const channelIcon = (c: string) => (c === "email" ? Mail : c === "api" || c === "expert_answer" ? MessageSquare : Upload);

function Pipeline({ status }: { status: EpisodeStatus }) {
  const at = STEPS.indexOf(status);
  const held = HELD[status];
  if (held) {
    return (
      <Pill icon={held.icon} tone="ink">
        {held.label}
      </Pill>
    );
  }
  return (
    <ol className="flex flex-wrap items-center gap-1" aria-label={`Pipeline: ${status}`}>
      {STEPS.map((s, i) => {
        const done = i < at || status === "published";
        const current = i === at && status !== "published";
        return (
          <li key={s}>
            <span
              className={cx(
                "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
                done ? "bg-fill text-ink" : current ? "bg-fill text-ink" : "border border-hairline text-muted",
              )}
              aria-current={current ? "step" : undefined}
            >
              {current && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-rose" aria-hidden />}
              {done && <Check className="h-3 w-3" aria-hidden />}
              {s}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

const FIELD_LABEL: Record<string, string> = {
  doc_type: "type",
  dated: "date",
  status: "status",
  version: "version",
  scope: "scope",
};

function fieldValue(src: SourceBrief, f: string): string {
  if (f === "dated") return src.dated ? fmtDate(src.dated) : "unknown";
  if (f === "scope") return src.client_scope;
  return String((src as unknown as Record<string, unknown>)[f] ?? "unknown");
}

/** A low-confidence inferred field, editable once by the owner. */
function UnsureChip({ src, u, onSaved }: { src: SourceBrief; u: UnsureField; onSaved: () => void }) {
  const { userId } = useRole();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(u.field === "dated" ? (src.dated ?? "") : fieldValue(src, u.field));
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    const key = u.field === "scope" ? "client_scope" : u.field;
    try {
      await apiSend("PATCH", `/sources/${src.id}`, { by: userId, [key]: value });
      toast(`${src.short_label}: ${FIELD_LABEL[u.field] ?? u.field} confirmed. Its facts are being re-checked.`);
      setEditing(false);
      onSaved();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };
  if (editing) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-muted bg-surface py-0.5 pl-2.5 pr-1">
        <span className="font-mono text-[11px] text-muted">{FIELD_LABEL[u.field] ?? u.field}</span>
        <input
          type={u.field === "dated" ? "date" : "text"}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          aria-label={`Correct ${FIELD_LABEL[u.field] ?? u.field}`}
          className="w-32 bg-transparent font-mono text-[12px] text-ink focus:outline-none"
        />
        <button
          type="button"
          onClick={() => void save()}
          disabled={busy || !value}
          className="rounded-full border border-ink bg-surface px-2 py-0.5 text-[11px] font-medium text-ink disabled:opacity-50"
        >
          Save
        </button>
      </span>
    );
  }
  return (
    <button
      type="button"
      onClick={() => setEditing(true)}
      className="group inline-flex items-center gap-1.5 rounded-full border border-dashed border-hairline bg-surface px-2.5 py-0.5 text-left hover:border-muted"
      title="Inferred with low confidence: click to correct"
    >
      <span className="font-mono text-[11px] text-muted">{FIELD_LABEL[u.field] ?? u.field}</span>
      <span className="text-[12px] font-medium text-ink">{fieldValue(src, u.field)}</span>
      <span className="font-mono text-[10px] text-muted">from {u.origin || "inference"}</span>
      <Pencil className="h-3 w-3 text-muted group-hover:text-ink" aria-hidden />
    </button>
  );
}

function EpisodeRow({ e, onChanged }: { e: Episode; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const toast = useToast();
  const Icon = channelIcon(e.channel);
  const name = (e.source_uri ?? e.id).split(/[\\/]/).pop() ?? e.id;
  const unsure = e.sources.flatMap((s) => s.unsure.map((u) => ({ s, u })));
  const retry = async () => {
    setRetrying(true);
    try {
      await apiSend("POST", `/episodes/${e.id}/retry`);
      toast(`${name} is queued again.`);
      onChanged();
    } catch (err) {
      toast((err as Error).message, "error");
    } finally {
      setRetrying(false);
    }
  };
  return (
    <Card as="li" className="overflow-hidden" data-episode={e.id} data-status={e.status}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-start gap-3 p-4 text-left hover:bg-canvas"
      >
        <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-fill text-muted">
          <Icon className="h-4 w-4" aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="truncate text-sm font-semibold text-ink">{name}</span>
            <span className="font-mono text-[11px] text-muted" title={fmtDateTime(e.received_at)}>
              {fmtAgo(e.received_at)}
            </span>
          </span>
          <span className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <Pipeline status={e.status} />
            {e.parse_tier !== null && (
              <span className="font-mono text-[11px] text-muted">
                tier {e.parse_tier}
                {e.parse_quality !== null ? ` · q ${e.parse_quality.toFixed(2)}` : ""}
              </span>
            )}
            <span className="font-mono text-[11px] text-muted">
              {plural(e.passages, "passage")} · {plural(e.facts, "fact")}
            </span>
            {e.confirmations > 0 && <span className="font-mono text-[11px] text-muted">received {e.confirmations + 1}×</span>}
          </span>
          {e.error && <span className="mt-2 block text-[13px] leading-snug text-ink">{e.error}</span>}
          {unsure.length > 0 && !open && (
            <span className="mt-2 inline-flex items-center gap-1 text-[12px] text-muted">
              <Pencil className="h-3 w-3" aria-hidden /> {plural(unsure.length, "field")} to check
            </span>
          )}
        </span>
        <ChevronDown className={cx("mt-1 h-4 w-4 shrink-0 text-muted transition-transform", open && "rotate-180")} aria-hidden />
      </button>
      {e.status === "failed" || e.status === "needs_attention" ? (
        <div className="flex justify-end border-t border-hairline px-4 py-2.5">
          <Button icon={RotateCw} busy={retrying} onClick={() => void retry()}>
            Retry
          </Button>
        </div>
      ) : null}
      {open && (
        <div className="border-t border-hairline bg-canvas px-4 py-3">
          {e.sources.length === 0 ? (
            <p className="text-[13px] text-muted">No documents parsed from this episode yet.</p>
          ) : (
            <ul className="space-y-3">
              {e.sources.map((s) => (
                <li key={s.id}>
                  <div className="flex flex-wrap items-center gap-2">
                    <DocGlyph type={s.doc_type} />
                    <span className="text-sm font-semibold text-ink">{s.short_label}</span>
                    <span className="font-mono text-[11px] text-muted">
                      {[s.doc_type, s.version && `v${s.version}`, s.dated && fmtDate(s.dated), s.status, s.client_scope !== "all" && s.client_scope]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                    {s.confirmed_by && <Pill icon={Check}>confirmed</Pill>}
                  </div>
                  {s.unsure.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {s.unsure.map((u) => (
                        <UnsureChip key={u.field} src={s} u={u} onSaved={onChanged} />
                      ))}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
          {!DEMO_MODE && (
            <a
              href={originalUrl(e.id)}
              target="_blank"
              rel="noreferrer"
              className="mt-3 inline-flex items-center gap-1.5 text-[13px] font-medium text-rose hover:text-rose-hover"
            >
              <ExternalLink className="h-3.5 w-3.5" aria-hidden /> Open original
            </a>
          )}
        </div>
      )}
    </Card>
  );
}

function DropZone({ onUploaded }: { onUploaded: () => void }) {
  const { userId, role } = useRole();
  const toast = useToast();
  const files = useRef<HTMLInputElement>(null);
  const folder = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);

  const send = async (list: File[]) => {
    if (!list.length) return;
    setBusy(true);
    try {
      const out = await uploadFiles(list, userId, role === "owner" ? "process owner" : "processor");
      const fresh = out.episodes.filter((e) => e.created).length;
      const dup = out.episodes.length - fresh;
      toast(
        `${plural(fresh, "file")} received${dup ? `, ${dup} already known (counted as a confirmation)` : ""}.${
          fresh ? ` Watch ${fresh === 1 ? "it" : "them"} move below.` : ""
        }`,
      );
      onUploaded();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
      if (files.current) files.current.value = "";
      if (folder.current) folder.current.value = "";
    }
  };

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        void send(Array.from(e.dataTransfer.files));
      }}
      className={cx(
        "flex flex-col items-center rounded-2xl border-2 border-dashed px-6 py-10 text-center transition-colors",
        over ? "border-muted bg-surface" : "border-hairline bg-surface/60",
      )}
    >
      <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-fill text-muted">
        <UploadCloud className="h-6 w-6" aria-hidden />
      </span>
      <p className="mt-3 font-display text-lg font-semibold text-ink">Drop documents, folders or emails here</p>
      <p className="mt-1 max-w-md text-sm text-muted">
        Any layout. Each file is parsed into cited passages, its rules become facts, and changes go live once checked.
      </p>
      <div className="mt-4 flex flex-wrap justify-center gap-2">
        <Button variant="primary" icon={Upload} busy={busy} onClick={() => files.current?.click()}>
          Choose files
        </Button>
        <Button icon={FolderOpen} disabled={busy} onClick={() => folder.current?.click()}>
          Choose a folder
        </Button>
      </div>
      <p className="mt-3 font-mono text-[11px] text-muted">{TYPES} and images</p>
      <input
        ref={files}
        type="file"
        multiple
        className="sr-only"
        aria-label="Choose files to upload"
        onChange={(e) => void send(Array.from(e.target.files ?? []))}
      />
      <input
        ref={folder}
        type="file"
        multiple
        className="sr-only"
        aria-label="Choose a folder to upload"
        // @ts-expect-error -- non-standard but supported by Chromium, Firefox and Safari
        webkitdirectory=""
        onChange={(e) => void send(Array.from(e.target.files ?? []))}
      />
    </div>
  );
}

interface WatchStatus {
  path: string;
  enabled: boolean;
  interval_s: number;
  last_scan_at: string | null;
}

function Connectors() {
  const { data } = useApi<{ watched_folder: WatchStatus }>(DEMO_MODE ? null : "/connectors", 30_000);
  const w = data?.watched_folder;
  const watchOn = Boolean(w?.enabled && w.last_scan_at);
  const items = [
    { icon: Upload, name: "Upload", detail: "Files, folders, zips", on: true },
    { icon: Mail, name: "Email", detail: "Drop .eml files; attachments split out", on: true },
    { icon: Globe, name: "API endpoint", detail: DEMO_MODE ? "POST /episodes" : `POST ${API_URL}/episodes`, on: !DEMO_MODE },
    {
      icon: FolderOpen,
      name: "Watched folder",
      detail: !w
        ? "Not enabled"
        : `${w.path} · every ${w.interval_s} s${w.last_scan_at ? ` · scanned ${fmtAgo(w.last_scan_at)}` : " · waiting for the worker"}`,
      on: watchOn,
    },
  ];
  return (
    <div className="mt-4 grid gap-2.5 sm:grid-cols-2">
      {items.map((c) => (
        <div key={c.name} className="flex items-start gap-3 rounded-2xl border border-hairline bg-surface p-3.5">
          <c.icon className="mt-0.5 h-4 w-4 shrink-0 text-muted" aria-hidden />
          <div className="min-w-0 flex-1">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-semibold text-ink">{c.name}</span>
              <Pill dot={c.on}>{c.on ? "active" : "off"}</Pill>
            </div>
            <p className="mt-0.5 truncate font-mono text-[11px] text-muted" title={c.detail}>
              {c.detail}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}

export function SourcesView() {
  const { refresh } = useSignals();
  const [fast, setFast] = useState(false);
  const { data, error, loading, reload } = useApi<Episode[]>("/episodes", fast ? 2000 : 10_000);
  const { data: stats, reload: reloadStats } = useApi<import("@/lib/types").Stats>("/stats", 10_000);
  const [filter, setFilter] = useState<"all" | "attention">("all");

  const episodes = useMemo(() => data ?? [], [data]);
  const busy = episodes.some((e) => STEPS.slice(0, 3).includes(e.status));
  useEffect(() => setFast(busy), [busy]);
  const attention = episodes.filter((e) => HELD[e.status] || e.sources.some((s) => s.unsure.length));
  const shown = filter === "attention" ? attention : episodes;
  const changed = () => {
    void reload();
    void reloadStats();
    refresh();
  };

  return (
    <PageColumns
      railLabel="Knowledge base totals"
      main={
        <>
          <PageHeader
            eyebrow="Sources"
            title="Feed the engine"
            meta={stats && <span>kb v{stats.kb_version}</span>}
            actions={
              <Link
                href="/sources/replay"
                className="inline-flex h-9 items-center gap-1.5 whitespace-nowrap rounded-full border border-hairline bg-surface px-4 text-[13px] font-medium text-ink transition-colors hover:border-muted"
              >
                <History className="h-4 w-4" aria-hidden />
                Replay history
              </Link>
            }
          >
            Everything the engine knows comes from here. Nothing is overwritten: a newer version retires the old rule and keeps it on record.
          </PageHeader>
          <DropZone onUploaded={changed} />
          <Connectors />

          <div className="mb-3 mt-10 flex flex-wrap items-center justify-between gap-3">
            <SectionLabel count={episodes.length}>Episode log</SectionLabel>
            <div className="flex gap-1.5" role="group" aria-label="Show">
              {(["all", "attention"] as const).map((f) => (
                <button
                  key={f}
                  type="button"
                  aria-pressed={filter === f}
                  onClick={() => setFilter(f)}
                  className={cx(
                    "rounded-full border px-3 py-1 text-[13px] font-medium",
                    filter === f ? "border-ink bg-fill text-ink" : "border-hairline bg-surface text-ink hover:border-muted",
                  )}
                >
                  {f === "all" ? "All" : `Needs a look · ${attention.length}`}
                </button>
              ))}
            </div>
          </div>
          {error ? (
            <ErrorNote message={error} onRetry={() => void reload()} />
          ) : loading && !data ? (
            <SkeletonRows rows={4} height="h-20" />
          ) : shown.length === 0 ? (
            <Empty icon={UploadCloud} title={filter === "all" ? "Nothing received yet" : "Nothing needs a look"}>
              {filter === "all" ? "Drop the first documents above." : "Held, failed and uncertain items appear here."}
            </Empty>
          ) : (
            <ul className="space-y-2.5">
              {shown.map((e) => (
                <EpisodeRow key={e.id} e={e} onChanged={changed} />
              ))}
            </ul>
          )}
        </>
      }
      rail={
        <div className="space-y-6">
          <div>
            <SectionLabel>Knowledge base</SectionLabel>
            <div className="grid grid-cols-2 gap-2.5">
              <Stat label="Documents" value={stats?.documents ?? "–"} />
              <Stat label="Passages" value={stats ? stats.passages.toLocaleString("en-IN") : "–"} />
              <Stat label="Facts" value={stats?.facts ?? "–"} hint={stats ? `${stats.facts_by_status.current ?? 0} current` : undefined} />
              <Stat label="Entities" value={stats?.entities ?? "–"} />
            </div>
          </div>
          <div>
            <SectionLabel>Pipeline</SectionLabel>
            <dl className="divide-y divide-hairline rounded-2xl border border-hairline bg-surface text-sm">
              {[
                ["kb version", stats ? `v${stats.kb_version}` : "–"],
                ["Jobs queued", stats?.queue.queued ?? "–"],
                ["Jobs running", stats?.queue.running ?? "–"],
                ["Jobs failed", stats?.queue.failed ?? "–"],
                ["Open conflicts", stats?.open_conflicts ?? "–"],
                ["Open reviews", stats?.open_reviews ?? "–"],
              ].map(([k, v]) => (
                <div key={String(k)} className="flex justify-between px-3.5 py-2">
                  <dt className="text-muted">{k}</dt>
                  <dd className="font-mono text-[13px] text-ink">{v}</dd>
                </div>
              ))}
            </dl>
          </div>
          {busy && (
            <p className="flex items-center gap-2 font-mono text-[11px] text-muted">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-rose" aria-hidden />
              processing · refreshing every 2 s
            </p>
          )}
        </div>
      }
    />
  );
}
