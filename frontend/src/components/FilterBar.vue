<script setup lang="ts">
import { computed, ref } from "vue";
import type { MessagesQuery } from "../api";
import type { AccountConfig } from "../types";

const props = defineProps<{
  modelValue: MessagesQuery;
  providers: string[];
  accounts: AccountConfig[];
}>();

const emit = defineEmits<{
  "update:modelValue": [value: MessagesQuery];
}>();

const expanded = ref(false);

function patch(updates: Partial<MessagesQuery>): void {
  emit("update:modelValue", { ...props.modelValue, ...updates });
}

// --- Sort ---
const ORDER_BY_OPTIONS: Array<{ value: NonNullable<MessagesQuery["order_by"]>; label: string }> = [
  { value: "triage_score", label: "推奨度" },
  { value: "received_at", label: "受信日時" },
  { value: "importance", label: "重要度" },
];

function setOrderBy(e: Event): void {
  patch({ order_by: (e.target as HTMLSelectElement).value as MessagesQuery["order_by"] });
}

function toggleDescending(): void {
  patch({ descending: !(props.modelValue.descending ?? true) });
}

// --- Providers ---
// undefined = フィルターなし（全選択と同等）, [] = 明示的に全解除（0件）
function isChecked(p: string): boolean {
  const ps = props.modelValue.providers;
  if (ps === undefined) return true;
  return ps.includes(p);
}

function toggleProvider(p: string): void {
  const current = props.modelValue.providers;
  const all = props.providers;
  if (current === undefined) {
    // 未設定（全表示）→ 1つ外す → 他を明示選択
    const next = all.filter((x) => x !== p);
    patch({ providers: next });
  } else if (current.includes(p)) {
    const next = current.filter((x) => x !== p);
    // 全部外れたら [] = 明示的に何も表示しない（undefined にしない）
    patch({ providers: next });
  } else {
    const next = [...current, p];
    // 全プロバイダが揃ったら undefined（= フィルターなし）に戻す
    patch({ providers: next.length >= all.length ? undefined : next });
  }
}

// --- Importance ---
const IMPORTANCE_OPTIONS: Array<{ value: number; label: string }> = [
  { value: 0, label: "すべて" },
  { value: 1, label: "1以上" },
  { value: 2, label: "2以上" },
  { value: 3, label: "3以上" },
  { value: 4, label: "4以上" },
  { value: 5, label: "5のみ" },
];

function setImportanceMin(e: Event): void {
  const n = Number((e.target as HTMLSelectElement).value);
  patch({ importance_min: n > 0 ? n : undefined });
}

// --- Dates ---
function toDateInput(iso: string | undefined): string {
  return iso ? iso.slice(0, 10) : "";
}

function setReceivedAfter(e: Event): void {
  const v = (e.target as HTMLInputElement).value;
  patch({ received_after: v ? `${v}T00:00:00Z` : undefined });
}

function setReceivedBefore(e: Event): void {
  const v = (e.target as HTMLInputElement).value;
  patch({ received_before: v ? `${v}T23:59:59Z` : undefined });
}

// --- Unread only ---
function setUnreadOnly(e: Event): void {
  const checked = (e.target as HTMLInputElement).checked;
  patch({ unread_only: checked || undefined });
}

// --- Accounts ---
function isAccountChecked(address: string): boolean {
  const as = props.modelValue.account_addresses;
  if (as === undefined) return true;
  return as.includes(address);
}

function toggleAccount(address: string): void {
  const current = props.modelValue.account_addresses;
  const allAddresses = props.accounts.map((a) => a.address);
  if (current === undefined) {
    const next = allAddresses.filter((x) => x !== address);
    patch({ account_addresses: next });
  } else if (current.includes(address)) {
    const next = current.filter((x) => x !== address);
    patch({ account_addresses: next });
  } else {
    const next = [...current, address];
    patch({ account_addresses: next.length >= allAddresses.length ? undefined : next });
  }
}

// --- Active filter count (sort 除く) ---
const activeFilterCount = computed<number>(() => {
  let n = 0;
  const q = props.modelValue;
  if (q.providers !== undefined) n++;
  if (q.account_addresses !== undefined) n++;
  if (q.importance_min && q.importance_min > 0) n++;
  if (q.received_after) n++;
  if (q.received_before) n++;
  if (q.unread_only) n++;
  return n;
});

function clearFilters(): void {
  emit("update:modelValue", {
    archived: props.modelValue.archived,
    order_by: props.modelValue.order_by,
    descending: props.modelValue.descending,
  });
}

function capitalize(s: string): string {
  return s.length === 0 ? s : s.charAt(0).toUpperCase() + s.slice(1);
}
</script>

