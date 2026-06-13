import { ref, watch } from "vue";

export function useAnimatedCount(getValue: () => number, duration = 400) {
  const displayed = ref(getValue());

  watch(getValue, (target, prev) => {
    if (target === prev) return;
    if (prev === 0) { displayed.value = target; return; }
    const start = prev;
    const diff = target - start;
    const startTime = performance.now();

    function step(now: number) {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      // ease-out
      const eased = 1 - Math.pow(1 - progress, 3);
      displayed.value = Math.round(start + diff * eased);
      if (progress < 1) requestAnimationFrame(step);
    }

    requestAnimationFrame(step);
  });

  return displayed;
}
