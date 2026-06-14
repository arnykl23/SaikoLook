<script setup lang="ts">
import { computed, ref } from "vue";
import type { MessagesQuery } from "../api";
import type { AccountConfig } from "../types";

// ────────────────────────────────────────────────────────
// Props / Emits
// ────────────────────────────────────────────────────────
const props = defineProps<{
  modelValue: MessagesQuery;
  providers: string[];
  accounts: AccountConfig[];
  selectedAccounts: string[];
}>();

const emit = defineEmits<{
  "update:modelValue": [value: MessagesQuery];
  "toggle-account": [address: string];
}>();

function patch(updates: Partial<MessagesQuery>): void {
  emit("update:modelValue", { ...props.modelValue, ...updates });
}

// ────────────────────────────────────────────────────────
// §1 並べ替え — セグメンテッドコントロール
// ────────────────────────────────────────────────────────
type SortColumn = "triage_score" | "importance" | "received_at";

interface SortSegment {
  order_by: SortColumn;
  label: string;
  ariaLabel: string;
}

const SORT_SEGMENTS: SortSegment[] = [
  { order_by: "triage_score", label: "推奨度",   ariaLabel: "推奨度で並べ替え" },
  { order_by: "importance",   label: "重要度",   ariaLabel: "重要度で並べ替え" },
  { order_by: "received_at",  label: "受信日時", ariaLabel: "受信日時で並べ替え" },
];

const sortColumn = computed<SortColumn>(() =>
  (props.modelValue.order_by as SortColumn | undefined) ?? "triage_score"
);
const sortDesc = computed<boolean>(() => props.modelValue.descending ?? true);

function selectSortColumn(col: SortColumn): void {
  if (sortColumn.value === col) {
    // 同じ列をクリック → 昇降を反転
    patch({ order_by: col, descending: !sortDesc.value });
  } else {
    // 新しい列 → 降順をデフォルト
    patch({ order_by: col, descending: true });
  }
}

function toggleSortDir(): void {
  patch({ descending: !sortDesc.value });
}

function sortSegmentKeydown(e: KeyboardEvent, col: SortColumn, idx: number): void {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    selectSortColumn(col);
  } else if (e.key === "ArrowRight") {
    e.preventDefault();
    const next = SORT_SEGMENTS[(idx + 1) % SORT_SEGMENTS.length];
    selectSortColumn(next.order_by);
    // フォーカス移動
    const btns = sortGroupRef.value?.querySelectorAll<HTMLButtonElement>(".sort-btn");
    btns?.[(idx + 1) % SORT_SEGMENTS.length]?.focus();
  } else if (e.key === "ArrowLeft") {
    e.preventDefault();
    const prev = SORT_SEGMENTS[(idx - 1 + SORT_SEGMENTS.length) % SORT_SEGMENTS.length];
    selectSortColumn(prev.order_by);
    const btns = sortGroupRef.value?.querySelectorAll<HTMLButtonElement>(".sort-btn");
    btns?.[(idx - 1 + SORT_SEGMENTS.length) % SORT_SEGMENTS.length]?.focus();
  }
}

const sortGroupRef = ref<HTMLElement | null>(null);

// ────────────────────────────────────────────────────────
// §2 重要度しきい値 — サイコロ1〜5タップ
// ────────────────────────────────────────────────────────

// pip positions for dice faces 1-6 (within 20x20 viewBox)
interface Pip { cx: number; cy: number }
const DICE_PIPS: Record<number, Pip[]> = {
  1: [{ cx: 10, cy: 10 }],
  2: [{ cx: 5.5, cy: 5.5 }, { cx: 14.5, cy: 14.5 }],
  3: [{ cx: 5.5, cy: 5.5 }, { cx: 10, cy: 10 }, { cx: 14.5, cy: 14.5 }],
  4: [{ cx: 5.5, cy: 5.5 }, { cx: 14.5, cy: 5.5 }, { cx: 5.5, cy: 14.5 }, { cx: 14.5, cy: 14.5 }],
  5: [{ cx: 5.5, cy: 5.5 }, { cx: 14.5, cy: 5.5 }, { cx: 10, cy: 10 }, { cx: 5.5, cy: 14.5 }, { cx: 14.5, cy: 14.5 }],
  6: [
    { cx: 5.5, cy: 5 }, { cx: 5.5, cy: 10 }, { cx: 5.5, cy: 15 },
    { cx: 14.5, cy: 5 }, { cx: 14.5, cy: 10 }, { cx: 14.5, cy: 15 },
  ],
};

