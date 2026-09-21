// Marketplace color vocabulary + mapping. Pure so Node tests can load this
// file without a DOM. Vendoo general / eBay accept Multicolor; Etsy and
// Poshmark do not, so Multicolor is skipped there and callers should promote
// secondary when primary maps away.
(function (root) {
  'use strict';

  const VENDOO_COLORS = [
    'Beige', 'Black', 'Blue', 'Brown', 'Cream', 'Gold', 'Gray', 'Green',
    'Orange', 'Multicolor', 'Pink', 'Purple', 'Red', 'Silver', 'Yellow', 'Tan', 'White',
  ];

  const COLOR_ALIASES = {
    grey: 'Gray',
    gray: 'Gray',
    multi: 'Multicolor',
    multicolor: 'Multicolor',
    'multi color': 'Multicolor',
    'multi-color': 'Multicolor',
    navy: 'Navy',
    burgundy: 'Burgundy',
    maroon: 'Burgundy',
    wine: 'Burgundy',
    khaki: 'Khaki',
    camel: 'Beige',
    beige: 'Beige',
    tan: 'Tan',
    cream: 'Cream',
    ivory: 'Cream',
    'off white': 'Cream',
    teal: 'Blue',
    turquoise: 'Blue',
    aqua: 'Blue',
    charcoal: 'Gray',
    slate: 'Gray',
    mint: 'Green',
    sage: 'Green',
    olive: 'Green',
    coral: 'Orange',
    salmon: 'Orange',
    peach: 'Orange',
    lavender: 'Purple',
    lilac: 'Purple',
    mauve: 'Purple',
  };

  const VENDOO_COLOR_IDENTITY = Object.fromEntries(VENDOO_COLORS.map((c) => [c, c]));

  const MARKETPLACE_COLOR_MAP = {
    vendoo: {
      ...VENDOO_COLOR_IDENTITY,
      Grey: 'Gray',
      Multi: 'Multicolor',
      Navy: 'Blue',
      Burgundy: 'Red',
      Khaki: 'Beige',
    },
    ebay: {
      ...VENDOO_COLOR_IDENTITY,
      Grey: 'Gray',
      Multi: 'Multicolor',
      Navy: 'Blue',
      Burgundy: 'Red',
      Khaki: 'Beige',
    },
    etsy: {
      ...VENDOO_COLOR_IDENTITY,
      Grey: 'Gray',
      // Etsy has no Multicolor option on Vendoo's primary/secondary dropdowns.
      Multicolor: null,
      Multi: null,
      Navy: 'Blue',
      Burgundy: 'Red',
      Khaki: 'Beige',
    },
    poshmark: {
      ...VENDOO_COLOR_IDENTITY,
      Beige: 'Tan',
      Multicolor: null,
      Grey: 'Gray',
      Multi: null,
      Navy: 'Blue',
      Burgundy: 'Red',
      Khaki: 'Tan',
    },
    depop: {
      ...VENDOO_COLOR_IDENTITY,
      Gray: 'Grey',
      Grey: 'Grey',
      Multicolor: 'Multi',
      Multi: 'Multi',
      Beige: 'Tan',
      Navy: 'Navy',
      Burgundy: 'Burgundy',
      Khaki: 'Khaki',
    },
  };

  function canonicalizeColor(raw) {
    if (raw == null) return raw;
    const original = String(raw).trim();
    if (!original) return original;

    const namedColors = [...VENDOO_COLORS, 'Grey', 'Multi', 'Navy', 'Burgundy', 'Khaki'];
    const exact = namedColors.find((c) => c.toLowerCase() === original.toLowerCase());
    if (exact) return exact === 'Grey' ? 'Gray' : exact === 'Multi' ? 'Multicolor' : exact;

    const t = original.toLowerCase().replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim();
    if (COLOR_ALIASES[t]) return COLOR_ALIASES[t];

    const words = new Set(t.split(' '));
    const contained = namedColors
      .filter((c) => words.has(c.toLowerCase()))
      .sort((a, b) => b.length - a.length)[0];
    if (contained) {
      return contained === 'Grey' ? 'Gray' : contained === 'Multi' ? 'Multicolor' : contained;
    }

    return original;
  }

  function mapColor(raw, marketplace) {
    if (raw == null || String(raw).trim() === '') return raw;
    const canonical = canonicalizeColor(raw);
    const table = MARKETPLACE_COLOR_MAP[marketplace] || MARKETPLACE_COLOR_MAP.vendoo;
    if (Object.prototype.hasOwnProperty.call(table, canonical)) {
      return table[canonical];
    }
    return canonical;
  }

  // When primary has no marketplace option (e.g. Multicolor on Etsy/Poshmark),
  // promote secondary so the required primary field is not left blank.
  function resolveMarketplaceColors(primaryRaw, secondaryRaw, marketplace) {
    let primary = mapColor(primaryRaw, marketplace);
    let secondary = mapColor(secondaryRaw, marketplace);
    if ((primary == null || primary === '') && secondary) {
      primary = secondary;
      secondary = null;
    }
    return { primary: primary || null, secondary: secondary || null };
  }

  const api = {
    VENDOO_COLORS,
    COLOR_ALIASES,
    MARKETPLACE_COLOR_MAP,
    canonicalizeColor,
    mapColor,
    resolveMarketplaceColors,
  };
  root.vendooMarketplaceColors = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
