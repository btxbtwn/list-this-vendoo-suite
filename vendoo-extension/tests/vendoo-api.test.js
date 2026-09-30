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
    if (req.url.startsWith('/photos/')) return res.end(Buffer.from([1, 2, 3, 4]));
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
  const item = { itemID: 'draft', generalDetails: { images: Array.from(prep.results, (row) => row.image) } };
  const saved = await worker.runVendooApiOps([
    { op: 'create_item', item }, { op: 'get_item', item_id: 'draft' },
  ]);
  assert.equal(saved.ok, true);
  assert.deepEqual(JSON.parse(JSON.stringify(saved.results[1].item)), JSON.parse(JSON.stringify(item)));
});
