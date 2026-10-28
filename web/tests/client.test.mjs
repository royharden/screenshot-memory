/** Synthetic transport controls for the built client, not a browser/backend execution. */
import test from "node:test";
import assert from "node:assert/strict";
import { CollectionClient } from "../../src/screenshot_memory/viewer_assets/client.mjs";

const TOKEN = "synthetic-session-token-control-000000000000";
const A = "a".repeat(32), B = "b".repeat(32), I = "c".repeat(32);
const item = { item_id: I, collection_id: A, encoded_bytes: 40, width_px: 8, height_px: 6,
  state: "partial", stages: [{ stage: "ocr", status: "not_run" }] };
const response = value => new Response(JSON.stringify(value), { headers: { "Content-Type": "application/json" } });
const receipt = (status, overrides = {}) => ({ status, collection_id: A, item_id: I,
  stores_verified: ["content"], wal_checkpointed: status === "deleted", files_absent: 1,
  files_planned: 1, ...overrides });

function transport(deletions = [receipt("deleted")]) {
  const calls = [];
  const fetcher = async (url, options) => {
    calls.push({ url, options });
    assert.equal(options.headers.Authorization, "Bearer " + TOKEN);
    assert.equal(options.mode, "same-origin"); assert.equal(options.credentials, "omit");
    assert.ok(!url.includes(TOKEN)); assert.ok(!("Origin" in options.headers));
    if (options.method === "DELETE") {
      const value = deletions.shift(); if (value instanceof Error) throw value;
      assert.equal(options.body, '{"confirm":true}'); return response(value);
    }
    if (url.endsWith("/detail")) return response({ item, lines: [], words: [], overlay_status: "ocr_not_run" });
    if (url.endsWith("/render") || url.endsWith("/original")) return new Response(new Blob(["synthetic-image-control"], { type: "image/png" }));
    return response({ items: url.includes(B) ? [] : [item] });
  };
  return { calls, fetcher };
}

test("token is private memory; same-origin authenticated original requests and disconnect", async () => {
  const server = transport(), client = new CollectionClient(server.fetcher);
  client.connect(TOKEN); await client.open(A); await client.select(I);
  assert.equal(client.detail.overlay_status, "ocr_not_run");
  assert.equal((await client.original()).type, "image/png");
  assert.ok(!JSON.stringify(client).includes(TOKEN));
  client.disconnect(); assert.equal(client.connected, false); assert.equal(client.collection, null);
  assert.deepEqual(client.items, []); assert.equal(client.detail, null);
  await assert.rejects(client.open(A));
});

test("a late response cannot restore a previous collection or selected source", async () => {
  let release;
  const fetcher = (url) => url.includes(A) ? new Promise(resolve => { release = () => resolve(response({ items: [item] })); }) : Promise.resolve(response({ items: [] }));
  const client = new CollectionClient(fetcher); client.connect(TOKEN);
  const old = client.open(A); await client.open(B); release();
  await assert.rejects(old, { name: "AbortError" });
  assert.equal(client.collection.id, B); assert.deepEqual(client.items, []);
  assert.equal(client.selected, null); assert.equal(client.detail, null);
});

test("confirmed deletion preserves pending cleanup then accepts exact verified retry", async () => {
  const server = transport([receipt("cleanup_pending"), receipt("deleted")]);
  const client = new CollectionClient(server.fetcher); client.connect(TOKEN);
  await client.open(A); await client.select(I);
  await assert.rejects(client.deleteConfirmed());
  client.prepareDelete(); await client.deleteConfirmed();
  assert.equal(client.deletion.phase, "cleanup_pending"); assert.deepEqual(client.visible(), []);
  assert.equal(client.detail, null); await client.deleteConfirmed(true);
  assert.equal(client.deletion.phase, "deleted");
  assert.equal(server.calls.filter(c => c.options.method === "DELETE").length, 2);
});

test("lost receipt remains unverified; same confirmed request can be retried", async () => {
  const server = transport([new TypeError("synthetic dropped connection"), receipt("deleted")]);
  const client = new CollectionClient(server.fetcher); client.connect(TOKEN);
  await client.open(A); await client.select(I); client.prepareDelete();
  await assert.rejects(client.deleteConfirmed()); assert.equal(client.deletion.phase, "pending");
  assert.deepEqual(client.visible(), []); assert.equal(client.detail, null);
  await client.deleteConfirmed(true); assert.equal(client.deletion.phase, "deleted");
});

test("foreign/incomplete deletion receipts never attest completion; collection switch cancels intent", async () => {
  for (const value of [receipt("deleted", { collection_id: B }), receipt("deleted", { wal_checkpointed: false })]) {
    const server = transport([value]), client = new CollectionClient(server.fetcher);
    client.connect(TOKEN); await client.open(A); await client.select(I); client.prepareDelete();
    await assert.rejects(client.deleteConfirmed()); assert.notEqual(client.deletion.phase, "deleted");
    await client.open(B); await assert.rejects(client.deleteConfirmed(true));
    assert.equal(server.calls.filter(c => c.options.method === "DELETE").length, 1);
  }
});

