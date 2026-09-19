/** Map a Forms editor field key onto static Vendoo dropdown lists. */

export type DropdownForms = Record<string, Record<string, string[]>>;

const GENERAL_FIELD_ALIASES: Record<string, string> = {
  condition: "condition",
  primarycolor: "primaryColor",
  secondarycolor: "secondaryColor",
  size: "usSize",
};

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
  const folded = fieldLeaf.toLowerCase();
  for (const [key, values] of Object.entries(bucket)) {
    if (key.toLowerCase() === folded && values.length) return values;
  }
  return undefined;
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
