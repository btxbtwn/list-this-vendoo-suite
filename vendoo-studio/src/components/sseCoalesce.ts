export type SseParts = { content: string; thinking: string; status: string };

/** Batch window for streamed SSE events, in milliseconds. */
const SSE_FLUSH_MS = 50;

/** Collapse a burst of SSE events into one call per event type.
 *
 * The server streams one event per token, and every event carries the whole
 * message so far. Each call re-scans that cumulative text in
 * stableStreamingText and re-renders the chat, so a long reply costs O(n^2)
 * scanning and hundreds of renders -- enough memory churn on a small machine
 * to get the WebKit content process killed mid-reply. Only the newest event of
 * each type carries new information, so a window collapses to one call per
 * type with no loss.
 */
export function coalesceSseEvents(
  onEvent: (event: string, parts: SseParts) => void,
  intervalMs: number = SSE_FLUSH_MS,
): { push: (event: string, parts: SseParts) => void; flush: () => void } {
  const pendingTypes = new Set<string>();
  let pendingParts: SseParts | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let started = false;

  const flush = () => {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
    const parts = pendingParts;
    if (!pendingTypes.size || !parts) return;
    const types = [...pendingTypes];
    pendingTypes.clear();
    pendingParts = null;
    // Insertion order, so thinking/status still land before the content they precede.
    for (const type of types) onEvent(type, parts);
  };

  return {
    push(event, parts) {
      pendingTypes.add(event);
      pendingParts = parts;
      // Paint the first token immediately; batch the burst that follows.
      if (!started) {
        started = true;
        flush();
        return;
      }
      if (timer === null) timer = setTimeout(flush, intervalMs);
    },
    flush,
  };
}
