"use client";

import {
  ArrowLeft,
  ArrowRight,
  Check,
  CircleAlert,
  History,
  Pause,
  Play,
  RotateCcw,
  Send,
  ShieldAlert,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { StatusPill } from "@/components/ask/AnswerBlocks";
import { CitedText } from "@/components/ask/CitedText";
import { PageColumns } from "@/components/shell/PageColumns";
import { useRole } from "@/components/shell/RoleContext";
import { Button, Card, Empty, ErrorNote, PageHeader, Pill, SectionLabel, SkeletonRows, Stat, useToast } from "@/components/ui/Primitives";
import { DEMO_MODE, apiSend, ask } from "@/lib/api";
import { cx, fmtDate, fmtDateTime, plural } from "@/lib/format";
import type { AnswerCard, ReplayState, ReplayStep, ReplaySwap } from "@/lib/types";
import { useApi } from "@/lib/useApi";

const QUESTIONS = [
  "What is the price tolerance on a PO invoice line?",
  "Who approves an invoice above ₹10 lakh?",
  "What is the e-invoice turnover threshold for IRN?",
  "What quantity tolerance applies to cement for Arvana Infra Projects?",
];
const PLAY_MS = 4000;

type Answer = { state: "loading" } | { state: "done"; card: AnswerCard } | { state: "error"; message: string };

const fileName = (f: string) => f.replace(/\.[a-z0-9]+$/i, "").replace(/[_-]+/g, " ");
const topic = (s: ReplaySwap) => {
  const param = s.attribute.includes(":") ? s.attribute.split(":").pop()! : s.attribute.split(".").pop()!;
  return `${s.subject ? `${s.subject} · ` : ""}${param.replace(/_/g, " ")}`;
};

function SwapList({ items, total, kind }: { items: ReplaySwap[]; total: number; kind: "replaced" | "outranked" }) {
  if (!items.length) return null;
  return (
    <ul className="divide-y divide-hairline rounded-2xl border border-hairline bg-surface">
      {items.map((s, i) => (
        <li key={i} className="grid gap-1 px-4 py-3 text-sm sm:grid-cols-[1fr_1.4fr] sm:gap-4">
          <span className="font-medium text-ink">{topic(s)}</span>
          {kind === "replaced" ? (
            <span className="text-ink">
              <s className="text-muted">{s.old}</s>
              <ArrowRight className="mx-1.5 inline h-3.5 w-3.5 text-muted" aria-label="replaced by" />
              <span className="font-medium">{s.new}</span>
              <span className="mt-0.5 block font-mono text-[11px] text-muted">
                {s.old_source ?? "older source"} → {s.new_source ?? "this file"}
                {s.valid_from ? ` · from ${fmtDate(s.valid_from)}` : ""}
              </span>
            </span>
          ) : (
            <span className="text-ink">
              <span className="text-muted">Said </span>
              <s className="text-muted">{s.old}</s>
              <span className="text-muted"> · kept </span>
              <span className="font-medium">{s.new}</span>
              <span className="mt-0.5 block font-mono text-[11px] text-muted">
                {s.new_source ?? "a better source"} ranks above {s.old_source ?? "this file"}
              </span>
            </span>
          )}
        </li>
      ))}
      {total > items.length && (
        <li className="px-4 py-2.5 font-mono text-[11px] text-muted">and {total - items.length} more</li>
      )}
    </ul>
  );
}

function StepDetail({ step, n, total }: { step: ReplayStep; n: number; total: number }) {
  const quiet = !step.replaced.length && !step.outranked.length && !step.held.length && !step.announced.length;
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="eyebrow">
          Step {n} of {total}
        </p>
        <span className="font-mono text-[11px] text-muted">
          {step.done_at ? `learned by ${fmtDateTime(step.done_at)}` : "processing now"}
        </span>
      </div>
      <h2 className="mt-2 font-display text-xl font-semibold text-ink">{fileName(step.file)}</h2>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {step.sources.map((s) => (
          <Pill key={s.label} tone="outline">
            {s.label}
            {s.dated ? ` · ${fmtDate(s.dated)}` : ""}
          </Pill>
        ))}
      </div>
      <div className="mt-4 grid grid-cols-2 gap-2.5">
        <Stat label="Facts from this file" value={step.facts} />
        <Stat label="Rules in force after" value={step.done_at ? step.rules_in_force : "–"} />
      </div>

      {step.announced.length > 0 && (
        <div className="mt-5">
          <SectionLabel>Change announced</SectionLabel>
          <ul className="space-y-1.5">
            {step.announced.map((a, i) => (
              <li key={i} className="rounded-2xl bg-rose-tint px-4 py-2.5 text-sm text-ink">
                {a}
              </li>
            ))}
          </ul>
        </div>
      )}
      {step.replaced.length > 0 && (
        <div className="mt-5">
          <SectionLabel count={step.replaced_total}>Rules it replaced</SectionLabel>
          <SwapList items={step.replaced} total={step.replaced_total} kind="replaced" />
        </div>
      )}
      {step.outranked.length > 0 && (
        <div className="mt-5">
          <SectionLabel count={step.outranked_total}>Said differently, but a better source wins</SectionLabel>
          <SwapList items={step.outranked} total={step.outranked_total} kind="outranked" />
        </div>
      )}
      {step.held.length > 0 && (
        <div className="mt-5">
          <SectionLabel count={step.held_total}>Held for review, not used in answers</SectionLabel>
          <ul className="space-y-1.5">
            {step.held.map((h, i) => (
              <li key={i} className="flex gap-2 rounded-2xl border border-hairline bg-surface px-4 py-2.5 text-sm text-ink">
                <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-muted" aria-hidden />
                {h}
              </li>
            ))}
          </ul>
        </div>
      )}
      {quiet && step.done_at && (
        <p className="mt-5 text-sm text-muted">New facts only: nothing earlier was replaced or contradicted.</p>
      )}
    </Card>
  );
}

