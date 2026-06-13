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
  }>(),
  { mode: "inbox" },
);

const emit = defineEmits<{
  (e: "change-state", state: MessageState): void;
  (e: "unarchive"): void;
}>();

const STATE_LABELS: Record<MessageState, string> = {
  unhandled: "未対応",
  in_progress: "対応中",
  done: "完了",
  snoozed: "保留",
  dismissed: "対象外",
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
  return d.toLocaleString("ja-JP", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
});

const triage = computed(() => props.record.triage_score.toFixed(1));

const isArchive = computed(() => props.mode === "archive");

const expanded = ref(false);
const bodyText = computed(() => email.value.body_text?.trim() || null);

// 現在の状態は遷移先ボタンから除く
const nextStates = computed(() =>
  ACTIONABLE_STATES.filter((s) => s !== props.record.state),
);
</script>

<template>
  <article class="card" :class="{ unread: email.is_unread, archive: isArchive, expanded }">
    <div
      class="content-area"
      role="button"
      :aria-expanded="expanded"
      tabindex="0"
      @click="expanded = !expanded"
      @keydown.enter.space.prevent="expanded = !expanded"
    >
      <div class="top">
        <ImportanceBadge :importance="importance" />
        <div class="head">
          <div class="subject-row">
            <span class="subject">{{ email.subject || "(件名なし)" }}</span>
            <span v-if="email.is_unread" class="unread-dot" title="未読" aria-label="未読" />
          </div>
          <div class="meta">
            <span class="sender">{{ email.sender || "(差出人不明)" }}</span>
            <span class="dot">·</span>
            <span class="provider">{{ email.provider }}</span>
            <span v-if="receivedAt" class="dot">·</span>
            <time v-if="receivedAt">{{ receivedAt }}</time>
          </div>
        </div>
        <StateBadge :state="record.state" />
      </div>

      <p v-if="!expanded" class="summary">{{ summary }}</p>

      <div v-else class="body-expanded">
        <p v-if="bodyText" class="body-text">{{ bodyText }}</p>
        <p v-else class="summary summary-full">{{ summary }}</p>
        <p v-if="analysis?.suggested_action" class="suggested-action">
          <span class="suggested-label">提案：</span>{{ analysis.suggested_action }}
        </p>
      </div>

      <div class="tags">
        <span v-if="category" class="tag">{{ category }}</span>
        <span v-if="weightLabel" class="tag weight">負荷 {{ weightLabel }}</span>
        <span v-if="analysis?.needs_reply" class="tag reply">要返信</span>
        <span
          v-if="analyzerLabel"
          class="tag analyzer"
          :title="`判定した分析器: ${analyzerLabel}`"
          >🤖 {{ analyzerLabel }}</span
        >
        <span class="tag triage" :title="`トリアージスコア ${triage}`">▲ {{ triage }}</span>
        <span class="expand-icon" :aria-hidden="true">{{ expanded ? "▲" : "▼" }}</span>
      </div>
    </div>

    <div class="actions" @click.stop>
      <template v-if="!isArchive">
        <button
          v-for="s in nextStates"
          :key="s"
          type="button"
          class="act"
          :class="`act-${s}`"
          :disabled="busy"
          @click="emit('change-state', s)"
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
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.card.unread {
  border-left: 3px solid var(--accent);
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
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.top {
  display: flex;
  align-items: flex-start;
  gap: 10px;
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
}
.unread .subject {
  font-weight: 700;
}
.unread-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--accent);
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
  opacity: 0.5;
}
.summary {
  margin: 0;
  color: var(--text);
  font-size: 13px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
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
}
.body-text {
  margin: 0;
  color: var(--text);
  font-size: 13px;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
  max-height: 400px;
  overflow-y: auto;
  padding: 8px 10px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 4px;
}
.suggested-action {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
}
.suggested-label {
  color: var(--accent);
  font-weight: 600;
}
.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.tag {
  font-size: 11px;
  color: var(--text-muted);
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 1px 7px;
}
.tag.reply {
  color: var(--accent);
  border-color: var(--accent);
  background: var(--accent-weak);
}
.tag.triage {
  color: var(--text-muted);
}
.tag.analyzer {
  color: var(--text-muted);
  font-variant: tabular-nums;
}
.expand-icon {
  margin-left: auto;
  font-size: 10px;
  color: var(--text-muted);
  opacity: 0.5;
  user-select: none;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  border-top: 1px solid var(--border);
  padding-top: 8px;
}
.act {
  font-size: 12px;
  padding: 4px 12px;
  border-radius: 4px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
}
.act:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
}
.act:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.act-done:hover:not(:disabled) {
  border-color: var(--success);
  color: var(--success);
}
.act-dismissed:hover:not(:disabled) {
  border-color: var(--text-muted);
  color: var(--text-muted);
}
.act-unarchive:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
}
.card.archive {
  background: var(--bg);
  opacity: 0.85;
}
</style>
