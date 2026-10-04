/**
 * Rewrite or generate several listings from their photos and item details.
 * Each listing uses the same reset as Regenerate (keep photos, measurements,
 * flaws, COG, labels and notes) and then the generate stream. A confirmed
 * price drop is saved first, so the rewrite reuses that price. The next listing
 * waits for a worker whose stream and leftover field fill have finished.
 */

export type BulkRegenerateProgress = {
  index: number;
  total: number;
  id: string;
  phase: "dropping" | "resetting" | "generating" | "finishing";
};

export type BulkRegenerateFailure = {
  id: string;
  message: string;
};

export type BulkRegenerateResult = {
  completed: string[];
  failed: BulkRegenerateFailure[];
  /** Wipe was stopped before the rewrite, so generate never started. */
  skipped: string[];
  cancelled: boolean;
};

/** Same cuts the single-listing dialog offers, applied to every priced listing. */
export const BULK_DROP_PERCENTS = [10, 15, 20] as const;

export type BulkDropPercent = (typeof BULK_DROP_PERCENTS)[number];

export type BulkPriceChoice =
  | { kind: "keep" }
  | { kind: "percent"; percent: BulkDropPercent }
  | { kind: "suggested" };

export type BulkPriceDrop = {
  price: number;
  percent: number;
  mode: "percent" | "comps" | "custom";
};

export type BulkPriceSuggestion = BulkPriceDrop;

export type BulkRegenerateListing = {
  id: string;
  title: string;
  price: number | null;
};

/**
 * Whole dollars a stated cut lands on, rounded down.
 * Matches ``price_after_percent``: 10% off $14 is $12, not $13.
 */
export function priceAfterPercent(current: number, percent: number): number {
  if (!(current > 0) || !(percent > 0)) return 0;
  return Math.max(1, Math.floor(current * (1 - percent / 100)));
}

export function effectiveDropPercent(current: number, price: number): number {
  if (!(current > 0) || !(price > 0)) return 0;
  return Math.round((1 - price / current) * 1000) / 10;
}

/** The drops to save before rewriting. Keep, and any price that would not fall, are omitted. */
export function bulkPriceDrops(
  listings: readonly Pick<BulkRegenerateListing, "id" | "price">[],
  choice: BulkPriceChoice,
  suggestions: ReadonlyMap<string, BulkPriceSuggestion | null> = new Map(),
): Map<string, BulkPriceDrop> {
  const drops = new Map<string, BulkPriceDrop>();
  if (choice.kind === "keep") return drops;
  for (const listing of listings) {
    const current = listing.price;
    if (current == null || !(current > 0)) continue;
    if (choice.kind === "percent") {
      const price = priceAfterPercent(current, choice.percent);
      if (price >= current) continue;
      drops.set(listing.id, {
        price,
        percent: effectiveDropPercent(current, price),
        mode: "percent",
      });
      continue;
    }
    const suggested = suggestions.get(listing.id);
    if (!suggested || !(suggested.price > 0) || suggested.price >= current) continue;
    drops.set(listing.id, suggested);
  }
  return drops;
}

export type BulkRegenerateDeps = {
  /** True when this listing should be marked down before the wipe. */
  willDrop?(id: string): boolean;
  /** Save the lower price. Rejecting skips the rewrite so the old price stays. */
  drop?(id: string): Promise<void>;
  reset(id: string): Promise<void>;
  /** False when Stop dropped the wipe and this listing should stay cleared. */
  accepted(id: string): boolean;
  /** Resolve when the generate stream finishes. Reject when the rewrite fails. */
  generate(id: string): Promise<void>;
  /** True while post-generate work is still writing this listing. */
  pending(id: string): Promise<boolean>;
  sleep(ms: number): Promise<void>;
  pollMs?: number;
  /** Give up waiting on field fill so one stuck listing cannot hold the queue. */
  maxPendingPolls?: number;
};

export type BulkRegenerateControl = {
  cancelled(): boolean;
  concurrency?: number;
  onProgress?(progress: BulkRegenerateProgress): void;
  onSettled?(id: string): void;
};

export const BULK_GENERATE_CONCURRENCY = 3;

const DEFAULT_POLL_MS = 1000;
const DEFAULT_MAX_PENDING_POLLS = 600;

export function listingCanRegenerate(listing: {
  cover_photo_url?: string | null;
  settled_at?: string | null;
}): boolean {
  return Boolean(listing.cover_photo_url) && !listing.settled_at;
}

/** Suggestions come first, then the rest of the list, with each listing once. */
export function mergeRegenerateIds(
  suggestionIds: readonly string[],
  listingIds: readonly string[],
): string[] {
  const seen = new Set<string>();
  const ids: string[] = [];
  for (const id of [...suggestionIds, ...listingIds]) {
    if (!id || seen.has(id)) continue;
    seen.add(id);
    ids.push(id);
  }
  return ids;
}

/** Rewrite wipes and redoes listings; generate writes fresh drafts from a bulk upload. */
export type BulkRunMode = "rewrite" | "generate";

