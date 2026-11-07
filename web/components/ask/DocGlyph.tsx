import { BookUser, Mail, MessageSquare, Mic, Play } from "lucide-react";

import type { DocType } from "@/lib/types";

const LETTER: Partial<Record<DocType, string>> = {
  sop: "S",
  client_memo: "M",
  desk_instruction: "D",
  faq: "F",
};

const ICON = {
  training_video: Play,
  interview: Mic,
  shadowing: Mic,
  email: Mail,
  chat: MessageSquare,
  expert_entry: BookUser,
} as const;

const NAME: Record<DocType, string> = {
  sop: "SOP",
  client_memo: "Client memo",
  desk_instruction: "Desk instruction",
  faq: "FAQ",
  training_video: "Training video",
  interview: "Interview",
  shadowing: "Shadowing notes",
  email: "Email",
  chat: "Chat",
  expert_entry: "Expert entry",
};

/** 16px rounded square identifying the document type (DESIGN.md §6). */
export function DocGlyph({ type }: { type: DocType }) {
  const letter = LETTER[type];
  const Icon = letter ? null : ICON[type as keyof typeof ICON];
  return (
    <span
      title={NAME[type]}
      className="relative inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-[4px] bg-fill text-muted"
    >
      {letter ? (
        <span className="font-mono text-[9px] font-medium leading-none">{letter}</span>
      ) : Icon ? (
        <Icon className="h-[9px] w-[9px]" strokeWidth={2.5} aria-hidden />
      ) : null}
      <span className="sr-only">{NAME[type]}</span>
    </span>
  );
}
