import { lazy, Suspense } from "react";

const MarkdownRenderer = lazy(() => import("./MarkdownRenderer"));

interface Props {
  text: string;
  lineBreaks?: boolean;
  /** Fades in each block that arrives mid-response and parses incrementally. */
  isStreaming?: boolean;
}

/** Renders chat markdown; shows plain text until the markdown bundle loads. */
export function ChatMarkdown({ text, lineBreaks = false, isStreaming = false }: Props) {
  return (
    <Suspense fallback={<div className="chat-markdown" style={{ whiteSpace: "pre-wrap" }}>{text}</div>}>
      <MarkdownRenderer text={text} lineBreaks={lineBreaks} isStreaming={isStreaming} />
    </Suspense>
  );
}
