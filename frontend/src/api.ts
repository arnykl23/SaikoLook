import type { AccountConfig, AccountConfigCreate, MessageRecord, MessageState } from "./types";

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

export interface MessagesQuery {
  archived?: boolean;
  providers?: string[];
  account_addresses?: string[];
  importance_min?: number;
  received_after?: string;
  received_before?: string;
  order_by?: "triage_score" | "received_at" | "importance";
  descending?: boolean;
  unread_only?: boolean;
}

/** メッセージ一覧取得. */
export async function getMessages(query: MessagesQuery = {}): Promise<MessageRecord[]> {
  const params = new URLSearchParams();
  if (query.archived !== undefined) params.set("archived", String(query.archived));
  // undefined = フィルターなし（全表示）, [] = 明示的に全解除（0件）, [...] = 絞り込み
  if (query.providers !== undefined) {
    if (query.providers.length === 0) params.append("providers", "__none__");
    else for (const p of query.providers) params.append("providers", p);
  }
  if (query.account_addresses !== undefined) {
    if (query.account_addresses.length === 0) params.append("account_addresses", "__none__");
    else for (const a of query.account_addresses) params.append("account_addresses", a);
  }
  if (query.importance_min !== undefined && query.importance_min > 0) {
    params.set("importance_min", String(query.importance_min));
  }
  if (query.received_after) params.set("received_after", query.received_after);
  if (query.received_before) params.set("received_before", query.received_before);
  params.set("order_by", query.order_by ?? "triage_score");
  params.set("descending", String(query.descending ?? true));
  if (query.unread_only) params.set("unread_only", "true");
  const res = await fetch(`${API_BASE}/messages?${params.toString()}`);
  if (!res.ok) {
    throw new ApiError(await parseError(res), res.status);
  }
  return (await res.json()) as MessageRecord[];
}

/** 利用可能なプロバイダ一覧取得. */
export async function getProviders(): Promise<string[]> {
  const res = await fetch(`${API_BASE}/providers`);
  if (!res.ok) {
    throw new ApiError(await parseError(res), res.status);
  }
  return (await res.json()) as string[];
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

/** 手動アーカイブ. */
export async function archiveMessage(messageId: string): Promise<MessageRecord> {
  const url = `${API_BASE}/messages/${encodeURIComponent(messageId)}/archive`;
  const res = await fetch(url, { method: "POST" });
  if (!res.ok) {
    throw new ApiError(await parseError(res), res.status);
  }
  return (await res.json()) as MessageRecord;
}

/** アカウント一覧取得（認証情報は含まない）. */
export async function getAccounts(): Promise<AccountConfig[]> {
  const res = await fetch(`${API_BASE}/accounts`);
  if (!res.ok) throw new ApiError(await parseError(res), res.status);
  return (await res.json()) as AccountConfig[];
}

/** アカウント追加. */
export async function createAccount(data: AccountConfigCreate): Promise<AccountConfig> {
  const res = await fetch(`${API_BASE}/accounts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new ApiError(await parseError(res), res.status);
  return (await res.json()) as AccountConfig;
}

/** アカウント削除. */
export async function deleteAccount(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/accounts/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new ApiError(await parseError(res), res.status);
}

/** 復元 (is_archived=false & state=unhandled に戻す). */
export async function unarchiveMessage(messageId: string): Promise<MessageRecord> {
  const url = `${API_BASE}/messages/${encodeURIComponent(messageId)}/unarchive`;
  const res = await fetch(url, { method: "POST" });
  if (!res.ok) {
    throw new ApiError(await parseError(res), res.status);
  }
  return (await res.json()) as MessageRecord;
}
