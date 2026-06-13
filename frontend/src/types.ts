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
  is_spam: boolean;
}

export type TaskWeight = "light" | "medium" | "heavy";

export type RequestType =
  | "reply_required"
  | "task_required"
  | "review_required"
  | "approval_required"
  | "waiting_other"
  | "info_only";

export interface AnalysisResult {
  importance: number; // 1-6
  task_weight: TaskWeight;
  request_type: RequestType;
  is_promotional: boolean;
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
  account_address: string;
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
  address: string;
  auth_type: string;    // 'imap' | 'oauth'
  auth_status: string;  // 'ok' | 'reauth_required' | 'revoked'
  created_at: string | null;
}

export interface OAuthStartResponse {
  auth_url: string;
  state: string;
}

export interface AccountConfigCreate {
  provider: string;
  label: string;
  address: string;
  credential: string;
}
