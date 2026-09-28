import { describe, expect, it, vi } from "vitest";
import {
  bulkRegenerateToast,
  bulkRegenerateWarning,
  followListingGeneration,
  listingCanRegenerate,
  mergeRegenerateIds,
  parseGenerationSse,
  runBulkRegenerate,
  toggleListingSelection,
  type BulkRegenerateDeps,
} from "./bulkRegenerate";

function deps(overrides: Partial<BulkRegenerateDeps> = {}): BulkRegenerateDeps {
  return {
    reset: async () => {},
    accepted: () => true,
    generate: async () => {},
    pending: async () => false,
    sleep: async () => {},
    pollMs: 0,
    maxPendingPolls: 5,
    ...overrides,
  };
}

describe("listingCanRegenerate", () => {
  it("requires local photos and an unsettled listing", () => {
    expect(listingCanRegenerate({ cover_photo_url: "/api/photos/1", settled_at: null })).toBe(true);
    expect(listingCanRegenerate({ cover_photo_url: null, settled_at: null })).toBe(false);
    expect(listingCanRegenerate({ cover_photo_url: "/api/photos/1", settled_at: "2026-09-01" })).toBe(false);
  });
});

describe("mergeRegenerateIds", () => {
  it("keeps suggestion listings first and drops duplicates", () => {
    expect(mergeRegenerateIds(["s1", "s2"], ["a", "s1", "b"])).toEqual(["s1", "s2", "a", "b"]);
  });
});

describe("bulkRegenerateWarning", () => {
  it("names one listing and a count of many", () => {
    expect(bulkRegenerateWarning(1)).toContain("Rewrite this listing from scratch?");
    expect(bulkRegenerateWarning(4)).toContain("Rewrite 4 listings from scratch?");
    expect(bulkRegenerateWarning(4)).toContain("one listing at a time");
  });
});

describe("bulkRegenerateToast", () => {
  it("reports a full rewrite, a partial failure, and a stop", () => {
    expect(bulkRegenerateToast({
      completed: ["a", "b"],
      failed: [],
      skipped: [],
      cancelled: false,
    }).title).toBe("Rewrote 2 listings");
    expect(bulkRegenerateToast({
      completed: ["a"],
      failed: [{ id: "b", message: "model busy" }],
      skipped: [],
      cancelled: false,
    })).toMatchObject({
      type: "warning",
      title: "Rewrote 1 listing. 1 could not be rewritten.",
      description: "model busy",
    });
    expect(bulkRegenerateToast({
      completed: ["a"],
      failed: [],
      skipped: [],
      cancelled: true,
    }).title).toBe("Stopped after rewriting 1 listing");
  });
});

describe("toggleListingSelection", () => {
  const ordered = ["a", "b", "c", "d"];

  it("toggles a single row and moves the anchor", () => {
    const first = toggleListingSelection(new Set(), "b", ordered, false, null);
    expect([...first.selected]).toEqual(["b"]);
    const second = toggleListingSelection(first.selected, "b", ordered, false, first.anchorId);
    expect(second.selected.size).toBe(0);
    expect(second.anchorId).toBe("b");
  });

  it("shift-click selects the inclusive range", () => {
    const anchored = toggleListingSelection(new Set(), "b", ordered, false, null);
    const ranged = toggleListingSelection(anchored.selected, "d", ordered, true, anchored.anchorId);
    expect([...ranged.selected]).toEqual(["b", "c", "d"]);
  });
});

