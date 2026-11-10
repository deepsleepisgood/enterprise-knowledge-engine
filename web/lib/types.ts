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
  /** Owner view only: the text the verifier could not confirm, and why. */
  draft?: { rule: { text: string; citations: Citation[] }; problems: string[] } | null;
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

// ---------------------------------------------------------------- engine pages (API Phase 7)

export interface ChangeFeedItem extends ChangeItem {
  attribute: string | null;
  acknowledged: number;
}

export interface UnsureField {
  field: string;
  origin: string;
  confidence: number | null;
}

export interface SourceBrief {
  id: string;
  short_label: string;
  title: string;
  doc_type: DocType;
  version: string | null;
  dated: string | null;
  status: SourceStatus | "outdated" | "unknown";
  client_scope: string;
  confirmed_by: string | null;
  unsure: UnsureField[];
}

export type EpisodeStatus =
  | "queued"
  | "parsed"
  | "extracted"
  | "published"
  | "pending_review"
  | "needs_attention"
  | "failed"
  | "ignored" // triage: noise, nothing extracted
  | "answered"; // triage: an emailed question, answered without changing the knowledge base

export interface Episode {
  id: string;
  channel: string;
  source_uri: string | null;
  mime: string | null;
  sender: string | null;
  sender_role: string | null;
  received_at: string;
  parse_tier: number | null;
  parse_quality: number | null;
  status: EpisodeStatus;
  error: string | null;
  confirmations: number;
  meta: Record<string, unknown>;
  created_at: string;
  passages: number;
  facts: number;
  sources: SourceBrief[];
}

export interface Stats {
  episodes: number;
  documents: number;
  passages: number;
  facts: number;
  entities: number;
  kb_version: number;
  queue: { queued: number; running: number; failed: number };
  users: number;
  open_conflicts: number;
  open_reviews: number;
  episodes_by_status: Record<string, number>;
  facts_by_status: Record<string, number>;
  entities_by_type: Record<string, number>;
}

export type Risk = "high" | "medium" | "low";

export interface OntologyAttribute {
  key: string;
  topic: string;
  label: string;
  description: string;
  value_type: string;
  unit: string | null;
  synonyms: string[];
  /** Key of the general attribute this one is a client-specific version of. */
  variant_of?: string | null;
}

export interface OntologyTopic {
  key: string;
  label: string;
  description: string;
  synonyms: string[];
  risk: Risk;
}

export interface SourceRank {
  doc_type: string;
  rank: number;
  practice: boolean;
  reason: string;
}

export interface SenderAuthority {
  who: string;
  client: string;
  topics: string[];
}

export interface Ontology {
  name: string;
  base_currency: string | null;
  units: Record<string, number>;
  entity_types: { name: string; description: string }[];
  topics: OntologyTopic[];
  attributes: OntologyAttribute[];
  source_ranking: SourceRank[];
  scope_keys: string[];
  sender_authority: SenderAuthority[];
}

export interface SchemaVersion {
  id: number;
  version: number;
  status: "draft" | "frozen";
  mode: string;
  ontology: Ontology;
  sample: string[];
  created_at: string;
  frozen_at: string | null;
  frozen_by: string | null;
}

export interface SchemaState {
  active: SchemaVersion | null;
  draft: SchemaVersion | null;
  kb_version: number;
}

export interface Binding {
  id: number;
  plugin: string;
  param: string;
  attribute_key: string | null;
  subject_entity_id: string | null;
  confidence: number | null;
  confirmed_by: string | null;
  meta: Record<string, unknown>;
  updated_at: string;
}

export interface EntitySummary {
  id: string;
  type: string;
  name: string;
  aliases: string[];
  facts: number;
}

export interface FactValue {
  type?: string;
  number?: number | null;
  unit?: string | null;
  text?: string | null;
  items?: string[] | null;
}

export interface FactVersion {
  id: number;
  subject_id: string;
  attribute: string;
  value: FactValue;
  scope: Record<string, string>;
  statement: string;
  kind: string;
  status: string;
  valid_from: string | null;
  valid_to: string | null;
  recorded_at: string;
  retracted_at: string | null;
  authority_rank: number;
  quote: string | null;
  passage_id: string | null;
  source_label: string | null;
  locator: string | null;
  subject_name: string | null;
}

export interface Timeline {
  entity: { id: string; type: string; name: string; aliases: string[] };
  attributes: { attribute: string; versions: FactVersion[] }[];
}

export interface ConflictSide {
  fact_id: number;
  passage_id: string | null;
  source: string | null;
  locator: string | null;
  value: string;
  statement: string;
  quote: string | null;
  status: string;
  valid_from: string | null;
}

export interface Conflict {
  id: number;
  kind: "value" | "self_contradiction" | "practice_vs_rule" | "scope";
  status: string;
  attribute: string | null;
  scope: Record<string, string>;
  topic: string | null;
  authoritative: ConflictSide | null;
  conflicting: ConflictSide | null;
  reason: string | null;
  detected_at: string;
}

export interface ScanStatus {
  status: "never" | "queued" | "running" | "done" | "failed";
  job_id?: number;
  queued_at?: string;
  finished_at?: string | null;
  result?: { conflicts?: number; cleared?: number; judged?: number };
  error?: string | null;
}

export interface ReviewItem {
  id: number;
  kind: string;
  payload: Record<string, unknown>;
  risk_tier: string;
  status: string;
  row_version: number;
  decided_by: string | null;
  decided_at: string | null;
  created_at: string;
}

export interface Escalation {
  id: number;
  answer_id: number | null;
  question: string;
  client: string | null;
  asked_by: string;
  routed_to_role: string;
  kind: string;
  status: string;
  found: Record<string, unknown>;
  expert_reply: string | null;
  expert_id: string | null;
  episode_id: string | null;
  created_at: string;
  answered_at: string | null;
}

export interface Notification {
  id: number;
  kind: string;
  body: string;
  answer_id: number | null;
  change_id: number | null;
  at: string;
  read: boolean;
}

export interface PassageDetail {
  id: string;
  locator: string;
  section_title: string | null;
  speaker: string | null;
  text: string;
  context_header: string;
  segment_kind: string;
  position: Record<string, unknown>;
  episode_id: string;
  source: {
    id: string;
    short_label: string;
    title: string;
    doc_type: DocType;
    version: string | null;
    dated: string | null;
    status: string;
    client_scope: string;
  } | null;
  position_in_source: {
    index: number | null;
    of: number;
    previous: { id: string; locator: string; section_title: string | null } | null;
    next: { id: string; locator: string; section_title: string | null } | null;
  };
}

export interface Analytics {
  answers: number;
  users: number;
  by_status: Record<string, number>;
  by_route: Record<string, number>;
  top_topics: { topic: string; count: number }[];
  unanswered: { id: number; question: string; client: string | null; status: string; created_at: string }[];
  top_sources: { passage_id: string; count: number; label: string; locator: string; section_title: string | null }[];
  latency_ms: { p50: number | null; p90: number | null };
  acknowledgements: { changes: number; acks: number; rate: number | null };
}
