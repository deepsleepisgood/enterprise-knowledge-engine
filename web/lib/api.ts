import changesFixture from "@/fixtures/changes.json";
import invoicesFixture from "@/fixtures/invoices.json";
import scopesFixture from "@/fixtures/scopes.json";
import t1AsOf from "@/fixtures/t1_as_of.json";
import t1 from "@/fixtures/t1_price_tolerance.json";
import t3 from "@/fixtures/t3_conflict_excipients.json";
import t5 from "@/fixtures/t5_price_calc.json";
import t8 from "@/fixtures/t8_unsupported.json";
import type {
  AnswerCard,
  ChangeFeedItem,
  ChangeItem,
  ClientKey,
  InvoiceContext,
  PassageDetail,
  Scope,
} from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "";

/** True when no API is configured and the UI reads from web/fixtures. */
export const DEMO_MODE = API_BASE === "";

export const API_URL = API_BASE;

export interface SampleQuestion {
  question: string;
  card: AnswerCard;
  keywords: RegExp;
}

export const SAMPLES: SampleQuestion[] = [
  {
    question: "What is the price tolerance on a PO invoice line?",
    card: t1 as AnswerCard,
    keywords: /price\s+toleran|price\s+variance\s+limit/i,
  },
  {
    question: "PO price ₹395, invoice price ₹400, quantity 500. Does the line pass?",
    card: t5 as AnswerCard,
    keywords: /395|₹\s?400|400\s*[x×]/i,
  },
  {
    question: "Do pharma excipient invoices need QA release before payment?",
    card: t3 as AnswerCard,
    keywords: /excipient|qa\s+release/i,
  },
  {
    question: "What is the canteen subsidy for night-shift staff?",
    card: t8 as AnswerCard,
    keywords: /canteen/i,
  },
];

export class DemoMissError extends Error {
  constructor() {
    super("Demo mode answers only the sample questions.");
  }
}

