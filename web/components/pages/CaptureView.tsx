"use client";

import {
  AlertTriangle,
  ArrowRight,
  BookOpen,
  BookUser,
  Check,
  CheckCircle2,
  Clock,
  Link2,
  Pencil,
  RotateCcw,
  ShieldQuestion,
  Sparkles,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { PageColumns } from "@/components/shell/PageColumns";
import { useRole } from "@/components/shell/RoleContext";
import { Button, Card, Empty, ErrorNote, PageHeader, Pill, SectionLabel, SkeletonRows, useToast } from "@/components/ui/Primitives";
import { ApiError, DEMO_MODE, apiSend } from "@/lib/api";
import { cx, fmtAgo } from "@/lib/format";
import type {
  CaptureCandidate,
  CaptureEntries,
  CaptureEntry,
  CaptureQuestion,
  CaptureQuestions,
  CapturedEntry,
  RuleCheck,
} from "@/lib/types";
import { useApi } from "@/lib/useApi";

type Key = CaptureQuestion["key"];
type Answers = Partial<Record<Key, string>>;
const OPTIONAL: Key[] = ["trigger", "evidence"];

const CHECK: Record<RuleCheck["verdict"], { label: string; icon: typeof Check }> = {
  compatible: { label: "Fits the rules", icon: CheckCircle2 },
  conflict: { label: "Possible conflict with a rule", icon: AlertTriangle },
  no_rule: { label: "No rule covers this", icon: ShieldQuestion },
  unchecked: { label: "Not checked", icon: ShieldQuestion },
};

function CheckNote({ check }: { check: RuleCheck }) {
  const c = CHECK[check.verdict];
  return (
    <div className={cx("mt-3 rounded-xl p-3 text-[13px]", check.verdict === "conflict" ? "bg-rose-tint text-ink" : "bg-canvas text-ink")}>
      <p className="flex items-center gap-1.5 font-medium">
        <c.icon className={cx("h-4 w-4", check.verdict === "conflict" ? "text-rose" : "text-muted")} aria-hidden />
        {c.label}
      </p>
      <p className="mt-1 leading-relaxed text-muted">{check.reason}</p>
      {check.rules.length > 0 && (
        <p className="mt-1.5 font-mono text-[11px] text-muted">{check.rules.map((r) => r.label).join(" · ")}</p>
      )}
    </div>
  );
}

function statusOf(e: CapturedEntry): { label: string; icon: typeof Check } {
  if (e.review?.status === "rejected") return { label: e.edited_from ? "replaced" : "rejected", icon: X };
  if (e.fact_status === "current" || e.status === "published") return { label: "in the knowledge base", icon: Check };
  if (e.status === "pending_review") return { label: "pending review", icon: Clock };
  if (e.status === "needs_attention") return { label: "needs attention", icon: AlertTriangle };
  return { label: "processing", icon: Clock };
}

const FIELDS: { key: Exclude<Key, "subject">; label: string }[] = [
  { key: "habit", label: "Habit" },
  { key: "trigger", label: "How to spot it" },
  { key: "what_to_do", label: "What to do" },
  { key: "evidence", label: "How they know" },
];

function EntryCard({ e, onChanged }: { e: CapturedEntry; onChanged: () => void }) {
  const { role, userId } = useRole();
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Partial<CaptureEntry>>({});
  const s = statusOf(e);
  const open = e.review?.status === "open";
  const reviewer = role === "owner" && open && !DEMO_MODE;

  const decide = async (decision: "approve" | "reject") => {
    if (!e.review) return;
    setBusy(decision);
    try {
      await apiSend("POST", `/review/${e.review.id}`, { decision, by: userId, row_version: e.review.row_version });
      toast(decision === "approve" ? "Approved. It is now shown beside the rules." : "Rejected. Nothing was added.");
      onChanged();
    } catch (err) {
      toast(err instanceof ApiError && err.status === 409 ? "Someone else just decided this entry." : (err as Error).message, "error");
      onChanged();
    } finally {
      setBusy(null);
    }
  };

  const saveEdit = async () => {
    if (!e.entry) return;
    setBusy("edit");
    try {
      await apiSend("POST", `/capture/entries/${e.episode_id}/edit`, { entry: { ...e.entry, ...draft }, by: userId });
      toast("Edited. The new version waits for review in place of the old one.");
      setEditing(false);
      onChanged();
    } catch (err) {
      toast((err as Error).message, "error");
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card as="li" className="p-4">
      <div className="flex items-start justify-between gap-2">
        <span className="min-w-0 text-sm font-semibold text-ink">{e.subject_name ?? e.entry?.subject}</span>
        <Pill icon={s.icon}>{s.label}</Pill>
      </div>
      {editing ? (
        <div className="mt-2 space-y-2">
          {FIELDS.map((f) => (
            <label key={f.key} className="block">
              <span className="eyebrow">{f.label}</span>
              <textarea
                rows={2}
                defaultValue={e.entry?.[f.key] ?? ""}
                onChange={(ev) => setDraft((d) => ({ ...d, [f.key]: ev.target.value }))}
                className="mt-1 block w-full resize-none rounded-xl border border-hairline bg-surface px-3 py-2 text-[13px] text-ink focus:border-muted focus:outline-none"
              />
            </label>
          ))}
          <div className="flex gap-2">
            <Button variant="primary" busy={busy === "edit"} onClick={() => void saveEdit()}>
              Save edit
            </Button>
            <Button variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <dl className="mt-2 space-y-1.5 text-[13px]">
          {FIELDS.map((f) =>
            e.entry?.[f.key] ? (
              <div key={f.key}>
                <dt className="eyebrow">{f.label}</dt>
                <dd className="text-ink">{e.entry[f.key]}</dd>
              </div>
            ) : null,
          )}
        </dl>
      )}
      {e.check && !editing && <CheckNote check={e.check} />}
      <p className="mt-2 font-mono text-[11px] text-muted">
        {[e.entry?.author, e.entry?.date, e.reviewer ? `reviewer: ${e.reviewer}` : "", e.approved_by ? `approved by ${e.approved_by}` : "", e.received_at ? fmtAgo(e.received_at) : ""]
          .filter(Boolean)
          .join(" · ")}
      </p>
      {reviewer && !editing && (
        <div className="mt-3 flex flex-wrap gap-2">
          <Button variant="primary" icon={Check} busy={busy === "approve"} onClick={() => void decide("approve")}>
            Approve
          </Button>
          <Button icon={Pencil} onClick={() => setEditing(true)}>
            Edit
          </Button>
          <Button icon={X} busy={busy === "reject"} onClick={() => void decide("reject")}>
            Reject
          </Button>
        </div>
      )}
    </Card>
  );
}

function Known({ known }: { known: CaptureEntries["known"] }) {
  const [all, setAll] = useState(false);
  if (!known.total) return null;
  const shown = all ? known.notes : known.notes.slice(0, 5);
  return (
    <div className="mt-8">
      <SectionLabel icon={BookOpen} count={known.total}>
        Already known
      </SectionLabel>
      <p className="mb-3 text-[13px] text-muted">
        Practice notes the knowledge base already has
        {Object.entries(known.by_origin).length > 0 &&
          ` (${Object.entries(known.by_origin)
            .map(([k, n]) => `${n} from ${k === "capture" ? "captures" : k === "data row" ? "data rows" : "documents"}`)
            .join(", ")})`}
        . Check here before adding the same habit twice.
      </p>
      <ul className="space-y-2">
        {shown.map((n, i) => (
          <li key={i} className="rounded-xl bg-canvas p-3 text-[13px] leading-relaxed text-ink">
            {n.statement}
            <span className="mt-1 block font-mono text-[11px] text-muted">
              {[n.source, n.author, n.date].filter(Boolean).join(" · ")}
            </span>
          </li>
        ))}
      </ul>
      {known.notes.length > 5 && (
        <button type="button" onClick={() => setAll((v) => !v)} className="mt-2 text-[13px] font-medium text-rose hover:text-rose-hover">
          {all ? "Show fewer" : `Show all ${known.notes.length}`}
        </button>
      )}
    </div>
  );
}

export function CaptureView() {
  const { userId, role } = useRole();
  const toast = useToast();
  const qs = useApi<CaptureQuestions>("/capture/questions");
  const list = useApi<CaptureEntries>("/capture/entries", 8000);
  const questions = qs.data?.questions ?? [];
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState<Answers>({});
  const [text, setText] = useState("");
  const [candidates, setCandidates] = useState<CaptureCandidate[]>([]);
  const [subjectId, setSubjectId] = useState<string | null>(null);
  const [check, setCheck] = useState<RuleCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [reviewer, setReviewer] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);

  const done = questions.length > 0 && step >= questions.length;
  const current = questions[step];
  useEffect(() => input.current?.focus(), [step]);
  useEffect(() => {
    if (qs.data && !reviewer) setReviewer(qs.data.default_reviewer);
  }, [qs.data, reviewer]);

  const entry: CaptureEntry = useMemo(
    () => ({
      subject: answers.subject ?? "",
      habit: answers.habit ?? "",
      trigger: answers.trigger ?? "",
      what_to_do: answers.what_to_do ?? "",
      evidence: answers.evidence ?? "",
      author: userId,
      author_role: role === "owner" ? "Process owner" : null,
      subject_entity_id: subjectId,
    }),
    [answers, userId, role, subjectId],
  );

  // Once the five answers are in, check them against the rules in force.
  useEffect(() => {
    if (!done || DEMO_MODE) return;
    let live = true;
    setChecking(true);
    apiSend<RuleCheck>("POST", "/capture/check", { entry })
      .then((c) => live && setCheck(c))
      .catch(() => live && setCheck({ verdict: "unchecked", reason: "The rule check is not available right now.", rules: [] }))
      .finally(() => live && setChecking(false));
    return () => {
      live = false;
    };
    // Re-check only when the answers change, not on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [done, answers]);

  const reset = () => {
    setAnswers({});
    setStep(0);
    setCandidates([]);
    setSubjectId(null);
    setCheck(null);
  };

  const answer = (skip = false) => {
    const v = text.trim();
    if (!current || (!v && !(skip && OPTIONAL.includes(current.key)))) return;
    setAnswers((a) => ({ ...a, [current.key]: v }));
    setText("");
    setStep((s) => s + 1);
    if (current.key === "subject" && v && !DEMO_MODE) {
      apiSend<{ candidates: CaptureCandidate[] }>("POST", "/capture/match", { text: v })
        .then((r) => {
          setCandidates(r.candidates);
          setSubjectId(r.candidates[0]?.id ?? null);
        })
        .catch(() => setCandidates([]));
    }
  };

  const submit = async () => {
    setBusy(true);
    try {
      await apiSend("POST", "/capture/entries", { entry, reviewer, check });
      toast(`Sent to ${reviewer}. Nobody sees it as practice until it is approved.`);
      reset();
      void list.reload();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const entries = list.data?.entries ?? [];
  return (
    <PageColumns
      railLabel="Captured entries"
      main={
        <>
          <PageHeader eyebrow="Expert capture" title="Write down what only you know">
            Five short questions about a habit a newcomer would not expect. Your answers become one entry; it is checked against the rules in force and goes to a reviewer before it appears next to the rules.
          </PageHeader>
          {qs.error ? (
            <ErrorNote message={qs.error} onRetry={() => void qs.reload()} />
          ) : !qs.data ? (
            <SkeletonRows rows={2} />
          ) : (
            <>
              <ol className="space-y-4" aria-live="polite">
                {questions.slice(0, Math.min(step + 1, questions.length)).map((q, i) => (
                  <li key={q.key} className="space-y-2">
                    <div className="flex items-start gap-2.5">
                      <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-rose-tint text-rose">
                        <Sparkles className="h-3.5 w-3.5" aria-hidden />
                      </span>
                      <p className="rounded-2xl rounded-tl-md bg-surface px-4 py-2.5 text-[15px] text-ink shadow-card">{q.ask}</p>
                    </div>
                    {i < step && (
                      <div className="flex justify-end">
                        <p className="max-w-[85%] rounded-2xl rounded-tr-md border border-hairline bg-fill px-4 py-2.5 text-[15px] text-ink">
                          {answers[q.key] || <span className="text-muted">(skipped)</span>}
                        </p>
                      </div>
                    )}
                    {q.key === "subject" && i < step && candidates.length > 0 && (
                      <div className="flex flex-wrap items-center justify-end gap-1.5">
                        <span className="text-[12px] text-muted">
                          <Link2 className="mr-1 inline h-3.5 w-3.5" aria-hidden />
                          Link to
                        </span>
                        {candidates.map((c) => (
                          <button
                            key={c.id}
                            type="button"
                            onClick={() => setSubjectId(c.id === subjectId ? null : c.id)}
                            aria-pressed={c.id === subjectId}
                            className={cx(
                              "rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors",
                              c.id === subjectId ? "border-rose bg-rose-tint text-rose" : "border-hairline bg-surface text-muted hover:border-muted",
                            )}
                          >
                            {c.name} <span className="font-mono text-[10px]">{c.type}</span>
                          </button>
                        ))}
                      </div>
                    )}
                  </li>
                ))}
              </ol>
              {done ? (
                <Card className="mt-6 p-4">
                  <p className="text-[15px] font-medium text-ink">Your entry</p>
                  <p className="mt-1 text-[13px] text-muted">
                    About <span className="text-ink">{candidates.find((c) => c.id === subjectId)?.name ?? entry.subject}</span>
                  </p>
                  {checking ? (
                    <p className="mt-3 text-[13px] text-muted">Checking it against the rules in force…</p>
                  ) : check ? (
                    <CheckNote check={check} />
                  ) : null}
                  <label className="mt-4 block">
                    <span className="eyebrow">Reviewer</span>
                    <select
                      value={reviewer}
                      onChange={(e) => setReviewer(e.target.value)}
                      className="mt-1 block h-9 w-full max-w-xs rounded-full border border-hairline bg-surface px-3 text-[13px] text-ink focus:border-muted focus:outline-none"
                    >
                      {qs.data.reviewers.map((r) => (
                        <option key={r}>{r}</option>
                      ))}
                    </select>
                  </label>
                  <div className="mt-4 flex flex-wrap gap-2">
                    <Button variant="primary" icon={ArrowRight} busy={busy} disabled={checking || DEMO_MODE} onClick={() => void submit()}>
                      Send for review
                    </Button>
                    <Button variant="ghost" icon={RotateCcw} onClick={reset}>
                      Start over
                    </Button>
                  </div>
                </Card>
              ) : (
                <form
                  className="mt-6 rounded-2xl border border-hairline bg-surface p-3 shadow-card"
                  onSubmit={(e) => {
                    e.preventDefault();
                    answer();
                  }}
                >
                  <label htmlFor="capture-input" className="sr-only">
                    {current?.ask}
                  </label>
                  <textarea
                    id="capture-input"
                    ref={input}
                    rows={2}
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        answer();
                      }
                    }}
                    placeholder="Type your answer…"
                    className="block w-full resize-none bg-transparent px-1.5 py-1 text-[15px] leading-relaxed text-ink placeholder:text-muted focus:outline-none"
                  />
                  <div className="mt-2 flex items-center justify-between gap-2">
                    <span className="font-mono text-[11px] text-muted">
                      {step + 1} of {questions.length}
                    </span>
                    <div className="flex items-center gap-2">
                      {current && OPTIONAL.includes(current.key) && (
                        <Button variant="ghost" onClick={() => answer(true)}>
                          Skip
                        </Button>
                      )}
                      <button
                        type="submit"
                        disabled={!text.trim()}
                        aria-label="Answer"
                        className="flex h-9 w-9 items-center justify-center rounded-full bg-rose text-surface transition-colors hover:bg-rose-hover disabled:opacity-40"
                      >
                        <ArrowRight className="h-[18px] w-[18px]" aria-hidden />
                      </button>
                    </div>
                  </div>
                </form>
              )}
            </>
          )}
        </>
      }
      rail={
        <div>
          <SectionLabel icon={BookUser} count={entries.length}>
            Entries
          </SectionLabel>
          {list.error ? (
            <ErrorNote message={list.error} onRetry={() => void list.reload()} />
          ) : !list.data ? (
            <SkeletonRows rows={2} />
          ) : entries.length === 0 ? (
            <Empty icon={BookUser} title="Nothing captured yet">
              Entries appear here with their review status. Reviewers approve, edit or reject them here or in the review queue.
            </Empty>
          ) : (
            <ul className="space-y-2.5">
              {entries.map((e) => (
                <EntryCard key={e.episode_id} e={e} onChanged={() => void list.reload()} />
              ))}
            </ul>
          )}
          {list.data && <Known known={list.data.known} />}
        </div>
      }
    />
  );
}
