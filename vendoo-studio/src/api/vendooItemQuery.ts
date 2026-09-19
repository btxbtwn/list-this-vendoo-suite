import type { QueryClient } from "@tanstack/react-query";
import { api } from "./client";

export const vendooItemQueryKey = (jobId: string) => ["vendoo-item", jobId] as const;

/** Keep an API draft read fresh so remounts don't immediately replace it with a cache read. */
export const VENDOO_ITEM_STALE_MS = 60_000;

/** Read the Vendoo draft (API get_item, or tab scrape when resolving photos) and own the shared React Query cache. */
export async function fetchVendooItemLive(
  queryClient: QueryClient,
  jobId: string,
  opts?: { force?: boolean; resolvePhotos?: boolean },
) {
  const queryKey = vendooItemQueryKey(jobId);
  if (opts?.force) {
    await queryClient.cancelQueries({ queryKey });
    await queryClient.invalidateQueries({ queryKey, refetchType: "none" });
  }
  return queryClient.fetchQuery({
    queryKey,
    queryFn: () => api.jobs.vendooItem(jobId, { refresh: true, resolvePhotos: opts?.resolvePhotos }),
    staleTime: VENDOO_ITEM_STALE_MS,
  });
}
