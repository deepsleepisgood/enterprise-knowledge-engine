"use client";

import { BarChart3, FileText, HelpCircle, Timer } from "lucide-react";
import Link from "next/link";

import { placeLabel } from "@/components/pages/ConflictsView";
import { PageColumns } from "@/components/shell/PageColumns";
import { Card, Empty, ErrorNote, PageHeader, SectionLabel, SkeletonRows, Stat } from "@/components/ui/Primitives";
import { fmtAgo, plural } from "@/lib/format";
import type { Analytics } from "@/lib/types";
import { useApi } from "@/lib/useApi";

function Bars({ rows }: { rows: { label: string; count: number }[] }) {
  const max = Math.max(1, ...rows.map((r) => r.count));
  return (
    <ul className="space-y-2.5">
      {rows.map((r, i) => (
        <li key={r.label}>
          <div className="flex justify-between gap-3 text-[13px]">
            <span className="truncate text-ink">{r.label}</span>
            <span className="font-mono text-[11px] text-muted">{r.count}</span>
          </div>
          <div className="mt-1 h-2 overflow-hidden rounded-full bg-fill">
            <div className={i === 0 ? "h-full rounded-full bg-rose" : "h-full rounded-full bg-muted/40"} style={{ width: `${(r.count / max) * 100}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

export function AnalyticsView() {
  const { data, error, loading, reload } = useApi<Analytics>("/analytics", 30_000);
  const answered = data ? (data.by_status.answered ?? 0) + (data.by_status.provisional ?? 0) : 0;
  const rate = data && data.answers ? Math.round((answered / data.answers) * 100) : null;
  const ack = data?.acknowledgements.rate;

  return (
    <PageColumns
      railLabel="Answer outcomes"
      main={
        <>
          <PageHeader eyebrow="Analytics" title="How the engine is used">
            What people ask, what the documents could not answer, and which sources carry the most weight. Evaluation runs are left out.
          </PageHeader>
          {error ? (
            <ErrorNote message={error} onRetry={() => void reload()} />
          ) : loading && !data ? (
            <SkeletonRows rows={3} height="h-40" />
          ) : !data || data.answers === 0 ? (
            <Empty icon={BarChart3} title="No questions asked yet">
              Ask something on the Ask page and the numbers start here.
            </Empty>
          ) : (
            <div className="space-y-5">
              <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
                <Stat label="Questions" value={data.answers} hint={plural(data.users, "person", "people")} />
                <Stat label="Answered" value={rate === null ? "–" : `${rate}%`} hint={`${answered} with citations`} />
                <Stat
                  label="Median wait"
                  value={data.latency_ms.p50 ? `${(data.latency_ms.p50 / 1000).toFixed(1)} s` : "–"}
                  hint={data.latency_ms.p90 ? `p90 ${(data.latency_ms.p90 / 1000).toFixed(1)} s` : undefined}
                />
                <Stat
                  label="Changes seen"
                  value={ack === null || ack === undefined ? "–" : `${Math.round(ack * 100)}%`}
                  hint={`${data.acknowledgements.acks} acks · ${data.acknowledgements.changes} changes`}
                />
              </div>
              <div className="grid gap-5 md:grid-cols-2">
                <Card className="p-4">
                  <SectionLabel icon={BarChart3}>Most-asked topics</SectionLabel>
                  {data.top_topics.length ? (
                    <Bars rows={data.top_topics.map((t) => ({ label: t.topic, count: t.count }))} />
                  ) : (
                    <p className="text-[13px] text-muted">No topics yet.</p>
                  )}
                </Card>
                <Card className="p-4">
                  <SectionLabel icon={FileText}>Most-cited sources</SectionLabel>
                  {data.top_sources.length ? (
                    <Bars rows={data.top_sources.map((s) => ({ label: placeLabel(s.label, s.locator), count: s.count }))} />
                  ) : (
                    <p className="text-[13px] text-muted">No citations yet.</p>
                  )}
                </Card>
              </div>
              <Card className="overflow-hidden">
                <div className="border-b border-hairline px-4 py-3">
                  <SectionLabel icon={HelpCircle} count={data.unanswered.length}>
                    Not answered from the documents
                  </SectionLabel>
                  <p className="-mt-1 text-[13px] text-muted">Gaps worth a document or an expert entry.</p>
                </div>
                {data.unanswered.length === 0 ? (
                  <p className="px-4 py-3 text-[13px] text-muted">Every question so far was answered.</p>
                ) : (
                  <ul className="divide-y divide-hairline">
                    {data.unanswered.map((u) => (
                      <li key={u.id} className="flex items-start justify-between gap-3 px-4 py-2.5">
                        <Link href={`/?q=${encodeURIComponent(u.question)}`} className="text-sm text-ink hover:underline">
                          {u.question}
                        </Link>
                        <span className="shrink-0 font-mono text-[11px] text-muted">
                          {u.status} · {fmtAgo(u.created_at)}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
            </div>
          )}
        </>
      }
      rail={
        data && data.answers > 0 ? (
          <div className="space-y-6">
            <div>
              <SectionLabel>Outcomes</SectionLabel>
              <Bars rows={Object.entries(data.by_status).sort((a, b) => b[1] - a[1]).map(([k, n]) => ({ label: k, count: n }))} />
            </div>
            <div>
              <SectionLabel icon={Timer}>Routes</SectionLabel>
              <Bars rows={Object.entries(data.by_route).sort((a, b) => b[1] - a[1]).map(([k, n]) => ({ label: k.replace(/^calculator:/, "calc · "), count: n }))} />
            </div>
          </div>
        ) : (
          <p className="text-[13px] text-muted">Outcomes appear once questions are asked.</p>
        )
      }
    />
  );
}
