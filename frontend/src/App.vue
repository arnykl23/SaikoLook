<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import type { DirectiveBinding } from "vue";
import type { MessageRecord, MessageState } from "./types";
import {
  type MessagesQuery,
  ConflictError,
  getMessages,
  getProviders,
  triggerIngest,
  archiveMessage,
  unarchiveMessage,
  updateMessageState,
  getAccounts,
  reauthGmailAccount,
  reauthGithubAccount,
} from "./api";
import MessageCard from "./components/MessageCard.vue";
import FilterBar from "./components/FilterBar.vue";
import AccountsModal from "./components/AccountsModal.vue";
import ToastContainer from "./components/ToastContainer.vue";
import { useToast } from "./composables/useToast";
import { useAnimatedCount } from "./composables/useAnimatedCount";

const { addToast, addActionToast } = useToast();

const vClickOutside = {
  mounted(el: HTMLElement, binding: DirectiveBinding) {
    (el as any)._clickOutside = (e: MouseEvent) => {
      if (!el.contains(e.target as Node)) binding.value();
    };
    document.addEventListener("mousedown", (el as any)._clickOutside);
  },
  unmounted(el: HTMLElement) {
    document.removeEventListener("mousedown", (el as any)._clickOutside);
  },
};

type Tab = "inbox" | "archive";

const inboxRecords = ref<MessageRecord[]>([]);
const archiveRecords = ref<MessageRecord[]>([]);
const inboxLoaded = ref(false);
const archiveLoaded = ref(false);
const loading = ref(false);
const ingesting = ref(false);
const busyIds = ref<Set<string>>(new Set());
const activeTab = ref<Tab>("inbox");
const availableProviders = ref<string[]>([]);

const sortOrderBy = ref<NonNullable<MessagesQuery["order_by"]>>(
  (localStorage.getItem("sortOrderBy") as MessagesQuery["order_by"]) ?? "importance",
);
const sortDescending = ref(localStorage.getItem("sortDescending") !== "false");

const inboxQuery = ref<MessagesQuery>({ archived: false });
const archiveQuery = ref<MessagesQuery>({ archived: true });

const activeRecords = computed(() =>
  activeTab.value === "inbox" ? inboxRecords.value : archiveRecords.value,
);

const unhandledCount = computed(
  () => inboxRecords.value.filter((r) => r.state === "unhandled").length,
);

function updateFavicon(count: number): void {
  const canvas = document.createElement("canvas");
  canvas.width = 32;
  canvas.height = 32;
  const ctx = canvas.getContext("2d")!;
  // Base icon: rounded rect + R
  ctx.fillStyle = "#049DBF";
  ctx.beginPath();
  ctx.roundRect(0, 0, 32, 32, 6);
  ctx.fill();
  ctx.fillStyle = "#fff";
  ctx.font = "bold 18px sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText("R", 16, 17);
  // Badge dot (bottom-right, no number — tab title already shows count)
  if (count > 0) {
    ctx.fillStyle = "#E05252";
    ctx.beginPath();
    ctx.arc(26, 26, 5, 0, Math.PI * 2);
    ctx.fill();
    // White ring to distinguish dot from background
    ctx.strokeStyle = "#fff";
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }
  const link = (document.getElementById("favicon") as HTMLLinkElement) ?? document.createElement("link");
  link.id = "favicon";
  link.rel = "icon";
  link.href = canvas.toDataURL();
  if (!link.parentNode) document.head.appendChild(link);
}

watch(unhandledCount, (n) => {
  document.title = n > 0 ? `(${n}) ReplyGuard` : "ReplyGuard";
  updateFavicon(n);
}, { immediate: true });

// 期限の「日付」はユーザーのローカルタイムゾーンで判定する.
// バックエンドは時刻を UTC で返すため, ISO 文字列の先頭10文字を切り出すと
// JST など UTC+ の地域では日付が1日前にずれ,「本日中」の期限が誤って
// 期限切れと判定される. Date でパースしローカル日付へ正規化して比較する.
function toLocalDateStr(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}
function deadlineLocalDate(deadline: string | null | undefined): string | null {
  if (!deadline) return null;
  const d = new Date(deadline);
  return Number.isNaN(d.getTime()) ? deadline.slice(0, 10) : toLocalDateStr(d);
}
function localToday(): string {
  return toLocalDateStr(new Date());
}

const inboxStats = computed(() => {
  const list = inboxRecords.value;
  const today = localToday();
  return {
    total:       list.length,
    unhandled:   list.filter(r => r.state === "unhandled").length,
    in_progress: list.filter(r => r.state === "in_progress").length,
    snoozed:     list.filter(r => r.state === "snoozed").length,
    needsReply:  list.filter(r => r.analysis?.request_type === "reply_required").length,
    today:       list.filter(r => deadlineLocalDate(r.analysis?.deadline) === today).length,
    overdue:     list.filter(r => {
      const d = deadlineLocalDate(r.analysis?.deadline);
      return d !== null && d < today;
    }).length,
  };
});

const animTotal      = useAnimatedCount(() => inboxStats.value.total);
const animUnhandled  = useAnimatedCount(() => inboxStats.value.unhandled);
const animInProgress = useAnimatedCount(() => inboxStats.value.in_progress);
const animSnoozed    = useAnimatedCount(() => inboxStats.value.snoozed);
const animNeedsReply = useAnimatedCount(() => inboxStats.value.needsReply);
const animToday      = useAnimatedCount(() => inboxStats.value.today);
const animOverdue    = useAnimatedCount(() => inboxStats.value.overdue);

const archiveStats = computed(() => {
  const list = archiveRecords.value;
  return {
    total:       list.length,
    done:        list.filter(r => r.state === "done").length,
    in_progress: list.filter(r => r.state === "in_progress").length,
    snoozed:     list.filter(r => r.state === "snoozed").length,
  };
});

const animArchiveTotal      = useAnimatedCount(() => archiveStats.value.total);
const animArchiveDone       = useAnimatedCount(() => archiveStats.value.done);
const animArchiveInProgress = useAnimatedCount(() => archiveStats.value.in_progress);
const animArchiveSnoozed    = useAnimatedCount(() => archiveStats.value.snoozed);

// --- Quick-filter chips ---
type TimeChip = "needs_reply" | "today" | "overdue" | null;
type StateChip = "unhandled" | "in_progress" | "done" | "snoozed" | "dismissed" | null;

// アカウント絞り込み：アカウント個別（address）の複数選択
const selectedAccounts = ref<string[]>([]);
const timeChip = ref<TimeChip>(null);
const stateChip = ref<StateChip>(null);

function toggleAccount(address: string): void {
  selectedAccounts.value = selectedAccounts.value.includes(address)
    ? selectedAccounts.value.filter((a) => a !== address)
    : [...selectedAccounts.value, address];
}
function toggleTime(chip: TimeChip): void {
  timeChip.value = timeChip.value === chip ? null : chip;
}
function toggleState(chip: StateChip): void {
  stateChip.value = stateChip.value === chip ? null : chip;
}
function clearChips(): void {
  selectedAccounts.value = [];
  timeChip.value = null;
  stateChip.value = null;
}

// --- Density ---
const compact = ref(localStorage.getItem("compact") === "true");
function toggleCompact(): void {
  compact.value = !compact.value;
  localStorage.setItem("compact", String(compact.value));
}

// --- Bulk selection ---
const selectedIds = ref<Set<string>>(new Set());

function toggleSelect(id: string, force?: boolean): void {
  const next = new Set(selectedIds.value);
  const shouldAdd = force ?? !next.has(id);
  if (shouldAdd) next.add(id);
  else next.delete(id);
  selectedIds.value = next;
}

function clearSelection(): void {
  selectedIds.value = new Set();
}

function selectAll(): void {
  selectedIds.value = new Set(displayedRecords.value.map(r => r.message_id));
}

const selectedRecords = computed(() =>
  displayedRecords.value.filter(r => selectedIds.value.has(r.message_id))
);

async function bulkChangeState(state: MessageState): Promise<void> {
  const records = selectedRecords.value;
  clearSelection();
  await Promise.all(records.map(r => onChangeState(r, state)));
}

async function bulkArchive(): Promise<void> {
  const records = selectedRecords.value;
  clearSelection();
  await Promise.all(records.map(r => onArchive(r)));
}

