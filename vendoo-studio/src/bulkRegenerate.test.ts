import { describe, expect, it, vi } from "vitest";
import {
  bulkPriceDrops,
  bulkRegenerateToast,
  bulkRegenerateWarning,
  effectiveDropPercent,
  followListingGeneration,
  listingCanRegenerate,
  mergeRegenerateIds,
  parseGenerationSse,
  priceAfterPercent,
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
  it("says generated for fresh drafts from a bulk upload", () => {
    expect(bulkRegenerateToast({
      completed: ["a", "b", "c"],
      failed: [],
      skipped: [],
      cancelled: false,
    }, "generate").title).toBe("Generated 3 listings");
    expect(bulkRegenerateToast({
      completed: ["a"],
      failed: [{ id: "b", message: "model busy" }],
      skipped: [],
      cancelled: false,
    }, "generate").title).toBe("Generated 1 listing. 1 could not be generated.");
  });

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

describe("bulkPriceDrops", () => {
  const listings = [
    { id: "priced", price: 40 },
    { id: "small", price: 14 },
    { id: "bare", price: null },
  ];

  it("keeps every price when that is the choice", () => {
    expect(bulkPriceDrops(listings, { kind: "keep" }).size).toBe(0);
  });

  it("marks each priced listing down by the same percent, rounded down", () => {
    expect(priceAfterPercent(14, 10)).toBe(12);
    expect(effectiveDropPercent(14, 12)).toBe(14.3);
    const drops = bulkPriceDrops(listings, { kind: "percent", percent: 10 });
    expect(drops.get("priced")).toEqual({ price: 36, percent: 10, mode: "percent" });
    expect(drops.get("small")).toEqual({ price: 12, percent: 14.3, mode: "percent" });
    expect(drops.has("bare")).toBe(false);
  });

  it("skips a cut that cannot move a whole-dollar price", () => {
    expect(bulkPriceDrops([{ id: "one", price: 1 }], { kind: "percent", percent: 10 }).size).toBe(0);
  });

  it("uses each listing's own suggestion and skips one that would not fall", () => {
    const suggestions = new Map([
      ["priced", { price: 33, percent: 17.5, mode: "percent" as const }],
      ["small", { price: 14, percent: 0, mode: "comps" as const }],
    ]);
    const drops = bulkPriceDrops(listings, { kind: "suggested" }, suggestions);
    expect([...drops.keys()]).toEqual(["priced"]);
    expect(drops.get("priced")?.price).toBe(33);
  });
});

describe("runBulkRegenerate", () => {
  it("runs three generation streams concurrently and refills a free slot", async () => {
    const gates = new Map(["a", "b", "c", "d"].map((id) => [id, deferred()]));
    const started: string[] = [];
    const settled: string[] = [];
    const phases = new Map<string, string>();
    const run = runBulkRegenerate(["a", "b", "c", "d"], deps({
      generate: (id) => followListingGeneration(id, {
        fetchImpl: async () => new Response(new ReadableStream({
          async start(controller) {
            started.push(id);
            await gates.get(id)!.promise;
            controller.enqueue(new TextEncoder().encode(`data: {"title":"${id}"}\n\ndata: [DONE]\n\n`));
            controller.close();
          },
        })),
      }),
    }), {
      cancelled: () => false,
      concurrency: 3,
      onProgress: ({ id, phase }) => phases.set(id, phase),
      onSettled: (id) => settled.push(id),
    });
    await vi.waitFor(() => expect(started).toEqual(["a", "b", "c"]));
    expect([...phases.values()]).toEqual(["generating", "generating", "generating"]);
    gates.get("b")!.resolve();
    await vi.waitFor(() => expect(started).toEqual(["a", "b", "c", "d"]));
    expect(settled).toEqual(["b"]);
    for (const gate of gates.values()) gate.resolve();
    const result = await run;
    expect([...result.completed].sort()).toEqual(["a", "b", "c", "d"]);
    expect(result.failed).toEqual([]);
    expect([...settled].sort()).toEqual(["a", "b", "c", "d"]);
  });

  it("keeps a worker occupied until its marketplace fields finish", async () => {
    const fill = deferred();
    const started: string[] = [];
    let polls = 0;
    const run = runBulkRegenerate(["a", "b", "c"], deps({
      generate: async (id) => { started.push(id); },
      pending: async (id) => id === "a" && polls++ === 0,
      sleep: () => fill.promise,
    }), { cancelled: () => false, concurrency: 2 });
    await vi.waitFor(() => expect(started).toEqual(["a", "b", "c"]));
    let finished = false;
    void run.then(() => { finished = true; });
    await Promise.resolve();
    expect(finished).toBe(false);
    fill.resolve();
    expect([...(await run).completed].sort()).toEqual(["a", "b", "c"]);
  });

  it("stops waiting listings and lets every active listing finish", async () => {
    const gate = deferred();
    const started: string[] = [];
    let cancel = false;
    const run = runBulkRegenerate(["a", "b", "c", "d"], deps({
      generate: async (id) => {
        started.push(id);
        await gate.promise;
      },
    }), { cancelled: () => cancel, concurrency: 3 });
    await vi.waitFor(() => expect(started).toEqual(["a", "b", "c"]));
    cancel = true;
    gate.resolve();
    const result = await run;
    expect(started).toEqual(["a", "b", "c"]);
    expect([...result.completed].sort()).toEqual(["a", "b", "c"]);
    expect(result.cancelled).toBe(true);
  });

  it("continues concurrent work when one listing fails", async () => {
    const result = await runBulkRegenerate(["a", "b", "c", "d"], deps({
      generate: async (id) => {
        if (id === "b") throw new Error("model busy");
      },
    }), { cancelled: () => false, concurrency: 3 });
    expect([...result.completed].sort()).toEqual(["a", "c", "d"]);
    expect(result.failed).toEqual([{ id: "b", message: "model busy" }]);
  });

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

  it("drops the price before the rewrite and skips a listing whose drop fails", async () => {
    const order: string[] = [];
    const result = await runBulkRegenerate(["a", "b"], deps({
      willDrop: () => true,
      drop: async (id) => {
        order.push(`drop:${id}`);
        if (id === "a") throw new Error("price unchanged");
      },
      reset: async (id) => {
        order.push(`reset:${id}`);
      },
      generate: async (id) => {
        order.push(`generate:${id}`);
      },
    }), { cancelled: () => false });

    expect(order).toEqual(["drop:a", "drop:b", "reset:b", "generate:b"]);
    expect(result.failed).toEqual([{ id: "a", message: "price unchanged" }]);
    expect(result.completed).toEqual(["b"]);
  });

  it("still rewrites a listing whose price already dropped when cancel lands", async () => {
    let cancel = false;
    const order: string[] = [];
    const result = await runBulkRegenerate(["a", "b"], deps({
      willDrop: (id) => id === "a",
      drop: async (id) => {
        order.push(`drop:${id}`);
        cancel = true;
      },
      reset: async (id) => {
        order.push(`reset:${id}`);
      },
      generate: async (id) => {
        order.push(`generate:${id}`);
      },
    }), { cancelled: () => cancel });

    expect(order).toEqual(["drop:a", "reset:a", "generate:a"]);
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

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => { resolve = done; });
  return { promise, resolve };
}
