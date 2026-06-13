<script setup lang="ts">
import { computed, ref } from "vue";
import type { MessageRecord, MessageState } from "../types";
import { ACTIONABLE_STATES } from "../types";
import ImportanceBadge from "./ImportanceBadge.vue";
import StateBadge from "./StateBadge.vue";

const props = withDefaults(
  defineProps<{
    record: MessageRecord;
    busy?: boolean;
    mode?: "inbox" | "archive";
    compact?: boolean;
    focused?: boolean;
    selected?: boolean;
    searchQuery?: string;
  }>(),
  { mode: "inbox", compact: false, focused: false, selected: false, searchQuery: "" },
);

function highlight(text: string): string {
  const q = props.searchQuery?.trim();
  if (!q) return escapeHtml(text);
  const escaped = escapeHtml(text);
  const escapedQ = escapeHtml(q).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return escaped.replace(new RegExp(escapedQ, "gi"), (m) => `<mark class="hl">${m}</mark>`);
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

const emit = defineEmits<{
  (e: "change-state", state: MessageState): void;
  (e: "archive"): void;
  (e: "unarchive"): void;
  (e: "toggle-select"): void;
}>();

const STATE_LABELS: Record<MessageState, string> = {
  unhandled: "未対応",
  in_progress: "対応中",
  done: "完了",
  snoozed: "保留",
  dismissed: "アーカイブ",
};

const WEIGHT_LABELS: Record<string, string> = {
  light: "軽",
  medium: "中",
  heavy: "重",
};

// どの分析器が判定したか（説明可能性）. 未知の値はそのまま表示する.
const ANALYZER_LABELS: Record<string, string> = {
  gemini: "Gemini",
  anthropic: "Claude",
  openai: "GPT",
  stub: "ルールベース",
};

const email = computed(() => props.record.email);
const analysis = computed(() => props.record.analysis);

const avatarInitials = computed(() => {
  const sender = email.value.sender || "";
  // Extract name part before the email address if present
  const name = sender.replace(/<[^>]+>/, "").trim() || sender;
  const words = name.split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  if (words.length === 1) return words[0][0].toUpperCase();
  return (words[0][0] + words[words.length - 1][0]).toUpperCase();
});

const avatarColor = computed(() => {
  const str = email.value.sender || "?";
  let hash = 0;
  for (let i = 0; i < str.length; i++) hash = str.charCodeAt(i) + ((hash << 5) - hash);
  const hue = ((hash % 360) + 360) % 360;
  return `hsl(${hue}, 55%, 45%)`;
});

const importance = computed(() => analysis.value?.importance ?? 1);
const summary = computed(() => analysis.value?.summary ?? email.value.snippet);
const category = computed(() => analysis.value?.category ?? "");
const weightLabel = computed(() => {
  const w = analysis.value?.task_weight;
  return w ? (WEIGHT_LABELS[w] ?? w) : "";
});
const analyzerLabel = computed(() => {
  const a = analysis.value?.analyzer;
  return a ? (ANALYZER_LABELS[a] ?? a) : "";
});

const receivedAt = computed(() => {
  const raw = email.value.received_at;
  if (!raw) return "";
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return raw;
  const diff = Date.now() - d.getTime();
  const mins  = Math.floor(diff / 60_000);
  const hours = Math.floor(diff / 3_600_000);
  const days  = Math.floor(diff / 86_400_000);
  if (mins < 1)   return "たった今";
  if (mins < 60)  return `${mins}分前`;
  if (hours < 24) return `${hours}時間前`;
  if (days < 2)   return "昨日";
  if (days < 7)   return `${days}日前`;
  return d.toLocaleDateString("ja-JP", { month: "short", day: "numeric" });
});

const receivedAtFull = computed(() => {
  const raw = email.value.received_at;
  if (!raw) return "";
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return raw;
  return d.toLocaleString("ja-JP", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
});

const triage = computed(() => props.record.triage_score.toFixed(1));

const isArchive = computed(() => props.mode === "archive");

const expanded = ref(false);
const bodyText = computed(() => email.value.body_text?.trim() || null);

const bodyHtml = computed(() => {
  const raw = bodyText.value;
  if (!raw) return null;
  // Escape HTML entities, then convert newlines and linkify URLs
  const escaped = raw
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  const linked = escaped.replace(
    /(https?:\/\/[^\s<>"']+)/g,
    '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>',
  );
  return linked.replace(/\n/g, "<br>");
});

// 現在の状態は遷移先ボタンから除く
const nextStates = computed(() => ACTIONABLE_STATES);
</script>

<template>
  <article
    class="card"
    :class="{ unread: email.is_unread, archive: isArchive, expanded, compact: props.compact, focused: props.focused, selected: props.selected }"
    :style="{ '--imp-color': `var(--imp-${importance})` }"
  >
    <div
      class="content-area"
      role="button"
      :aria-expanded="expanded"
      tabindex="0"
      @click="expanded = !expanded"
      @keydown.enter.space.prevent="expanded = !expanded"
    >
      <div class="top">
        <div
          class="avatar-wrap"
          :title="email.sender || ''"
          @click.stop="emit('toggle-select')"
        >
          <div
            class="avatar"
            :style="{ background: avatarColor }"
            aria-hidden="true"
          >{{ avatarInitials }}</div>
          <div class="avatar-check" :class="{ checked: props.selected }" aria-hidden="true">
            <svg v-if="props.selected" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="20 6 9 17 4 12"/>
            </svg>
          </div>
        </div>
        <div class="head">
          <div class="subject-row">
            <span class="subject" v-html="highlight(email.subject || '(件名なし)')" />
            <span v-if="email.is_unread" class="unread-dot" title="未読" aria-label="未読" />
          </div>
          <div class="meta">
            <span class="sender" v-html="highlight(email.sender || '(差出人不明)')" />
            <span class="dot">·</span>
            <span class="provider">{{ email.provider }}</span>
            <span v-if="receivedAt" class="dot">·</span>
            <time v-if="receivedAt" :title="receivedAtFull">{{ receivedAt }}</time>
          </div>
        </div>
        <StateBadge :state="record.state" />
        <ImportanceBadge :importance="importance" />
      </div>

      <p v-if="!expanded && !props.compact" class="summary" v-html="highlight(summary)" />
      <Transition name="expand">
        <div v-if="expanded" class="body-expanded">
          <div v-if="bodyHtml" class="body-text" v-html="bodyHtml" />
          <p v-else class="summary summary-full">{{ summary }}</p>
          <p v-if="analysis?.suggested_action" class="suggested-action">
            <span class="suggested-label">提案：</span>{{ analysis.suggested_action }}
          </p>
        </div>
      </Transition>

      <div class="tags">
        <template v-if="!props.compact">
          <span v-if="category" class="tag">{{ category }}</span>
          <span v-if="weightLabel" class="tag weight">負荷 {{ weightLabel }}</span>
          <span v-if="analysis?.needs_reply" class="tag reply">要返信</span>
          <span
            v-if="analyzerLabel"
            class="tag analyzer"
            :title="`判定した分析器: ${analyzerLabel}`"
            >🤖 {{ analyzerLabel }}</span
          >
          <span class="tag triage triage-tip">
            ▲ {{ triage }}
            <span class="triage-tooltip">
              <span class="triage-row">重要度 {{ importance }} / 5</span>
              <span v-if="analysis?.needs_reply" class="triage-row">要返信</span>
              <span v-if="analysis?.deadline" class="triage-row">期限：{{ analysis.deadline.slice(0, 10) }}</span>
              <span v-if="weightLabel" class="triage-row">タスク負荷：{{ weightLabel }}</span>
              <span v-if="analyzerLabel" class="triage-row">判定：{{ analyzerLabel }}</span>
            </span>
          </span>
        </template>
        <span class="expand-icon" aria-hidden="true">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polyline :points="expanded ? '18 15 12 9 6 15' : '6 9 12 15 18 9'" />
          </svg>
        </span>
      </div>
    </div>

    <div class="actions" @click.stop>
      <template v-if="!isArchive">
        <button
          v-for="s in nextStates"
          :key="s"
          type="button"
          class="act"
          :class="[`act-${s}`, { 'act-active': record.state === s }]"
          :disabled="busy"
          @click="s === 'dismissed' ? emit('archive') : emit('change-state', record.state === s ? 'unhandled' : s)"
        >
          {{ STATE_LABELS[s] }}
        </button>
      </template>
      <button
        v-else
        type="button"
        class="act act-unarchive"
        :disabled="busy"
        @click="emit('unarchive')"
      >
        復元
      </button>
    </div>
  </article>
</template>

<style scoped>
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 16px 14px 20px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  box-shadow: var(--shadow-sm);
  transition: box-shadow 0.15s;
  position: relative;
}
.card.compact {
  padding: 8px 16px 8px 20px;
  gap: 0;
}
.card.compact .content-area {
  gap: 0;
}
.card.compact.expanded .content-area {
  gap: 8px;
}
.card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  border-radius: var(--radius) 0 0 var(--radius);
  background: var(--imp-color, var(--border));
  opacity: 0.5;
  transition: opacity 0.15s;
}
.card:hover::before {
  opacity: 1;
}
.card.unread::before {
  opacity: 1;
}
.card.archive {
  background: var(--snow-white);
  opacity: 0.88;
  box-shadow: none;
}
.card.archive::before {
  opacity: 0.25;
}
.card.focused {
  outline: 2px solid var(--brand-blue);
  outline-offset: 1px;
}
.card.focused::before {
  opacity: 1;
}

.content-area {
  display: flex;
  flex-direction: column;
  gap: 8px;
  cursor: pointer;
  outline: none;
  border-radius: calc(var(--radius) - 2px);
}
.content-area:focus-visible {
  outline: 2px solid var(--brand-blue);
  outline-offset: 2px;
}

.top {
  display: flex;
  align-items: center;
  gap: 10px;
}

.avatar-wrap {
  position: relative;
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  cursor: pointer;
}
.avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  color: #fff;
  letter-spacing: 0.02em;
  transition: opacity 0.15s;
}
.avatar-check {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  background: var(--snow-surface);
  border: 2px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity 0.15s;
  color: #fff;
}
.avatar-check.checked {
  background: var(--brand-blue);
  border-color: var(--brand-blue);
  opacity: 1;
}
.avatar-wrap:hover .avatar-check:not(.checked) {
  opacity: 1;
}
.card.selected .avatar-check {
  opacity: 1;
}
.avatar-wrap:hover .avatar {
  opacity: 0;
}
.card.selected .avatar {
  opacity: 0;
}
.card.selected {
  background: var(--accent-weak);
  border-color: var(--brand-blue);
}
.card.selected::before {
  opacity: 1;
  background: var(--brand-blue);
}
.head {
  flex: 1;
  min-width: 0;
}
.subject-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.subject {
  font-weight: 600;
  font-size: 15px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text);
}
.unread .subject {
  font-weight: 700;
}
.unread-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--brand-blue);
  flex: none;
}

