<script setup lang="ts">
import { computed } from "vue";
import type { MessagesQuery } from "../api";
import type { AccountConfig } from "../types";

const props = defineProps<{
  modelValue: MessagesQuery;
  providers: string[];
  accounts: AccountConfig[];
  sourceChip: string | null;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: MessagesQuery];
  "update:sourceChip": [value: string | null];
}>();

function patch(updates: Partial<MessagesQuery>): void {
  emit("update:modelValue", { ...props.modelValue, ...updates });
}

// --- Sort ---
type SortOption = { order_by: NonNullable<MessagesQuery["order_by"]>; descending: boolean; label: string };
const SORT_OPTIONS: SortOption[] = [
  { order_by: "triage_score", descending: true,  label: "推奨度" },
  { order_by: "importance",   descending: true,  label: "重要度（高い順）" },
  { order_by: "importance",   descending: false, label: "重要度（低い順）" },
  { order_by: "received_at",  descending: true,  label: "受信日時（新しい順）" },
  { order_by: "received_at",  descending: false, label: "受信日時（古い順）" },
];

const sortValue = computed(() => {
  const ob = props.modelValue.order_by ?? "triage_score";
  const desc = props.modelValue.descending ?? true;
  return `${ob}:${desc}`;
});

function setSort(e: Event): void {
  const [order_by, descStr] = (e.target as HTMLSelectElement).value.split(":");
  patch({ order_by: order_by as MessagesQuery["order_by"], descending: descStr === "true" });
}

// --- Importance ---
const IMPORTANCE_OPTIONS: Array<{ value: number; label: string }> = [
  { value: 0, label: "すべて" },
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

// --- Active filter count (sort 除く) ---
const activeFilterCount = computed<number>(() => {
  let n = 0;
  const q = props.modelValue;
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

</script>

<template>
  <div class="filter-bar">
    <template v-if="accounts.length > 1">
      <div class="section-label">アカウント</div>
      <div class="account-chips">
        <button
          v-for="acc in accounts"
          :key="acc.id"
          type="button"
          class="account-chip"
          :class="[`account-chip--${acc.provider.toLowerCase()}`, { active: sourceChip === acc.provider.toLowerCase() }]"
          @click="emit('update:sourceChip', sourceChip === acc.provider.toLowerCase() ? null : acc.provider.toLowerCase())"
        >
          {{ acc.label || acc.provider }}
        </button>
      </div>
      <div class="divider" />
    </template>

    <div class="section-label">並べ替え</div>
    <select class="ctrl-select" :value="sortValue" @change="setSort">
      <option
        v-for="opt in SORT_OPTIONS"
        :key="`${opt.order_by}:${opt.descending}`"
        :value="`${opt.order_by}:${opt.descending}`"
      >{{ opt.label }}</option>
    </select>

    <div class="divider" />

    <div class="section-label">
      フィルター
      <span class="filter-badge" :style="{ visibility: activeFilterCount > 0 ? 'visible' : 'hidden' }">{{ activeFilterCount }}</span>
      <button
        type="button"
        class="clear-btn"
        :style="{ visibility: activeFilterCount > 0 ? 'visible' : 'hidden' }"
        :disabled="activeFilterCount === 0"
        @click="clearFilters"
      >クリア</button>
    </div>

    <div class="filter-group">
      <label class="group-label" for="importance-select">重要度</label>
      <select
        id="importance-select"
        class="ctrl-select"
        :value="modelValue.importance_min ?? 0"
        @change="setImportanceMin"
      >
        <option v-for="opt in IMPORTANCE_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
      </select>
    </div>

    <div class="filter-group">
      <span class="group-label">受信日時（from）</span>
      <input
        type="date"
        class="date-input"
        aria-label="受信日時（from）"
        :value="toDateInput(modelValue.received_after)"
        @change="setReceivedAfter"
      />
      <span class="group-label" style="margin-top:4px">受信日時（to）</span>
      <input
        type="date"
        class="date-input"
        aria-label="受信日時（to）"
        :value="toDateInput(modelValue.received_before)"
        @change="setReceivedBefore"
      />
    </div>

    <div class="filter-group">
      <label class="check-item">
        <input type="checkbox" :checked="modelValue.unread_only ?? false" @change="setUnreadOnly" />
        未読のみ
      </label>
    </div>

  </div>
</template>

<style scoped>
.filter-bar {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-top: 8px;
}

.section-label {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 6px;
}

.divider {
  height: 1px;
  background: var(--border);
  margin: 2px 0;
}

.filter-badge {
  font-size: 11px;
  font-weight: 700;
  background: var(--brand-blue);
  color: #fff;
  border-radius: var(--radius-pill);
  padding: 1px 6px;
  min-width: 18px;
  text-align: center;
}

.filter-group {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.group-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
}

.ctrl-select,
.date-input {
  font-size: 12px;
  padding: 5px 7px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--snow-surface);
  color: var(--text);
  width: 100%;
}

.check-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  cursor: pointer;
  user-select: none;
}
.check-item input[type="checkbox"] {
  accent-color: var(--brand-blue);
  width: 14px;
  height: 14px;
  cursor: pointer;
}

.clear-btn {
  font-size: 11px;
  padding: 0;
  border: none;
  background: none;
  color: var(--text-muted);
  display: inline-flex;
  align-items: center;
  margin-left: auto;
  text-decoration: underline;
  text-underline-offset: 2px;
  font-weight: 600;
  letter-spacing: 0.04em;
}
.clear-btn:hover:not(:disabled) {
  color: var(--danger);
}
.clear-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.account-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.account-chip {
  font-size: 12px;
  font-weight: 500;
  padding: 3px 10px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--border);
  background: var(--snow-surface);
  color: var(--text-muted);
  cursor: pointer;
}
.account-chip:hover {
  border-color: currentColor;
  opacity: 0.85;
}

/* Gmail — red */
.account-chip--gmail { --svc: #EA4335; }
/* Slack — purple */
.account-chip--slack { --svc: #4A154B; }
/* fallback */
.account-chip--gmail,
.account-chip--slack {
  border-color: var(--svc);
  color: var(--svc);
  background: color-mix(in srgb, var(--svc) 8%, transparent);
}
.account-chip--gmail.active,
.account-chip--slack.active {
  background: var(--svc);
  color: #fff;
  font-weight: 600;
}
</style>
