type ConfirmVariant = "default" | "destructive";

type ConfirmState =
  | { status: "idle" }
  | {
      status: "confirming";
      message: string;
      variant: ConfirmVariant;
      resolve: (value: boolean) => void;
    };

let state: ConfirmState = { status: "idle" };
let hostRegistered = false;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((listener) => listener());
}

export function subscribeConfirmDialog(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function readConfirmDialogState(): ConfirmState {
  return state;
}

export function isConfirmDialogOpen() {
  return state.status === "confirming";
}

export function registerConfirmDialogHost() {
  hostRegistered = true;
  return () => {
    hostRegistered = false;
    if (state.status === "confirming") {
      const resolve = state.resolve;
      state = { status: "idle" };
      resolve(false);
      emit();
    }
  };
}

export function confirmDialog(message: string, options?: { variant?: ConfirmVariant }): Promise<boolean> {
  if (!hostRegistered) return Promise.resolve(false);
  if (state.status === "confirming") return Promise.resolve(false);

  return new Promise((resolve) => {
    state = {
      status: "confirming",
      message,
      variant: options?.variant ?? "default",
      resolve,
    };
    emit();
  });
}

export function respondToConfirmDialog(value: boolean) {
  if (state.status !== "confirming") return;
  const resolve = state.resolve;
  state = { status: "idle" };
  resolve(value);
  emit();
}

export function resolveConfirmDialogCopy(message: string): { title: string; description: string | null } {
  const normalizedMessage = message.trim();
  const lines = normalizedMessage.split("\n");
  const questionLineIndex = lines.findIndex((line) => line.trim().endsWith("?"));

  if (questionLineIndex >= 0) {
    const title = lines[questionLineIndex]!.trim();
    const description = lines
      .filter((_, index) => index !== questionLineIndex)
      .join("\n")
      .trim();
    return { title, description: description || null };
  }

  const questionMarkIndex = normalizedMessage.indexOf("?");
  if (questionMarkIndex >= 0) {
    return {
      title: normalizedMessage.slice(0, questionMarkIndex + 1).trim(),
      description: normalizedMessage.slice(questionMarkIndex + 1).trim() || null,
    };
  }

  return {
    title: "Confirm action",
    description: normalizedMessage || "This action requires your confirmation.",
  };
}