const MODE_WORDS: Record<BulkRunMode, { verb: string; past: string; ing: string; done: string; noun: string }> = {
  rewrite: { verb: "rewrite", past: "Rewrote", ing: "rewriting", done: "rewritten", noun: "rewrite" },
  generate: { verb: "generate", past: "Generated", ing: "generating", done: "generated", noun: "draft" },
};

export function bulkRegenerateToast(result: BulkRegenerateResult, mode: BulkRunMode = "rewrite"): {
  type: "success" | "warning" | "error";
  title: string;
  description?: string;
} {
  const words = MODE_WORDS[mode];
  const written = result.completed.length;
  const failed = result.failed.length;
  const listingWord = written === 1 ? "listing" : "listings";
  const failure = result.failed[0]?.message;
  const skipped = result.skipped.length
    ? `${result.skipped.length} stopped before the ${words.noun}.`
    : undefined;
  if (result.cancelled) {
    return {
      type: "warning",
      title: written
        ? `Stopped after ${words.ing} ${written} ${listingWord}`
        : `Stopped before a ${words.noun} finished`,
      description: failure || skipped,
    };
  }
  if (failed && written) {
    return {
      type: "warning",
      title: `${words.past} ${written} ${listingWord}. ${failed} could not be ${words.done}.`,
      description: failure,
    };
  }
  if (failed) {
    return {
      type: "error",
      title: failed === 1 ? `Could not ${words.verb} that listing` : `Could not ${words.verb} ${failed} listings`,
      description: failure,
    };
  }
  return {
    type: "success",
    title: `${words.past} ${written} ${listingWord}`,
    description: skipped,
  };
}

export function bulkRegenerateWarning(count: number): string {
  const noun = count === 1 ? "this listing" : `${count} listings`;
  const each = count === 1 ? "the listing is" : "each listing is";
  return [
    `Rewrite ${noun} from scratch?`,
    `Chat and every generated field are discarded, then ${each} written again from its photos and item details. Measurements, flaws, COG, labels and notes are kept. Vendoo stays as it is until you send again. Studio rewrites one listing at a time.`,
  ].join("\n");
}

/** Shift-click selects the range; a plain click toggles one row. */
export function toggleListingSelection(
  selected: ReadonlySet<string>,
  id: string,
  orderedIds: readonly string[],
  shift: boolean,
  anchorId: string | null,
): { selected: Set<string>; anchorId: string } {
  const next = new Set(selected);
  if (shift && anchorId && anchorId !== id) {
    const start = orderedIds.indexOf(anchorId);
    const end = orderedIds.indexOf(id);
    if (start >= 0 && end >= 0) {
      const [from, to] = start < end ? [start, end] : [end, start];
      for (const item of orderedIds.slice(from, to + 1)) next.add(item);
      return { selected: next, anchorId: id };
    }
  }
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return { selected: next, anchorId: id };
}

export async function runBulkRegenerate(
  ids: readonly string[],
  deps: BulkRegenerateDeps,
  control: BulkRegenerateControl,
): Promise<BulkRegenerateResult> {
  const result: BulkRegenerateResult = {
    completed: [],
    failed: [],
    skipped: [],
    cancelled: false,
  };
  const pollMs = deps.pollMs ?? DEFAULT_POLL_MS;
  const maxPendingPolls = deps.maxPendingPolls ?? DEFAULT_MAX_PENDING_POLLS;

  async function runListing(index: number) {
    const id = ids[index]!;
    const progress = { index, total: ids.length, id };
    if (deps.willDrop?.(id)) {
      control.onProgress?.({ ...progress, phase: "dropping" });
      try {
        await deps.drop?.(id);
      } catch (err) {
        result.failed.push({ id, message: errorText(err) });
        return;
      }
      // The price is already the new one. Cancel still rewrites this listing
      // so the draft is written at the dropped price.
    }
    control.onProgress?.({ ...progress, phase: "resetting" });
    try {
      await deps.reset(id);
    } catch (err) {
      result.failed.push({ id, message: errorText(err) });
      return;
    }
    if (!deps.accepted(id)) {
      result.skipped.push(id);
      return;
    }
    // Cancel during the wipe still rewrites this listing. Stopping here would
    // leave the chat and generated fields discarded with nothing written back.
    control.onProgress?.({ ...progress, phase: "generating" });
    try {
      await deps.generate(id);
    } catch (err) {
      result.failed.push({ id, message: errorText(err) });
      return;
    }
    result.completed.push(id);
    control.onProgress?.({ ...progress, phase: "finishing" });
    let polls = 0;
    while (await deps.pending(id)) {
      polls += 1;
      if (polls >= maxPendingPolls) break;
      await deps.sleep(pollMs);
    }
  }

  let nextIndex = 0;
  async function worker() {
    while (nextIndex < ids.length && !control.cancelled()) {
      const index = nextIndex++;
      try {
        await runListing(index);
      } finally {
        control.onSettled?.(ids[index]!);
      }
    }
  }
  const concurrency = Math.min(ids.length, Math.max(1, Math.floor(control.concurrency ?? 1)));
  await Promise.all(Array.from({ length: concurrency }, () => worker()));
  result.cancelled ||= control.cancelled();
  return result;
}