async function bulkUnarchive(): Promise<void> {
  const records = selectedRecords.value;
  clearSelection();
  await Promise.all(records.map(r => onUnarchive(r)));
}

// --- Search ---
const searchQuery = ref("");

const displayedRecords = computed(() => {
  let list = activeRecords.value;
  const q = searchQuery.value.trim().toLowerCase();
  if (q) {
    list = list.filter((r) =>
      r.email.subject?.toLowerCase().includes(q) ||
      r.email.sender?.toLowerCase().includes(q) ||
      r.email.snippet?.toLowerCase().includes(q) ||
      r.analysis?.summary?.toLowerCase().includes(q)
    );
  }
  if (stateChip.value) {
    list = list.filter((r) => r.state === stateChip.value);
  }
  if (selectedAccounts.value.length > 0) {
    list = list.filter((r) => selectedAccounts.value.includes(r.account_address));
  }
  if (timeChip.value === "needs_reply") {
    list = list.filter((r) => r.analysis?.request_type === "reply_required");
  } else if (timeChip.value === "today") {
    const today = localToday();
    list = list.filter((r) => deadlineLocalDate(r.analysis?.deadline) === today);
  } else if (timeChip.value === "overdue") {
    const today = localToday();
    list = list.filter((r) => {
      const d = deadlineLocalDate(r.analysis?.deadline);
      return d !== null && d < today;
    });
  }
  // Client-side sort
  const ob = sortOrderBy.value;
  const desc = sortDescending.value;
  list = [...list].sort((a, b) => {
    let av: number, bv: number;
    if (ob === "importance") {
      av = a.analysis?.importance ?? 0;
      bv = b.analysis?.importance ?? 0;
    } else if (ob === "received_at") {
      av = a.email.received_at ? new Date(a.email.received_at).getTime() : 0;
      bv = b.email.received_at ? new Date(b.email.received_at).getTime() : 0;
    } else {
      av = a.triage_score;
      bv = b.triage_score;
    }
    return desc ? bv - av : av - bv;
  });

  return list;
});

async function loadTab(tab: Tab): Promise<void> {
  loading.value = true;
  try {
    const query = tab === "inbox" ? inboxQuery.value : archiveQuery.value;
    const result = await getMessages(query);
    if (tab === "inbox") {
      inboxRecords.value = result;
      inboxLoaded.value = true;
    } else {
      archiveRecords.value = result;
      archiveLoaded.value = true;
    }
  } catch (e) {
    addToast(e instanceof Error ? e.message : "読み込みに失敗しました.", "error");
  } finally {
    loading.value = false;
  }
}

async function load(): Promise<void> {
  await loadTab(activeTab.value);
}

function onQueryChange(q: MessagesQuery): void {
  if (q.order_by !== undefined) {
    sortOrderBy.value = q.order_by;
    localStorage.setItem("sortOrderBy", q.order_by);
  }
  if (q.descending !== undefined) {
    sortDescending.value = q.descending;
    localStorage.setItem("sortDescending", String(q.descending));
  }

  const { order_by: _ob, descending: _desc, ...filters } = q;
  const newQuery = { ...filters, archived: activeTab.value === "archive" };
  const current = activeTab.value === "inbox" ? inboxQuery.value : archiveQuery.value;

  const filtersChanged = JSON.stringify(newQuery) !== JSON.stringify(current);
  if (activeTab.value === "inbox") {
    inboxQuery.value = newQuery;
  } else {
    archiveQuery.value = newQuery;
  }
  if (filtersChanged) void load();
}

async function switchTab(tab: Tab): Promise<void> {
  if (activeTab.value === tab) return;
  const go = async () => {
    activeTab.value = tab;
    clearChips();
    clearSelection();
    const alreadyLoaded = tab === "inbox" ? inboxLoaded.value : archiveLoaded.value;
    if (!alreadyLoaded) await loadTab(tab);
  };
  await go();
}