.meta {
  display: flex;
  align-items: center;
  gap: 5px;
  color: var(--text-muted);
  font-size: 12px;
  margin-top: 2px;
}
.sender {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 280px;
}
.dot {
  opacity: 0.4;
}

.summary {
  margin: 0;
  color: var(--text-muted);
  font-size: 13px;
  display: -webkit-box;
  -webkit-line-clamp: 1;
  line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.55;
}
.summary-full {
  display: block;
  -webkit-line-clamp: unset;
  line-clamp: unset;
  overflow: visible;
}

.body-expanded {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: -4px;
}
.body-text {
  margin: 0;
  color: var(--text);
  font-size: 13px;
  word-break: break-word;
  line-height: 1.65;
  max-height: 400px;
  overflow-y: auto;
  padding: 10px 12px;
  background: var(--snow-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}
.body-text :deep(a) {
  color: var(--brand-blue);
  word-break: break-all;
}
.suggested-action {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
}
.suggested-label {
  color: var(--brand-blue);
  font-weight: 600;
}

.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.tag {
  font-size: 11px;
  color: var(--text-muted);
  background: var(--snow-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  padding: 2px 9px;
}
.tag.reply {
  color: var(--brand-blue);
  border-color: var(--brand-blue);
  background: var(--accent-weak);
  font-weight: 600;
}
.tag.triage {
  color: var(--text-muted);
}
.triage-tip {
  position: relative;
  cursor: default;
}
.triage-tooltip {
  display: none;
  position: absolute;
  bottom: calc(100% + 6px);
  left: 50%;
  transform: translateX(-50%);
  background: var(--text);
  color: var(--surface);
  border-radius: var(--radius-sm);
  padding: 7px 10px;
  font-size: 11px;
  white-space: nowrap;
  z-index: 100;
  flex-direction: column;
  gap: 3px;
  box-shadow: var(--shadow-lg);
  pointer-events: none;
}
.triage-tooltip::after {
  content: '';
  position: absolute;
  top: 100%;
  left: 50%;
  transform: translateX(-50%);
  border: 5px solid transparent;
  border-top-color: var(--text);
}
.triage-tip:hover .triage-tooltip {
  display: flex;
}
.triage-row {
  display: block;
  line-height: 1.5;
}
.tag.analyzer {
  color: var(--text-muted);
  font-variant: tabular-nums;
}
.expand-icon {
  margin-left: auto;
  font-size: 10px;
  color: var(--text-muted);
  opacity: 0.45;
  user-select: none;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  border-top: 1px solid var(--border);
  padding-top: 10px;
}
.card.compact .actions {
  padding-top: 6px;
}
.act {
  font-size: 12px;
  font-weight: 500;
  padding: 4px 14px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text-muted);
  transition: border-color 0.15s, color 0.15s, background 0.15s;
}
.act:hover:not(:disabled) {
  border-color: var(--brand-blue);
  color: var(--brand-blue);
  background: var(--accent-weak);
}
.act.act-active {
  font-weight: 600;
  border-color: currentColor;
  opacity: 1;
}
.act-unhandled.act-active  { color: var(--text-muted); border-color: var(--text-muted); background: var(--snow-surface); }
.act-in_progress.act-active { color: var(--brand-blue); border-color: var(--brand-blue); background: var(--accent-weak); }
.act-done.act-active        { color: var(--success);    border-color: var(--success);    background: var(--success-weak); }
.act-snoozed.act-active     { color: var(--warning);    border-color: var(--warning);    background: var(--warning-weak); }
.act-dismissed.act-active   { color: var(--brand-purple); border-color: var(--brand-purple); background: #F3EEFF; }
.act:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.act-done:hover:not(:disabled) {
  border-color: var(--success);
  color: var(--success);
  background: var(--success-weak);
}
.act-dismissed:hover:not(:disabled) {
  border-color: var(--brand-purple);
  color: var(--brand-purple);
  background: #F3EEFF;
}
.act-unarchive:hover:not(:disabled) {
  border-color: var(--brand-purple);
  color: var(--brand-purple);
  background: #F3EEFF;
}

:deep(.hl) {
  background: #FFF176;
  color: #1a1a1a;
  border-radius: 2px;
  padding: 0 1px;
}
html.dark :deep(.hl) {
  background: #7B6B00;
  color: #fff;
}

/* Expand animation */
.expand-enter-active,
.expand-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
  transform-origin: top;
}
.expand-enter-from,
.expand-leave-to {
  opacity: 0;
  transform: scaleY(0.95);
}
</style>
