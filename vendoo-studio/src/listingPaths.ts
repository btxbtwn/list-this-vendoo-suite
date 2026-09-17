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
