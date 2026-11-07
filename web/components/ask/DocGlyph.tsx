import {
  BookUser,
  FileText,
  Mail,
  MessageSquare,
  Mic,
  Play,
  Presentation,
  ScanLine,
  Table,
} from "lucide-react";

import type { DocType } from "@/lib/types";

const LETTER: Partial<Record<DocType, string>> = {
  policy: "S",
  sop: "S",
  memo: "M",
  work_instruction: "D",
  faq: "F",
};

const ICON = {
  training: Play,
  interview: Mic,
  observation: Mic,
  email: Mail,
  chat: MessageSquare,
  expert_answer: BookUser,
  spreadsheet: Table,
  slides: Presentation,
  image: ScanLine,
} as const;

const NAME: Record<DocType, string> = {
  policy: "Policy",
  sop: "SOP",
  work_instruction: "Desk instruction",
  memo: "Memo",
  faq: "FAQ",
  training: "Training",
  interview: "Interview",
  observation: "Observation notes",
  email: "Email",
  chat: "Chat",
  spreadsheet: "Spreadsheet",
  slides: "Slides",
  report: "Report",
  contract: "Contract",
  form: "Form",
  image: "Scanned page",
  expert_answer: "Expert entry",
  other: "Document",
};

/** 16px rounded square identifying the document type (DESIGN.md §6). */
export function DocGlyph({ type }: { type: DocType }) {
  const letter = LETTER[type];
  const Icon = letter ? null : (ICON[type as keyof typeof ICON] ?? FileText);
  return (
    <span
      title={NAME[type] ?? "Document"}
      className="relative inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-[4px] bg-fill text-muted"
    >
      {letter ? (
        <span className="font-mono text-[9px] font-medium leading-none">{letter}</span>
      ) : Icon ? (
        <Icon className="h-[9px] w-[9px]" strokeWidth={2.5} aria-hidden />
      ) : null}
      <span className="sr-only">{NAME[type] ?? "Document"}</span>
    </span>
  );
}
