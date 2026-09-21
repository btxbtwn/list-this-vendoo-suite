/** A follow-up typed while generation/chat is still running. */
export type QueuedChatMessage = {
  id: string;
  text: string;
  /** Vendoo browser job the snapped fields belong to. */
  browserJobId?: string;
  /** Snapshot of browser fields pointed at when the user queued. */
  browserFields?: Array<{
    marketplace: string;
    label: string;
    value: string;
    key?: string;
    filled?: boolean;
    account_managed?: boolean;
  }>;
  createdAt: string;
};

export function newQueuedChatMessage(
  text: string,
  opts?: {
    browserJobId?: string;
    browserFields?: QueuedChatMessage["browserFields"];
  },
): QueuedChatMessage {
  const browserFields = opts?.browserFields;
  return {
    id: crypto.randomUUID(),
    text,
    ...(opts?.browserJobId ? { browserJobId: opts.browserJobId } : {}),
    ...(browserFields?.length ? { browserFields } : {}),
    createdAt: new Date().toISOString(),
  };
}

export function enqueueChatMessage(
  queue: readonly QueuedChatMessage[],
  message: QueuedChatMessage,
): QueuedChatMessage[] {
  return [...queue, message];
}

export function removeChatMessage(
  queue: readonly QueuedChatMessage[],
  id: string,
): QueuedChatMessage[] {
  return queue.filter((message) => message.id !== id);
}

/** Oldest message leaves; remaining stay in order. */
export function takeNextChatMessage(queue: readonly QueuedChatMessage[]): {
  next: QueuedChatMessage | null;
  rest: QueuedChatMessage[];
} {
  if (queue.length === 0) return { next: null, rest: [] };
  return { next: queue[0], rest: queue.slice(1) };
}
