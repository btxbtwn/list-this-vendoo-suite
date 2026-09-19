import type { ListingData } from "./api/types";

export function getNestedValue(obj: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>(
    (o, k) => (o && typeof o === "object" ? (o as Record<string, unknown>)[k] : undefined),
    obj,
  );
}

export function cloneListing(listing: ListingData | undefined): ListingData {
  try {
    return JSON.parse(JSON.stringify(listing || {}));
  } catch {
    return { ...listing };
  }
}

export function setNestedValue(obj: ListingData, path: string, value: unknown): ListingData {
  const keys = path.split(".");
  const last = keys.pop()!;
  let target: Record<string, unknown> = obj;
  for (const k of keys) {
    if (!target[k] || typeof target[k] !== "object") target[k] = {};
    target = target[k] as Record<string, unknown>;
  }
  target[last] = value;
  return obj;
}

/** Case- and separator-free form used to spot variants of the same JSON key. */
export function squashFieldKey(value: string): string {
  return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "");
}

/**
 * Map a Vendoo form label ("Sleeve Length") onto the listing JSON key ("sleeveLength").
 * Mirrors server ``label_to_json_key``.
 */
export function labelToJsonKey(fieldLabel: string): string {
  const label = String(fieldLabel || "")
    .toLowerCase()
    .replace(/[_/]+/g, " ")
    .replace(/-/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!label) return "";
  const known: Record<string, string> = {
    "size type": "sizeType",
    "sleeve length": "sleeveLength",
    "sleeve type": "sleeveType",
    "country of origin": "countryOfOrigin",
    "fabric type": "fabricType",
    "fabric weight": "fabricWeight",
    "garment care": "garmentCare",
    "unit quantity": "unitQuantity",
    "unit type": "unitType",
    "character family": "characterFamily",
    "performance activity": "performanceActivity",
    "year manufactured": "yearManufactured",
    "collar style": "collarStyle",
    "strap type": "strapType",
    "clothing style": "clothingStyle",
  };
  if (known[label]) return known[label];
  const parts = label.split(" ").filter(Boolean);
  if (!parts.length) return "";
  return parts[0] + parts.slice(1).map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join("");
}

/** Resolve which key inside ``*_specifics`` holds a schema field's value. */
export function resolveSpecificsKey(
  specifics: Record<string, unknown> | undefined,
  schemaKey: string,
): string {
  const want = squashFieldKey(schemaKey);
  if (!want) return schemaKey;
  if (specifics && typeof specifics === "object") {
    for (const alias of Object.keys(specifics)) {
      if (squashFieldKey(alias) === want) return alias;
    }
  }
  return labelToJsonKey(schemaKey) || schemaKey;
}

/** Read a Forms-tab field, matching schema labels to camelCase listing keys. */
export function getListingEditorValue(listing: ListingData | undefined, path: string): unknown {
  const direct = getNestedValue(listing, path);
  if (direct != null && String(direct).trim() !== "") return direct;
  const parts = path.split(".");
  if (parts.length === 2 && parts[0].endsWith("_specifics")) {
    const specifics = listing?.[parts[0]];
    if (specifics && typeof specifics === "object" && !Array.isArray(specifics)) {
      const key = resolveSpecificsKey(specifics as Record<string, unknown>, parts[1]);
      return (specifics as Record<string, unknown>)[key];
    }
  }
  return direct;
}

/** Write a Forms-tab field onto the matching listing JSON key. */
export function setListingEditorValue(
  listing: ListingData,
  path: string,
  value: unknown,
): ListingData {
  const parts = path.split(".");
  if (parts.length === 2 && parts[0].endsWith("_specifics")) {
    const bucket = parts[0];
    const current = (listing[bucket] && typeof listing[bucket] === "object" && !Array.isArray(listing[bucket]))
      ? { ...(listing[bucket] as Record<string, unknown>) }
      : {};
    const key = resolveSpecificsKey(current, parts[1]);
    // Drop schema-label duplicates so we don't keep both Accents and accents.
    const want = squashFieldKey(parts[1]);
    for (const alias of Object.keys(current)) {
      if (alias !== key && squashFieldKey(alias) === want) delete current[alias];
    }
    current[key] = value;
    listing[bucket] = current;
    return listing;
  }
  return setNestedValue(listing, path, value);
}
