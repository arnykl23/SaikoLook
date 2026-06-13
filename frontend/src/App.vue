<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import type { MessageRecord, MessageState } from "./types";
import {
  type MessagesQuery,
  ConflictError,
  getMessages,
  getProviders,
  triggerIngest,
  unarchiveMessage,
  updateMessageState,
  getAccounts,
  reauthGmailAccount,
} from "./api";
import MessageCard from "./components/MessageCard.vue";
import FilterBar from "./components/FilterBar.vue";
import AccountsModal from "./components/AccountsModal.vue";

type Tab = "inbox" | "archive";

const records = ref<MessageRecord[]>([]);
const loading = ref(false);
const ingesting = ref(false);
const error = ref<string | null>(null);
const notice = ref<string | null>(null);
const busyIds = ref<Set<string>>(new Set());
const activeTab = ref<Tab>("inbox");
const availableProviders = ref<string[]>([]);

const inboxQuery = ref<MessagesQuery>({
  archived: false,
  order_by: "importance",
  descending: true,
});
const archiveQuery = ref<MessagesQuery>({
  archived: true,
  order_by: "importance",
  descending: true,
});

const unhandledCount = computed(
  () => records.value.filter((r) => r.state === "unhandled").length,
);

async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    const query = activeTab.value === "inbox" ? inboxQuery.value : archiveQuery.value;
    records.value = await getMessages(query);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "読み込みに失敗しました.";
  } finally {
    loading.value = false;
  }
}

function onQueryChange(q: MessagesQuery): void {
  if (activeTab.value === "inbox") {
    inboxQuery.value = q;
  } else {
    archiveQuery.value = q;
  }
  void load();
}

async function switchTab(tab: Tab): Promise<void> {
  if (activeTab.value === tab) return;
  activeTab.value = tab;
  await load();
}

async function onIngest(): Promise<void> {
  ingesting.value = true;
  error.value = null;
  notice.value = null;
  try {
    await triggerIngest();
    await load();
    notice.value = "取り込みが完了しました.";
  } catch (e) {
    error.value = e instanceof Error ? e.message : "取り込みに失敗しました.";
  } finally {
    ingesting.value = false;
  }
}

function setBusy(id: string, on: boolean): void {
  const next = new Set(busyIds.value);
  if (on) next.add(id);
  else next.delete(id);
  busyIds.value = next;
}

async function onChangeState(
  record: MessageRecord,
  state: MessageState,
): Promise<void> {
  setBusy(record.message_id, true);
  error.value = null;
  notice.value = null;
  try {
    await updateMessageState(record.message_id, state, record.version);
    // done/dismissed 後にバックエンドが自動アーカイブするため全件リフェッチ
    await load();
  } catch (e) {
    if (e instanceof ConflictError) {
      notice.value = e.message;
      await load();
    } else {
      error.value = e instanceof Error ? e.message : "更新に失敗しました.";
    }
  } finally {
    setBusy(record.message_id, false);
  }
}

async function onUnarchive(record: MessageRecord): Promise<void> {
  setBusy(record.message_id, true);
  error.value = null;
  notice.value = null;
  try {
    await unarchiveMessage(record.message_id);
    await load();
    notice.value = "受信トレイに復元しました.";
  } catch (e) {
    error.value = e instanceof Error ? e.message : "復元に失敗しました.";
  } finally {
    setBusy(record.message_id, false);
  }
}

const AUTO_REFRESH_INTERVAL_MS = 60_000;
let autoRefreshTimer: ReturnType<typeof setInterval> | null = null;
const autoRefresh = ref(true);

function startAutoRefresh(): void {
  if (autoRefreshTimer !== null) return;
  autoRefreshTimer = setInterval(() => { void load(); }, AUTO_REFRESH_INTERVAL_MS);
}

function stopAutoRefresh(): void {
  if (autoRefreshTimer !== null) {
    clearInterval(autoRefreshTimer);
    autoRefreshTimer = null;
  }
}

function toggleAutoRefresh(): void {
  autoRefresh.value = !autoRefresh.value;
  autoRefresh.value ? startAutoRefresh() : stopAutoRefresh();
}

// --- アカウント管理 ---
const showAccounts = ref(false);
const hasAccounts = ref<boolean | null>(null);
const accountsList = ref<import("./types").AccountConfig[]>([]);
const oauthSuccessBanner = ref(false);

