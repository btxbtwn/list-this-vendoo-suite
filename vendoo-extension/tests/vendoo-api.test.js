const test = require('node:test');
const assert = require('node:assert/strict');
const { loadWorker } = require('./worker-context');

const tick = () => new Promise((resolve) => setImmediate(resolve));
const photo = (id) => ({ op: 'upload_photo', photo: { id } });

test('photo uploads overlap, stay bounded and retain seller order before create', async () => {
  const worker = loadWorker();
  worker.freshVendooSession = async () => ({ uid: 'u1' });
  const pending = new Map();
  let active = 0;
  let peak = 0;
  worker.uploadVendooPhoto = async (_session, image) => {
    active += 1;
    peak = Math.max(peak, active);
    await new Promise((resolve) => pending.set(image.id, resolve));
    active -= 1;
    return { version: 3, id: image.id };
  };
  let created = false;
  worker.createVendooItem = async () => {
    assert.equal(active, 0);
    created = true;
    return {};
  };
  const result = worker.runVendooApiOps([
    ...['a', 'b', 'c', 'd', 'e'].map(photo), { op: 'create_item', item: {} },
  ]);
  await tick();
  assert.deepEqual([...pending.keys()], ['a', 'b', 'c']);
  assert.equal(created, false);
  pending.get('c')();
  pending.get('b')();
  await tick();
  assert.equal(pending.has('d'), false);
  pending.get('a')();
  await tick();
  assert.equal(peak, 3);
  pending.get('e')();
  pending.get('d')();
  const reply = JSON.parse(JSON.stringify(await result));
  assert.equal(reply.ok, true);
  assert.equal(created, true);
  assert.deepEqual(reply.results.slice(0, 5).map((row) => row.image.id), ['a', 'b', 'c', 'd', 'e']);
});

test('a failed photo settles the current batch and prevents later uploads and writes', async () => {
  const worker = loadWorker();
  worker.freshVendooSession = async () => ({ uid: 'u1' });
  let finish;
  const started = [];
  worker.uploadVendooPhoto = async (_session, image) => {
    started.push(image.id);
    if (image.id === 'b') throw new Error('upload failed');
    if (image.id === 'c') await new Promise((resolve) => { finish = resolve; });
    return { version: 3, id: image.id };
  };
  worker.createVendooItem = async () => { assert.fail('must not create'); };
  const result = worker.runVendooApiOps([
    ...['a', 'b', 'c', 'd'].map(photo), { op: 'create_item', item: {} },
  ]);
  let settled = false;
  result.then(() => { settled = true; });
  await tick();
  assert.equal(settled, false);
  finish();
  const reply = JSON.parse(JSON.stringify(await result));
  assert.equal(reply.ok, false);
  assert.deepEqual(started, ['a', 'b', 'c']);
  assert.deepEqual(reply.results.map((row) => row.ok), [true, false, true]);
  assert.equal(reply.results[1].photo_id, 'b');
});

test('dependent reads and writes remain sequential around upload batches', async () => {
  const worker = loadWorker();
  worker.freshVendooSession = async () => ({ uid: 'u1' });
  const calls = [];
  worker.uploadVendooPhoto = async () => { calls.push('upload'); return {}; };
  worker.createVendooItem = async () => { calls.push('create'); return {}; };
  worker.getVendooItem = async () => { calls.push('read'); return {}; };
  const reply = await worker.runVendooApiOps([
    photo('a'), { op: 'create_item', item: {} }, { op: 'get_item', item_id: 'item' }, photo('b'),
  ]);
  assert.equal(reply.ok, true);
  assert.deepEqual(calls, ['upload', 'create', 'read', 'upload']);
});

