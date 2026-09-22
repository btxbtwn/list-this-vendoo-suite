import { useEffect, useRef } from "react";
import { formatWorkingTimerSince } from "./workingDuration";

/**
 * Self-ticking elapsed label so the parent chat row does not re-render every
 * second (same approach as T3 Code's WorkingTimer).
 */
export function WorkingDuration({
  startedAtMs,
  className,
}: {
  startedAtMs: number;
  className?: string;
}) {
  const textRef = useRef<HTMLSpanElement>(null);
  const initialText = formatWorkingTimerSince(startedAtMs);

  useEffect(() => {
    const updateText = () => {
      if (textRef.current) {
        textRef.current.textContent = formatWorkingTimerSince(startedAtMs);
      }
    };
    updateText();
    const id = window.setInterval(updateText, 1_000);
    return () => window.clearInterval(id);
  }, [startedAtMs]);

  return (
    <span ref={textRef} className={className} aria-hidden="true">
      {initialText}
    </span>
  );
}