// 表示順：左ほど高い重要度（降順）．後で 6 を分析側に追加予定
const IMPORTANCE_FACES = [6, 5, 4, 3, 2, 1];

const importanceMin = computed<number>(() => props.modelValue.importance_min ?? 0);

function setImportanceMin(val: number): void {
  patch({ importance_min: val > 0 ? val : undefined });
}

// 並びに依存しない（DOM 兄弟でフォーカス移動）キーボード操作
function diceKeydown(e: KeyboardEvent, face: number): void {
  const btn = e.currentTarget as HTMLElement;
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    setImportanceMin(importanceMin.value === face ? 0 : face);
  } else if (e.key === "ArrowRight" || e.key === "ArrowDown") {
    e.preventDefault();
    (btn.nextElementSibling as HTMLElement | null)?.focus();
  } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
    e.preventDefault();
    (btn.previousElementSibling as HTMLElement | null)?.focus();
  }
}

const diceFocusRef = ref<HTMLElement | null>(null);

// ────────────────────────────────────────────────────────
// §3 受信日時 — インライン date input
// ────────────────────────────────────────────────────────
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

// ────────────────────────────────────────────────────────
// §4 未読のみ — トグルチップ（role="switch"）
// ────────────────────────────────────────────────────────
const unreadOnly = computed<boolean>(() => props.modelValue.unread_only ?? false);

function toggleUnreadOnly(): void {
  patch({ unread_only: unreadOnly.value ? undefined : true });
}

// ────────────────────────────────────────────────────────
// §5 アカウント source — マルチセレクトチップ
// ────────────────────────────────────────────────────────
function toggleAccount(address: string): void {
  emit("toggle-account", address);
}
function isAccountSelected(address: string): boolean {
  return props.selectedAccounts.includes(address);
}

// プロバイダ表示名
const PROVIDER_NAMES: Record<string, string> = {
  gmail: "Gmail",
  github: "GitHub",
  slack: "Slack",
  outlook: "Outlook",
};

// アカウントをプロバイダ（アプリ）ごとにグループ化
const groupedAccounts = computed(() => {
  const groups = new Map<string, { provider: string; name: string; accounts: AccountConfig[] }>();
  for (const acc of props.accounts) {
    const key = acc.provider.toLowerCase();
    if (!groups.has(key)) {
      groups.set(key, { provider: key, name: PROVIDER_NAMES[key] ?? acc.provider, accounts: [] });
    }
    groups.get(key)!.accounts.push(acc);
  }
  return [...groups.values()];
});

// ────────────────────────────────────────────────────────
// §6 サマリーバー / クリア
// ────────────────────────────────────────────────────────
</script>

