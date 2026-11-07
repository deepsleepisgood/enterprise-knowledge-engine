// Answer card returned by POST /ask (BUILD_PLAN.md Phase 4). Keep field names stable.

// Document types the engine infers (app/ingest/metadata.py DOC_TYPES); generic across companies.
export type DocType =
  | "policy"
  | "sop"
  | "work_instruction"
  | "memo"
  | "faq"
  | "training"
  | "interview"
  | "observation"
  | "email"
  | "chat"
  | "spreadsheet"
  | "slides"
  | "report"
  | "contract"
  | "form"
  | "image"
  | "expert_answer"
  | "other";

export type SourceStatus = "current" | "superseded" | "stale" | "draft" | "record" | "provisional";

export type CardStatus = "answered" | "provisional" | "unverified" | "unsupported" | "needs_specialist";

export interface Citation {
  n: number;
  passage_id: string;
  file: string;
  short_label: string; // "SOP v4.0 §4.2", "CM-PHA-01", "Interview 1 [02:30]"
  locator: string;
  section_title: string;
  doc_type: DocType;
  status: SourceStatus;
  quote: string;
}

export interface WorkingRow {
  label: string;
  value: string;
}

export interface OlderSource {
  topic: string;
  current_value: string;
  older_value: string;
  file: string;
  locator: string;
  superseded_by: string;
  superseded_on: string; // ISO date
}

export interface ExpertTip {
  text: string;
  author: string;
  date: string; // ISO date
  citation: Citation;
  approved_by: string | null;
}

export interface RouteTo {
  role: string;
  reason: string;
}

export interface EntityRef {
  id: string;
  name: string;
  type: string;
}

export interface AnswerCard {
  answer_id: string;
  kb_version: number;
  as_of: string | null; // ISO date; null means "today"
  superseded_since?: string | null; // for as_of answers: when the rule in force then was replaced
  client: string | null;
  route: string;
  status: CardStatus;
  rule: { text: string; citations: Citation[] };
  working: WorkingRow[] | null;
  decision: string | null;
  exception_code: string | null;
  next_owner: string | null;
  older_sources: OlderSource[];
  expert_tip: ExpertTip | null;
  route_to: RouteTo | null;
  entities: EntityRef[];
  related: string[];
  latency_ms: number;
}

export interface ChangeItem {
  id: number;
  kb_version: number;
  summary: string;
  topic: string;
  old_value: string;
  new_value: string;
  effective_at: string;
  status: "provisional" | "confirmed" | "rejected";
  source_label: string;
}

export interface InvoiceContext {
  invoice_id: string;
  client: string;
  vendor_id: string;
  vendor_name: string;
  invoice_date: string;
  total_inr: number;
  po_backed: boolean;
  msme_category: string;
  einvoice_required: boolean;
  qrmp_filer: boolean;
  due_date: string;
  payment_run: string;
  habits: string[];
}

/** A scope the schema knows (a client entity), or "all". Labels come from the API. */
export type ClientKey = string;

export interface Scope {
  key: ClientKey;
  label: string;
}

export const ALL_SCOPE: Scope = { key: "all", label: "All clients" };
