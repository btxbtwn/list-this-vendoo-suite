import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import {
  followListingGeneration,
  runBulkRegenerate,
  type BulkRegenerateProgress,
  type BulkRegenerateResult,
  type BulkRunMode,
} from "../bulkRegenerate";
import { refreshAfterReset } from "./ClearListingButton";
import {
  chatOwnsGeneration,
  clearChatGenerating,
  isChatResetting,
  markChatGenerating,
  markChatResetting,
  resetChatLive,
} from "./ChatPanel";

export type BulkRegenerateRun = BulkRegenerateProgress & {
  cancelRequested: boolean;
  mode: BulkRunMode;
  /** The listing being worked on, as the seller named it. */
  title: string;
};

export type BulkRegenerate = ReturnType<typeof useBulkRegenerate>;

/**
 * Rewrites the given listings one at a time, or generates fresh drafts the
 * same way. Lives in App, so collapsing the sidebar does not drop a run. The open chat hears about the
 * run after the server has registered it, and attaches to that same stream.
 */
export function useBulkRegenerate(chatOpen: (id: string) => boolean) {
  const queryClient = useQueryClient();
  const chatOpenRef = useRef(chatOpen);
  useEffect(() => {
    chatOpenRef.current = chatOpen;
  }, [chatOpen]);
  const cancelRef = useRef(false);
  const runningRef = useRef(false);
  const [run, setRun] = useState<BulkRegenerateRun | null>(null);
  const [pendingIds, setPendingIds] = useState<string[]>([]);

  async function start(
    ids: string[],
    titles: ReadonlyMap<string, string>,
    mode: BulkRunMode = "rewrite",
  ): Promise<BulkRegenerateResult | null> {
    if (runningRef.current || ids.length === 0) return null;
    runningRef.current = true;
    cancelRef.current = false;
    const marked = new Set<string>();
    const titleOf = (id: string) => titles.get(id) || "listing";
    setPendingIds(ids);
    setRun({
      index: 0,
      total: ids.length,
      id: ids[0] || "",
      phase: "resetting",
      cancelRequested: false,
      mode,
      title: titleOf(ids[0] || ""),
    });
    try {
      return await runBulkRegenerate(ids, {
        async reset(id) {
          // A fresh draft has no chat or generated fields to wipe.
          if (mode === "generate") return;
          const showWipe = chatOpenRef.current(id);
          resetChatLive(id);
          if (showWipe) {
            markChatResetting(id, true);
            marked.add(id);
          }
          try {
            await api.conversations.reset(id, { keepInputs: true });
            await queryClient.cancelQueries({ queryKey: ["listing", id] });
            await queryClient.cancelQueries({ queryKey: ["messages", id] });
            const [listing, messages] = await Promise.all([
              api.listings.get(id),
              api.conversations.messages(id),
            ]);
            queryClient.setQueryData(["listing", id], listing);
            queryClient.setQueryData(["messages", id], messages);
            await refreshAfterReset(queryClient, id);
          } catch (err) {
            if (showWipe) markChatResetting(id, false);
            marked.delete(id);
            throw err;
          }
        },
        accepted(id) {
          return !marked.has(id) || isChatResetting(id);
        },
        async generate(id) {
          let started = false;
          try {
            await followListingGeneration(id, {
              onStarted: () => {
                started = true;
                markChatGenerating(id);
              },
            });
          } finally {
            if (!started) {
              // The wipe was already on screen and the rewrite never began.
              markChatResetting(id, false);
            } else if (!chatOwnsGeneration(id)) {
              clearChatGenerating(id);
            }
          }
        },
        async pending(id) {
          try {
            const activity = await api.conversations.activity(id);
            return activity.busy;
          } catch {
            return false;
          }
        },
        sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
      }, {
        cancelled: () => cancelRef.current,
        onProgress: (progress) => {
          setPendingIds(ids.slice(progress.index));
          setRun({ ...progress, cancelRequested: cancelRef.current, mode, title: titleOf(progress.id) });
        },
      });
    } finally {
      runningRef.current = false;
      setRun(null);
      setPendingIds([]);
    }
  }

  function cancel() {
    cancelRef.current = true;
    setRun((current) => (current ? { ...current, cancelRequested: true } : current));
  }

  return {
    running: run != null,
    run,
    pendingIds,
    start,
    cancel,
  };
}