<template>
  <div class="filter-bar">

    <!-- ══════════════════════════════
         §1 並べ替え — セグメンテッドコントロール
         ══════════════════════════════ -->
    <section class="filter-section" aria-labelledby="sort-label">
      <div class="sort-header">
        <div id="sort-label" class="section-label">並べ替え</div>
        <!-- 昇降トグル（「並べ替え」ラベルの右隣） -->
        <button
          type="button"
          class="dir-toggle"
          :aria-label="sortDesc ? '昇順に切り替え' : '降順に切り替え'"
          :title="sortDesc ? '昇順に切り替え' : '降順に切り替え'"
          @click="toggleSortDir"
        >
          <span :class="sortDesc ? 'dir-icon--desc' : 'dir-icon--asc'" aria-hidden="true">
            {{ sortDesc ? "↓" : "↑" }}
          </span>
          <span class="dir-toggle-label">{{ sortDesc ? "降順" : "昇順" }}</span>
        </button>
      </div>
      <div
        ref="sortGroupRef"
        class="segment-group"
        role="group"
        aria-label="並べ替え列の選択"
      >
        <button
          v-for="(seg, idx) in SORT_SEGMENTS"
          :key="seg.order_by"
          type="button"
          class="sort-btn"
          :class="{ 'sort-btn--active': sortColumn === seg.order_by }"
          :aria-pressed="sortColumn === seg.order_by"
          :aria-label="seg.ariaLabel + (sortColumn === seg.order_by ? (sortDesc ? '降順' : '昇順') : '')"
          :tabindex="sortColumn === seg.order_by || (idx === 0 && !SORT_SEGMENTS.some((s, i) => i !== idx && sortColumn === s.order_by)) ? 0 : -1"
          @click="selectSortColumn(seg.order_by)"
          @keydown="sortSegmentKeydown($event, seg.order_by, idx)"
        >
          {{ seg.label }}
        </button>
      </div>
    </section>

    <!-- ══════════════════════════════
         アカウント — アプリ（プロバイダ）ごとにグループ表示
         ══════════════════════════════ -->
    <template v-if="accounts.length > 1">
      <div class="divider" role="separator" aria-hidden="true" />
      <section class="filter-section" aria-labelledby="account-label">
        <div id="account-label" class="section-label">アカウント</div>
        <div
          v-for="group in groupedAccounts"
          :key="group.provider"
          class="account-group"
        >
          <span class="account-provider-name">{{ group.name }}:</span>
          <div class="account-chips" role="group" :aria-label="`${group.name} のアカウントで絞り込み`">
            <button
              v-for="acc in group.accounts"
              :key="acc.id"
              type="button"
              class="account-chip"
              :class="{ 'account-chip--active': isAccountSelected(acc.address) }"
              :aria-pressed="isAccountSelected(acc.address)"
              :aria-label="`${acc.label || acc.provider} でフィルター${isAccountSelected(acc.address) ? '（選択中）' : ''}`"
              @click="toggleAccount(acc.address)"
            >
              {{ acc.label || acc.provider }}
              <span
                v-if="isAccountSelected(acc.address)"
                class="chip-x"
                aria-hidden="true"
              >×</span>
            </button>
          </div>
        </div>
      </section>
    </template>

    <div class="divider" role="separator" aria-hidden="true" />

    <!-- ══════════════════════════════
         §2 重要度 — サイコロ1〜5タップ
         ══════════════════════════════ -->
    <section class="filter-section" aria-labelledby="imp-label">
      <div id="imp-label" class="section-label">重要度</div>
      <div class="dice-row" ref="diceFocusRef">
        <div
          role="radiogroup"
          aria-label="重要度しきい値（選択した数以上を表示）"
          class="dice-group"
        >
          <button
            v-for="face in IMPORTANCE_FACES"
            :key="face"
            type="button"
            class="dice-face"
            :class="{
              'dice-face--selected': importanceMin === face,
              'dice-face--gte': importanceMin > 0 && face >= importanceMin,
              [`dice-face--imp${face}`]: true,
            }"
            role="radio"
            :aria-checked="importanceMin === face"
            :aria-label="`重要度${face}以上`"
            @click="setImportanceMin(importanceMin === face ? 0 : face)"
            @keydown="diceKeydown($event, face)"
          >
            <svg viewBox="0 0 20 20" aria-hidden="true" class="dice-svg">
              <circle
                v-for="(pip, pi) in DICE_PIPS[face]"
                :key="pi"
                :cx="pip.cx"
                :cy="pip.cy"
                r="1.8"
                class="pip"
              />
            </svg>
          </button>
        </div>
      </div>
      <div class="dice-hint" aria-live="polite">
        <template v-if="importanceMin === 0">すべて表示</template>
        <template v-else>重要度 {{ importanceMin }} 以上を表示</template>
      </div>
    </section>

    <div class="divider" role="separator" aria-hidden="true" />

    <!-- ══════════════════════════════
         §3 受信日時 — インライン date input
         ══════════════════════════════ -->
    <section class="filter-section" aria-labelledby="date-label">
      <div id="date-label" class="section-label">受信日時</div>
      <div class="date-inputs-col">
        <label class="date-input-row">
          <span class="date-input-label">from</span>
          <input
            type="date"
            class="date-input"
            :class="{ 'date-input--active': !!modelValue.received_after }"
            :value="toDateInput(modelValue.received_after)"
            aria-label="受信日時 from"
            @change="setReceivedAfter"
          />
        </label>
        <label class="date-input-row">
          <span class="date-input-label">to</span>
          <input
            type="date"
            class="date-input"
            :class="{ 'date-input--active': !!modelValue.received_before }"
            :value="toDateInput(modelValue.received_before)"
            aria-label="受信日時 to"
            @change="setReceivedBefore"
          />
        </label>
      </div>
    </section>

    <div class="divider" role="separator" aria-hidden="true" />

    <!-- ══════════════════════════════
         §4 未読のみ — トグルチップ
         ══════════════════════════════ -->
    <section class="filter-section" aria-labelledby="unread-label">
      <div id="unread-label" class="section-label">未読</div>
      <button
        type="button"
        class="toggle-chip"
        :class="{ 'toggle-chip--on': unreadOnly }"
        role="switch"
        :aria-checked="unreadOnly"
        aria-label="未読メッセージのみを表示"
        @click="toggleUnreadOnly"
        @keydown.space.prevent="toggleUnreadOnly"
      >
        <span class="toggle-track" aria-hidden="true">
          <span class="toggle-thumb"></span>
        </span>
        <span class="toggle-text">未読のみ</span>
      </button>
    </section>

  </div>
