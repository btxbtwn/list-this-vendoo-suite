import type { ListingChange } from "../api/types";
import { changeValue, fieldLabel } from "./listingChanges";

export function ListingChangeList({ changes, beforeLabel = "Before", afterLabel = "After" }: {
  changes: ListingChange[];
  beforeLabel?: string;
  afterLabel?: string;
}) {
  if (!changes.length) return <p className="text-muted">No field changes.</p>;
  return (
    <div className="listing-changes">
      {changes.map((change) => (
        <details key={change.field} className="listing-change" open={changes.length <= 6}>
          <summary>{fieldLabel(change.field)}</summary>
          <div className="listing-change-values">
            <div><span className="label">{beforeLabel}</span><pre>{changeValue(change.before)}</pre></div>
            <div><span className="label">{afterLabel}</span><pre>{changeValue(change.after)}</pre></div>
          </div>
        </details>
      ))}
    </div>
  );
}