test("foreign metadata and malformed collection handles refuse without cached display", async () => {
  const client = new CollectionClient(async () => response({ items: [{ ...item, collection_id: B }] }));
  client.connect(TOKEN); await assert.rejects(client.open(A));
  assert.equal(client.collection, null); assert.deepEqual(client.items, []);
  await assert.rejects(client.open("../private"));
});

test("a confirmed item disappears immediately while its receipt is still pending", async () => {
  const server = transport(); let release;
  const fetcher = (url, options) => options.method === "DELETE" ? new Promise(resolve => {
    release = () => resolve(response(receipt("deleted")));
  }) : server.fetcher(url, options);
  const client = new CollectionClient(fetcher); client.connect(TOKEN);
  await client.open(A); await client.select(I); client.prepareDelete();
  const pending = client.deleteConfirmed();
  assert.equal(client.deletion.phase, "pending"); assert.deepEqual(client.visible(), []);
  assert.equal(client.selected, null); assert.equal(client.detail, null);
  release(); await pending; assert.equal(client.deletion.phase, "deleted");
});

const keywordHit = { item_id: I, rank: 1, declared_text_provenance: {}, generation_token: {
  collection_id: A, item_id: I, collection_generation: "9223372036854775807", item_generation: "0",
} };
const keywordResult = { collection_id: A, mode: "keyword", status: "ok", hits: [keywordHit],
  coverage: { visible_items: 1, indexed_items: 1, empty_ocr_items: 0, unindexed_items: 0 } };

test("keyword hit source and original retain exact decimal generation counters", async () => {
  // Catches a browser hit selection that rounds counters or falls back to fresh GET source.
  const server = transport(), calls = [];
  const client = new CollectionClient(async (url, options) => {
    calls.push({ url, options });
    if (url.endsWith("/query")) {
      assert.equal(options.method, "POST"); assert.deepEqual(JSON.parse(options.body), { query: "needle" });
      return response(keywordResult);
    }
    if (/\/(detail|render|original)$/.test(url)) {
      assert.equal(options.method, "POST");
      assert.deepEqual(JSON.parse(options.body), { generation_token: keywordHit.generation_token });
    }
    return server.fetcher(url, options);
  });
  client.connect(TOKEN); await client.open(A); const result = await client.query("needle");
  await client.selectHit(result.hits[0]); await client.original();
  assert.equal(client.selectedToken.collection_generation, "9223372036854775807");
  client.prepareDelete(); await client.deleteConfirmed();
  assert.equal(client.searchResult, null); assert.deepEqual(client.visible(), []);
  assert.equal(calls.filter(call => call.url.endsWith("/query")).length, 1);
});

test("late and foreign keyword results cannot enter a different collection", async () => {
  // Catches old query results reappearing after navigation or foreign token selection.
  let release;
  const server = transport(), client = new CollectionClient((url, options) => url.endsWith("/query") ?
    new Promise(resolve => { release = () => resolve(response(keywordResult)); }) : server.fetcher(url, options));
  client.connect(TOKEN); await client.open(A); const old = client.query("needle");
  await client.open(B); release(); await assert.rejects(old, { name: "AbortError" });
  assert.equal(client.searchResult, null); assert.equal(client.collection.id, B);
  const foreign = new CollectionClient(async url => url.endsWith("/query") ? response({ ...keywordResult,
    hits: [{ ...keywordHit, generation_token: { ...keywordHit.generation_token, collection_id: B } }] }) : response({ items: [item] }));
  foreign.connect(TOKEN); await foreign.open(A); await assert.rejects(foreign.query("needle"));
  assert.equal(foreign.searchResult, null);
});

test("unavailable keyword coverage stays explicit and bad queries do no transport", async () => {
  let queries = 0;
  const client = new CollectionClient(async url => {
    if (!url.endsWith("/query")) return response({ items: [item] });
    queries++; return response({ ...keywordResult, status: "unavailable", executed: false, hits: [],
      reason: "keyword_index_not_ready", coverage: { visible_items: 1, indexed_items: 0, empty_ocr_items: 0, unindexed_items: 1 } });
  });
  client.connect(TOKEN); await client.open(A);
  for (const invalid of ["", " ", "x".repeat(1001), null]) await assert.rejects(client.query(invalid));
  assert.equal(queries, 0);
  const result = await client.query("needle"); assert.equal(result.executed, false);
  assert.equal(client.searchResult.status, "unavailable"); assert.deepEqual(result.hits, []);
});

test("a stale keyword source refusal clears the hit and never retries a fresh token", async () => {
  const sourceCalls = [];
  const client = new CollectionClient(async (url, options) => {
    if (url.endsWith("/query")) return response(keywordResult);
    if (url.endsWith("/detail")) {
      sourceCalls.push(options); return new Response('{"status":"refused"}', { status: 409 });
    }
    return response({ items: [item] });
  });
  client.connect(TOKEN); await client.open(A); const result = await client.query("needle");
  await assert.rejects(client.selectHit(result.hits[0]));
  assert.equal(sourceCalls.length, 1); assert.equal(sourceCalls[0].method, "POST");
  assert.equal(client.searchResult, null); assert.equal(client.selected, null); assert.equal(client.detail, null);
});
