/** Map a Forms editor field key onto static Vendoo dropdown lists. */

export type DropdownForms = Record<string, Record<string, string[]>>;

/**
 * Every fix prompt says this: a listed dropdown is the whole menu, and a value
 * outside it has to be cleared rather than swapped for another invention.
 */
export const OPTIONS_RULE =
  "When a field lists options, every value you send for it must be copied from that list verbatim "
  + "(same spelling, spacing and capitalization). Anything outside the list — \"Other\", \"Mixed\", "
  + "\"Unknown\" — fails validation again. If nothing in the list fits, send that field with an empty "
  + "value (\"value\": \"\") to clear whatever is there now, and say why in prose.";

const GENERAL_FIELD_ALIASES: Record<string, string> = {
  condition: "condition",
  primarycolor: "primaryColor",
  secondarycolor: "secondaryColor",
  size: "usSize",
};

/** Validation field names that do not match the scraped dropdown key. */
const FIELD_ALIASES: Record<string, string> = {
  whatis: "whatIsIt",
  whatisit: "whatIsIt",
  whomade: "whoMade",
  whenmade: "whenMade",
  parcelsize: "parcelSize",
  shippinglabel: "shippingLabel",
};

function optionKey(text: string): string {
  return String(text || "").toLowerCase().replace(/[^a-z0-9]/g, "");
}

function leafKey(fieldKey: string): string {
  const parts = fieldKey.split(".");
  return parts[parts.length - 1] || fieldKey;
}

function optionsFor(
  forms: DropdownForms | undefined,
  marketplace: string,
  fieldLeaf: string,
): string[] | undefined {
  const bucket = forms?.[marketplace];
  if (!bucket) return undefined;
  if (bucket[fieldLeaf]?.length) return bucket[fieldLeaf];
  const folded = optionKey(FIELD_ALIASES[optionKey(fieldLeaf)] || fieldLeaf);
  for (const [key, values] of Object.entries(bucket)) {
    if (optionKey(key) === folded && values.length) return values;
  }
  return undefined;
}

/**
 * Dropdown list for one validation field path ("depop_specifics.material").
 *
 * Fix-errors prompts paste these into chat so the model repairs a rejected
 * value with one the Depop/Etsy dropdown really offers instead of "Other".
 */
export function optionsForField(
  forms: DropdownForms | undefined,
  marketplace: string,
  field: string,
): string[] | undefined {
  if (!forms) return undefined;
  const leaf = leafKey(String(field || ""));
  if (!leaf) return undefined;
  const market = String(marketplace || "").toLowerCase();
  if (market === "general" || market === "vendoo") {
    const alias = GENERAL_FIELD_ALIASES[leaf.toLowerCase()];
    return optionsFor(forms, "vendoo", alias || leaf) || optionsFor(forms, "vendoo", leaf);
  }
  return optionsFor(forms, market, leaf);
}

/** Attach static dropdown options to editor fields that do not already have any. */
export function withDropdownOptions<T extends { key: string; options?: string[] }>(
  fields: T[],
  tab: string,
  forms: DropdownForms | undefined,
): T[] {
  if (!forms) return fields;
  return fields.map((field) => {
    if (field.options?.length) return field;
    const leaf = leafKey(field.key);
    let options: string[] | undefined;
    if (tab === "general") {
      const alias = GENERAL_FIELD_ALIASES[leaf.toLowerCase()];
      options = alias ? optionsFor(forms, "vendoo", alias) : undefined;
      if (!options) options = optionsFor(forms, "vendoo", leaf);
    } else {
      options = optionsFor(forms, tab, leaf);
    }
    return options?.length ? { ...field, options } : field;
  });
}
