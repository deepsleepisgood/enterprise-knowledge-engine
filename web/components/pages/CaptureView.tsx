"use client";

import { ArrowRight, BookUser, Check, Clock, RotateCcw, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { PageColumns } from "@/components/shell/PageColumns";
import { useRole } from "@/components/shell/RoleContext";
import { Button, Card, Empty, PageHeader, Pill, SectionLabel, useToast } from "@/components/ui/Primitives";
import { DEMO_MODE, apiGet, apiSend } from "@/lib/api";
import { fmtAgo, safeStorageGet, safeStorageSet } from "@/lib/format";
import type { Episode } from "@/lib/types";

// Five generic prompts: who or what, the habit, when it shows up, what to do, and how it is known.
const STEPS = [
  { key: "subject", ask: "Who or what is this about? A supplier, a client, a system, a kind of document…", label: "About" },
  { key: "habit", ask: "What do they do that a newcomer would not expect?", label: "Habit" },
  { key: "trigger", ask: "How do you spot it? What does it look like when it happens?", label: "Trigger" },
  { key: "action", ask: "What should someone do when they see it?", label: "What to do" },
  { key: "source", ask: "How do you know, and since when? (an email, an incident, years of practice…)", label: "Source" },
] as const;

type Answers = Partial<Record<(typeof STEPS)[number]["key"], string>>;

interface Entry {
  episode_id: string;
  answers: Answers;
  at: string;
  status?: string;
}

const KEY = "ps07.capture";

function loadEntries(): Entry[] {
  try {
    return JSON.parse(safeStorageGet(KEY) ?? "[]") as Entry[];
  } catch {
    return [];
  }
}

function EntryCard({ e }: { e: Entry }) {
  const published = e.status === "published";
  return (
    <Card as="li" className="p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm font-semibold text-ink">{e.answers.subject}</span>
        <Pill icon={published ? Check : Clock}>{published ? "in the knowledge base" : "pending review"}</Pill>
      </div>
      <dl className="mt-2 space-y-1.5 text-[13px]">
        {STEPS.slice(1).map((s) =>
          e.answers[s.key] ? (
            <div key={s.key}>
              <dt className="eyebrow">{s.label}</dt>
              <dd className="text-ink">{e.answers[s.key]}</dd>
            </div>
          ) : null,
        )}
      </dl>
      <p className="mt-2 font-mono text-[11px] text-muted">
        {fmtAgo(e.at)}
        {e.status ? ` · ${e.status}` : ""}
      </p>
    </Card>
  );
}

export function CaptureView() {
  const { userId, role } = useRole();
  const toast = useToast();
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState<Answers>({});
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [entries, setEntries] = useState<Entry[]>([]);
  const input = useRef<HTMLTextAreaElement>(null);

  useEffect(() => setEntries(loadEntries()), []);
  useEffect(() => input.current?.focus(), [step]);

  // Follow each entry through the pipeline.
  useEffect(() => {
    if (DEMO_MODE || entries.every((e) => e.status === "published")) return;
    const id = window.setInterval(async () => {
      const next = await Promise.all(
        entries.map(async (e) => {
          if (e.status === "published") return e;
          try {
            const ep = await apiGet<Episode>(`/episodes/${e.episode_id}`);
            return { ...e, status: ep.status };
          } catch {
            return e;
          }
        }),
      );
      setEntries(next);
      safeStorageSet(KEY, JSON.stringify(next));
    }, 5000);
    return () => window.clearInterval(id);
  }, [entries]);

  const done = step >= STEPS.length;

  const answer = () => {
    const v = text.trim();
    if (!v) return;
    const cur = STEPS[step];
    if (!cur) return;
    setAnswers((a) => ({ ...a, [cur.key]: v }));
    setText("");
    setStep((s) => s + 1);
  };

  const submit = async () => {
    setBusy(true);
    const body = STEPS.map((s) => `${s.label}: ${answers[s.key] ?? ""}`).join("\n");
    try {
      const out = await apiSend<{ episodes: { episode_id: string }[] }>("POST", "/episodes", {
        text: body,
        subject: `Expert practice: ${answers.subject ?? ""}`.slice(0, 120),
        sender: userId,
        sender_role: role === "owner" ? "process owner" : "expert",
        channel: "expert_answer",
      });
      const entry: Entry = {
        episode_id: out.episodes[0]?.episode_id ?? "",
        answers,
        at: new Date().toISOString(),
        status: "queued",
      };
      const next = [entry, ...entries].slice(0, 20);
      setEntries(next);
      safeStorageSet(KEY, JSON.stringify(next));
      toast("Captured. It goes to review before anyone sees it as practice.");
      setAnswers({});
      setStep(0);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <PageColumns
      railLabel="Captured entries"
      main={
        <>
          <PageHeader eyebrow="Expert capture" title="Write down what only you know">
            Five short questions. Your answers become a practice entry; the process owner reviews it before it appears next to the rules.
          </PageHeader>
          <ol className="space-y-4" aria-live="polite">
            {STEPS.slice(0, Math.min(step + 1, STEPS.length)).map((s, i) => (
              <li key={s.key} className="space-y-2">
                <div className="flex items-start gap-2.5">
                  <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-rose-tint text-rose">
                    <Sparkles className="h-3.5 w-3.5" aria-hidden />
                  </span>
                  <p className="rounded-2xl rounded-tl-md bg-surface px-4 py-2.5 text-[15px] text-ink shadow-card">{s.ask}</p>
                </div>
                {answers[s.key] && i < step && (
                  <div className="flex justify-end">
                    <p className="max-w-[85%] rounded-2xl rounded-tr-md border border-hairline bg-fill px-4 py-2.5 text-[15px] text-ink">{answers[s.key]}</p>
                  </div>
                )}
              </li>
            ))}
          </ol>
          {done ? (
            <Card className="mt-6 p-4">
              <p className="text-[15px] text-ink">That&apos;s everything. Send it for review?</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button variant="primary" icon={ArrowRight} busy={busy} onClick={() => void submit()}>
                  Send for review
                </Button>
                <Button
                  variant="ghost"
                  icon={RotateCcw}
                  onClick={() => {
                    setAnswers({});
                    setStep(0);
                  }}
                >
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
                {STEPS[step]?.ask}
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
              <div className="mt-2 flex items-center justify-between">
                <span className="font-mono text-[11px] text-muted">
                  {step + 1} of {STEPS.length}
                </span>
                <button
                  type="submit"
                  disabled={!text.trim()}
                  aria-label="Answer"
                  className="flex h-9 w-9 items-center justify-center rounded-full bg-rose text-surface transition-colors hover:bg-rose-hover disabled:opacity-40"
                >
                  <ArrowRight className="h-[18px] w-[18px]" aria-hidden />
                </button>
              </div>
            </form>
          )}
        </>
      }
      rail={
        <div>
          <SectionLabel icon={BookUser} count={entries.length}>
            Your entries
          </SectionLabel>
          {entries.length === 0 ? (
            <Empty icon={BookUser} title="Nothing captured yet">
              Entries you send appear here with their review status.
            </Empty>
          ) : (
            <ul className="space-y-2.5">
              {entries.map((e) => (
                <EntryCard key={e.episode_id || e.at} e={e} />
              ))}
            </ul>
          )}
        </div>
      }
    />
  );
}