function AnswerAt({ answer }: { answer: Answer | undefined }) {
  const [active, setActive] = useState<number | null>(null);
  if (!answer) return null;
  if (answer.state === "loading") return <SkeletonRows rows={2} height="h-16" />;
  if (answer.state === "error") return <ErrorNote message={answer.message} />;
  const { card } = answer;
  if (card.status === "unsupported" || !card.rule.text) {
    return (
      <p className="flex gap-2 rounded-2xl border border-hairline bg-surface px-4 py-3 text-sm text-ink">
        <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-muted" aria-hidden />
        At this point the documents didn&apos;t cover this.
      </p>
    );
  }
  return (
    <div className="space-y-3 rounded-2xl border border-hairline bg-surface p-4">
      <StatusPill status={card.status} />
      <CitedText text={card.rule.text} citations={card.rule.citations} active={active} onActivate={(n) => setActive(n)} />
      <ol className="space-y-1.5 border-t border-hairline pt-3">
        {card.rule.citations.map((c) => (
          <li key={c.n} className={cx("text-[13px] leading-snug", active === c.n ? "text-ink" : "text-muted")}>
            <span className="font-mono text-[11px]">[{c.n}] {c.short_label}</span>
            {c.quote && <span className="ml-1.5">“{c.quote}”</span>}
          </li>
        ))}
      </ol>
      {card.older_sources.length > 0 && (
        <p className="font-mono text-[11px] leading-relaxed text-muted">
          Older at this point:{" "}
          {card.older_sources.map((o) => `${o.topic} ${o.older_value} (${o.locator})`).join(" · ")}
        </p>
      )}
    </div>
  );
}