</template>

<style scoped>
/* ── ベースレイアウト ── */
.filter-bar {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding-top: 8px;
}

.filter-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* 並べ替え：ラベル行に降順トグルを右寄せで同居させる */
.sort-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.section-label {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--ocean);
  user-select: none;
}

.divider {
  height: 1px;
  background: var(--sage-weak);
  margin: 0;
}

/* ── §6 サマリーバー ── */
.summary-bar {
  display: flex;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 6px;
  padding: 8px 10px;
  background: var(--ocean-08);
  border: 1px solid var(--ocean-20);
  border-radius: var(--radius-sm);
  font-size: 11px;
}

.summary-label {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--ocean);
  padding-top: 1px;
  flex-shrink: 0;
}

.summary-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  flex: 1;
}

.summary-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 600;
  color: var(--ocean);
  background: var(--ocean-12);
  border: 1px solid var(--ocean-20);
  border-radius: var(--radius-pill);
  padding: 2px 8px;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out-expo),
              transform var(--dur-fast) var(--ease-spring);
}
.summary-chip:hover {
  background: var(--ocean-20);
  transform: scale(1.04);
}
.summary-chip:active {
  transform: scale(0.96);
}

.clear-all-btn {
  margin-left: auto;
  font-size: 11px;
  font-weight: 600;
  color: var(--ocean);
  background: none;
  border: none;
  padding: 2px 0;
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 2px;
  flex-shrink: 0;
  transition: opacity var(--dur-fast) var(--ease-out-expo),
              transform 120ms var(--ease-spring);
}
.clear-all-btn:hover {
  opacity: 0.75;
  transform: scale(1.05);
}
.clear-all-btn:active {
  transform: scale(0.94);
}

/* summary-bar トランジション */
.summary-bar-enter-active {
  animation: pop-in 150ms var(--ease-spring) both;
}
.summary-bar-leave-active {
  animation: pop-in 120ms var(--ease-out-expo) reverse both;
}

/* ── §1 セグメンテッドコントロール ── */
.segment-group {
  display: flex;
  gap: 4px;
  background: var(--mist);
  border: 1px solid var(--sage-weak);
  border-radius: var(--radius-pill);
  padding: 3px;
}

.sort-btn {
  flex: 1;
  min-width: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 500;
  color: var(--ocean);
  background: transparent;
  border: none;
  border-radius: var(--radius-pill);
  padding: 5px 6px;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out-expo),
              color var(--dur-fast) var(--ease-out-expo),
              box-shadow var(--dur-fast) var(--ease-out-expo),
              transform 120ms var(--ease-spring);
  white-space: nowrap;
}
.sort-btn:hover:not(.sort-btn--active) {
  background: var(--ocean-08);
  color: var(--ocean);
  transform: translateY(-1px) scale(1.03);
}
.sort-btn:active {
  transform: scale(0.94) !important;
}
.sort-btn--active {
  background: var(--ocean);
  color: var(--white);
  font-weight: 700;
  box-shadow: 0 2px 8px var(--ocean-20);
}
/* 選択の瞬間にポップ（active→selected 遷移）は transform が spring で担う */
.sort-btn--active:not(:active) {
  transform: translateY(-1px) scale(1.02);
}

.sort-dir-badge {
  font-size: 13px;
  font-weight: 700;
  line-height: 1;
}

.dir-toggle {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 11px;
  font-weight: 600;
  color: var(--ocean);
  background: var(--ocean-08);
  border: 1px solid var(--ocean-20);
  border-radius: var(--radius-pill);
  padding: 5px 8px;
  cursor: pointer;
  white-space: nowrap;
  transition: background var(--dur-fast) var(--ease-out-expo),
              transform 120ms var(--ease-spring),
              box-shadow var(--dur-fast) var(--ease-out-expo);
}
.dir-toggle:hover {
  background: var(--ocean-12);
  transform: translateY(-1px) scale(1.03);
  box-shadow: 0 3px 8px var(--ocean-12);
}
.dir-toggle:active {
  transform: scale(0.94) !important;
  box-shadow: none;
}

