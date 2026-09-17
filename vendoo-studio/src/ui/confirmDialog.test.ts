import { afterEach, describe, expect, it } from "vitest";
import {
  confirmDialog,
  isConfirmDialogOpen,
  readConfirmDialogState,
  registerConfirmDialogHost,
  resolveConfirmDialogCopy,
  respondToConfirmDialog,
} from "./confirmDialog";

let unregister: (() => void) | null = null;

afterEach(() => {
  unregister?.();
  unregister = null;
});

describe("confirmDialog", () => {
  it("declines immediately when no host is mounted", async () => {
    await expect(confirmDialog("Delete listing?")).resolves.toBe(false);
  });

  it("resolves with the user's answer and returns to idle", async () => {
    unregister = registerConfirmDialogHost();
    const answer = confirmDialog("Delete listing?", { variant: "destructive", confirmLabel: " Delete " });
    const state = readConfirmDialogState();
    expect(state.status === "confirming" && state.confirmLabel).toBe("Delete");
    await expect(confirmDialog("Second prompt?")).resolves.toBe(false);
    respondToConfirmDialog(true);
    await expect(answer).resolves.toBe(true);
    expect(isConfirmDialogOpen()).toBe(false);
  });

  it("declines a pending prompt when the host unmounts", async () => {
    unregister = registerConfirmDialogHost();
    const answer = confirmDialog("Clear listing?");
    unregister();
    unregister = null;
    await expect(answer).resolves.toBe(false);
  });
});

describe("resolveConfirmDialogCopy", () => {
  it("uses the question line as the title", () => {
    expect(resolveConfirmDialogCopy("This removes photos.\nDelete listing?")).toEqual({
      title: "Delete listing?",
      description: "This removes photos.",
    });
  });

  it("splits inline questions and handles plain statements", () => {
    expect(resolveConfirmDialogCopy("Overwrite draft? Vendoo keeps no history.")).toEqual({
      title: "Overwrite draft?",
      description: "Vendoo keeps no history.",
    });
    expect(resolveConfirmDialogCopy("Sends to Vendoo.")).toEqual({ title: "Confirm action", description: "Sends to Vendoo." });
  });
});