const reauthAccounts = computed(() =>
  accountsList.value.filter(a => a.auth_status === "reauth_required")
);

async function onReauth(accountId: string): Promise<void> {
  try {
    const { auth_url } = await reauthGmailAccount(accountId);
    window.location.href = auth_url;
  } catch (e) {
    console.error("再接続 URL 取得失敗", e);
  }
}

async function refreshAccountStatus(): Promise<void> {
  try {
    const acs = await getAccounts();
    accountsList.value = acs;
    hasAccounts.value = acs.length > 0;
  } catch {
    // 取得失敗時は判定を null のまま（既存の空状態を表示しない）
    hasAccounts.value = null;
  }
}

function onAccountsChanged(): void {
  void refreshAccountStatus();
  void load();
}

onMounted(async () => {
  void load();
  getProviders()
    .then((ps) => { availableProviders.value = ps; })
    .catch(() => {});
  await refreshAccountStatus();
  startAutoRefresh();

  const urlParams = new URLSearchParams(window.location.search);
  if (urlParams.get("oauth_success") === "1") {
    oauthSuccessBanner.value = true;
    window.history.replaceState({}, "", window.location.pathname);
    await refreshAccountStatus();
  }
});

onUnmounted(() => { stopAutoRefresh(); });
</script>

<template>
  <div class="app">
    <header class="bar">
      <div class="brand">
        <span class="logo">ReplyGuard</span>
        <span class="tag-line">受信トレイ管制塔</span>
      </div>
      <div class="bar-right">
        <span
          v-if="activeTab === 'inbox'"
          class="counter"
          :class="{ alert: unhandledCount > 0 }"
        >
          未対応 {{ unhandledCount }}
        </span>
        <button
          type="button"
          class="accounts-btn"
          @click="showAccounts = true"
        >
          アカウント
        </button>
        <button
          type="button"
          class="auto-refresh-btn"
          :class="{ active: autoRefresh }"
          :aria-pressed="autoRefresh ? 'true' : 'false'"
          :title="autoRefresh ? '自動更新 オン（クリックでオフ）' : '自動更新 オフ（クリックでオン）'"
          @click="toggleAutoRefresh"
        >
          {{ autoRefresh ? "自動 ●" : "自動 ○" }}
        </button>
        <button
          type="button"
          class="refresh"
          :disabled="loading"
          @click="load"
        >
          再読込
        </button>
        <button
          type="button"
          class="ingest"
          :disabled="loading || ingesting"
          @click="onIngest"
        >
          {{ ingesting ? "取り込み中…" : "手動更新" }}
        </button>
      </div>
    </header>

    <nav class="tabs" role="tablist" aria-label="メールビュー切り替え">
      <button
        role="tab"
        :aria-selected="activeTab === 'inbox'"
        class="tab"
        :class="{ active: activeTab === 'inbox' }"
        @click="switchTab('inbox')"
      >
        受信トレイ
        <span
          v-if="activeTab === 'inbox' && unhandledCount > 0"
          class="tab-badge"
          aria-hidden="true"
        >{{ unhandledCount }}</span>
      </button>
      <button
        role="tab"
        :aria-selected="activeTab === 'archive'"
        class="tab"
        :class="{ active: activeTab === 'archive' }"
        @click="switchTab('archive')"
      >
        アーカイブ
      </button>
    </nav>

    <main class="main">
      <!-- OAuth 成功バナー -->
      <div v-if="oauthSuccessBanner" class="banner banner--success">
        Gmail アカウントの接続が完了しました．
        <button @click="oauthSuccessBanner = false">✕</button>
      </div>

      <!-- reauth_required バナー -->
      <div v-if="reauthAccounts.length" class="banner banner--warn">
        {{ reauthAccounts.length }} 件のアカウントで Google 認証の更新が必要です．
        <button
          v-for="acc in reauthAccounts"
          :key="acc.id"
          @click="onReauth(acc.id)"
        >{{ acc.label }} を再接続</button>
      </div>

      <p v-if="error" class="banner err" role="alert">{{ error }}</p>
      <p v-if="notice" class="banner info" role="status">{{ notice }}</p>

      <FilterBar
        :model-value="activeTab === 'inbox' ? inboxQuery : archiveQuery"
        :providers="availableProviders"
        :accounts="accountsList"
        @update:model-value="onQueryChange"
      />

      <p v-if="loading && records.length === 0" class="state-msg">読み込み中…</p>
      <div
        v-else-if="!loading && records.length === 0 && !error && hasAccounts === false"
        class="state-msg no-account"
      >
        <p>アカウントが設定されていません.</p>
        <button type="button" class="btn-add-account" @click="showAccounts = true">
          アカウントを追加
        </button>
      </div>
      <p
        v-else-if="!loading && records.length === 0 && !error"
        class="state-msg"
      >
        <template v-if="activeTab === 'inbox'">
          メッセージはありません. 「手動更新」で取り込んでください.
        </template>
        <template v-else>
          アーカイブにメッセージはありません.
        </template>
      </p>

      <div v-else class="list">
        <MessageCard
          v-for="r in records"
          :key="r.message_id"
          :record="r"
          :busy="busyIds.has(r.message_id)"
          :mode="activeTab"
          @change-state="(s) => onChangeState(r, s)"
          @unarchive="onUnarchive(r)"
        />
      </div>
    </main>

    <AccountsModal
      v-if="showAccounts"
      @close="showAccounts = false"
      @accounts-changed="onAccountsChanged"
    />
  </div>
