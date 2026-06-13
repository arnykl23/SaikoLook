<script setup lang="ts">
import { useToast } from "../composables/useToast";

const { toasts, dismiss } = useToast();

const ICONS: Record<string, string> = {
  info: "M12 8h.01M12 12v4",
  success: "M9 12l2 2 4-4",
  error: "M12 8v4m0 4h.01",
  warn: "M12 8v4m0 4h.01",
};
</script>

<template>
  <Teleport to="body">
    <div class="toast-container" aria-live="polite" aria-atomic="false">
      <TransitionGroup name="toast">
        <div
          v-for="t in toasts"
          :key="t.id"
          class="toast"
          :class="`toast--${t.type}`"
          role="status"
        >
          <div class="toast-body">
            <svg class="toast-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <circle cx="12" cy="12" r="10"/>
              <path :d="ICONS[t.type]"/>
            </svg>
            <span class="toast-msg">{{ t.message }}</span>
            <button
              v-if="t.action"
              type="button"
              class="toast-action"
              @click="t.action.fn(); dismiss(t.id)"
            >{{ t.action.label }}</button>
            <button
              type="button"
              class="toast-close"
              aria-label="閉じる"
              @click="dismiss(t.id)"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" aria-hidden="true">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>
          <div
            v-if="t.duration > 0"
            class="toast-progress"
            :style="{ animationDuration: `${t.duration}ms` }"
          />
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<style scoped>
.toast-container {
  position: fixed;
  bottom: 24px;
  left: 24px;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 10px;
  pointer-events: none;
}

.toast {
  pointer-events: all;
  display: flex;
  flex-direction: column;
  border-radius: var(--radius);
  border: 1px solid;
  box-shadow: var(--shadow-lg);
  font-size: 13px;
  font-weight: 500;
  min-width: 260px;
  max-width: 380px;
  backdrop-filter: blur(4px);
  overflow: hidden;
}

.toast-body {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 14px 11px 12px;
}

.toast--info    { background: var(--surface);       border-color: var(--brand-blue); color: var(--brand-blue); }
.toast--success { background: var(--success-weak);  border-color: var(--success);    color: var(--success); }
.toast--error   { background: var(--danger-weak);   border-color: var(--danger);     color: var(--danger); }
.toast--warn    { background: var(--warning-weak);  border-color: var(--warning);    color: var(--warning); }

.toast-icon { flex-shrink: 0; }

.toast-msg {
  flex: 1;
  line-height: 1.45;
}

.toast-action {
  background: none;
  border: none;
  padding: 0;
  font-size: inherit;
  font-weight: 600;
  cursor: pointer;
  color: currentColor;
  text-decoration: underline;
  text-underline-offset: 2px;
  white-space: nowrap;
}
.toast-close {
  flex-shrink: 0;
  background: none;
  border: none;
  padding: 2px;
  cursor: pointer;
  color: currentColor;
  opacity: 0.5;
  display: flex;
  align-items: center;
}
.toast-close:hover { opacity: 1; }

/* Progress bar */
.toast-progress {
  height: 3px;
  background: currentColor;
  opacity: 0.35;
  transform-origin: left;
  animation: toast-shrink linear forwards;
}

@keyframes toast-shrink {
  from { transform: scaleX(1); }
  to   { transform: scaleX(0); }
}

/* Slide in from bottom */
.toast-enter-active {
  transition: transform 0.28s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.2s ease;
}
.toast-leave-active {
  transition: transform 0.2s ease-in, opacity 0.2s ease;
}
.toast-enter-from {
  transform: translateY(120%);
  opacity: 0;
}
.toast-leave-to {
  transform: translateY(120%);
  opacity: 0;
}
</style>
