import React, { use, useMemo } from "react";
import ReactMarkdown, { defaultUrlTransform, type ExtraProps } from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import { CitationChip } from "./CitationChip";
import { ChatCitationRevealContext } from "./chatCitationContext";
import { parseChatCitationHref } from "./chatCitations";
import {
  createIncrementalMarkdownPlugin,
  shouldParseIncrementally,
} from "./markdownIncremental";

interface Props {
  text: string;
  lineBreaks?: boolean;
  isStreaming?: boolean;
}

type MarkdownProps<Tag extends keyof React.JSX.IntrinsicElements> =
  React.ComponentPropsWithoutRef<Tag> & ExtraProps;

const BASE_PLUGINS = [remarkGfm];
const BASE_PLUGINS_WITH_BREAKS = [remarkGfm, remarkBreaks];

// react-markdown drops unknown protocols; citation links have to survive it.
function markdownUrlTransform(href: string): string | null | undefined {
  return parseChatCitationHref(href) ? href : defaultUrlTransform(href);
}

export default function MarkdownRenderer({ text, lineBreaks = false, isStreaming = false }: Props) {
  const reveal = use(ChatCitationRevealContext);
  const incrementalParsing = isStreaming && shouldParseIncrementally(text);
  const remarkPlugins = useMemo(
    () => [
      ...(lineBreaks ? BASE_PLUGINS_WITH_BREAKS : BASE_PLUGINS),
      ...(incrementalParsing ? [createIncrementalMarkdownPlugin()] : []),
    ],
    [incrementalParsing, lineBreaks],
  );

  return (
    <div
      className="chat-markdown"
      // Gates the fade-in for blocks that arrive while the response streams.
      data-streaming={isStreaming ? "" : undefined}
    >
      <ReactMarkdown
        remarkPlugins={remarkPlugins}
        urlTransform={markdownUrlTransform}
        components={{
          a({ href, children }: MarkdownProps<"a">) {
            const citation = href ? parseChatCitationHref(href) : null;
            if (citation) {
              return (
                <CitationChip citation={citation} onReveal={(cited) => reveal?.(cited)} />
              );
            }
            return (
              <a href={href} target="_blank" rel="noopener noreferrer">
                {children}
              </a>
            );
          },
          table({ children }: MarkdownProps<"table">) {
            return (
              <div className="chat-markdown-table-container">
                <table>{children}</table>
              </div>
            );
          },
          input({ type, node: _node, ...props }: MarkdownProps<"input">) {
            return <input type={type} disabled={type === "checkbox"} {...props} />;
          },
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
