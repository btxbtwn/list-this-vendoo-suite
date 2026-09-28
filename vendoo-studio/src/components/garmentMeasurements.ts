export type Garment = "top" | "pants";

export interface MeasurementField {
  key: string;
  label: string;
  placeholder: string;
}

// Keys and labels mirror GARMENT_MEASUREMENTS in server listing_generate.py.
export const GARMENTS: { id: Garment; label: string; fields: MeasurementField[] }[] = [
  {
    id: "top",
    label: "Top",
    fields: [
      { key: "pitToPit", label: "Pit to Pit", placeholder: "22.5" },
      { key: "length", label: "Length", placeholder: "27" },
      { key: "sleeve", label: "Sleeve", placeholder: "9" },
    ],
  },
  // Pants cover shorts too: same waist, rise, inseam and leg opening.
  {
    id: "pants",
    label: "Pants",
    fields: [
      { key: "waist", label: "Waist", placeholder: "16" },
      { key: "rise", label: "Rise", placeholder: "11" },
      { key: "inseam", label: "Inseam", placeholder: "30" },
      { key: "legOpening", label: "Leg Opening", placeholder: "8" },
    ],
  },
];

export type Measurements = Record<Garment, Record<string, string>>;

export function garmentFields(garment: Garment): MeasurementField[] {
  return (GARMENTS.find((g) => g.id === garment) || GARMENTS[0]!).fields;
}

const PANTS_WORDS = /\b(pants|jeans|shorts|trousers|slacks|chinos|cargos?|joggers|sweatpants|leggings|overalls)\b/i;

/** A folder called "Levi's 505 jeans" is measured as pants; anything else starts as a top. */
export function guessGarment(title: string): Garment {
  return PANTS_WORDS.test(title) ? "pants" : "top";
}

/** Only the chosen garment's typed values, with blanks dropped. */
export function typedMeasurements(garment: Garment, values: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const field of garmentFields(garment)) {
    const value = (values[field.key] || "").trim();
    if (value) out[field.key] = value;
  }
  return out;
}

/**
 * Item Details notes with the garment and its measurements set, the rest kept.
 * Generation reads these as seller facts and writes them into the description
 * word for word.
 */
export function notesWithMeasurements(
  notes: string | null | undefined,
  garment: Garment,
  values: Record<string, string>,
): string {
  let parsed: Record<string, unknown> = {};
  try {
    const raw = notes ? JSON.parse(notes) : {};
    if (raw && typeof raw === "object" && !Array.isArray(raw)) parsed = raw as Record<string, unknown>;
  } catch {
    parsed = notes ? { sellerNotes: notes } : {};
  }
  const existing = parsed.measurements && typeof parsed.measurements === "object"
    ? (parsed.measurements as Record<string, unknown>)
    : {};
  return JSON.stringify({
    ...parsed,
    garment,
    measurements: { ...existing, [garment]: typedMeasurements(garment, values) },
  });
}
