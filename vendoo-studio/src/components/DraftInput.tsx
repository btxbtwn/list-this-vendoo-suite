import { useState } from "react";

/** A small inline field that saves on blur or Enter and reverts on Escape. */
export function DraftInput({
  value,
  label,
  prefix,
  width,
  inputMode,
  maxLength,
  disabled,
  clean,
  accept,
  onCommit,
}: {
  value: string;
  label: string;
  prefix?: string;
  width: string;
  inputMode: "numeric" | "decimal";
  maxLength?: number;
  disabled: boolean;
  clean: (text: string) => string;
  accept: (text: string) => boolean;
  onCommit: (text: string) => void;
}) {
  const [draft, setDraft] = useState(value);
  const [saved, setSaved] = useState(value);
  if (saved !== value) {
    // The saved value changed underneath the field, e.g. a recent ZIP was tapped.
    setSaved(value);
    setDraft(value);
  }
  const commit = () => {
    const next = draft.trim();
    if (next !== value && accept(next)) onCommit(next);
    else setDraft(value);
  };
  return (
    <span className="sourcing-input">
      {prefix ? <span className="sourcing-input-prefix">{prefix}</span> : null}
      <input
        className="input input-sm"
        style={{ width }}
        type="text"
        inputMode={inputMode}
        maxLength={maxLength}
        aria-label={label}
        value={draft}
        disabled={disabled}
        onChange={(event) => setDraft(clean(event.target.value))}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
          if (event.key === "Escape") setDraft(value);
        }}
      />
    </span>
  );
}
