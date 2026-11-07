// Answer card returned by POST /ask (BUILD_PLAN.md Phase 4). Keep field names stable.

export type DocType =
  | "sop"
  | "client_memo"
  | "desk_instruction"
  | "faq"
  | "training_video"
  | "interview"
  | "shadowing"
  | "email"
  | "chat"
  | "expert_entry";

export type SourceStatus =
  | "current"
  | "superseded"
  | "stale"
  | "partly_outdated"
  | "observation"
  | "knowledge_capture"
  | "provisional";

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

export interface AnswerCard {
  answer_id: string;
  kb_version: number;
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

export type ClientKey = "all" | "retail" | "pharma" | "infra";

export const CLIENTS: { key: ClientKey; label: string }[] = [
  { key: "all", label: "All clients" },
  { key: "retail", label: "Arvana Retail" },
  { key: "pharma", label: "Arvana Pharma" },
  { key: "infra", label: "Arvana Infra" },
];