async function onIngest(): Promise<void> {
  ingesting.value = true;
  try {
    await triggerIngest();
    await Promise.all([loadTab("inbox"), loadTab("archive")]);
    addToast("同期が完了しました.", "success");
  } catch (e) {
    addToast(e instanceof Error ? e.message : "同期に失敗しました.", "error");
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

const STATE_TOAST_LABELS: Partial<Record<MessageState, string>> = {
  done:        "完了にしました。",
  in_progress: "対応中にしました。",
  snoozed:     "保留にしました。",
  unhandled:   "未対応に戻しました。",
};

async function onChangeState(
  record: MessageRecord,
  state: MessageState,
  isUndo = false,
): Promise<void> {
  const prevState = record.state;
  setBusy(record.message_id, true);
  try {
    const updated = await updateMessageState(record.message_id, state, record.version);
    await Promise.all([loadTab("inbox"), loadTab("archive")]);
    const label = STATE_TOAST_LABELS[state] ?? `${state}にしました。`;
    if (isUndo) {
      addToast(label, "success");
    } else {
      addActionToast(label, "success", {
        label: "元に戻す",
        fn: () => void onChangeState(updated, prevState, true),
      });
    }
  } catch (e) {
    if (e instanceof ConflictError) {
      addToast(e.message, "warn");
      await Promise.all([loadTab("inbox"), loadTab("archive")]);
    } else {
      addToast(e instanceof Error ? e.message : "更新に失敗しました.", "error");
    }
  } finally {
    setBusy(record.message_id, false);
  }
}

function onFeedbackApplied(record: MessageRecord, patch: Partial<import("./types").AnalysisResult>): void {
  for (const list of [inboxRecords, archiveRecords]) {
    const idx = list.value.findIndex((r) => r.message_id === record.message_id);
    if (idx !== -1 && list.value[idx].analysis) {
      list.value[idx] = {
        ...list.value[idx],
        analysis: { ...list.value[idx].analysis!, ...patch },
      };
    }
  }
}

async function onUnarchive(record: MessageRecord, isUndo = false): Promise<void> {
  setBusy(record.message_id, true);
  try {
    const updated = await unarchiveMessage(record.message_id);
    await Promise.all([loadTab("inbox"), loadTab("archive")]);
    if (isUndo) {
      addToast("受信トレイに復元しました。", "success");
    } else {
      addActionToast("受信トレイに復元しました。", "success", {
        label: "元に戻す",
        fn: () => void onArchive(updated, true),
      });
    }
  } catch (e) {
    addToast(e instanceof Error ? e.message : "復元に失敗しました。", "error");
  } finally {
    setBusy(record.message_id, false);
  }
}

async function onArchive(record: MessageRecord, isUndo = false): Promise<void> {
  setBusy(record.message_id, true);
  try {
    const updated = await archiveMessage(record.message_id);
    toggleSelect(record.message_id, false);
    await Promise.all([loadTab("inbox"), loadTab("archive")]);
    if (isUndo) {
      addToast("アーカイブしました.", "success");
    } else {
      addActionToast("アーカイブしました.", "success", {
        label: "元に戻す",
        fn: () => void onUnarchive(updated, true),
      });
    }
  } catch (e) {
    addToast(e instanceof Error ? e.message : "アーカイブに失敗しました.", "error");
  } finally {
    setBusy(record.message_id, false);
  }
}

const AUTO_REFRESH_INTERVAL_MS = 60_000;
let autoRefreshTimer: ReturnType<typeof setInterval> | null = null;
const autoRefresh = ref(true);

function startAutoRefresh(): void {
  if (autoRefreshTimer !== null) return;
  autoRefreshTimer = setInterval(() => {
    void Promise.all([loadTab("inbox"), loadTab("archive")]);
  }, AUTO_REFRESH_INTERVAL_MS);
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

const STATE_EMPTY_LABELS: Partial<Record<string, string>> = {
  unhandled:   "未対応のメールはありません",
  in_progress: "対応中のメールはありません",
  snoozed:     "保留中のメールはありません",
};
const TIME_EMPTY_LABELS: Partial<Record<string, string>> = {
  needs_reply: "要返信のメールはありません",
  today:       "今日期限のメールはありません",
  overdue:     "期限切れのメールはありません",
};

const emptyLabel = computed(() => {
  if (searchQuery.value) return `"${searchQuery.value}" に一致するメールはありません`;
  if (stateChip.value && STATE_EMPTY_LABELS[stateChip.value]) return STATE_EMPTY_LABELS[stateChip.value]!;
  if (timeChip.value && TIME_EMPTY_LABELS[timeChip.value]) return TIME_EMPTY_LABELS[timeChip.value]!;
  if (selectedAccounts.value.length > 0) return "選択したアカウントのメールはありません";
  return activeTab.value === "inbox" ? "受信トレイは空です" : "アーカイブにメッセージはありません";
});

// --- Keyboard shortcuts ---
const showShortcuts = ref(false);
const focusedIndex = ref<number>(-1);
const searchInputEl = ref<HTMLInputElement | null>(null);

function focusedRecord(): MessageRecord | null {
  return displayedRecords.value[focusedIndex.value] ?? null;
}

const keyboardNav = ref(false);

function onMouseMove(): void {
  if (keyboardNav.value) {
    keyboardNav.value = false;
    focusedIndex.value = -1;
  }
}

function onKeydown(e: KeyboardEvent): void {
  const tag = (e.target as HTMLElement).tagName;
  const inInput = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";

  // Ctrl+/ always works
  if (e.key === "/" && (e.metaKey || e.ctrlKey)) {
    e.preventDefault();
    showShortcuts.value = !showShortcuts.value;
    return;
  }

  // Escape closes any modal
  if (e.key === "Escape") {
    if (showShortcuts.value) { showShortcuts.value = false; return; }
    if (showAccounts.value)  { showAccounts.value = false;  return; }
    if (showDropdown.value)  { showDropdown.value = false;  return; }
    if (searchQuery.value)   { searchQuery.value = "";      return; }
    focusedIndex.value = -1;
    return;
  }

  if (inInput) return;

  const total = displayedRecords.value.length;

  switch (e.key) {
    case "j":
      e.preventDefault();
      keyboardNav.value = true;
      focusedIndex.value = Math.min(focusedIndex.value + 1, total - 1);
      break;
    case "k":
      e.preventDefault();
      keyboardNav.value = true;
      focusedIndex.value = Math.max(focusedIndex.value - 1, 0);
      break;
    case "/":
      e.preventDefault();
      searchInputEl.value?.focus();
      break;
    case "1":
      void switchTab("inbox");
      break;
    case "2":
      void switchTab("archive");
      break;
    case "e": {
      const r = focusedRecord();
      if (r && activeTab.value === "inbox") void onArchive(r);
      break;
    }
    case "d": {
      const r = focusedRecord();
      if (r) void onChangeState(r, r.state === "done" ? "unhandled" : "done");
      break;
    }
    case "u": {
      const r = focusedRecord();
      if (r) void onChangeState(r, r.state === "in_progress" ? "unhandled" : "in_progress");
      break;
    }
    case "s": {
      const r = focusedRecord();
      if (r) void onChangeState(r, r.state === "snoozed" ? "unhandled" : "snoozed");
      break;
    }
    case "x": {
      const r = focusedRecord();
      if (r) void onArchive(r);
      break;
    }
  }
}

// --- Sidebar collapse ---
const sidebarCollapsed = ref(localStorage.getItem("sidebarCollapsed") === "true");
const sidebarToggling = ref(false);
function toggleSidebar(): void {
  sidebarToggling.value = true;
  sidebarCollapsed.value = !sidebarCollapsed.value;
  localStorage.setItem("sidebarCollapsed", String(sidebarCollapsed.value));
  setTimeout(() => { sidebarToggling.value = false; }, 50);
}

// --- Scroll to top ---
const scrollContainer = ref<HTMLElement | null>(null);
const showScrollTop = ref(false);
function onScroll(): void {
  showScrollTop.value = (scrollContainer.value?.scrollTop ?? 0) > 300;
}
function scrollToTop(): void {
  scrollContainer.value?.scrollTo({ top: 0, behavior: "smooth" });
}

// --- Avatar dropdown ---
const showDropdown = ref(false);

function toggleDropdown(): void {
  showDropdown.value = !showDropdown.value;
}
function closeDropdown(): void {
  showDropdown.value = false;
}

// --- アカウント管理 ---
const showAccounts = ref(false);
const hasAccounts = ref<boolean | null>(null);
const accountsList = ref<import("./types").AccountConfig[]>([]);

const reauthAccounts = computed(() =>
  accountsList.value.filter(a => a.auth_status === "reauth_required")
);

async function onReauth(accountId: string): Promise<void> {
  try {
    const provider = accountsList.value.find((a) => a.id === accountId)?.provider;
    const { auth_url } =
      provider === "github"
        ? await reauthGithubAccount(accountId)
        : await reauthGmailAccount(accountId);
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
  void Promise.all([loadTab("inbox"), loadTab("archive")]);
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
    window.history.replaceState({}, "", window.location.pathname);
    await refreshAccountStatus();
    addToast("アカウントの接続が完了しました．", "success");
    try {
      await triggerIngest();
    } catch (e) {
      console.error("自動同期に失敗（次回の自動更新で補完）:", e);
    }
    await load();
  }
});

onMounted(() => {
  document.addEventListener("keydown", onKeydown);
  document.addEventListener("mousemove", onMouseMove);
  scrollContainer.value?.addEventListener("scroll", onScroll, { passive: true });
});
onUnmounted(() => {
  stopAutoRefresh();
  document.removeEventListener("keydown", onKeydown);
  document.removeEventListener("mousemove", onMouseMove);
  scrollContainer.value?.removeEventListener("scroll", onScroll);
});
</script>

<template>
  <div class="app">
    <!-- gooey SVG フィルタ（同一ドキュメント ID 参照のため直書き） -->
    <svg width="0" height="0" aria-hidden="true" style="position:absolute;pointer-events:none">
      <filter id="liquid-goo">
        <feGaussianBlur in="SourceGraphic" stdDeviation="10" result="blur"/>
        <feColorMatrix in="blur" mode="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 20 -9" result="goo"/>
        <feBlend in="SourceGraphic" in2="goo"/>
      </filter>
    </svg>

    <!-- リキッド背景ブロブ（styles.css の .bg-blobs/.bg-blob--N を使用） -->
    <div class="bg-blobs" aria-hidden="true">
      <span class="bg-blob bg-blob--1"></span>
      <span class="bg-blob bg-blob--2"></span>
      <span class="bg-blob bg-blob--3"></span>
      <span class="bg-blob bg-blob--4"></span>
    </div>

    <!-- ヘッダー：浮遊ガラスバー -->
    <header class="bar glass">
      <div class="brand">
        <span class="logo">ReplyGuard</span>
        <span class="tag-line">受信トレイ管制塔</span>
      </div>
      <div class="search-wrap">
        <svg class="search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
        </svg>
        <input
          ref="searchInputEl"
          v-model="searchQuery"
          type="text"
          class="search-input"
          placeholder="検索…"
          aria-label="メッセージを検索"
        />
        <button
          v-if="searchQuery"
          type="button"
          class="search-clear"
          aria-label="検索をクリア"
          @click="searchQuery = ''"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" aria-hidden="true">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>

      <div class="bar-right">
        <button
          type="button"
          class="ingest lift"
          :class="{ 'ingest--spinning': ingesting }"
          :disabled="loading || ingesting"
          :title="ingesting ? '同期中…' : '手動でメールを取り込む'"
          @click="onIngest"
        >
          <svg class="ingest-dice" width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <rect x="3" y="3" width="18" height="18" rx="3.5" fill="currentColor" opacity="0.15" stroke="currentColor" stroke-width="1.8"/>
            <circle cx="8"  cy="8"  r="1.85" fill="currentColor"/>
            <circle cx="16" cy="8"  r="1.85" fill="currentColor"/>
            <circle cx="12" cy="12" r="1.85" fill="currentColor"/>
            <circle cx="8"  cy="16" r="1.85" fill="currentColor"/>
            <circle cx="16" cy="16" r="1.85" fill="currentColor"/>
          </svg>
          {{ ingesting ? "同期中…" : "同期" }}
        </button>
        <div class="avatar-wrap" v-click-outside="closeDropdown">
          <button
            type="button"
            class="accounts-btn"
            :aria-expanded="showDropdown"
            aria-label="メニューを開く"
            @click="toggleDropdown"
          >
            <svg width="32" height="32" viewBox="0 0 32 32" fill="none" aria-hidden="true">
              <circle cx="16" cy="16" r="16" fill="var(--ocean)"/>
              <circle cx="16" cy="13" r="5" fill="rgba(255,255,255,0.9)"/>
              <path d="M6 28c0-5.5 4.5-9 10-9s10 3.5 10 9" fill="rgba(255,255,255,0.9)"/>
            </svg>
          </button>

          <!-- ドロップダウン：ガラス化 -->
          <Transition name="dropdown">
            <div v-if="showDropdown" class="dropdown glass" role="menu">
              <div class="dropdown-section">
                <button class="dropdown-item" role="menuitem" @click="showAccounts = true; closeDropdown()">
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <circle cx="12" cy="8" r="4"/>
                    <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/>
                  </svg>
                  アカウント設定
                </button>
                <button class="dropdown-item" role="menuitem" @click="toggleAutoRefresh(); closeDropdown()">
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path d="M21 12a9 9 0 1 1-3-6.7"/>
                    <polyline points="21 3 21 9 15 9"/>
                  </svg>
                  自動更新：{{ autoRefresh ? 'オン' : 'オフ' }}
                  <span class="dropdown-dot" :class="{ on: autoRefresh }" aria-hidden="true" />
                </button>
              </div>
              <div class="dropdown-divider" />
              <div class="dropdown-section">
                <button class="dropdown-item dropdown-item--danger" role="menuitem" @click="closeDropdown">
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
                    <polyline points="16 17 21 12 16 7"/>
                    <line x1="21" y1="12" x2="9" y2="12"/>
                  </svg>
                  ログアウト
                </button>
              </div>
            </div>
          </Transition>
        </div>
      </div>
    </header>

    <div class="app-body">
    <!-- タブ：セグメンテッド風ガラスコントロール -->
    <nav class="tabs glass" role="tablist" aria-label="メールビュー切り替え">
      <button
        role="tab"
        :aria-selected="activeTab === 'inbox'"
        class="tab"
        :class="{ active: activeTab === 'inbox' }"
        @click="switchTab('inbox')"
      >
        受信トレイ
        <span
          v-if="unhandledCount > 0"
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


    <main class="main" :class="{ 'main--collapsed': sidebarCollapsed }">
      <aside class="sidebar">
        <button type="button" class="sidebar-toggle" :title="sidebarCollapsed ? 'フィルターを表示' : 'フィルターを非表示'" @click="toggleSidebar">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <line x1="3" y1="6" x2="21" y2="6"/>
            <line x1="3" y1="12" x2="21" y2="12"/>
            <line x1="3" y1="18" x2="21" y2="18"/>
          </svg>
          <span>{{ sidebarCollapsed ? 'フィルター' : '非表示' }}</span>
        </button>
        <div class="sidebar-content">
        <FilterBar
          :model-value="{ ...(activeTab === 'inbox' ? inboxQuery : archiveQuery), order_by: sortOrderBy, descending: sortDescending }"
          :providers="availableProviders"
          :accounts="accountsList"
          :selected-accounts="selectedAccounts"
          @update:model-value="onQueryChange"
          @toggle-account="toggleAccount"
        />
        </div>
      </aside>

      <div ref="scrollContainer" class="content">
      <!-- Stats row：ガラスカード化（主要 stat は glass--ocean ヒーロー） -->
      <div v-if="(activeTab === 'inbox' && inboxStats.total > 0) || (activeTab === 'archive' && archiveStats.total > 0) || selectedIds.size > 0" class="stats-row glass">
        <label class="select-all-wrap" :title="selectedIds.size === displayedRecords.length ? '選択解除' : 'すべて選択'">
          <input
            type="checkbox"
            class="select-all-check"
            :checked="selectedIds.size > 0 && selectedIds.size === displayedRecords.length"
            :indeterminate="selectedIds.size > 0 && selectedIds.size < displayedRecords.length"
            @change="selectedIds.size === displayedRecords.length ? clearSelection() : selectAll()"
          />
        </label>

        <!-- Inbox: no selection -->
        <template v-if="activeTab === 'inbox' && selectedIds.size === 0">
          <div class="stat">
            <span class="stat-value">{{ animTotal }}</span>
            <span class="stat-label">件</span>
          </div>
          <div class="stat-sep" />
          <!-- 未対応：glass--ocean ヒーロー化 -->
          <button type="button" class="stat stat-btn stat-btn--hero" :class="{ 'stat-btn--active': stateChip === 'unhandled', 'stat-btn--hero-on': inboxStats.unhandled > 0 }" @click="toggleState('unhandled')">
            <span class="stat-value">{{ animUnhandled }}</span>
            <span class="stat-label">未対応</span>
          </button>
          <button type="button" class="stat stat-btn stat-btn--sand" :class="{ 'stat-btn--active': stateChip === 'in_progress' }" @click="toggleState('in_progress')">
            <span class="stat-value">{{ animInProgress }}</span>
            <span class="stat-label">対応中</span>
          </button>
          <button type="button" class="stat stat-btn stat-btn--sage" :class="{ 'stat-btn--active': stateChip === 'snoozed' }" @click="toggleState('snoozed')">
            <span class="stat-value">{{ animSnoozed }}</span>
            <span class="stat-label">保留</span>
          </button>
          <div class="stat-sep" />
          <button type="button" class="stat stat-btn" :class="{ 'stat-btn--active': timeChip === 'needs_reply' }" @click="toggleTime('needs_reply')">
            <span class="stat-value">{{ animNeedsReply }}</span>
            <span class="stat-label">要返信</span>
          </button>
          <button type="button" class="stat stat-btn" :class="{ 'stat-btn--active': timeChip === 'today' }" @click="toggleTime('today')">
            <span class="stat-value">{{ animToday }}</span>
            <span class="stat-label">今日期限</span>
          </button>
          <!-- 期限切れ：ocean 塗り反転で最強シグナル -->
          <button type="button" class="stat stat-btn stat-btn--overdue" :class="{ 'stat-btn--active': timeChip === 'overdue', 'stat-btn--overdue-active': inboxStats.overdue > 0 }" @click="toggleTime('overdue')">
            <span class="stat-value">{{ animOverdue }}</span>
            <span class="stat-label">期限切れ</span>
          </button>
        </template>

        <!-- Archive: no selection -->
        <template v-else-if="activeTab === 'archive' && selectedIds.size === 0">
          <div class="stat">
            <span class="stat-value">{{ animArchiveTotal }}</span>
            <span class="stat-label">件</span>
          </div>
          <div class="stat-sep" />
          <button type="button" class="stat stat-btn stat-btn--leaf" :class="{ 'stat-btn--active': stateChip === 'done' }" @click="toggleState('done')">
            <span class="stat-value">{{ animArchiveDone }}</span>
            <span class="stat-label">完了</span>
          </button>
          <button type="button" class="stat stat-btn stat-btn--sand" :class="{ 'stat-btn--active': stateChip === 'in_progress' }" @click="toggleState('in_progress')">
            <span class="stat-value">{{ animArchiveInProgress }}</span>
            <span class="stat-label">対応中</span>
          </button>
          <button type="button" class="stat stat-btn stat-btn--sage" :class="{ 'stat-btn--active': stateChip === 'snoozed' }" @click="toggleState('snoozed')">
            <span class="stat-value">{{ animArchiveSnoozed }}</span>
            <span class="stat-label">保留</span>
          </button>
        </template>

        <!-- Inbox bulk actions -->
        <template v-else-if="activeTab === 'inbox'">
          <div class="stat">
            <span class="stat-value stat-selected">{{ selectedIds.size }}</span>
            <span class="stat-label">件選択中</span>
          </div>
          <div class="stat-sep" />
          <button type="button" class="bulk-btn bulk-btn--sand" @click="bulkChangeState('in_progress')">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            対応中
          </button>
          <button type="button" class="bulk-btn bulk-btn--leaf" @click="bulkChangeState('done')">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg>
            完了
          </button>
          <button type="button" class="bulk-btn bulk-btn--sage" @click="bulkChangeState('snoozed')">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>
            保留
          </button>
          <button type="button" class="bulk-btn" @click="bulkArchive()">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="21 8 21 21 3 21 3 8"/><rect x="1" y="3" width="22" height="5"/><line x1="10" y1="12" x2="14" y2="12"/></svg>
            アーカイブ
          </button>
          <button type="button" class="bulk-btn bulk-btn--clear" @click="clearSelection()">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            キャンセル
          </button>
        </template>

        <!-- Archive bulk actions -->
        <template v-else>
          <div class="stat">
            <span class="stat-value stat-selected">{{ selectedIds.size }}</span>
            <span class="stat-label">件選択中</span>
          </div>
          <div class="stat-sep" />
          <button type="button" class="bulk-btn bulk-btn--sand" @click="bulkChangeState('in_progress')">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            対応中
          </button>
          <button type="button" class="bulk-btn bulk-btn--leaf" @click="bulkChangeState('done')">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg>
            完了
          </button>
          <button type="button" class="bulk-btn bulk-btn--sage" @click="bulkChangeState('snoozed')">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>
            保留
          </button>
          <button type="button" class="bulk-btn bulk-btn--sage" @click="bulkUnarchive()">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="21 8 21 21 3 21 3 8"/><rect x="1" y="3" width="22" height="5"/><polyline points="9 12 12 9 15 12"/><line x1="12" y1="9" x2="12" y2="15"/></svg>
            受信トレイに戻す
          </button>
          <button type="button" class="bulk-btn bulk-btn--clear" @click="clearSelection()">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            キャンセル
          </button>
        </template>

        <button
          type="button"
          class="density-btn"
          :title="compact ? '快適表示に切り替え' : 'コンパクト表示に切り替え'"
          @click="toggleCompact"
          aria-label="表示密度を切り替え"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <line x1="8" y1="6" x2="21" y2="6"/>
            <line x1="8" y1="12" x2="21" y2="12"/>
            <line x1="8" y1="18" x2="21" y2="18"/>
            <circle cx="3" cy="6" r="1" fill="currentColor" stroke="none"/>
            <circle cx="3" cy="12" r="1" fill="currentColor" stroke="none"/>
            <circle cx="3" cy="18" r="1" fill="currentColor" stroke="none"/>
          </svg>
          <span>{{ compact ? 'コンパクト' : '標準' }}</span>
        </button>
      </div>

      <!-- reauth_required バナー (inline — needs action button) -->
      <div v-if="reauthAccounts.length" class="banner banner--warn glass">
        {{ reauthAccounts.length }} 件のアカウントで Google 認証の更新が必要です．
        <button
          v-for="acc in reauthAccounts"
          :key="acc.id"
          @click="onReauth(acc.id)"
        >{{ acc.label }} を再接続</button>
      </div>

      <!-- ローディング・空状態（ガラスパネル内） -->
      <div v-if="loading && displayedRecords.length === 0" class="empty-state">
        <div class="empty-panel glass">
          <svg class="empty-illustration dice-spin" viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
            <circle cx="60" cy="60" r="48" fill="var(--mist)"/>
            <!-- dice body -->
            <rect x="34" y="34" width="52" height="52" rx="10" fill="var(--ocean)"/>
            <!-- dots: die face showing 4 -->
            <circle cx="47" cy="47" r="4.5" fill="white"/>
            <circle cx="73" cy="47" r="4.5" fill="white"/>
            <circle cx="47" cy="73" r="4.5" fill="white"/>
            <circle cx="73" cy="73" r="4.5" fill="white"/>
          </svg>
          <p class="empty-label">読み込み中…</p>
        </div>
      </div>

      <div
        v-else-if="!loading && displayedRecords.length === 0 && hasAccounts === false"
        class="empty-state"
      >
        <div class="empty-panel glass">
          <svg class="empty-illustration" viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
            <circle cx="60" cy="60" r="48" fill="var(--mist)"/>
            <rect x="28" y="38" width="64" height="44" rx="5" fill="var(--sage-weak)"/>
            <path d="M28 43l32 22 32-22" stroke="var(--white)" stroke-width="2.5" stroke-linecap="round"/>
            <line x1="44" y1="70" x2="76" y2="70" stroke="var(--white)" stroke-width="2.5" stroke-linecap="round"/>
            <line x1="44" y1="76" x2="64" y2="76" stroke="var(--white)" stroke-width="2.5" stroke-linecap="round"/>
            <circle cx="84" cy="36" r="12" fill="var(--ocean)"/>
            <line x1="84" y1="31" x2="84" y2="41" stroke="white" stroke-width="2.5" stroke-linecap="round"/>
            <line x1="79" y1="36" x2="89" y2="36" stroke="white" stroke-width="2.5" stroke-linecap="round"/>
          </svg>
          <p class="empty-label">アカウントが設定されていません</p>
          <button type="button" class="btn-add-account lift" @click="showAccounts = true">
            アカウントを追加
          </button>
        </div>
      </div>

      <div
        v-else-if="!loading && displayedRecords.length === 0"
        class="empty-state"
      >
        <div class="empty-panel glass">
          <svg class="empty-illustration" viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
            <circle cx="60" cy="60" r="48" fill="var(--mist)"/>
            <rect x="28" y="38" width="64" height="44" rx="5" fill="var(--sage-weak)"/>
            <path d="M28 43l32 22 32-22" stroke="var(--white)" stroke-width="2.5" stroke-linecap="round"/>
            <line x1="44" y1="70" x2="76" y2="70" stroke="var(--white)" stroke-width="2.5" stroke-linecap="round"/>
            <line x1="44" y1="76" x2="64" y2="76" stroke="var(--white)" stroke-width="2.5" stroke-linecap="round"/>
            <circle cx="84" cy="36" r="12" fill="var(--leaf)"/>
            <polyline points="79,36 83,40 90,32" stroke="white" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          <p class="empty-label">{{ emptyLabel }}</p>
          <button v-if="stateChip || timeChip || selectedAccounts.length || searchQuery" type="button" class="empty-clear-btn" @click="clearChips(); searchQuery = ''">フィルターをクリア</button>
          <p class="empty-sub" v-else-if="activeTab === 'inbox'">「同期」で新しいメールを取り込めます。</p>
        </div>
      </div>

      <!-- メッセージリスト：TransitionGroup FLIP + stagger -->
      <TransitionGroup
        v-else
        tag="div"
        name="list"
        :class="['list', { 'list--no-move': sidebarToggling }]"
      >
        <MessageCard
          v-for="(r, i) in displayedRecords"
          :key="r.message_id"
          :record="r"
          :busy="busyIds.has(r.message_id)"
          :mode="activeTab === 'archive' ? 'archive' : 'inbox'"
          :compact="compact"
          :focused="focusedIndex === i"
          :selected="selectedIds.has(r.message_id)"
          :search-query="searchQuery"
          :style="{ '--i': Math.min(i, 10) }"
          @change-state="(s) => onChangeState(r, s)"
          @archive="onArchive(r)"
          @unarchive="onUnarchive(r)"
          @feedback-applied="(patch) => onFeedbackApplied(r, patch)"
          @click="focusedIndex = -1"
          @toggle-select="toggleSelect(r.message_id)"
        />
      </TransitionGroup>
      </div>
    </main>

    <AccountsModal
      v-if="showAccounts"
      @close="showAccounts = false"
      @accounts-changed="onAccountsChanged"
    />
    </div><!-- /app-body -->

    <!-- Keyboard shortcuts modal -->
    <Teleport to="body">
      <Transition name="modal">
        <div v-if="showShortcuts" class="shortcuts-backdrop" @click.self="showShortcuts = false">
          <div class="shortcuts-modal glass" role="dialog" aria-modal="true" aria-label="キーボードショートカット">
            <div class="shortcuts-header">
              <span class="shortcuts-title">キーボードショートカット</span>
              <button type="button" class="shortcuts-close" aria-label="閉じる" @click="showShortcuts = false">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" aria-hidden="true">
                  <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                </svg>
              </button>
            </div>
            <div class="shortcuts-body">
              <div class="shortcuts-section">
                <div class="shortcuts-section-title">ナビゲーション</div>
                <div class="shortcut-row"><kbd>j</kbd><span>次の項目</span></div>
                <div class="shortcut-row"><kbd>k</kbd><span>前の項目</span></div>
                <div class="shortcut-row"><kbd>/</kbd><span>検索にフォーカス</span></div>
                <div class="shortcut-row"><kbd>1</kbd><span>受信トレイ</span></div>
                <div class="shortcut-row"><kbd>2</kbd><span>アーカイブ</span></div>
                <div class="shortcut-row"><kbd>Esc</kbd><span>選択解除 / 閉じる</span></div>
              </div>
              <div class="shortcuts-section">
                <div class="shortcuts-section-title">アクション（選択中のメール）</div>
                <div class="shortcut-row"><kbd>e</kbd><span>アーカイブ</span></div>
                <div class="shortcut-row"><kbd>u</kbd><span>対応中 / 未対応に戻す</span></div>
                <div class="shortcut-row"><kbd>d</kbd><span>完了 / 未対応に戻す</span></div>
                <div class="shortcut-row"><kbd>s</kbd><span>保留 / 未対応に戻す</span></div>
                <div class="shortcut-row"><kbd>x</kbd><span>アーカイブ</span></div>
              </div>
              <div class="shortcuts-divider" />
              <div class="shortcuts-section">
                <div class="shortcut-row"><kbd>⌘</kbd><kbd>/</kbd><span>このページを表示</span></div>
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <ToastContainer />

    <!-- Jump to top：白ガラス丸 + ocean -->
    <Teleport to="body">
      <Transition name="scroll-top">
        <button
          v-if="showScrollTop"
          type="button"
          class="scroll-top-btn glass lift"
          aria-label="トップへ戻る"
          @click="scrollToTop"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <polyline points="18 15 12 9 6 15"/>
          </svg>
        </button>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.app {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
  position: relative;
  z-index: 0;
}

.app-body {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  padding: 0 20px;
  max-width: 1200px;
  width: 100%;
  margin: 0 auto;
  box-sizing: border-box;
  position: relative;
  z-index: 1;
}

/* ── Header bar：浮遊ガラスバー（glass クラスはグローバル） ── */
.bar {
  flex-shrink: 0;
  z-index: 10;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 0 20px;
  height: 56px;
  margin: 10px 16px 0;
  /* glass クラスで background/backdrop-filter/box-shadow/border-radius を上書き */
  border-radius: var(--radius) !important;
}

.brand {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.logo {
  font-size: 20px;
  font-weight: 800;
  color: var(--ocean);
  letter-spacing: -0.3px;
}
.tag-line {
  font-size: 12px;
  color: var(--text-muted);
}

.search-wrap {
  flex: 1;
  max-width: 640px;
  position: relative;
  display: flex;
  align-items: center;
}
.search-icon {
  position: absolute;
  left: 10px;
  color: var(--text-muted);
  pointer-events: none;
}
.search-input {
  width: 100%;
  padding: 6px 12px 6px 32px;
  border-radius: var(--radius-pill);
  border: 1.5px solid var(--border);
  background: rgba(228, 235, 242, 0.55);
  color: var(--ocean);
  font: inherit;
  font-size: 13px;
  outline: none;
  transition: border-color 0.15s, background 0.15s;
}
.search-input::placeholder { color: var(--text-muted); }
.search-input:focus {
  background: rgba(255, 255, 255, 0.80);
  border-color: var(--ocean);
  box-shadow: 0 0 0 3px var(--ocean-12);
}
.search-clear {
  position: absolute;
  right: 8px;
  background: none;
  border: none;
  padding: 2px;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  cursor: pointer;
  transition:
    color var(--dur-fast) var(--ease-out-expo),
    transform var(--dur-fast) var(--ease-spring),
    opacity var(--dur-fast) var(--ease-out-expo);
}
.search-clear:hover {
  color: var(--ocean);
  transform: scale(1.15);
}
.search-clear:active { transform: scale(0.9); }

.bar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.avatar-wrap {
  position: relative;
  display: flex;
  align-items: center;
  margin-left: 8px;
}
.accounts-btn {
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  line-height: 0;
  opacity: 0.9;
  border-radius: 50%;
  transition:
    opacity var(--dur-fast) var(--ease-out-expo),
    box-shadow var(--dur-fast) var(--ease-out-expo),
    transform var(--dur-fast) var(--ease-spring);
}
.accounts-btn:hover {
  opacity: 1;
  box-shadow: 0 0 0 3px var(--ocean-12);
  transform: scale(1.1);
}
.accounts-btn:active { transform: scale(0.9); }

/* ── Dropdown：ガラス化 ── */
.dropdown {
  position: absolute;
  top: calc(100% + 10px);
  right: 0;
  min-width: 210px;
  border-radius: var(--radius-sm) !important;
  z-index: 200;
  overflow: hidden;
  background: var(--white) !important;
  -webkit-backdrop-filter: none !important;
  backdrop-filter: none !important;
}
.dropdown-section {
  padding: 4px 0;
}
.dropdown-divider {
  height: 1px;
  background: var(--border);
  margin: 0;
}
.dropdown-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 16px;
  font-size: 13px;
  font-weight: 500;
  color: var(--ocean);
  background: none;
  border: none;
  text-align: left;
  cursor: pointer;
  transition:
    background var(--dur-fast) var(--ease-out-expo),
    transform var(--dur-fast) var(--ease-out-expo),
    color var(--dur-fast) var(--ease-out-expo);
}
.dropdown-item:hover {
  background: rgba(228, 235, 242, 0.60);
  transform: translateX(2px);
}
.dropdown-item:hover > svg:first-child {
  transform: translateX(0);
}
.dropdown-item:active { transform: translateX(2px) scale(0.98); }
.dropdown-item--danger {
  color: var(--red);
}
.dropdown-item--danger:hover {
  background: var(--red-12);
}
.dropdown-dot {
  margin-left: auto;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--border);
  flex-shrink: 0;
  transition: background 0.2s, box-shadow 0.2s;
}
.dropdown-dot.on {
  background: var(--leaf);
  box-shadow: 0 0 5px rgba(119, 191, 86, 0.6);
}

/* ── ドロップダウン Transition ── */
.dropdown-enter-active, .dropdown-leave-active {
  transition: opacity var(--dur-fast) var(--ease-out-expo), transform var(--dur-fast) var(--ease-out-expo);
}
.dropdown-enter-from, .dropdown-leave-to {
  opacity: 0;
  transform: translateY(-6px) scale(0.97);
}

/* ── 同期ボタン（ocean 塗り・pill・lift） ── */
.ingest {
  font-size: 13px;
  padding: 0 16px;
  height: 36px;
  width: 100px;
  white-space: nowrap;
  border-radius: var(--radius-pill);
  border: none;
  background: var(--ocean);
  color: var(--white);
  font-weight: 600;
  box-shadow: var(--shadow-sm);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  line-height: 36px;
  vertical-align: middle;
  transition:
    background var(--dur-fast) var(--ease-out-expo),
    box-shadow var(--dur-fast) var(--ease-out-expo),
    transform var(--dur-fast) var(--ease-spring),
    color var(--dur-fast) var(--ease-out-expo);
}
.ingest:hover:not(:disabled) {
  background: var(--ocean-72);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px) scale(1.02);
}
.ingest:active:not(:disabled) { transform: scale(0.97); }
.ingest:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@keyframes dice-roll {
  0%   { transform: rotate(0deg); }
  15%  { transform: rotate(22deg); }
  35%  { transform: rotate(-18deg); }
  55%  { transform: rotate(12deg); }
  75%  { transform: rotate(-7deg); }
  90%  { transform: rotate(3deg); }
  100% { transform: rotate(0deg); }
}
.ingest-dice {
  flex-shrink: 0;
  display: block;
  margin-top: 1px;
}
.ingest--spinning .ingest-dice {
  animation: dice-roll 0.9s ease-in-out infinite;
  transform-origin: center;
}