<template>
  <div class="filter-bar">
    <!-- ソートコントロール（常時表示） -->
    <div class="sort-row">
      <div class="sort-controls">
        <label class="ctrl-label" for="sort-select">並べ替え</label>
        <select
          id="sort-select"
          class="ctrl-select"
          :value="modelValue.order_by ?? 'triage_score'"
          @change="setOrderBy"
        >
          <option
            v-for="opt in ORDER_BY_OPTIONS"
            :key="opt.value"
            :value="opt.value"
          >{{ opt.label }}</option>
        </select>
        <button
          type="button"
          class="dir-btn"
          :aria-label="(modelValue.descending ?? true) ? '降順（クリックで昇順に変更）' : '昇順（クリックで降順に変更）'"
          @click="toggleDescending"
        >
          {{ (modelValue.descending ?? true) ? "↓" : "↑" }}
        </button>
      </div>
      <button
        type="button"
        class="filter-toggle-btn"
        :aria-expanded="expanded ? 'true' : 'false'"
        @click="expanded = !expanded"
      >
        フィルター
        <span
          v-if="activeFilterCount > 0"
          class="filter-badge"
          :aria-label="`${activeFilterCount}件のフィルター適用中`"
        >{{ activeFilterCount }}</span>
      </button>
    </div>

    <!-- フィルターパネル（折りたたみ） -->
    <div
      v-if="expanded"
      class="filter-panel"
      role="group"
      aria-label="フィルター条件"
    >
      <!-- プロバイダ -->
      <div v-if="providers.length > 0" class="filter-group">
        <span class="group-label">アプリ</span>
        <div class="checkbox-row">
          <label
            v-for="p in providers"
            :key="p"
            class="check-item"
          >
            <input
              type="checkbox"
              :checked="isChecked(p)"
              @change="toggleProvider(p)"
            />
            {{ capitalize(p) }}
          </label>
        </div>
      </div>

      <!-- アカウント -->
      <div v-if="accounts.length > 0" class="filter-group">
        <span class="group-label">アカウント</span>
        <div class="checkbox-row">
          <label
            v-for="ac in accounts"
            :key="ac.id"
            class="check-item"
          >
            <input
              type="checkbox"
              :checked="isAccountChecked(ac.address)"
              @change="toggleAccount(ac.address)"
            />
            {{ ac.label }}
          </label>
        </div>
      </div>

      <!-- 重要度 -->
      <div class="filter-group">
        <label class="group-label" for="importance-select">重要度（最低）</label>
        <select
          id="importance-select"
          class="ctrl-select"
          :value="modelValue.importance_min ?? 0"
          @change="setImportanceMin"
        >
          <option
            v-for="opt in IMPORTANCE_OPTIONS"
            :key="opt.value"
            :value="opt.value"
          >{{ opt.label }}</option>
        </select>
      </div>

      <!-- 受信日時（from / to） -->
      <div class="filter-group">
        <span class="group-label">受信日時</span>
        <div class="date-range">
          <input
            type="date"
            class="date-input"
            aria-label="受信日時（from）"
            :value="toDateInput(modelValue.received_after)"
            @change="setReceivedAfter"
          />
          <span class="date-sep" aria-hidden="true">〜</span>
          <input
            type="date"
            class="date-input"
            aria-label="受信日時（to）"
            :value="toDateInput(modelValue.received_before)"
            @change="setReceivedBefore"
          />
        </div>
      </div>

      <!-- 未読のみ -->
      <div class="filter-group">
        <label class="check-item">
          <input
            type="checkbox"
            :checked="modelValue.unread_only ?? false"
            @change="setUnreadOnly"
          />
          未読のみ
        </label>
      </div>

      <!-- クリア -->
      <div class="filter-actions">
        <button
          type="button"
          class="clear-btn"
          :disabled="activeFilterCount === 0"
          @click="clearFilters"
        >
          フィルタークリア
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.filter-bar {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 8px 12px;
  margin-bottom: 12px;
}

.sort-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.sort-controls {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
}

.ctrl-label,
.group-label {
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
}

.ctrl-select {
  font-size: 13px;
  padding: 4px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg);
  color: var(--text);
}

.dir-btn {
  font-size: 14px;
  width: 30px;
  height: 28px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--text);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.1s;
}

.dir-btn:hover {
  background: var(--bg);
}

.filter-toggle-btn {
  font-size: 13px;
  padding: 4px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--text);
  display: flex;
  align-items: center;
  gap: 6px;
  transition: background 0.1s;
}

.filter-toggle-btn:hover {
  background: var(--bg);
}

.filter-badge {
  font-size: 11px;
  font-weight: 700;
  background: var(--accent);
  color: #fff;
  border-radius: 999px;
  padding: 1px 6px;
  min-width: 16px;
  text-align: center;
}

.filter-panel {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  align-items: flex-start;
}

.filter-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.checkbox-row {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 16px;
}

.check-item {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 13px;
  cursor: pointer;
  user-select: none;
}

.check-item input[type="checkbox"] {
  accent-color: var(--accent);
  width: 14px;
  height: 14px;
  cursor: pointer;
}

.date-range {
  display: flex;
  align-items: center;
  gap: 6px;
}

.date-input {
  font-size: 13px;
  padding: 4px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg);
  color: var(--text);
}

.date-sep {
  color: var(--text-muted);
  font-size: 13px;
}

.filter-actions {
  margin-left: auto;
  display: flex;
  align-items: flex-end;
}

.clear-btn {
  font-size: 12px;
  padding: 4px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--text-muted);
  transition: background 0.1s, color 0.1s, border-color 0.1s;
}

.clear-btn:hover:not(:disabled) {
  background: var(--danger-weak);
  color: var(--danger);
  border-color: var(--danger);
}

.clear-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>
