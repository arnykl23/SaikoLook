<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ importance: number }>();

const level = computed(() => Math.min(5, Math.max(1, props.importance)));
const label = computed(() => `重要度 ${level.value} / 5`);

// Dot positions for each die face (cx, cy pairs within 0 0 20 20 viewBox)
const DOTS: Record<number, [number, number][]> = {
  1: [[10, 10]],
  2: [[6, 6], [14, 14]],
  3: [[6, 6], [10, 10], [14, 14]],
  4: [[6, 6], [14, 6], [6, 14], [14, 14]],
  5: [[6, 6], [14, 6], [10, 10], [6, 14], [14, 14]],
};
</script>

<template>
  <span
    class="imp"
    :class="`imp-${level}`"
    :title="label"
    :aria-label="label"
  >
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <rect x="1" y="1" width="18" height="18" rx="3.5" fill="currentColor" opacity="0.15" stroke="currentColor" stroke-width="1.4"/>
      <circle
        v-for="([cx, cy], i) in DOTS[level]"
        :key="i"
        :cx="cx"
        :cy="cy"
        r="1.7"
        fill="currentColor"
      />
    </svg>
  </span>
</template>

<style scoped>
.imp {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.imp-1 { color: var(--imp-1); }
.imp-2 { color: var(--imp-2); }
.imp-3 { color: var(--imp-3); }
.imp-4 { color: var(--imp-4); }
.imp-5 { color: var(--imp-5); }
</style>