/* ── Tabs：セグメンテッド風ガラスコントロール ── */
.tabs {
  display: flex;
  margin-top: 14px;
  position: relative;
  z-index: 1;
  padding: 4px 4px;
  gap: 2px;
  /* border-radius は glass から：var(--radius) */
}
.tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 20px;
  font-size: 14px;
  font-weight: 500;
  color: var(--text-muted);
  background: none;
  border: none;
  border-radius: calc(var(--radius) - 4px);
  cursor: pointer;
  transition:
    color var(--dur-fast) var(--ease-out-expo),
    background var(--dur-fast) var(--ease-out-expo),
    transform var(--dur-fast) var(--ease-spring),
    box-shadow var(--dur-fast) var(--ease-out-expo);
  position: relative;
}
.tab:hover {
  color: var(--ocean);
  background: rgba(255, 255, 255, 0.45);
  transform: scale(1.03);
}
.tab:active { transform: scale(0.94); }
.tab.active {
  color: var(--white);
  background: var(--ocean);
  font-weight: 700;
  box-shadow: 0 2px 8px rgba(4, 157, 191, 0.30);
}
.tab-badge {
  font-size: 11px;
  font-weight: 700;
  background: var(--red);
  color: var(--white);
  border-radius: var(--radius-pill);
  padding: 1px 6px;
  min-width: 18px;
  text-align: center;
}
.tab.active .tab-badge {
  background: var(--red);
  color: var(--white);
}

