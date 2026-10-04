import { MutationObserver, onlineManager } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { createStudioQueryClient } from "./queryClient";

afterEach(() => {
  onlineManager.setOnline(true);
});

it("starts a confirmed local action even when the webview reports offline", async () => {
  onlineManager.setOnline(false);
  const client = createStudioQueryClient();
  const confirm = vi.fn().mockResolvedValue({ ok: true });
  const mutation = new MutationObserver(client, { mutationFn: confirm });
  try {
    await expect(mutation.mutate(undefined)).resolves.toEqual({ ok: true });
    expect(confirm).toHaveBeenCalledOnce();
    expect(mutation.getCurrentResult().isPaused).toBe(false);
  } finally {
    client.clear();
  }
});

it("finishes local reads and retries after reset while offline", async () => {
  onlineManager.setOnline(false);
  const client = createStudioQueryClient();
  const read = vi.fn()
    .mockRejectedValueOnce(new Error("Temporary local error"))
    .mockResolvedValueOnce({ listing: {} });
  try {
    await expect(client.fetchQuery({
      queryKey: ["listing", "regenerated"], queryFn: read, retryDelay: 0,
    })).resolves.toEqual({ listing: {} });
    expect(read).toHaveBeenCalledTimes(2);
  } finally {
    client.clear();
  }
});
