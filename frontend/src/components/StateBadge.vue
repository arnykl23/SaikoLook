<script setup lang="ts">
import { computed } from "vue";
import type { MessageState } from "../types";

const props = defineProps<{ state: MessageState }>();

const LABELS: Record<MessageState, string> = {
  unhandled: "未対応",
  in_progress: "対応中",
  done: "完了",
  snoozed: "保留",
  dismissed: "対象外",
};

const label = computed(() => LABELS[props.state]);
</script>

<template>
  <span class="state" :class="`state-${state}`">{{ label }}</span>
</template>

<style scoped>
/*
 * StateBadge — 淡地＋ocean文字＋色枠＋左ドット（::before）で状態を示す
 * 色覚に依存しない冗長符号化: ドット色×枠色×地色の3重
 * DESIGN.md §7 準拠．5色パレット（ocean/leaf/sand/sage）のみ使用．
 */

.state {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 22px;
  padding: 0 10px 0 8px;
  border-radius: var(--radius-pill);
  font-size: 11px;
  font-weight: 600;
  border: 1px solid transparent;
  white-space: nowrap;
  flex-shrink: 0;
  color: var(--ocean);
  /* 状態色の遷移（background / border-color / color）を滑らかに */
  transition:
    background var(--dur-fast) var(--ease-out-expo),
    border-color var(--dur-fast) var(--ease-out-expo),
    color var(--dur-fast) var(--ease-out-expo),
    transform var(--dur-fast) var(--ease-spring);
}
.state:hover {
  transform: translateY(-1px) scale(1.03);
}

/* 色ドット（::before で疑似要素） */
.state::before {
  content: '';
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
  transition: background var(--dur-fast) var(--ease-out-expo);
}

/* unhandled（未対応）= red: 最も目立つ・要対応 */
.state-unhandled {
  background: var(--red-12);
  border-color: var(--red);
  color: var(--red);
}
.state-unhandled::before {
  background: var(--red);
}

/* in_progress（対応中）= sand */
.state-in_progress {
  background: var(--sand-weak);
  border-color: var(--sand);
  color: var(--ocean);
}
.state-in_progress::before {
  background: var(--sand);
}

/* done（完了）= leaf */
.state-done {
  background: var(--leaf-weak);
  border-color: var(--leaf);
  color: var(--ocean);
}
.state-done::before {
  background: var(--leaf);
}

/* snoozed（保留）= mauve */
.state-snoozed {
  background: var(--mauve-weak);
  border-color: var(--mauve);
  color: var(--mauve);
}
.state-snoozed::before {
  background: var(--mauve);
}

/* dismissed（対象外）= sage 退色: opacity .6 で「盤面から外れた」質感 */
.state-dismissed {
  background: var(--sage-weak);
  border-color: var(--sage);
  color: var(--ocean);
  opacity: 0.6;
}
.state-dismissed::before {
  background: var(--sage);
}
</style>
