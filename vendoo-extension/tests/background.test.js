const test = require('node:test');
const assert = require('node:assert/strict');
const { loadWorker, call } = require('./worker-context');

const worker = loadWorker();

test('Vendoo URL helpers recognise draft pages', () => {
  assert.equal(call(worker, 'isNewItemUrl', 'https://web.vendoo.co/app/item/new?marketplace=general'), true);
  assert.equal(call(worker, 'isNewItemUrl', 'https://web.vendoo.co/app/item/abc123'), false);
  assert.equal(call(worker, 'isVendooUrl', 'https://app.vendoo.co/app/item/abc'), true);
  assert.equal(call(worker, 'isVendooUrl', 'https://www.ebay.com/sl/sell'), false);
  assert.equal(call(worker, 'isVendooUrl', ''), false);
});

test('marketplace query is set and compared case-insensitively', () => {
  const url = call(worker, 'withMarketplaceQuery', 'https://web.vendoo.co/app/item/abc?marketplace=general', 'ETSY');
  assert.equal(url, 'https://web.vendoo.co/app/item/abc?marketplace=etsy');
  assert.equal(call(worker, 'listingUrlsMatch', 'https://web.vendoo.co/app/item/abc?marketplace=Etsy', url), true);
  assert.equal(call(worker, 'listingUrlsMatch', 'https://web.vendoo.co/app/item/abc?marketplace=ebay', url), false);
  assert.equal(call(worker, 'listingUrlsMatch', 'https://web.vendoo.co/app/item/xyz', 'https://web.vendoo.co/app/item/abc'), false);
});

test('only durable Vendoo item ids are extracted', () => {
  assert.equal(call(worker, 'extractItemIdFromUrl', 'https://web.vendoo.co/app/item/65f0c1?marketplace=ebay'), '65f0c1');
  assert.equal(call(worker, 'extractItemIdFromUrl', 'https://web.vendoo.co/app/item/new'), '');
  assert.equal(call(worker, 'durableItemId', ' Edit '), '');
  assert.equal(call(worker, 'extractItemIdFromUrl', 'not a url'), '');
});

test('fill fields are grouped per marketplace in batches of 25', () => {
  const fields = [
    ...Array.from({ length: 26 }, (_, i) => ({ marketplace: 'EBAY', field: `f${i}` })),
    { field: 'Title' },
  ];
  const groups = call(worker, 'groupFillFieldMarketplaces', fields);
  assert.deepEqual(groups.map((g) => [g.marketplace, g.batches.map((b) => b.length)]), [
    ['ebay', [25, 1]],
    ['general', [1]],
  ]);
  assert.deepEqual(call(worker, 'groupFillFieldMarketplaces', null), []);
});

test('fill logs merge entries across batches', () => {
  assert.equal(call(worker, 'mergeFillLogs', [{}, { fill_log: { entries: [] } }]), null);
  assert.deepEqual(
    call(worker, 'mergeFillLogs', [
      { fill_log: { entries: [{ marketplace: 'depop', field: 'Style' }] } },
      { fill_log: { entries: [{ marketplace: 'depop', field: 'Parcel size' }] } },
    ]),
    { marketplace: 'depop', entries: [{ marketplace: 'depop', field: 'Style' }, { marketplace: 'depop', field: 'Parcel size' }] },
  );
});

test('save commands target the right Vendoo tab', () => {
  assert.deepEqual(call(worker, 'saveCommandForMarketplace', 'Mercari'), { type: 'SAVE_MARKETPLACE', platform: 'mercari' });
  assert.deepEqual(call(worker, 'saveCommandForMarketplace', 'unknown'), { type: 'SAVE_GENERAL' });
  assert.deepEqual(call(worker, 'saveCommandForMarketplace', ''), { type: 'SAVE_GENERAL' });
});

test('command timeouts scale with work and stay bounded', () => {
  assert.equal(call(worker, 'commandTimeoutMs', { type: 'FILL_FIELDS', fields: [] }), 90000);
  assert.equal(call(worker, 'commandTimeoutMs', { type: 'FILL_FIELDS', fields: new Array(100).fill({}) }), 300000);
  assert.equal(call(worker, 'commandTimeoutMs', { type: 'UPLOAD_PHOTOS', files: new Array(8).fill({}) }), 100000);
  assert.equal(call(worker, 'commandTimeoutMs', { type: 'DISCOVER_SCHEMA', platforms: ['ebay'] }), 120000);
  assert.equal(call(worker, 'commandTimeoutMs', { type: 'SOMETHING_NEW' }), 45000);
});

test('step names map to marketplaces', () => {
  assert.equal(call(worker, 'marketplaceFromStep', 'filling_etsy'), 'etsy');
  assert.equal(call(worker, 'marketplaceFromStep', 'auditing_marketplaces'), 'general');
  assert.equal(call(worker, 'marketplaceFromStep', 'uploading_photos'), 'general');
});

test('resumed jobs keep preflight steps and skip ahead', () => {
  const steps = ['opening_vendoo', 'waiting_ready', 'uploading_photos', 'filling_general', 'filling_ebay', 'saving_ebay']
    .map((step) => ({ step }));
  const resumed = call(worker, 'selectJobSteps', { options: { resumeFrom: 'filling_ebay' } }, steps);
  assert.deepEqual(resumed.map((s) => s.step), ['opening_vendoo', 'waiting_ready', 'filling_ebay', 'saving_ebay']);
  const unknown = call(worker, 'selectJobSteps', { options: { resumeFrom: 'filling_vinted' } }, steps);
  assert.equal(unknown.length, steps.length);
});

test('Vendoo item payloads are compacted before crossing the websocket', () => {
  const compact = call(worker, 'compactVendooValue', {
    title: 'x'.repeat(9000),
    photo: `data:image/png;base64,${'A'.repeat(300)}`,
    images: Array.from({ length: 50 }, (_, i) => i),
    generalDetails: { brand: "Levi's" },
  }, 0);
  assert.deepEqual(Object.keys(compact).slice(0, 2), ['generalDetails', 'images']);
  assert.equal(compact.images.length, 40);
  assert.match(compact.title, /…\[truncated 9000 chars\]$/);
  assert.equal(compact.photo, '[data-url 322 chars]');
});

test('imported listings keep unique image URLs only', () => {
  const urls = call(worker, 'collectImportedImageUrls',
    { images: ['//res.cloudinary.com/demo/a.jpg', 'https://example.com/readme.txt', 'data:image/png;base64,AAAA'] },
    [{ url: 'https://res.cloudinary.com/demo/a.jpg' }, 'https://cdn.example.com/b.webp?w=800'],
  );
  assert.deepEqual(urls, ['https://res.cloudinary.com/demo/a.jpg', 'https://cdn.example.com/b.webp?w=800']);
});

test('diagnostic filenames are slugged from the page URL', () => {
  const name = call(worker, 'buildDiagnosticFilename', 'https://web.vendoo.co/app/item/new?marketplace=ebay');
  assert.match(name, /^vendoo-diagnostic-web-vendoo-co-app-item-new-marketplace-ebay-\d{4}-\d{2}-\d{2}T[\d-]+Z\.json$/);
  assert.match(call(worker, 'buildDiagnosticFilename', ''), /^vendoo-diagnostic-page-/);
});
