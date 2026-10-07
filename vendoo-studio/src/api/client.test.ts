import { afterEach, describe, expect, it, vi } from "vitest";
import { api, errorMessage } from "./client";

describe("errorMessage", () => {
  it("prefers a string detail", () => {
    expect(errorMessage({ detail: "Conversation not found" }, "fallback")).toBe("Conversation not found");
  });

  it("joins FastAPI validation errors", () => {
    const body = { detail: [{ msg: "field required" }, { message: "too long" }, "bad value"] };
    expect(errorMessage(body, "fallback")).toBe("field required; too long; bad value");
  });

  it("reads structured detail objects", () => {
    expect(errorMessage({ detail: { message: "Chrome is not connected" } }, "fallback")).toBe("Chrome is not connected");
    expect(errorMessage({ detail: { errors: [{ message: "Price is required" }, { msg: "Add photos" }] } }, "fallback"))
      .toBe("Price is required; Add photos");
  });

  it("falls back to a top-level message, then the fallback", () => {
    expect(errorMessage({ message: "Upstream failed" }, "fallback")).toBe("Upstream failed");
    expect(errorMessage({ detail: "   " }, "Request failed: 500")).toBe("Request failed: 500");
    expect(errorMessage(null, "Request failed: 502")).toBe("Request failed: 502");
  });
});

describe("Listing action deadlines", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("aborts a stalled request and allows the next attempt to succeed", async () => {
    vi.useFakeTimers();
    let signal: AbortSignal | undefined;
    const fetch = vi.fn().mockImplementationOnce((_url: string, options: RequestInit) => {
      signal = options.signal as AbortSignal;
      return new Promise((_resolve, reject) => {
        signal!.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
      });
    }).mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, url: "https://web.vendoo.co/app/item/item1", via: "chrome" })));
    vi.stubGlobal("fetch", fetch);

    const first = expect(api.jobs.open("job1")).rejects.toThrow("you do not need to restart Studio");
    await vi.advanceTimersByTimeAsync(25000);
    await first;
    expect(signal?.aborted).toBe(true);
    await expect(api.jobs.open("job1")).resolves.toMatchObject({ ok: true, via: "chrome" });
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("preserves server errors and clears the deadline", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: "No Vendoo draft is available yet." }), { status: 400 },
    )));
    await expect(api.jobs.open("job1")).rejects.toThrow("No Vendoo draft is available yet.");
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each([
    ["reset", () => api.conversations.reset("listing1", { keepInputs: true })],
    ["price confirmation", () => api.listings.applyPriceDrop("listing1", { price: 20, mode: "custom" })],
  ] as const)("releases a stalled %s without starting another write", async (_label, action) => {
    vi.useFakeTimers();
    const fetch = vi.fn().mockImplementation((_url: string, options: RequestInit) =>
      new Promise((_resolve, reject) => {
        options.signal!.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
      }),
    );
    vi.stubGlobal("fetch", fetch);
    const failure = expect(action()).rejects.toThrow("you do not need to restart Studio");
    await vi.advanceTimersByTimeAsync(30000);
    await failure;
    expect(fetch).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("Send to Vendoo", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("prepares and queues the clicked send without another approval", async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ review_id: "prepared-1" })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "job-1", status: "queued" })));
    vi.stubGlobal("fetch", fetch);

    await expect(api.jobs.send("listing-1")).resolves.toMatchObject({ id: "job-1", status: "queued" });
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch.mock.calls[0][0]).toContain("/jobs/send-preview");
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ conversation_id: "listing-1" });
    expect(fetch.mock.calls[1][0]).toContain("/jobs/send");
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ conversation_id: "listing-1", review_id: "prepared-1" });
  });

  it("does not enqueue when preparing the draft fails", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: "Chrome disconnected" }), { status: 502 },
    ));
    vi.stubGlobal("fetch", fetch);

    await expect(api.jobs.send("listing-1")).rejects.toThrow("Chrome disconnected");
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("surfaces a changed listing without retrying or starting another send", async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ review_id: "prepared-1" })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "This listing changed" }), { status: 409 }));
    vi.stubGlobal("fetch", fetch);

    await expect(api.jobs.send("listing-1")).rejects.toThrow("This listing changed");
    expect(fetch).toHaveBeenCalledTimes(2);
  });
});

describe("Listing evidence", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("preserves unknown shipping amounts and observed zero buyer-response counts", async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ shipping: null, engagement: [], sale_snapshots: [] }))));
    vi.stubGlobal("fetch", fetch);
    await api.evidence.shipping("listing1", { shipped_on: "2026-10-01", packed_weight_oz: 12,
      length_in: null, width_in: null, height_in: null, postage_paid: null, currency: "USD" });
    await api.evidence.engagement("listing1", { marketplace: "ebay", start_date: "2026-09-01", end_date: "2026-10-01",
      impressions: 100, views: 0, offers: null, returns: null, return_reason: null });
    const sent = fetch.mock.calls.map((call) => JSON.parse(call[1].body));
    expect(sent[0].shipping.postage_paid).toBeNull();
    expect(sent[1].views).toBe(0);
    expect(sent[1].offers).toBeNull();
  });

  it("removes only the selected marketplace reporting period", async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ shipping: null, engagement: [], sale_snapshots: [] }))));
    vi.stubGlobal("fetch", fetch);
    await api.evidence.removeEngagement("listing1", { marketplace: "ebay", start_date: "2026-09-01", end_date: "2026-10-01",
      impressions: null, views: 0, offers: null, returns: null, return_reason: null });
    expect(fetch.mock.calls[0][0]).toContain("/listing1/evidence/engagement?marketplace=ebay&start_date=2026-09-01&end_date=2026-10-01");
    expect(fetch.mock.calls[0][1].method).toBe("DELETE");
  });
});