/* ── Quick-filter chips ── */
.density-btn {
  margin-left: auto;
  background: none;
  border: none;
  padding: 0 2px;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
  opacity: 0.6;
  transition:
    opacity var(--dur-fast) var(--ease-out-expo),
    color var(--dur-fast) var(--ease-out-expo),
    transform var(--dur-fast) var(--ease-spring);
}
.density-btn:hover {
  opacity: 1;
  color: var(--ocean);
  transform: scale(1.1);
}
.density-btn:active { transform: scale(0.9); }
.chip {
  font-size: 12px;
  font-weight: 500;
  padding: 4px 12px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--border);
  background: rgba(255, 255, 255, 0.50);
  color: var(--text-muted);
  cursor: pointer;
}
.chip:hover {
  border-color: var(--ocean);
  color: var(--ocean);
}
.chip.active {
  background: var(--ocean);
  border-color: var(--ocean);
  color: var(--white);
  font-weight: 600;
}

/* ── Main content ── */
.main {
  flex: 1;
  overflow: visible;
  margin-top: 16px;
  display: grid;
  grid-template-columns: 200px 1fr;
  gap: 0 28px;
  align-items: start;
  min-height: 0;
}

/* ── Sidebar ── */
.sidebar {
  position: sticky;
  top: 16px;
  border-right: 1px solid var(--border);
  padding-right: 16px;
}

