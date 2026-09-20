/** ``warning`` is for work that succeeded but left the seller a step to take. */
export type ToastType = "success" | "error" | "warning";

export type ToastData = {
  id: string;
  type: ToastType;
  title: string;
  description?: string;
};

type ToastListener = () => void;

let toasts: ToastData[] = [];
let nextId = 1;
const listeners = new Set<ToastListener>();
const timers = new Map<string, number>();

function emit() {
  listeners.forEach((listener) => listener());
}

export function subscribeToasts(listener: ToastListener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function readToasts() {
  return toasts;
}

export function closeToast(id: string) {
  const timer = timers.get(id);
  if (timer) {
    window.clearTimeout(timer);
    timers.delete(id);
  }
  toasts = toasts.filter((toast) => toast.id !== id);
  emit();
}

export function addToast(toast: Omit<ToastData, "id">) {
  const id = String(nextId++);
  toasts = [...toasts, { ...toast, id }];
  emit();
  const timeoutMs = toast.type === "success" ? 5000 : 8000;
  timers.set(id, window.setTimeout(() => closeToast(id), timeoutMs));
  return id;
}
