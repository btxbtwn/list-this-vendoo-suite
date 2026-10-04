import type { ListingChange, ListingData } from "../api/types";
import { squashFieldKey } from "../listingPaths";
import { marketplaceName } from "./marketplaceNames";

export function listingChanges(before: ListingData, after: ListingData): ListingChange[] {
  const changes: ListingChange[] = [];
  function walk(left: unknown, right: unknown, path: string) {
    const object = (value: unknown): value is Record<string, unknown> =>
      value !== null && typeof value === "object" && !Array.isArray(value);
    if (object(left) || object(right)) {
      const a = object(left) ? left : {};
      const b = object(right) ? right : {};
      for (const key of [...new Set([...Object.keys(a), ...Object.keys(b)])].sort()) {
        if (!key.startsWith("_")) walk(a[key], b[key], path ? `${path}.${key}` : key);
      }
    } else if (JSON.stringify(left) !== JSON.stringify(right)) {
      changes.push({ field: path, before: left, after: right });
    }
  }
  walk(before, after, "");
  return changes;
}

export function changeValue(value: unknown): string {
  if (value === undefined || value === null || value === "") return "Empty";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

export function fieldLabel(path: string): string {
  return path.split(".").filter((key) => !["generalDetails", "overrides", "marketplaceSpecifics", "categorySpecifics", "category_specifics", "listings"].includes(key))
    .map((key) => key.endsWith("_specifics") ? marketplaceName(key.replace("_specifics", "")) : key.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/_/g, " "))
    .join(" · ");
}

export function blockerTarget(field: string): { reviewTab: "input" | "forms"; tab: string; field: string } {
  if (field === "photos") return { reviewTab: "input", tab: "general", field };
  const marketplace = field.match(/^([a-z]+)_specifics(?:\.|$)/)?.[1];
  return { reviewTab: "forms", tab: marketplace || "general", field };
}

export function matchingEditorField(fields: { key: string }[], target: string): string | undefined {
  const normalize = (path: string) => squashFieldKey(path.replace(".category_specifics.", "."));
  return fields.find((field) => normalize(field.key) === normalize(target))?.key;
}