.sidebar-toggle {
  display: flex;
  align-items: center;
  gap: 5px;
  background: none;
  border: none;
  padding: 4px 2px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  cursor: pointer;
  opacity: 0.6;
  margin-bottom: 4px;
  transition:
    opacity var(--dur-fast) var(--ease-out-expo),
    color var(--dur-fast) var(--ease-out-expo),
    transform var(--dur-fast) var(--ease-spring);
}
.sidebar-toggle:hover {
  opacity: 1;
  color: var(--ocean);
  transform: scale(1.05);
}
.sidebar-toggle:active { transform: scale(0.95); }

.sidebar-content {
  overflow: visible;
  transition: opacity 0.2s ease;
}

.main--collapsed {
  grid-template-columns: auto 1fr;
}
.main--collapsed .sidebar-content {
  display: none;
}
.main--collapsed .sidebar {
  width: auto;
  border-right: none;
  padding-right: 0;
}

.content {
  min-width: 0;
  height: 100%;
  overflow-y: auto;
  overflow-x: hidden;
  /* 右にスクロールバーが出るため，カードとバーの間に余白を多めに取る */
  padding: 6px 22px 48px 14px;
}

/* ── Scroll to top：白ガラス丸 + ocean ── */
.scroll-top-btn {
  position: fixed;
  bottom: 24px;
  right: 24px;
  width: 44px;
  height: 44px;
  border-radius: 50% !important;
  border: none;
  color: var(--ocean);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  z-index: 500;
  transition:
    background var(--dur-fast) var(--ease-out-expo),
    color var(--dur-fast) var(--ease-out-expo),
    transform var(--dur-fast) var(--ease-spring),
    box-shadow var(--dur-fast) var(--ease-out-expo);
}
.scroll-top-btn:hover {
  background: var(--ocean) !important;
  color: var(--white);
  transform: translateY(-2px) scale(1.1);
  box-shadow: 0 6px 20px rgba(4, 157, 191, 0.30);
}
.scroll-top-btn:active { transform: scale(0.9); }
.scroll-top-enter-active, .scroll-top-leave-active {
  transition: opacity var(--dur-fast) var(--ease-standard), transform var(--dur-fast) var(--ease-standard);
}
.scroll-top-enter-from, .scroll-top-leave-to {
  opacity: 0;
  transform: translateY(10px);
}

