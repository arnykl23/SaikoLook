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
.state {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  border: 1px solid transparent;
}
.state-unhandled {
  color: var(--danger);
  background: var(--danger-weak);
  border-color: var(--danger);
}
.state-in_progress {
  color: var(--accent);
  background: var(--accent-weak);
  border-color: var(--accent);
}
.state-done {
  color: var(--success);
  background: var(--success-weak);
  border-color: var(--success);
}
.state-snoozed {
  color: var(--warning);
  background: var(--warning-weak);
  border-color: var(--warning);
}
.state-dismissed {
  color: var(--text-muted);
  background: var(--bg);
  border-color: var(--border);
}
</style>
