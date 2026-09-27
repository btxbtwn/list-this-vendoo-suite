/** Filters for the raghouse box scout, and the presets the Sourcing page offers. */
export interface ScoutFilters {
  trend: string;
  minPcs: number;
  targetCog: number;
  maxCog: number;
  maxPrice: number;
  includeVip: boolean;
}

export type ScoutPresetId = "everyday" | "higher-value";

// Tees and tops land well under $2 a usable piece; jackets, fleece and sweaters
// cost more per piece and resell for more, so they need their own caps.
export const SCOUT_PRESETS: { id: ScoutPresetId; label: string; filters: Pick<ScoutFilters, "minPcs" | "targetCog" | "maxCog"> }[] = [
  { id: "everyday", label: "Tees & tops", filters: { minPcs: 20, targetCog: 2, maxCog: 4 } },
  { id: "higher-value", label: "Jackets & sweaters", filters: { minPcs: 12, targetCog: 4, maxCog: 8 } },
];

export const DEFAULT_SCOUT_FILTERS: ScoutFilters = {
  trend: "",
  ...SCOUT_PRESETS[0].filters,
  maxPrice: 0,
  includeVip: true,
};

export function scoutQuery(filters: ScoutFilters, refresh = false): string {
  const params = new URLSearchParams({
    min_pcs: String(filters.minPcs),
    target_cog: String(filters.targetCog),
    max_cog: String(filters.maxCog),
    include_vip: String(filters.includeVip),
  });
  const trend = normalizeTrend(filters.trend);
  if (trend) params.set("trend", trend);
  if (filters.maxPrice > 0) params.set("max_price", String(filters.maxPrice));
  if (refresh) params.set("refresh", "true");
  return params.toString();
}

/** "Carhartt,  y2k ,,Band" -> "carhartt, y2k, band", so equal lists share a cache entry. */
export function normalizeTrend(text: string): string {
  return text
    .split(",")
    .map((term) => term.trim().toLowerCase())
    .filter(Boolean)
    .join(", ");
}

export function activePreset(filters: ScoutFilters): ScoutPresetId | null {
  const match = SCOUT_PRESETS.find(
    (preset) =>
      preset.filters.minPcs === filters.minPcs &&
      preset.filters.targetCog === filters.targetCog &&
      preset.filters.maxCog === filters.maxCog,
  );
  return match?.id ?? null;
}

export const GRADE_LABELS: Record<"good" | "mixed" | "recycle", string> = {
  good: "Good",
  mixed: "Recycle & Good",
  recycle: "Recycle",
};