.dir-icon--desc,
.dir-icon--asc {
  font-size: 14px;
  line-height: 1;
  display: inline-block;
  transition: transform var(--dur-base) var(--ease-out-expo);
}
/* 昇降切替：矢印をフリップで表現（rotate で direction を伝える） */
.dir-icon--asc {
  transform: rotate(180deg);
}

.dir-toggle-label {
  font-size: 11px;
}

/* ── §2 サイコロ ── */
.dice-row {
  display: flex;
  align-items: center;
  flex-wrap: nowrap;
  gap: 6px;
  overflow: visible;
}

.dice-group {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-wrap: nowrap;
  gap: 5px;
  overflow: visible;
}

.dice-all-btn {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 700;
  color: var(--ocean);
  background: var(--mist);
  border: 1.5px solid var(--sage-weak);
  cursor: pointer;
  flex-shrink: 0;
  transition: background var(--dur-fast) var(--ease-out-expo),
              color var(--dur-fast) var(--ease-out-expo),
              border-color var(--dur-fast) var(--ease-out-expo),
              transform 100ms var(--ease-spring);
  display: flex;
  align-items: center;
  justify-content: center;
}
.dice-all-btn:hover:not(.dice-all-btn--active) {
  background: var(--ocean-08);
  color: var(--ocean);
  border-color: var(--ocean-20);
}
.dice-all-btn:active {
  transform: scale(0.90);
}
.dice-all-btn--active {
  background: var(--ocean);
  color: var(--white);
  border-color: var(--ocean);
}

.dice-face {
  flex: 1 1 0;
  min-width: 0;
  max-width: 34px;
  aspect-ratio: 1 / 1;
  border-radius: 5px;
  border: 1.5px solid var(--sage-weak);
  background: var(--mist);
  cursor: pointer;
  padding: 3px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background var(--dur-fast) var(--ease-out-expo),
              border-color var(--dur-fast) var(--ease-out-expo),
              transform 180ms var(--ease-spring),
              box-shadow var(--dur-fast) var(--ease-out-expo);
}
.dice-face:hover:not(.dice-face--selected) {
  border-color: var(--ocean-20);
  background: var(--ocean-08);
  transform: translateY(-2px) scale(1.12);
  box-shadow: 0 6px 14px var(--ocean-12);
}
.dice-face:active {
  transform: scale(0.92) !important;
  box-shadow: none !important;
}

