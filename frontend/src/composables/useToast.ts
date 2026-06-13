import { ref } from "vue";

export type ToastType = "info" | "success" | "error" | "warn";

export interface Toast {
  id: number;
  message: string;
  type: ToastType;
  duration: number; // ms until auto-dismiss (0 = never)
  action?: { label: string; fn: () => void };
}

let nextId = 0;
const toasts = ref<Toast[]>([]);

const AUTO_DISMISS_MS: Record<ToastType, number> = {
  info: 4000,
  success: 5000,
  warn: 6000,
  error: 0,
};

let actionToastId: number | null = null;
let actionToastTimer: ReturnType<typeof setTimeout> | null = null;

export function useToast() {
  function addToast(
    message: string,
    type: ToastType = "info",
    action?: Toast["action"],
  ): void {
    const id = nextId++;
    const duration = AUTO_DISMISS_MS[type];
    toasts.value.push({ id, message, type, duration, action });
    if (duration > 0) {
      setTimeout(() => dismiss(id), duration);
    }
  }

  // Replaces the previous action toast instead of stacking
  function addActionToast(
    message: string,
    type: ToastType = "success",
    action?: Toast["action"],
  ): void {
    if (actionToastId !== null) {
      toasts.value = toasts.value.filter((t) => t.id !== actionToastId);
    }
    if (actionToastTimer !== null) clearTimeout(actionToastTimer);

    const id = nextId++;
    actionToastId = id;
    const duration = AUTO_DISMISS_MS[type];
    toasts.value.push({ id, message, type, duration, action });

    actionToastTimer = setTimeout(() => {
      dismiss(id);
      actionToastId = null;
      actionToastTimer = null;
    }, AUTO_DISMISS_MS[type]);
  }

  function dismiss(id: number): void {
    toasts.value = toasts.value.filter((t) => t.id !== id);
    if (id === actionToastId) actionToastId = null;
  }

  return { toasts, addToast, addActionToast, dismiss };
}