/** A write attempted without an API: the demo is read-only. */
export class DemoReadOnlyError extends Error {
  constructor() {
    super("Demo mode is read-only. Connect the API to make changes.");
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

// Read-only fixtures for demo mode, by path (loaded on demand: never shipped to API users).
const FIXTURES: [RegExp, () => Promise<{ default: unknown }>][] = [
  [/^\/episodes(\?|$)/, () => import("@/fixtures/episodes.json")],
  [/^\/stats$/, () => import("@/fixtures/stats.json")],
  [/^\/schema$/, () => import("@/fixtures/schema.json")],
  [/^\/bindings/, () => import("@/fixtures/bindings.json")],
  [/^\/entities\/[^/]+\/timeline/, () => import("@/fixtures/timeline.json")],
  [/^\/entities(\?|$)/, () => import("@/fixtures/entities.json")],
  [/^\/conflicts(\?|$)/, () => import("@/fixtures/conflicts.json")],
  [/^\/conflict-scan$/, () => import("@/fixtures/conflict_scan.json")],
  [/^\/review-queue/, () => import("@/fixtures/review_queue.json")],
  [/^\/escalations/, () => import("@/fixtures/escalations.json")],
  [/^\/analytics$/, () => import("@/fixtures/analytics.json")],
  [/^\/notifications/, async () => ({ default: [] })],
  [/^\/changes/, () => import("@/fixtures/changes.json")],
  [/^\/replay$/, () => import("@/fixtures/replay.json")],
];

async function errorFrom(res: Response): Promise<ApiError> {
  let detail: unknown = null;
  try {
    detail = (await res.json())?.detail;
  } catch {
    /* not JSON */
  }
  const text = typeof detail === "string" ? detail : `The service returned ${res.status}.`;
  return new ApiError(res.status, text);
}

export async function apiGet<T>(path: string, headers?: Record<string, string>): Promise<T> {
  if (DEMO_MODE) {
    const hit = FIXTURES.find(([re]) => re.test(path));
    if (!hit) throw new ApiError(404, "Not available in demo mode.");
    const mod = await hit[1]();
    return structuredClone(mod.default) as T;
  }
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store", headers });
  if (!res.ok) throw await errorFrom(res);
  return (await res.json()) as T;
}

export async function apiSend<T>(
  method: "POST" | "PUT" | "PATCH",
  path: string,
  body?: unknown,
  headers?: Record<string, string>,
): Promise<T> {
  if (DEMO_MODE) throw new DemoReadOnlyError();
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { "Content-Type": "application/json", ...headers },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw await errorFrom(res);
  return (await res.json()) as T;
}

/** Files (or a folder's files) to the intake; zips expand on the server. */
export async function uploadFiles(
  files: File[],
  sender: string,
  senderRole?: string,
): Promise<{ episodes: { episode_id: string; file: string; created: boolean }[] }> {
  if (DEMO_MODE) throw new DemoReadOnlyError();
  const form = new FormData();
  for (const f of files) form.append("files", f, f.webkitRelativePath || f.name);
  const qs = new URLSearchParams({ sender });
  if (senderRole) qs.set("sender_role", senderRole);
  const res = await fetch(`${API_BASE}/episodes/upload?${qs.toString()}`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw await errorFrom(res);
  return res.json();
}

export const originalUrl = (episodeId: string) => `${API_BASE}/episodes/${episodeId}/original`;

export async function ask(params: {
  question: string;
  userId: string;
  client: ClientKey;
  invoiceId: string | null;
  asOf: string | null;
  viewer: "processor" | "owner";
  /** What the engine knew at this instant (ISO date-time); null means now. */
  knownAt?: string | null;
  /** Another tenant's knowledge base, such as the replay copy. */
  tenant?: string;
}): Promise<AnswerCard> {
  if (DEMO_MODE) {
    await delay(700);
    const hit = SAMPLES.find((s) => s.question === params.question || s.keywords.test(params.question));
    if (!hit) throw new DemoMissError();
    // The demo has one dated answer: the price-tolerance rule in force before 1 Apr 2026.
    if (params.asOf && params.asOf < "2026-04-01" && hit.card.answer_id === "fx-t1") {
      return { ...(t1AsOf as AnswerCard), as_of: params.asOf };
    }
    return { ...hit.card, as_of: params.asOf };
  }
  const body = {
    question: params.question,
    user_id: params.userId,
    client: params.client === "all" ? null : params.client,
    invoice_id: params.invoiceId,
    as_of: params.asOf,
    known_at: params.knownAt ?? null,
    viewer: params.viewer,
  };
  const headers = params.tenant ? { "X-Tenant": params.tenant } : undefined;
  // Start the answer and poll for it, so a slow model never hits a proxy's request timeout.
  let job: AskJob;
  try {
    job = await apiSend<AskJob>("POST", "/ask/jobs", body, headers);
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 405)) {
      return apiSend<AnswerCard>("POST", "/ask", body, headers); // an API without jobs
    }
    throw e;
  }
  const deadline = Date.now() + ASK_TIMEOUT_MS;
  while (Date.now() < deadline) {
    await delay(ASK_POLL_MS);
    const got = await apiGet<AskJob>(`/ask/jobs/${job.job_id}`, headers);
    if (got.status === "done" && got.card) return got.card;
    if (got.status === "error") {
      throw new ApiError(got.status_code ?? 500, got.error ?? "The answer failed.");
    }
  }
  throw new ApiError(504, "The answer is taking too long. Try again in a minute.");
}

interface AskJob {
  job_id: string;
  status: "pending" | "done" | "error";
  card?: AnswerCard;
  status_code?: number;
  error?: string;
}

const ASK_POLL_MS = 2_000;
const ASK_TIMEOUT_MS = 10 * 60_000;

export async function getChanges(sinceVersion: number): Promise<ChangeFeedItem[]> {
  if (DEMO_MODE) {
    return (changesFixture as ChangeItem[])
      .filter((c) => c.kb_version > sinceVersion)
      .map((c) => ({ ...c, attribute: c.topic, acknowledged: 0 }));
  }
  try {
    return await apiGet<ChangeFeedItem[]>(`/changes?since=${sinceVersion}`);
  } catch {
    return [];
  }
}

export async function ackChange(id: number, userId: string): Promise<void> {
  if (DEMO_MODE) return;
  await apiSend("POST", `/changes/${id}/ack`, { user_id: userId });
}

export async function searchInvoices(q: string): Promise<InvoiceContext[]> {
  if (DEMO_MODE) {
    const needle = q.trim().toLowerCase();
    return (invoicesFixture as InvoiceContext[]).filter(
      (i) => !needle || `${i.invoice_id} ${i.vendor_name} ${i.client}`.toLowerCase().includes(needle),
    );
  }
  try {
    return await apiGet<InvoiceContext[]>(`/invoices?q=${encodeURIComponent(q)}`);
  } catch {
    return [];
  }
}

/** Client scopes known to the graph, for the composer's client chip. */
export async function getScopes(): Promise<Scope[]> {
  if (DEMO_MODE) return scopesFixture as Scope[];
  try {
    return await apiGet<Scope[]>("/scopes");
  } catch {
    return [{ key: "all", label: "All clients" }];
  }
}

export interface InvoiceExtras {
  tips: string[];
  vendor: Record<string, unknown> | null;
}

/** Vendor tips and details for an attached invoice (plug-in context hook). */
export async function getContext(invoiceId: string): Promise<InvoiceExtras | null> {
  if (DEMO_MODE) {
    const inv = (invoicesFixture as InvoiceContext[]).find((i) => i.invoice_id === invoiceId);
    return inv ? { tips: inv.habits, vendor: null } : null;
  }
  try {
    return await apiGet<InvoiceExtras>(`/context?invoice_id=${encodeURIComponent(invoiceId)}`);
  } catch {
    return null;
  }
}

export async function getPassage(id: string): Promise<PassageDetail | null> {
  if (DEMO_MODE) return null;
  try {
    return await apiGet<PassageDetail>(`/passages/${encodeURIComponent(id)}`);
  } catch {
    return null;
  }
}

export async function escalate(answerId: string, userId: string): Promise<{ routed_to: string }> {
  if (DEMO_MODE) {
    await delay(400);
    return { routed_to: "" };
  }
  return apiSend("POST", "/escalations", { answer_id: Number(answerId), asked_by: userId });
}

export async function reportWrong(answerId: string, userId: string, note: string): Promise<void> {
  if (DEMO_MODE) {
    await delay(300);
    return;
  }
  await apiSend("POST", `/answers/${answerId}/report`, { user_id: userId, note });
}
