import { fieldLabel, blockerTarget } from "./listingChanges";
import { marketplaceName } from "./marketplaceNames";

export function ListingBlockers({ issues, onSelect }: {
  issues: { field?: string; message?: string }[];
  onSelect: (field: string) => void;
}) {
  const groups = new Map<string, typeof issues>();
  for (const issue of issues) {
    if (!issue.message) continue;
    const target = blockerTarget(issue.field || "");
    const group = target.reviewTab === "input" ? "Photos" : target.tab === "general" ? "General" : marketplaceName(target.tab);
    groups.set(group, [...(groups.get(group) || []), issue]);
  }
  if (!groups.size) return null;
  return (
    <div className="listing-blockers" aria-label="Fields to fix before sending">
      {[...groups].map(([group, entries]) => (
        <details key={group}>
          <summary>{group} · {entries.length} {entries.length === 1 ? "issue" : "issues"}</summary>
          {entries.map((issue, index) => <div key={`${issue.field}:${index}`} className="listing-blocker">
            <span>{issue.message}</span>
            {issue.field && <button type="button" className="btn btn-secondary btn-sm" onClick={() => onSelect(issue.field!)}>Fix {fieldLabel(issue.field)}</button>}
          </div>)}
        </details>
      ))}
    </div>
  );
}