/* ── Stats row：不透明な白バー（フロスト・影による境界を排除） ── */
.stats-row {
  display: flex;
  align-items: center;
  gap: 12px;
  height: 50px;
  position: sticky;
  top: 0;
  z-index: 5;
  border-radius: var(--radius) !important;
  margin: 0 0 8px;
  padding: 10px 16px;
}
.stats-row.glass {
  background: var(--white);
  -webkit-backdrop-filter: none;
  backdrop-filter: none;
  /* カードと同じ縁幅で揃える（縁の有無による段差をなくす） */
  border: 4px solid var(--sage);
  box-shadow: none;
}
.stats-row.glass::after {
  display: none;
}
.stats-row .density-btn {
  margin-left: auto;
}

.stat-selected {
  color: var(--ocean);
}

.select-all-wrap {
  display: flex;
  align-items: center;
  cursor: pointer;
  flex-shrink: 0;
}
.select-all-check {
  width: 15px;
  height: 15px;
  accent-color: var(--ocean);
  cursor: pointer;
}

/* ── Bulk buttons ── */
.bulk-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 500;
  height: 26px;
  padding: 0 11px;
  border-radius: var(--radius-pill);
  border: 1.5px solid var(--border);
  background: rgba(255, 255, 255, 0.60);
  color: var(--ocean);
  cursor: pointer;
  transition:
    border-color var(--dur-fast) var(--ease-out-expo),
    color var(--dur-fast) var(--ease-out-expo),
    background var(--dur-fast) var(--ease-out-expo),
    transform var(--dur-fast) var(--ease-spring),
    box-shadow var(--dur-fast) var(--ease-out-expo);
  white-space: nowrap;
}
.bulk-btn:hover {
  border-color: var(--ocean);
  background: var(--ocean);
  color: var(--white);
  transform: translateY(-1px) scale(1.03);
  box-shadow: 0 3px 10px rgba(4, 157, 191, 0.22);
}
.bulk-btn:active { transform: scale(0.94); }
/* ocean（デフォルト＝アーカイブ・未対応） */
.bulk-btn--ocean { color: var(--ocean); border-color: var(--ocean); background: var(--ocean-12); }
.bulk-btn--ocean:hover { background: var(--ocean); color: var(--white); }
/* sand（対応中） */
.bulk-btn--sand { color: var(--ocean); border-color: var(--sand); background: var(--sand-weak); }
.bulk-btn--sand:hover { background: var(--sand); color: var(--ocean); border-color: var(--sand); }
/* leaf（完了） */
.bulk-btn--leaf { color: var(--ocean); border-color: var(--leaf); background: var(--leaf-weak); }
.bulk-btn--leaf:hover { background: var(--leaf); color: var(--white); border-color: var(--leaf); }
/* sage（保留・受信トレイに戻す） */
.bulk-btn--sage { color: var(--mauve); border-color: var(--mauve); background: var(--mauve-weak); }
.bulk-btn--sage:hover { background: var(--mauve); color: var(--white); border-color: var(--mauve); }
/* clear（キャンセル） */
.bulk-btn--clear { color: var(--text-muted); border-color: transparent; background: none; }
.bulk-btn--clear:hover { color: var(--ocean); border-color: var(--ocean); background: var(--ocean-12); }

/* ── Stat items ── */
.stat {
  display: flex;
  align-items: baseline;
  gap: 4px;
}
.stat-value {
  font-size: 18px;
  font-weight: 700;
  color: var(--ocean);
  line-height: 1;
}
.stat-label {
  font-size: 11px;
  color: var(--text-muted);
  font-weight: 500;
}

/* stat-btn：ベース */
.stat-btn {
  background: none;
  border: 1.5px solid transparent;
  border-radius: var(--radius-sm);
  padding: 3px 7px;
  cursor: pointer;
  margin: -3px -7px;
  transition:
    border-color var(--dur-fast) var(--ease-out-expo),
    background var(--dur-fast) var(--ease-out-expo),
    transform var(--dur-fast) var(--ease-spring),
    box-shadow var(--dur-fast) var(--ease-out-expo);
}
.stat-btn:hover {
  border-color: var(--border);
  background: rgba(255, 255, 255, 0.45);
  transform: scale(1.04);
}
.stat-btn:active { transform: scale(0.94); }
/* 選択時のポップ */
.stat-btn--active {
  animation: stat-pop var(--dur-fast) var(--ease-spring);
}
@keyframes stat-pop {
  0%   { transform: scale(1); }
  50%  { transform: scale(1.08); }
  100% { transform: scale(1); }
}