export function ReplayView() {
  const { userId, role } = useRole();
  const toast = useToast();
  const [polling, setPolling] = useState(false);
  const { data, error, loading, reload } = useApi<ReplayState>("/replay", polling ? 3000 : undefined);
  const [picked, setPicked] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [question, setQuestion] = useState<string>(QUESTIONS[0] ?? "");
  const [answers, setAnswers] = useState<Record<string, Answer>>({});
  const [confirm, setConfirm] = useState(false);
  const [starting, setStarting] = useState(false);

  const steps = useMemo(() => data?.steps ?? [], [data]);
  const running = Boolean(data?.run.running);
  useEffect(() => setPolling(running), [running]);
  const at = picked === null ? steps.length - 1 : Math.min(picked, steps.length - 1);
  const step = at >= 0 ? (steps[at] ?? null) : null;

  useEffect(() => {
    if (!playing) return;
    if (at >= steps.length - 1) {
      setPlaying(false);
      return;
    }
    const id = window.setTimeout(() => setPicked(at + 1), PLAY_MS);
    return () => window.clearTimeout(id);
  }, [playing, at, steps.length]);

  const key = step ? `${step.episode_id}|${question.trim()}` : "";
  const askHere = async () => {
    if (!step?.done_at || !data || !question.trim()) return;
    const k = key;
    setAnswers((a) => ({ ...a, [k]: { state: "loading" } }));
    try {
      const card = await ask({
        question: question.trim(),
        userId,
        client: "all",
        invoiceId: null,
        asOf: null,
        viewer: role,
        knownAt: step.done_at,
        tenant: data.tenant,
      });
      setAnswers((a) => ({ ...a, [k]: { state: "done", card } }));
    } catch (e) {
      setAnswers((a) => ({ ...a, [k]: { state: "error", message: (e as Error).message } }));
    }
  };

  const start = async () => {
    setStarting(true);
    try {
      await apiSend("POST", "/replay", { by: userId });
      setConfirm(false);
      setPicked(null);
      setAnswers({});
      toast("Replay started: the copy is emptied and the files go in one by one.");
      await reload();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setStarting(false);
    }
  };

  const files = data?.files ?? [];
  return (
    <PageColumns
      railLabel="Replay run"
      main={
        <>
          <Link href="/sources" className="mb-4 inline-flex items-center gap-1 text-[13px] font-medium text-muted hover:text-ink">
            <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
            Sources
          </Link>
          <PageHeader
            eyebrow="Sources · Replay"
            title="Watch the knowledge base build itself"
            meta={data && <span>separate copy · {plural(files.length, "file")}</span>}
            actions={
              <Button icon={RotateCcw} disabled={DEMO_MODE || running} onClick={() => setConfirm(true)}>
                Run again from empty
              </Button>
            }
          >
            The documents go in one at a time, in the order they were written. Step through to see which rules each one added, replaced or
            failed to override, and ask a question as the engine knew it at that moment.
          </PageHeader>

          {confirm && (
            <Card className="mb-6 p-4">
              <p className="text-sm text-ink">
                This empties the replay copy and feeds all {files.length} files through the real pipeline, one after another. It takes about
                20–30 minutes and uses the language model. The live knowledge base and its answers are not touched.
              </p>
              <div className="mt-3 flex gap-2">
                <Button variant="primary" icon={Play} busy={starting} onClick={() => void start()}>
                  Start the replay
                </Button>
                <Button variant="ghost" onClick={() => setConfirm(false)}>
                  Cancel
                </Button>
              </div>
            </Card>
          )}

          {error ? (
            <ErrorNote message={error} onRetry={() => void reload()} />
          ) : loading && !data ? (
            <SkeletonRows rows={3} height="h-24" />
          ) : !step ? (
            <Empty icon={History} title={running ? "Starting…" : "No replay yet"}>
              {running ? "The first file is going in." : "Run a replay to rebuild the copy from empty."}
            </Empty>
          ) : (
            <>
              <div className="mb-4 flex flex-wrap items-center gap-2">
                <Button icon={ArrowLeft} aria-label="Previous step" disabled={at <= 0} onClick={() => setPicked(at - 1)} />
                <Button
                  icon={playing ? Pause : Play}
                  onClick={() => {
                    if (!playing && at >= steps.length - 1) setPicked(0);
                    setPlaying(!playing);
                  }}
                >
                  {playing ? "Pause" : "Play"}
                </Button>
                <Button icon={ArrowRight} aria-label="Next step" disabled={at >= steps.length - 1} onClick={() => setPicked(at + 1)} />
                <ol className="ml-1 flex flex-wrap gap-1.5" aria-label="Steps">
                  {steps.map((s, i) => (
                    <li key={s.episode_id}>
                      <button
                        type="button"
                        title={fileName(s.file)}
                        aria-current={i === at ? "step" : undefined}
                        onClick={() => {
                          setPlaying(false);
                          setPicked(i);
                        }}
                        className={cx(
                          "h-8 min-w-[2rem] rounded-full border px-2.5 font-mono text-[12px]",
                          i === at ? "border-ink bg-fill text-ink" : "border-hairline bg-surface text-muted hover:border-muted",
                        )}
                      >
                        {i + 1}
                      </button>
                    </li>
                  ))}
                </ol>
              </div>

              <StepDetail step={step} n={at + 1} total={steps.length} />

              <section aria-label="Ask at this step" className="mt-6">
                <SectionLabel>Ask as the engine knew it after step {at + 1}</SectionLabel>
                <div className="flex flex-wrap gap-1.5">
                  {QUESTIONS.map((q) => (
                    <button
                      key={q}
                      type="button"
                      onClick={() => setQuestion(q)}
                      className={cx(
                        "rounded-full border px-3 py-1 text-left text-[13px]",
                        question === q ? "border-ink bg-fill text-ink" : "border-hairline bg-surface text-ink hover:border-muted",
                      )}
                    >
                      {q}
                    </button>
                  ))}
                </div>
                <form
                  className="mt-3 flex gap-2"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void askHere();
                  }}
                >
                  <label htmlFor="replay-question" className="sr-only">
                    Question
                  </label>
                  <input
                    id="replay-question"
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    className="h-10 min-w-0 flex-1 rounded-full border border-hairline bg-surface px-4 text-sm text-ink focus:border-muted focus:outline-none"
                  />
                  <Button
                    type="submit"
                    variant="primary"
                    icon={Send}
                    className="h-10"
                    disabled={DEMO_MODE || !step.done_at || !question.trim()}
                    busy={answers[key]?.state === "loading"}
                  >
                    Ask
                  </Button>
                </form>
                {DEMO_MODE && <p className="mt-2 text-[13px] text-muted">Asking needs the API: this demo shows the recorded steps only.</p>}
                {!step.done_at && <p className="mt-2 text-[13px] text-muted">This step is still being processed.</p>}
                <div className="mt-3">
                  <AnswerAt answer={answers[key]} />
                </div>
              </section>
            </>
          )}
        </>
      }
      rail={
        <div className="space-y-6">
          <div>
            <SectionLabel>Replay copy</SectionLabel>
            <div className="grid grid-cols-2 gap-2.5">
              <Stat label="Steps" value={data ? `${steps.length}/${files.length}` : "–"} />
              <Stat label="Rules in force" value={steps.at(-1)?.rules_in_force ?? "–"} />
            </div>
            <p className="mt-3 text-[13px] leading-relaxed text-muted">
              A separate knowledge base: nothing here changes what Ask answers.
            </p>
          </div>
          {data?.run.running && (
            <div>
              <SectionLabel>Running</SectionLabel>
              <p className="flex items-center gap-2 text-sm text-ink">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-rose" aria-hidden />
                File {data.run.step} of {data.run.total}
              </p>
              <p className="mt-1 truncate font-mono text-[11px] text-muted" title={data.run.file ?? ""}>
                {data.run.file}
              </p>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-fill" aria-hidden>
                <div className="h-full bg-rose" style={{ width: `${(100 * (data.run.step ?? 0)) / (data.run.total || 1)}%` }} />
              </div>
            </div>
          )}
          {data?.run.error && <ErrorNote message={`The last replay stopped: ${data.run.error}`} />}
          <div>
            <SectionLabel count={files.length}>Order of arrival</SectionLabel>
            <ol className="space-y-1">
              {files.map((f, i) => {
                const done = Boolean(steps[i]?.done_at || (i < steps.length && !running));
                return (
                  <li key={f} className="flex items-center gap-2 text-[13px]">
                    <span className="w-5 text-right font-mono text-[11px] text-muted">{i + 1}</span>
                    {done ? (
                      <Check className="h-3.5 w-3.5 shrink-0 text-ink" aria-label="done" />
                    ) : (
                      <span className="h-3.5 w-3.5 shrink-0 rounded-full border border-hairline" aria-hidden />
                    )}
                    <span className={cx("truncate", done ? "text-ink" : "text-muted")} title={f}>
                      {fileName(f)}
                    </span>
                  </li>
                );
              })}
            </ol>
            {data?.run.finished_at && !running && (
              <p className="mt-3 font-mono text-[11px] text-muted">last run finished {fmtDateTime(data.run.finished_at)}</p>
            )}
          </div>
        </div>
      }
    />
  );
}
