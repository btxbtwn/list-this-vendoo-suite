/** One turn of the seller's conversation with the business assistant. */
export interface AssistantMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  created_at: string | null;
}

export interface AssistantStreamHandlers {
  /** The next piece of the answer. */
  onText: (piece: string) => void;
  /** What the assistant is doing before the answer starts. */
  onStatus: (status: string) => void;
}
