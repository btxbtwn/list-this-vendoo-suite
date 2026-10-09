import { useEffect, useRef, useState } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import "@xterm/xterm/css/xterm.css";
import { api } from "../api/client";

type TerminalState = "running" | "succeeded" | "failed";

/** Open links the way Studio's other external links open: in the seller's browser. */
function openLink(_event: MouseEvent, url: string) {
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.target = "_blank";
  anchor.rel = "noreferrer";
  anchor.click();
}

/**
 * A small terminal running `claude auth login`: the seller sees Claude Code's own
 * prompts and can paste its code. It runs that one command, not a shell. A
 * successful sign-in closes it; a failed one stays open so the error can be read.
 */
export function ClaudeLoginTerminal({ onClose }: { onClose: (signedIn: boolean) => void }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  const [state, setState] = useState<TerminalState>("running");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const styles = getComputedStyle(document.documentElement);
    const terminal = new Terminal({
      cursorBlink: true,
      fontSize: 12,
      fontFamily: styles.getPropertyValue("--font-mono").trim() || "ui-monospace, Menlo, monospace",
      theme: {
        background: "#000000",
        foreground: styles.getPropertyValue("--color-text").trim() || undefined,
        cursor: styles.getPropertyValue("--color-text").trim() || undefined,
      },
    });
    const fit = new FitAddon();
    terminal.loadAddon(fit);
    terminal.loadAddon(new WebLinksAddon(openLink));
    terminal.open(host);
    fit.fit();

    const socket = new WebSocket(api.settings.claudeLoginTerminalUrl(terminal.cols, terminal.rows));
    socket.binaryType = "arraybuffer";
    socket.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        terminal.write(new Uint8Array(event.data));
        return;
      }
      const frame = JSON.parse(event.data as string) as { type: string; code?: number; message?: string };
      if (frame.type === "exit" && frame.code === 0) {
        setState("succeeded");
        onCloseRef.current(true);
      } else if (frame.type === "exit") {
        setState("failed");
      } else if (frame.type === "error") {
        setState("failed");
        setMessage(frame.message ?? "Could not start Claude sign-in.");
      }
    };
    socket.onclose = () => setState((current) => (current === "running" ? "failed" : current));
    const input = terminal.onData((data) => {
      if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "input", data }));
    });
    const resize = terminal.onResize(({ cols, rows }) => {
      if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "resize", cols, rows }));
    });
    const observer = new ResizeObserver(() => fit.fit());
    observer.observe(host);
    terminal.focus();

    return () => {
      observer.disconnect();
      input.dispose();
      resize.dispose();
      socket.close();
      terminal.dispose();
    };
  }, []);

  return (
    <div className="claude-login-terminal">
      <div className="claude-login-terminal-bar">
        <span className={state === "failed" ? "text-error" : undefined}>
          {message ??
            (state === "running"
              ? "Finish signing in in the browser. If Claude asks for a code, paste it here."
              : state === "succeeded"
                ? "Signed in to Claude."
                : "Sign-in did not finish. Close it and sign in again.")}
        </span>
        <button type="button" className="btn btn-sm btn-ghost" onClick={() => onClose(state === "succeeded")}>
          Close
        </button>
      </div>
      <div ref={hostRef} className="claude-login-terminal-view" />
    </div>
  );
}
