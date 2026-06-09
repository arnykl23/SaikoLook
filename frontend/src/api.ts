import type { MessageRecord, MessageState } from "./types";

const API_BASE = (
  import.meta.env.VITE_API_BASE ?? "http://localhost:8000"
).replace(/\/$/, "");

/** 楽観ロック競合(409). 呼び出し側でリロードを促すために型で区別する. */
export class ConflictError extends Error {
  constructor(message = "他で更新されています. リロードしてください.") {
    super(message);
    this.name = "ConflictError";
  }
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function parseError(res: Response): Promise<string> {
  try {
    const data = await res.json();
    if (data && typeof data === "object" && "detail" in data) {
      return String((data as { detail: unknown }).detail);
    }
  } catch {
    // JSON でないレスポンスは無視してステータスのみ返す
  }
  return `HTTP ${res.status}`;
}

/** トリアージ高い順のメッセージ一覧. */
export async function fetchMessages(): Promise<MessageRecord[]> {
  const url = `${API_BASE}/messages?order_by=triage_score&descending=true`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new ApiError(await parseError(res), res.status);
  }
  return (await res.json()) as MessageRecord[];
}

/** 状態変更(楽観ロック). 409 は ConflictError として投げ直す. */
export async function updateMessageState(
  messageId: string,
  state: MessageState,
  version: number,
): Promise<MessageRecord> {
  const url = `${API_BASE}/messages/${encodeURIComponent(messageId)}/state`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ state, version }),
  });
  if (res.status === 409) {
    throw new ConflictError();
  }
  if (!res.ok) {
    throw new ApiError(await parseError(res), res.status);
  }
  return (await res.json()) as MessageRecord;
}

/** 手動取り込み. 完了後に呼び出し側でリフェッチする. */
export async function triggerIngest(): Promise<void> {
  const res = await fetch(`${API_BASE}/ingest`, { method: "POST" });
  if (!res.ok) {
    throw new ApiError(await parseError(res), res.status);
  }
}
