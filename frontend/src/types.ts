// app/models.py をミラーした型. バックエンドの契約と一致させる.

export interface EmailMessage {
  id: string;
  provider: string;
  subject: string;
  sender: string;
  to: string[];
  received_at: string | null;
  snippet: string;
  is_unread: boolean;
  body_text: string | null;
}

export type TaskWeight = "light" | "medium" | "heavy";

export interface AnalysisResult {
  importance: number; // 1-5
  needs_reply: boolean;
  task_weight: TaskWeight;
  category: string;
  summary: string;
  suggested_action: string | null;
  deadline: string | null;
  reason: string;
  analyzer: string;
}

export type MessageState =
  | "unhandled"
  | "in_progress"
  | "done"
  | "snoozed"
  | "dismissed";

export interface MessageRecord {
  message_id: string;
  email: EmailMessage;
  analysis: AnalysisResult | null;
  state: MessageState;
  triage_score: number;
  version: number;
  is_archived: boolean;
  created_at: string | null;
  updated_at: string | null;
}

// ユーザーが押せる状態遷移先 (unhandled は初期状態のため遷移先に出さない)
export const ACTIONABLE_STATES: readonly MessageState[] = [
  "in_progress",
  "done",
  "snoozed",
  "dismissed",
] as const;

export interface AccountConfig {
  id: string;
  provider: string;
  label: string;
  created_at: string | null;
}

export interface AccountConfigCreate {
  provider: string;
  label: string;
  address: string;
  credential: string;
}
