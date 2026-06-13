<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ importance: number }>();

const level = computed(() => Math.min(6, Math.max(1, props.importance)));
const label = computed(() => `重要度 ${level.value} / 6`);
</script>

<template>
  <span
    class="imp"
    :class="`imp-${level}`"
    :title="label"
    :aria-label="label"
  >
    {{ level }}
  </span>
</template>

<style scoped>
.imp {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 22px;
  height: 22px;
  padding: 0 6px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  color: #fff;
}
.imp-1 {
  background: var(--imp-1);
}
.imp-2 {
  background: var(--imp-2);
}
.imp-3 {
  background: var(--imp-3);
}
.imp-4 {
  background: var(--imp-4);
}
.imp-5 {
  background: var(--imp-5);
}
.imp-6 {
  background: var(--imp-6);
}
</style>