describe("runBulkRegenerate", () => {
  it("rewrites listings one at a time and waits for field fill", async () => {
    const order: string[] = [];
    let pending = true;
    const result = await runBulkRegenerate(["a", "b"], deps({
      reset: async (id) => {
        order.push(`reset:${id}`);
      },
      generate: async (id) => {
        order.push(`generate:${id}`);
        pending = true;
      },
      pending: async () => {
        if (!pending) return false;
        pending = false;
        return true;
      },
    }), { cancelled: () => false });

    expect(order).toEqual(["reset:a", "generate:a", "reset:b", "generate:b"]);
    expect(result.completed).toEqual(["a", "b"]);
    expect(result.cancelled).toBe(false);
  });

  it("continues after one listing fails", async () => {
    const result = await runBulkRegenerate(["a", "b"], deps({
      generate: async (id) => {
        if (id === "a") throw new Error("model busy");
      },
    }), { cancelled: () => false });

    expect(result.completed).toEqual(["b"]);
    expect(result.failed).toEqual([{ id: "a", message: "model busy" }]);
  });

  it("skips a listing whose wipe was stopped", async () => {
    const generated: string[] = [];
    const result = await runBulkRegenerate(["a", "b"], deps({
      accepted: (id) => id !== "a",
      generate: async (id) => {
        generated.push(id);
      },
    }), { cancelled: () => false });

    expect(generated).toEqual(["b"]);
    expect(result.skipped).toEqual(["a"]);
    expect(result.completed).toEqual(["b"]);
  });

  it("does not start the next listing after cancel", async () => {
    let cancel = false;
    const generated: string[] = [];
    const result = await runBulkRegenerate(["a", "b"], deps({
      generate: async (id) => {
        generated.push(id);
        cancel = true;
      },
    }), { cancelled: () => cancel });

    expect(generated).toEqual(["a"]);
    expect(result.completed).toEqual(["a"]);
    expect(result.cancelled).toBe(true);
  });

  it("still rewrites a listing that was wiped before cancel landed", async () => {
    let cancel = false;
    const generated: string[] = [];
    const result = await runBulkRegenerate(["a", "b"], deps({
      reset: async () => {
        cancel = true;
      },
      generate: async (id) => {
        generated.push(id);
      },
    }), { cancelled: () => cancel });

    expect(generated).toEqual(["a"]);
    expect(result.completed).toEqual(["a"]);
    expect(result.cancelled).toBe(true);
  });
});

describe("followListingGeneration", () => {
  it("resolves when the stream finishes with listing text", async () => {
    const started = vi.fn();
    await followListingGeneration("conv-1", {
      onStarted: started,
      fetchImpl: async () => sseResponse("data: {\"title\":\"Coat\"}\n\ndata: [DONE]\n\n"),
    });
    expect(started).toHaveBeenCalledOnce();
  });

  it("rejects a stream that reports an error", async () => {
    await expect(followListingGeneration("conv-1", {
      fetchImpl: async () => sseResponse("data: Error: no photos\n\ndata: [DONE]\n\n"),
    })).rejects.toThrow("no photos");
  });

  it("retries a dropped stream against the run already in progress", async () => {
    const urls: string[] = [];
    let calls = 0;
    await followListingGeneration("conv-1", {
      sleep: async () => {},
      fetchImpl: async (url) => {
        urls.push(url);
        calls += 1;
        if (calls === 1) return sseResponse("data: partial");
        return sseResponse("data: {\"title\":\"Coat\"}\n\ndata: [DONE]\n\n");
      },
    });
    expect(urls[0]).toBe("/api/conversations/conv-1/generate");
    expect(urls[1]).toBe("/api/conversations/conv-1/generate?resume=1");
  });

  it("does not treat an HTTP error as a finished rewrite", async () => {
    await expect(followListingGeneration("conv-1", {
      fetchImpl: async () => new Response(JSON.stringify({ detail: "No photos to generate from." }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      }),
    })).rejects.toThrow("No photos to generate from.");
  });
});

describe("parseGenerationSse", () => {
  it("ignores status frames and keepalives", () => {
    const parsed = parseGenerationSse(
      ": keepalive\n\nevent: status\ndata: Analyzing photos…\n\ndata: {\"title\":\"Coat\"}\n\ndata: [DONE]\n\n",
    );
    expect(parsed.sawDone).toBe(true);
    expect(parsed.content).toBe("{\"title\":\"Coat\"}");
  });
});

function sseResponse(body: string, status = 200): Response {
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(body));
      controller.close();
    },
  });
  return new Response(stream, {
    status,
    headers: { "Content-Type": "text/event-stream" },
  });
}
