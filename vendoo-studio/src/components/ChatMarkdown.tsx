import React from "react";
import ReactMarkdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";

interface Props {
  text: string;
  lineBreaks?: boolean;
}

export function ChatMarkdown({ text, lineBreaks = false }: Props) {
  return (
    <div className="chat-markdown">
      <ReactMarkdown
        remarkPlugins={lineBreaks ? [remarkGfm, remarkBreaks] : [remarkGfm]}
        components={{
          a({ href, children }) {
            return (
              <a href={href} target="_blank" rel="noopener noreferrer">
                {children}
              </a>
            );
          },
          table({ children }) {
            return (
              <div className="chat-markdown-table-container">
                <table>{children}</table>
              </div>
            );
          },
          input({ type, ...props }) {
            return <input type={type} disabled={type === "checkbox"} {...props} />;
          },
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
