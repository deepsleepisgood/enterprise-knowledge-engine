import changesFixture from "@/fixtures/changes.json";
import invoicesFixture from "@/fixtures/invoices.json";
import t1 from "@/fixtures/t1_price_tolerance.json";
import t3 from "@/fixtures/t3_conflict_excipients.json";
import t5 from "@/fixtures/t5_price_calc.json";
import t8 from "@/fixtures/t8_unsupported.json";
import type { AnswerCard, ChangeItem, ClientKey, InvoiceContext } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "";

/** True when no API is configured and the UI answers from web/fixtures. */
export const DEMO_MODE = API_BASE === "";

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
    question: "Do Arvana Pharma excipient invoices need QA release before payment?",
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

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function ask(params: {
  question: string;
  userId: string;
  client: ClientKey;
  invoiceId: string | null;
}): Promise<AnswerCard> {
  if (DEMO_MODE) {
    await delay(700);
    const hit = SAMPLES.find((s) => s.question === params.question || s.keywords.test(params.question));
    if (!hit) throw new DemoMissError();
    return hit.card;
  }
  const res = await fetch(`${API_BASE}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question: params.question,
      user_id: params.userId,
      client: params.client === "all" ? null : params.client,
      invoice_id: params.invoiceId,
    }),
  });
  if (!res.ok) throw new Error(`The answer service returned ${res.status}.`);
  return (await res.json()) as AnswerCard;
}

export async function getChanges(sinceVersion: number): Promise<ChangeItem[]> {
  if (DEMO_MODE) return (changesFixture as ChangeItem[]).filter((c) => c.kb_version > sinceVersion);
  const res = await fetch(`${API_BASE}/changes?since=${sinceVersion}`);
  if (!res.ok) return [];
  return (await res.json()) as ChangeItem[];
}

export async function ackChange(id: number, userId: string): Promise<void> {
  if (DEMO_MODE) return;
  await fetch(`${API_BASE}/changes/${id}/ack`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId }),
  });
}

export async function searchInvoices(q: string): Promise<InvoiceContext[]> {
  if (DEMO_MODE) {
    const needle = q.trim().toLowerCase();
    return (invoicesFixture as InvoiceContext[]).filter(
      (i) => !needle || `${i.invoice_id} ${i.vendor_name} ${i.client}`.toLowerCase().includes(needle),
    );
  }
  const res = await fetch(`${API_BASE}/invoices?q=${encodeURIComponent(q)}`);
  if (!res.ok) return [];
  return (await res.json()) as InvoiceContext[];
}
