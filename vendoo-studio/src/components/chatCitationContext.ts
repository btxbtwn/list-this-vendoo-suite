import { createContext } from "react";
import type { ChatCitation } from "./chatCitations";

/**
 * Lets a citation chip rendered deep inside chat markdown lead back to the
 * quoted text. T3 Code routes that through its router; Studio's chat lives in
 * one scroll container, so the panel hands down the reveal directly.
 */
export const ChatCitationRevealContext = createContext<((citation: ChatCitation) => void) | null>(
  null,
);
