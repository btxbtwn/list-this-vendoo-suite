const test = require('node:test');
const assert = require('node:assert/strict');
const {
  canonicalizeColor,
  mapColor,
  resolveMarketplaceColors,
} = require('../content-scripts/marketplace-colors.js');

test('canonicalizeColor normalizes Multi and Grey aliases', () => {
  assert.equal(canonicalizeColor('Multi'), 'Multicolor');
  assert.equal(canonicalizeColor('multi-color'), 'Multicolor');
  assert.equal(canonicalizeColor('Grey'), 'Gray');
  assert.equal(canonicalizeColor('Navy'), 'Navy');
});

test('eBay keeps Multicolor; Etsy and Poshmark skip it', () => {
  assert.equal(mapColor('Multicolor', 'ebay'), 'Multicolor');
  assert.equal(mapColor('Multicolor', 'etsy'), null);
  assert.equal(mapColor('Multi', 'etsy'), null);
  assert.equal(mapColor('Multicolor', 'poshmark'), null);
  assert.equal(mapColor('Multicolor', 'depop'), 'Multi');
});

test('Etsy Multicolor primary promotes secondary so primary is not blank', () => {
  assert.deepEqual(
    resolveMarketplaceColors('Multicolor', 'Purple', 'etsy'),
    { primary: 'Purple', secondary: null },
  );
  assert.deepEqual(
    resolveMarketplaceColors('Multicolor', '', 'etsy'),
    { primary: null, secondary: null },
  );
  assert.deepEqual(
    resolveMarketplaceColors('Blue', 'Purple', 'etsy'),
    { primary: 'Blue', secondary: 'Purple' },
  );
});

test('Poshmark Multicolor primary also promotes secondary', () => {
  assert.deepEqual(
    resolveMarketplaceColors('Multicolor', 'Pink', 'poshmark'),
    { primary: 'Pink', secondary: null },
  );
});