/* 重要度ランプ — face ごとに pip 色が変わる */
.dice-face--imp1 .pip { fill: #7A9490; }
.dice-face--imp2 .pip { fill: var(--leaf); }
.dice-face--imp3 .pip { fill: #2BBFA8; }
.dice-face--imp4 .pip { fill: #2B7FBF; }
.dice-face--imp5 .pip { fill: #4B5BBF; }
.dice-face--imp6 .pip { fill: #6B3BAF; }

/* しきい値以上に選択されている面 */
.dice-face--gte {
  border-color: var(--ocean-20);
  background: var(--ocean-08);
}

/* 選択されている面（=importanceMin）— spring でポップしてから定位置に落ち着く */
.dice-face--selected {
  background: var(--ocean) !important;
  border-color: var(--ocean) !important;
  box-shadow: 0 4px 12px var(--ocean-20);
  transform: translateY(-3px) scale(1.08) !important;
}
.dice-face--selected .pip { fill: var(--white) !important; }

/* 最高値（imp6）の sand halo */
.dice-face--imp6.dice-face--selected {
  box-shadow: 0 4px 12px var(--ocean-20), 0 0 0 3px rgba(242, 212, 155, 0.55);
}

.dice-svg {
  width: 100%;
  height: 100%;
}

.dice-hint {
  font-size: 11px;
  color: var(--ocean);
  min-height: 16px;
}

/* ── §3 日付インライン入力 ── */
.date-inputs-col {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.date-input-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  cursor: default;
}

.date-input-label {
  font-size: 11px;
  font-weight: 700;
  color: var(--ocean);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  width: 22px;
  flex-shrink: 0;
}

.date-input {
  font-size: 12px;
  font-family: inherit;
  color: var(--ocean);
  background: var(--mist);
  border: 1.5px solid var(--sage-weak);
  border-radius: var(--radius-sm);
  padding: 4px 7px;
  width: 130px;
  transition: border-color var(--dur-fast);
}
.date-input:focus {
  border-color: var(--ocean);
  outline: 3px solid var(--ocean-12);
  outline-offset: 1px;
}
.date-input--active {
  border-color: var(--ocean-20);
  background: var(--ocean-08);
}

/* ── §4 トグルチップ（role="switch"） ── */
.toggle-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--ocean);
  background: var(--mist);
  border: 1.5px solid var(--sage-weak);
  border-radius: var(--radius-pill);
  padding: 5px 12px;
  cursor: pointer;
  align-self: flex-start;
  transition: background var(--dur-fast) var(--ease-out-expo),
              border-color var(--dur-fast) var(--ease-out-expo),
              color var(--dur-fast) var(--ease-out-expo),
              box-shadow var(--dur-fast) var(--ease-out-expo),
              transform 120ms var(--ease-spring);
}
.toggle-chip:hover {
  background: var(--ocean-08);
  border-color: var(--ocean-20);
  transform: translateY(-1px) scale(1.03);
  box-shadow: 0 3px 8px var(--ocean-08);
}
.toggle-chip:active {
  transform: scale(0.94) !important;
  box-shadow: none;
}
.toggle-chip--on {
  background: var(--ocean);
  border-color: var(--ocean);
  color: var(--white);
}

.toggle-track {
  position: relative;
  width: 26px;
  height: 14px;
  border-radius: var(--radius-pill);
  background: var(--sage-weak);
  border: 1px solid var(--sage);
  flex-shrink: 0;
  transition: background var(--dur-fast) var(--ease-out-expo),
              border-color var(--dur-fast) var(--ease-out-expo);
}
.toggle-chip--on .toggle-track {
  background: rgba(255, 255, 255, 0.35);
  border-color: rgba(255, 255, 255, 0.45);
}
.toggle-thumb {
  position: absolute;
  top: 1px;
  left: 1px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--sage);
  /* spring で滑らかなサム移動（dur-base = 280ms で気持ちよい重さ） */
  transition: transform var(--dur-base) var(--ease-spring),
              background var(--dur-fast) var(--ease-out-expo);
}
.toggle-chip--on .toggle-thumb {
  transform: translateX(12px);
  background: var(--white);
}

.toggle-text {
  font-size: 12px;
  line-height: 1;
}

/* ── §5 アカウントチップ ── */
/* プロバイダごとのグループ（Gmail: [..] [..]） */
.account-group {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.account-provider-name {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 700;
  color: var(--ocean);
  min-width: 48px;
}

.account-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.account-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 500;
  color: var(--ocean);
  background: var(--mist);
  border: 1.5px solid var(--sage-weak);
  border-radius: var(--radius-pill);
  padding: 4px 12px;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out-expo),
              border-color var(--dur-fast) var(--ease-out-expo),
              color var(--dur-fast) var(--ease-out-expo),
              box-shadow var(--dur-fast) var(--ease-out-expo),
              transform 120ms var(--ease-spring);
}
.account-chip:hover:not(.account-chip--active) {
  background: var(--ocean-08);
  border-color: var(--ocean-20);
  transform: translateY(-1px) scale(1.03);
  box-shadow: 0 3px 8px var(--ocean-08);
}
.account-chip:active {
  transform: scale(0.94) !important;
  box-shadow: none;
}
.account-chip--active {
  background: var(--ocean);
  color: var(--white);
  border-color: var(--ocean);
  font-weight: 700;
  /* 選択切替の瞬間にわずかな lift でポップ感を演出 */
  transform: translateY(-1px);
  box-shadow: 0 3px 10px var(--ocean-20);
}
.account-chip--active:hover {
  transform: translateY(-2px) scale(1.03) !important;
}

/* chip-x（共通） */
.chip-x {
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  opacity: 0.75;
  display: inline-block;
  transition: transform 120ms var(--ease-spring),
              opacity var(--dur-fast) var(--ease-out-expo);
}
.account-chip:hover .chip-x {
  transform: scale(1.2);
  opacity: 1;
}
.account-chip:active .chip-x {
  transform: scale(0.9);
}
</style>
