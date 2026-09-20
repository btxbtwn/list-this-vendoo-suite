/** How each marketplace is named in the app's own copy, badges and labels. */

export const MARKETPLACE_NAMES: Record<string, string> = {
  general: "Vendoo",
  ebay: "eBay",
  etsy: "Etsy",
  poshmark: "Poshmark",
  mercari: "Mercari",
  depop: "Depop",
  facebook: "Facebook",
  shopify: "Shopify",
  vinted: "Vinted",
  whatnot: "Whatnot",
  sellwild: "Sellwild",
  grailed: "Grailed",
  vestiaire: "Vestiaire Collective",
};

/** A marketplace id as a person reads it; an unknown id is capitalised as-is. */
export function marketplaceName(id: string): string {
  return MARKETPLACE_NAMES[id] || id.charAt(0).toUpperCase() + id.slice(1);
}