</template>

<style scoped>
.app {
  max-width: 920px;
  margin: 0 auto;
  padding: 0 16px 48px;
}
.bar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 0;
  background: var(--bg);
  border-bottom: 1px solid var(--border);
}
.brand {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.logo {
  font-size: 18px;
  font-weight: 800;
  color: var(--accent);
}
.tag-line {
  font-size: 12px;
  color: var(--text-muted);
}
.bar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.counter {
  font-size: 13px;
  color: var(--text-muted);
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--border);
}
.counter.alert {
  color: var(--danger);
  background: var(--danger-weak);
  border-color: var(--danger);
  font-weight: 700;
}
.accounts-btn,
.auto-refresh-btn,
.refresh,
.ingest {
  font-size: 13px;
  padding: 6px 14px;
  border-radius: var(--radius);
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
}
.auto-refresh-btn.active {
  color: var(--accent);
  border-color: var(--accent);
}
.ingest {
  border-color: var(--accent);
  background: var(--accent);
  color: #fff;
}
.refresh:disabled,
.ingest:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.tabs {
  display: flex;
  border-bottom: 1px solid var(--border);
  margin-top: 12px;
}
.tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  font-size: 14px;
  font-weight: 500;
  color: var(--text-muted);
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
}
.tab:hover {
  color: var(--text);
}
.tab.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}
.tab-badge {
  font-size: 11px;
  font-weight: 700;
  background: var(--danger);
  color: #fff;
  border-radius: 999px;
  padding: 1px 6px;
  min-width: 16px;
  text-align: center;
}
.main {
  margin-top: 16px;
}
.banner {
  margin: 0 0 12px;
  padding: 10px 12px;
  border-radius: var(--radius);
  font-size: 13px;
}
.banner.err {
  color: var(--danger);
  background: var(--danger-weak);
  border: 1px solid var(--danger);
}
.banner.info {
  color: var(--accent);
  background: var(--accent-weak);
  border: 1px solid var(--accent);
}
.state-msg {
  color: var(--text-muted);
  text-align: center;
  padding: 48px 0;
}
.no-account {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}
.no-account p {
  margin: 0;
}
.btn-add-account {
  font-size: 13px;
  padding: 6px 16px;
  border-radius: var(--radius);
  border: 1px solid var(--accent);
  background: var(--accent);
  color: #fff;
  cursor: pointer;
}
.btn-add-account:hover {
  opacity: 0.88;
}
.list {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
}
.banner {
  padding: 0.75rem 1rem;
  border-radius: var(--radius-md, 8px);
  margin-bottom: 1rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}
.banner--success { background: #d1fae5; color: #065f46; }
.banner--warn    { background: #fef3c7; color: #92400e; }
.banner button   {
  margin-left: auto;
  background: transparent;
  border: 1px solid currentColor;
  border-radius: 4px;
  padding: 2px 8px;
  cursor: pointer;
}
</style>