test('the real upload/create/read path works over HTTP with concurrent photo PUTs', async (t) => {
  const http = require('node:http');
  const { once } = require('node:events');
  let base;
  let slots = 0;
  let active = 0;
  let peak = 0;
  let completed = 0;
  let stored;
  const server = http.createServer(async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const body = Buffer.concat(chunks);
    const json = (data) => {
      res.setHeader('Content-Type', 'application/json');
      res.end(JSON.stringify(data));
    };
    if (req.url === '/inventory/v1/images/url') {
      slots += 1;
      return json({ url: `${base}/put/${slots}`, imagePath: `images/${slots}.jpg` });
    }
    if (req.url.startsWith('/photos/')) return res.end(Buffer.from([Number(req.url.split("/").pop()), 2, 3, 4]));
    if (req.url.startsWith('/put/')) {
      assert.equal(req.method, 'PUT');
      assert.equal(req.headers['content-type'], 'image/jpeg');
      assert.equal(body.length, 4);
      active += 1;
      peak = Math.max(peak, active);
      await new Promise((resolve) => setTimeout(resolve, 50));
      active -= 1;
      completed += 1;
      return res.end();
    }
    if (req.url === '/items') {
      assert.equal(completed, 6);
      assert.equal(active, 0);
      stored = JSON.parse(body).data.payload.item;
      return json({ result: { ok: true } });
    }
    if (req.url.startsWith('/api/item/')) return json({ item: stored });
    res.statusCode = 404;
    res.end();
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  base = `http://127.0.0.1:${server.address().port}`;
  t.after(() => new Promise((resolve) => server.close(resolve)));
  const worker = loadWorker();
  worker.setTimeout = setTimeout;
  worker.clearTimeout = clearTimeout;
  worker.AbortController = AbortController;
  worker.freshVendooSession = async () => ({ uid: 'test-user', access_token: 'test-only' });
  worker.fetch = (url, options) => fetch(
    String(url).replace(/^https:\/\/(us\.vendoo\.co|api\.web\.vendoo\.co|us-central1-vendoo-prod-7948f\.cloudfunctions\.net)/, base),
    options,
  );
  const prep = await worker.runVendooApiOps(Array.from({ length: 6 }, (_, index) => ({
    op: 'upload_photo', photo: { id: `p${index}`, url: `${base}/photos/${index}`, mime_type: 'image/jpeg', max_dimension: 1000 + index },
  })));
  assert.equal(prep.ok, true, JSON.stringify(prep));
  assert.equal(peak, 3);
  assert.deepEqual(Array.from(prep.results, (row) => row.image.originalMaxDimension), [1000, 1001, 1002, 1003, 1004, 1005]);
  const item = { itemID: 'draft', userID: 'test-user', generalDetails: { images: Array.from(prep.results, (row) => row.image) } };
  const saved = await worker.runVendooApiOps([
    { op: 'create_item', item }, { op: 'get_item', item_id: 'draft' },
  ]);
  assert.equal(saved.ok, true);
  assert.deepEqual(JSON.parse(JSON.stringify(saved.results[1].item)), JSON.parse(JSON.stringify(item)));
});

function workerWithStorage(storage = {}) {
  const worker = loadWorker();
  worker.AbortController = AbortController;
  worker.chrome.storage.local.get = async (key) => ({ [key]: storage[key] });
  worker.chrome.storage.local.set = async (values) => Object.assign(storage, JSON.parse(JSON.stringify(values)));
  return worker;
}

test('completed uploads survive worker restart and stay isolated by account', async () => {
  const storage = {};
  let uploads = 0;
  const configure = (worker) => {
    worker.vendooFetch = async (_url, options = {}) => {
      if (options.responseType === 'blob') return { ok: true, data: new Blob(['photo bytes']) };
      if (options.method === 'POST') return { ok: true, data: { url: 'https://upload.test/photo', imagePath: `images/${++uploads}` } };
      return { ok: true };
    };
  };
  const worker = workerWithStorage(storage);
  configure(worker);
  const image = { url: 'http://localhost/photo', max_dimension: 1000 };
  const first = await worker.uploadVendooPhoto({ uid: 'one' }, image);
  const restarted = workerWithStorage(storage);
  configure(restarted);
  const reused = await restarted.uploadVendooPhoto({ uid: 'one' }, { ...image, max_dimension: 1500 });
  assert.equal(reused.id, first.id);
  assert.equal(reused.originalMaxDimension, 1500);
  assert.equal(uploads, 1);
  const other = await restarted.uploadVendooPhoto({ uid: 'two' }, image);
  assert.notEqual(other.id, first.id);
  assert.equal(uploads, 2);
  for (const entries of Object.values(storage)) {
    for (const entry of Object.values(entries)) entry.at = 0;
  }
  await restarted.uploadVendooPhoto({ uid: 'one' }, image);
  assert.equal(uploads, 3, 'expired upload references are replaced');
});

test('identical concurrent photos share an upload and failed PUTs are never cached', async () => {
  const storage = {};
  const worker = workerWithStorage(storage);
  let slots = 0;
  let fail = true;
  worker.vendooFetch = async (_url, options = {}) => {
    if (options.responseType === 'blob') return { ok: true, data: new Blob(['same bytes']) };
    if (options.method === 'POST') return { ok: true, data: { url: 'https://upload.test/photo', imagePath: `images/${++slots}` } };
    return { ok: !fail, status: fail ? 503 : 200 };
  };
  const session = { uid: 'one' };
  const image = { url: 'http://localhost/photo' };
  await assert.rejects(worker.uploadVendooPhoto(session, image), /503/);
  assert.deepEqual(storage, {});
  fail = false;
  const images = await Promise.all([
    worker.uploadVendooPhoto(session, image), worker.uploadVendooPhoto(session, image),
  ]);
  assert.equal(slots, 2);
  assert.equal(images[0].id, images[1].id);
});

test('independent reads overlap in bounded batches and settle before writes', async () => {
  const worker = loadWorker();
  worker.freshVendooSession = async () => ({ uid: 'u1' });
  const pending = new Map();
  worker.getVendooItem = async (_session, id) => {
    await new Promise((resolve) => pending.set(id, resolve));
    return { itemID: id };
  };
  let created = false;
  worker.createVendooItem = async () => { created = true; return {}; };
  const result = worker.runVendooApiOps([
    ...['a', 'b', 'c', 'd'].map((id) => ({ op: 'get_item', item_id: id })),
    { op: 'create_item', item: {} },
  ]);
  await tick();
  assert.deepEqual([...pending.keys()], ['a', 'b', 'c']);
  pending.get('c')();
  pending.get('a')();
  pending.get('b')();
  await tick();
  assert.equal(created, false);
  pending.get('d')();
  const reply = await result;
  assert.equal(created, true);
  assert.deepEqual(Array.from(reply.results.slice(0, 4), (row) => row.item.itemID), ['a', 'b', 'c', 'd']);
});

test('a failed read stops dependent writes after the current batch settles', async () => {
  const worker = loadWorker();
  worker.freshVendooSession = async () => ({ uid: 'u1' });
  let finish;
  worker.getVendooItem = async (_session, id) => {
    if (id === 'a') throw new Error('read failed');
    await new Promise((resolve) => { finish = resolve; });
    return {};
  };
  worker.createVendooItem = async () => assert.fail('must not create');
  const result = worker.runVendooApiOps([
    { op: 'get_item', item_id: 'a' }, { op: 'get_item', item_id: 'b' }, { op: 'create_item', item: {} },
  ]);
  await tick();
  finish();
  assert.equal((await result).ok, false);
});

test('recovery accepts only explicit not-found and stops on an account mismatch', async () => {
  const worker = loadWorker();
  worker.vendooFetch = async () => ({ ok: false, status: 404 });
  assert.equal(await worker.getVendooItem({ uid: 'one' }, 'item', { allowMissing: true }), null);
  worker.vendooFetch = async () => ({ ok: false, status: 403 });
  await assert.rejects(worker.getVendooItem({ uid: 'one' }, 'item', { allowMissing: true }), /403/);
  worker.freshVendooSession = async () => ({ uid: 'other' });
  worker.getVendooItem = async () => assert.fail('must not read another account');
  const reply = await worker.runVendooApiOps([
    { op: 'session', expected_uid: 'one' }, { op: 'get_item', item_id: 'item' },
  ]);
  assert.equal(reply.ok, false);
  assert.match(reply.results[0].error, /different Vendoo account/);
});

test('concurrent callers share authentication and temporary refresh failure preserves the session', async () => {
  const worker = workerWithStorage();
  let calls = 0;
  worker.loadFreshVendooSession = async () => { calls += 1; await tick(); return { uid: 'one' }; };
  const sessions = await Promise.all([worker.freshVendooSession(), worker.freshVendooSession()]);
  assert.equal(calls, 1);
  assert.equal(sessions[0], sessions[1]);

  const failing = workerWithStorage();
  failing.loadCachedVendooSession = async () => ({ uid: 'one', expiration_time: 0 });
  failing.refreshVendooToken = async () => { throw new Error('temporary network failure'); };
  failing.clearCachedVendooSession = async () => assert.fail('must retain cached session');
  failing.readVendooSession = async () => assert.fail('must not open Chrome');
  await assert.rejects(failing.freshVendooSession(), /temporary network failure/);
});

test('safe reads retry transient failures and honor Retry-After; writes and permanent errors do not retry', async () => {
  const worker = workerWithStorage();
  const delays = [];
  worker.setTimeout = (fn, ms) => {
    if (ms < 5000) { delays.push(ms); queueMicrotask(fn); }
    return 0;
  };
  let calls = 0;
  worker.fetch = async () => {
    calls += 1;
    return calls === 1
      ? new Response('{}', { status: 429, headers: { 'Retry-After': '1' } })
      : new Response('{}', { status: 200 });
  };
  assert.equal((await worker.vendooFetch('https://example.test/read')).status, 200);
  assert.equal(calls, 2);
  assert.deepEqual(delays, [1000]);
  calls = 0;
  worker.fetch = async () => { calls += 1; return new Response('{}', { status: 503 }); };
  assert.equal((await worker.vendooFetch('https://example.test/create', { method: 'POST' })).status, 503);
  assert.equal(calls, 1);
  calls = 0;
  worker.fetch = async () => { calls += 1; return new Response('{}', { status: 403 }); };
  assert.equal((await worker.vendooFetch('https://example.test/read')).status, 403);
  assert.equal(calls, 1);
  calls = 0;
  worker.fetch = async () => { calls += 1; throw new Error('offline'); };
  await assert.rejects(worker.vendooFetch('https://example.test/read'), /offline/);
  assert.equal(calls, 3);
});

test('conditional saves use the version read before the item snapshot and report conflicts', async () => {
  const worker = loadWorker();
  const requests = [];
  worker.vendooFetch = async (url, options = {}) => {
    requests.push({ url, options });
    if (options.method === 'PATCH') return { ok: true, data: { updateTime: 'next-version' } };
    if (String(url).includes('firestore.googleapis.com')) return { ok: true, data: { updateTime: 'original-version' } };
    return { ok: true, data: { item: { itemID: 'item', generalDetails: { title: 'Before' } } } };
  };
  const item = await worker.getVendooItem({ uid: 'one' }, 'item', { withVersion: true });
  assert.equal(item._studio_update_time, 'original-version');
  assert.match(requests[0].url, /firestore/);
  const written = await worker.updateVendooItem({ uid: 'one' }, {
    item_id: 'item', updates: { 'generalDetails.title': 'After' }, expected_update_time: item._studio_update_time,
  });
  assert.equal(written.update_time, 'next-version');
  const params = new URL(requests[2].url).searchParams;
  assert.equal(params.get('currentDocument.updateTime'), 'original-version');
  worker.vendooFetch = async () => ({ ok: false, status: 400, data: { error: { status: 'FAILED_PRECONDITION' } } });
  await assert.rejects(worker.updateVendooItem({ uid: 'one' }, {
    item_id: 'item', updates: { 'generalDetails.title': 'After' }, expected_update_time: 'old-version',
  }), /changed during this save/);
});

test('save verification reads exact Firestore values instead of the normalized item API', async () => {
  const worker = loadWorker();
  worker.freshVendooSession = async () => ({ uid: 'one' });
  const item = {
    itemID: 'item',
    listings: { depop: {
      dateLastModified: { _seconds: 1750000000, _nanoseconds: 123456789 },
      categorySpecifics: { womenswear_robes_quantity: '1', cleared: '' },
      marketplaceSpecifics: { location: { geoLat: 0, geoLng: 0 }, shippingMethods: [] },
    } },
  };
  const fields = {};
  for (const [key, value] of Object.entries(item)) fields[key] = worker.firestoreValue(value);
  const requests = [];
  worker.vendooFetch = async (url) => {
    requests.push(url);
    assert.match(url, /firestore.googleapis.com/);
    return { ok: true, data: { fields, updateTime: 'saved-version' } };
  };
  const reply = await worker.runVendooApiOps([{ op: 'get_item', item_id: 'item', raw: true }]);
  assert.equal(reply.ok, true);
  assert.deepEqual(JSON.parse(JSON.stringify(reply.results[0].item)), item);
  assert.equal(requests.length, 1);
  const versioned = await worker.getVendooItem({ uid: 'one' }, 'item', { raw: true, withVersion: true });
  assert.equal(versioned._studio_update_time, 'saved-version');
});

test('raw verification does not fall back to the item API when Firestore is unreadable', async () => {
  const worker = loadWorker();
  worker.vendooFetch = async (url) => {
    assert.match(url, /firestore.googleapis.com/);
    return { ok: false, status: 403, data: {} };
  };
  await assert.rejects(worker.getVendooItem({ uid: 'one' }, 'item', { raw: true }), /403/);
});

test('a rejected token is refreshed once for safe reads and cannot create in another account', async () => {
  const worker = workerWithStorage();
  let refreshes = 0;
  worker.loadFreshVendooSession = async (rejected) => {
    assert.equal(rejected, 'expired');
    refreshes += 1;
    return { uid: 'one', access_token: 'fresh' };
  };
  const tokens = [];
  worker.fetch = async (_url, options) => {
    tokens.push(options.headers.Authorization);
    return new Response('{}', { status: tokens.length === 1 ? 401 : 200 });
  };
  assert.equal((await worker.vendooFetch('https://example.test/read', { token: 'expired' })).status, 200);
  assert.equal(refreshes, 1);
  assert.deepEqual(tokens, ['Bearer expired', 'Bearer fresh']);
  worker.fetch = async () => assert.fail('must not send a draft to another account');
  await assert.rejects(worker.createVendooItem({ uid: 'other' }, { userID: 'one' }, 'v2'), /account changed/);
});