function errorText(err: unknown): string {
  if (err instanceof Error && err.message.trim()) return err.message.trim();
  return "Could not rewrite this listing.";
}

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export async function followListingGeneration(
  convId: string,
  options: {
    fetchImpl?: FetchLike;
    sleep?: (ms: number) => Promise<void>;
    maxAttempts?: number;
    onStarted?: () => void;
  } = {},
): Promise<void> {
  const fetchImpl = options.fetchImpl ?? fetch;
  const sleep = options.sleep ?? ((ms: number) => new Promise((resolve) => setTimeout(resolve, ms)));
  const maxAttempts = options.maxAttempts ?? 20;
  let started = false;
  let announced = false;
  let attempt = 0;
  let lastError = "Listing generation did not finish.";

  while (attempt < maxAttempts) {
    attempt += 1;
    const resume = started;
    const url = `/api/conversations/${encodeURIComponent(convId)}/generate${resume ? "?resume=1" : ""}`;
    let res: Response;
    try {
      res = await fetchImpl(url, {
        method: "POST",
        headers: { Accept: "text/event-stream" },
        cache: "no-store",
      });
    } catch (err) {
      lastError = errorText(err);
      await sleep(Math.min(1500 * attempt, 5000));
      continue;
    }
    if (!res.ok) {
      throw new Error(await responseError(res));
    }
    started = true;
    if (!announced) {
      announced = true;
      options.onStarted?.();
    }
    let content = "";
    let sawDone = false;
    try {
      ({ content, sawDone } = await readGenerationSse(res));
    } catch (err) {
      lastError = errorText(err);
      await sleep(Math.min(1500 * attempt, 5000));
      continue;
    }
    if (!sawDone) {
      lastError = "Listing generation did not finish.";
      await sleep(Math.min(1500 * attempt, 5000));
      continue;
    }
    const trimmed = content.trim();
    if (/^error:/i.test(trimmed)) {
      throw new Error(trimmed.replace(/^error:\s*/i, "") || "Could not rewrite this listing.");
    }
    if (!trimmed) {
      throw new Error("Listing generation did not finish.");
    }
    return;
  }
  throw new Error(lastError);
}

async function responseError(res: Response): Promise<string> {
  const fallback = `Could not rewrite this listing (${res.status}).`;
  try {
    const body = await res.json() as { detail?: unknown; message?: unknown };
    if (typeof body?.detail === "string" && body.detail.trim()) return body.detail.trim();
    if (Array.isArray(body?.detail)) {
      const messages = body.detail
        .map((item) => {
          if (typeof item === "string") return item;
          if (item && typeof item === "object" && "msg" in item) return String((item as { msg?: unknown }).msg || "");
          return "";
        })
        .filter(Boolean);
      if (messages.length) return messages.join("; ");
    }
    if (typeof body?.message === "string" && body.message.trim()) return body.message.trim();
  } catch {
    /* the body was not JSON */
  }
  return fallback;
}

export function parseGenerationSse(text: string): { content: string; sawDone: boolean } {
  let content = "";
  let sawDone = false;
  let eventType = "message";
  for (const line of text.split("\n")) {
    const next = applyGenerationSseLine(line, eventType);
    eventType = next.eventType;
    if (next.done) sawDone = true;
    if (next.text) content += next.text;
  }
  return { content, sawDone };
}

async function readGenerationSse(res: Response): Promise<{ content: string; sawDone: boolean }> {
  const reader = res.body?.getReader();
  if (!reader) return parseGenerationSse(await res.text());
  const decoder = new TextDecoder();
  let buffer = "";
  let content = "";
  let sawDone = false;
  let eventType = "message";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      const next = applyGenerationSseLine(line, eventType);
      eventType = next.eventType;
      if (next.done) sawDone = true;
      if (next.text) content += next.text;
    }
  }
  if (buffer) {
    const next = applyGenerationSseLine(buffer, eventType);
    if (next.done) sawDone = true;
    if (next.text) content += next.text;
  }
  return { content, sawDone };
}

function applyGenerationSseLine(
  raw: string,
  eventType: string,
): { eventType: string; done: boolean; text: string } {
  const line = raw.replace(/\r$/, "");
  if (!line) return { eventType: "message", done: false, text: "" };
  if (line.startsWith(":")) return { eventType, done: false, text: "" };
  if (line.startsWith("event:")) {
    return { eventType: line.slice(6).trim() || "message", done: false, text: "" };
  }
  if (!line.startsWith("data:")) return { eventType, done: false, text: "" };
  const chunk = line.startsWith("data: ") ? line.slice(6) : line.slice(5);
  if (chunk === "[DONE]") return { eventType: "message", done: true, text: "" };
  if (eventType !== "message") return { eventType, done: false, text: "" };
  return { eventType, done: false, text: chunk };
}