/* 未対応ヒーロー stat */
.stat-btn--hero-on .stat-value {
  color: var(--red);
}
.stat-btn--hero.stat-btn--active {
  border-color: var(--red) !important;
  background: var(--red-12) !important;
}
.stat-btn--hero.stat-btn--active .stat-value,
.stat-btn--hero.stat-btn--active .stat-label {
  color: var(--red);
}

/* stat-btn：状態別（常に ocean 文字・枠と地で色を示す） */
.stat-btn--active {
  border-color: var(--ocean) !important;
  background: var(--ocean-12) !important;
}
.stat-btn--active .stat-value,
.stat-btn--active .stat-label {
  color: var(--ocean);
}
/* sand（対応中）— amber */
.stat-btn--sand .stat-value {
  color: #C88A00;
}
.stat-btn--sand.stat-btn--active {
  border-color: var(--sand) !important;
  background: var(--sand-weak) !important;
}
.stat-btn--sand.stat-btn--active .stat-value,
.stat-btn--sand.stat-btn--active .stat-label {
  color: #C88A00;
}
/* leaf（完了） */
.stat-btn--leaf.stat-btn--active {
  border-color: var(--leaf) !important;
  background: var(--leaf-weak) !important;
}
/* mauve（保留） */
.stat-btn--sage .stat-value {
  color: var(--mauve);
}
.stat-btn--sage.stat-btn--active {
  border-color: var(--mauve) !important;
  background: var(--mauve-weak) !important;
}
.stat-btn--sage.stat-btn--active .stat-value,
.stat-btn--sage.stat-btn--active .stat-label {
  color: var(--mauve);
}
/* 期限切れ（ocean 塗り反転＝最強シグナル） */
.stat-btn--overdue-active {
  border-color: var(--red) !important;
}
.stat-btn--overdue-active .stat-value {
  color: var(--red);
  font-weight: 800;
}
.stat-btn--overdue.stat-btn--active {
  background: var(--red) !important;
  border-color: var(--red) !important;
}
.stat-btn--overdue.stat-btn--active .stat-value,
.stat-btn--overdue.stat-btn--active .stat-label {
  color: var(--white);
}

.stat-sep {
  width: 1px;
  height: 16px;
  background: var(--border);
  flex-shrink: 0;
}

/* ── Banner：ガラス化 ── */
.banner {
  padding: 10px 14px;
  border-radius: var(--radius) !important;
  margin-bottom: 12px;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  color: var(--ocean);
}
.banner--success {
  border: 1.5px solid var(--leaf);
}
.banner--warn {
  border: 1.5px solid var(--red);
}
.banner button {
  margin-left: auto;
  background: transparent;
  border: 1.5px solid var(--ocean);
  border-radius: var(--radius-sm);
  padding: 2px 8px;
  cursor: pointer;
  font-size: 12px;
  color: var(--ocean);
  font-weight: 600;
  transition: background 0.12s, color 0.12s;
}
.banner button:hover {
  background: var(--ocean);
  color: var(--white);
}

/* ── Empty state：ガラスパネル ── */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 56px 0 48px;
  text-align: center;
}
.empty-panel {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  padding: 40px 48px;
  border-radius: var(--radius-lg) !important;
  max-width: 360px;
  width: 100%;
}
.empty-illustration {
  width: 120px;
  height: 120px;
  opacity: 0.9;
}
@keyframes dice-spin-anim {
  0%   { transform: rotate(0deg); }
  20%  { transform: rotate(20deg); }
  40%  { transform: rotate(-15deg); }
  60%  { transform: rotate(10deg); }
  80%  { transform: rotate(-5deg); }
  100% { transform: rotate(0deg); }
}
.dice-spin {
  animation: dice-spin-anim 1.1s ease-in-out infinite;
  transform-origin: center;
}
@media (prefers-reduced-motion: reduce) {
  .dice-spin { animation: none !important; }
}
.empty-label {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--ocean);
}
.empty-sub {
  margin: 0;
  font-size: 13px;
  color: var(--text-muted);
  opacity: 0.7;
}
.empty-clear-btn {
  font-size: 13px;
  font-weight: 600;
  padding: 6px 16px;
  border-radius: var(--radius-pill);
  border: 1.5px solid var(--border);
  background: rgba(255, 255, 255, 0.60);
  color: var(--ocean);
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.empty-clear-btn:hover {
  border-color: var(--ocean);
  background: var(--ocean-12);
}
.btn-add-account {
  font-size: 13px;
  font-weight: 600;
  padding: 8px 20px;
  border-radius: var(--radius-pill);
  border: none;
  background: var(--ocean);
  color: var(--white);
  cursor: pointer;
  box-shadow: var(--shadow-md);
  transition: background var(--dur-base) var(--ease-standard), box-shadow var(--dur-base) var(--ease-standard), transform var(--dur-base) var(--ease-standard);
}
.btn-add-account:hover {
  background: var(--ocean-72);
  box-shadow: var(--shadow-lg);
}

/* ── メッセージリスト：FLIP + stagger ── */
.list {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
}

/* TransitionGroup FLIP（ゆっくり浮き出てくる＝ヌルヌル） */
.list-move {
  transition: transform 480ms var(--ease-out-expo);
}
.list--no-move .list-move {
  transition: none;
}
.list-enter-active {
  transition: opacity 480ms var(--ease-out-expo), transform 1333ms var(--ease-spring);
}
.list-leave-active {
  transition: opacity 200ms var(--ease-out-expo), transform 200ms var(--ease-out-expo);
}
.list-enter-from {
  opacity: 0;
  transform: translateY(23px) scale(0.96);
}
.list-leave-to {
  opacity: 0;
  transform: scale(0.97);
}

/* stagger：--i CSS 変数で出現を遅延（ゆったり順番に） */
.list-enter-active {
  transition-delay: calc(var(--i, 0) * 90ms);
}

@media (prefers-reduced-motion: reduce) {
  .list-move,
  .list-enter-active,
  .list-leave-active {
    transition: none !important;
  }
}

/* ── Shortcuts modal：ガラス化 ── */
.shortcuts-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(4, 157, 191, 0.12);
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  backdrop-filter: blur(4px);
}
.shortcuts-modal {
  border-radius: var(--radius) !important;
  width: 380px;
  max-width: calc(100vw - 32px);
  overflow: hidden;
}
.shortcuts-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px 12px;
  border-bottom: 1px solid var(--border);
}
.shortcuts-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--ocean);
}
.shortcuts-close {
  background: none;
  border: none;
  padding: 4px;
  color: var(--text-muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  border-radius: var(--radius-sm);
  transition:
    color var(--dur-fast) var(--ease-out-expo),
    background var(--dur-fast) var(--ease-out-expo),
    transform var(--dur-fast) var(--ease-spring);
}
.shortcuts-close:hover {
  color: var(--ocean);
  background: rgba(228, 235, 242, 0.60);
  transform: scale(1.15);
}
.shortcuts-close:active { transform: scale(0.9); }

.shortcuts-body {
  padding: 12px 16px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.shortcuts-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.shortcuts-section-title {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: var(--text-muted);
  margin-bottom: 2px;
}
.shortcuts-divider {
  height: 1px;
  background: var(--border);
}
.shortcut-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-muted);
}
.shortcut-row span {
  flex: 1;
}
kbd {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 22px;
  padding: 2px 6px;
  font-size: 11px;
  font-family: inherit;
  font-weight: 600;
  color: var(--ocean);
  background: rgba(228, 235, 242, 0.70);
  border: 1px solid var(--border);
  border-bottom-width: 2px;
  border-radius: 4px;
  white-space: nowrap;
}

/* Modal transition */
.modal-enter-active, .modal-leave-active {
  transition: opacity 0.18s ease;
}
.modal-enter-active .shortcuts-modal,
.modal-leave-active .shortcuts-modal {
  transition: transform 0.18s var(--ease-spring), opacity 0.18s ease;
}
.modal-enter-from, .modal-leave-to { opacity: 0; }
.modal-enter-from .shortcuts-modal { transform: scale(0.93); opacity: 0; }
.modal-leave-to .shortcuts-modal   { transform: scale(0.96); opacity: 0; }
</style>
