import React from "react";
import ReactMarkdown, { type ExtraProps } from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";

interface Props {
  text: string;
  lineBreaks?: boolean;
}

type MarkdownProps<Tag extends keyof JSX.IntrinsicElements> =
  React.ComponentPropsWithoutRef<Tag> & ExtraProps;

export function ChatMarkdown({ text, lineBreaks = false }: Props) {
  return (
    <div className="chat-markdown">
      <ReactMarkdown
        remarkPlugins={lineBreaks ? [remarkGfm, remarkBreaks] : [remarkGfm]}
        components={{
          a({ href, children }: MarkdownProps<"a">) {
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
