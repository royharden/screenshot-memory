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
