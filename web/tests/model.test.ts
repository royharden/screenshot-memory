import test from "node:test";
import assert from "node:assert/strict";
import {
  acceptsSearchResponse, canSearch, confirmDelete, displayBox, receiveDeleteStatus,
  sendConfirmedDelete, uploadProblem, visibleItems,
} from "../src/model.ts";
import type { ItemView, SearchEpoch, Selection } from "../src/model.ts";

const collection: Selection = { id: "gallery-a", version: "9223372036854775807" };
const item: ItemView = { collectionId: collection.id, id: "item-a", version: "7", state: "ready" };
const epoch: SearchEpoch = {
  collectionId: collection.id, collectionVersion: collection.version, requestId: "r2", query: "coffee notes",
};
const png = (size: number) => ({ size, type: "image/png" });

test("collection switch and delete mark immediately hide unrelated item views", () => {
  const rows: ItemView[] = [item, { ...item, id: "other", collectionId: "gallery-b" },
    { ...item, id: "deleted", state: "deleting" }, { ...item, id: "pending", state: "cleanup_pending" }];
  assert.deepEqual(visibleItems(collection, rows), [item]);
  assert.deepEqual(visibleItems(null, rows), []);
});

test("late search response cannot replace a newer query or collection generation", () => {
  assert.equal(acceptsSearchResponse(epoch, { ...epoch }, collection), true);
  for (const changed of [
    { ...epoch, requestId: "r1" }, { ...epoch, query: "old question" },
    { ...epoch, collectionId: "gallery-b" }, { ...epoch, collectionVersion: "1" },
  ]) assert.equal(acceptsSearchResponse(epoch, changed, collection), false);
  assert.equal(acceptsSearchResponse(epoch, epoch, { ...collection, version: "new" }), false);
  assert.equal(acceptsSearchResponse(epoch, epoch, { ...collection, id: "gallery-b" }), false);
  assert.equal(acceptsSearchResponse(null, epoch, collection), false);
});

test("generation text is compared exactly beyond JavaScript integer precision", () => {
  assert.equal(acceptsSearchResponse(epoch, { ...epoch, collectionVersion: "9223372036854775806" }, collection), false);
});

test("search guidance keeps raw length bound and needs a real available leg", () => {
  assert.equal(canSearch("a".repeat(1000), collection, true), true);
  assert.equal(canSearch("a".repeat(1001), collection, true), false);
  assert.equal(canSearch(" \n ", collection, true), false);
  assert.equal(canSearch("coffee", null, true), false);
  assert.equal(canSearch("coffee", collection, false), false);
});

test("Unicode query character limit matches backend codepoints rather than UTF16 units", () => {
  assert.equal(canSearch("🙂".repeat(1000), collection, true), true);
  assert.equal(canSearch("🙂".repeat(1001), collection, true), false);
});

test("an overflowing batch never becomes a partially accepted client selection", () => {
  assert.equal(uploadProblem([png(10), png(20)], 29, 300), "item_cap");
  assert.equal(uploadProblem([png(10), png(20)], 28, 300), null);
  assert.equal(uploadProblem([png(8 * 1024 * 1024)], 1, 99 * 1024 * 1024), "gallery_bytes");
  assert.equal(uploadProblem([png(8 * 1024 * 1024)], 1, 92 * 1024 * 1024), null);
});

test("per-image hints reject zero oversized unsafe sizes and known unsupported formats", () => {
  for (const size of [0, -1, NaN, Infinity, 1.5, 8 * 1024 * 1024 + 1]) {
    assert.equal(uploadProblem([png(size)], 0, 0), "image_bytes");
  }
  assert.equal(uploadProblem([{ size: 30, type: "image/svg+xml" }], 0, 0), "unsupported_format");
  assert.equal(uploadProblem([{ size: 30, type: "" }], 0, 0), null);
  assert.equal(uploadProblem([], 0, 0), "empty_batch");
  assert.throws(() => uploadProblem([png(20)], 31, 0));
});

test("deletion requires explicit confirmation and the original selected collection", () => {
  const confirmation = confirmDelete(collection, item);
  assert.throws(() => sendConfirmedDelete(confirmation, false, collection, "d1"));
  assert.throws(() => sendConfirmedDelete(confirmation, true, { ...collection, id: "other" }, "d1"));
  assert.throws(() => sendConfirmedDelete(confirmation, true, { ...collection, version: "old" }, "d1"));
  assert.throws(() => confirmDelete(collection, { ...item, collectionId: "other" }));
  assert.throws(() => confirmDelete(collection, { ...item, state: "deleting" }));
  assert.equal(sendConfirmedDelete(confirmation, true, collection, "d1").phase, "pending");
});

test("pending deletion remains pending and unrelated or late receipts are ignored", () => {
  const pending = sendConfirmedDelete(confirmDelete(collection, item), true, collection, "d2");
  const id = { collectionId: collection.id, itemId: item.id, requestId: "d2" };
  assert.equal(receiveDeleteStatus(pending, { ...id, requestId: "d1" }, "deleted"), pending);
  assert.equal(receiveDeleteStatus(pending, { ...id, itemId: "other" }, "deleted"), pending);
  const retry = receiveDeleteStatus(pending, id, "cleanup_pending");
  assert.equal(retry.phase, "cleanup_pending");
  assert.equal(receiveDeleteStatus(retry, id, "deleted").phase, "deleted");
  assert.equal(receiveDeleteStatus(pending, id, "not_found").phase, "idle");
  assert.throws(() => receiveDeleteStatus(pending, id, "invented" as "deleted"));
});

test("source pixels scale to the actual letterboxed image origin on each axis", () => {
  assert.deepEqual(displayBox([100, 50, 300, 150], 400, 200,
    { x: 20, y: 70, width: 200, height: 100 }), [70, 95, 170, 145]);
  assert.deepEqual(displayBox([0, 0, 400, 200], 400, 200,
    { x: 0, y: 0, width: 300, height: 200 }), [0, 0, 300, 200]);
});

test("invalid or stale source geometry is rejected instead of clamped into a believable box", () => {
  for (const box of [[-1, 0, 20, 20], [0, 0, 401, 20], [10, 0, 5, 20], [0, 0, NaN, 20]]) {
    assert.throws(() => displayBox(box as [number, number, number, number], 400, 200,
      { x: 0, y: 0, width: 200, height: 100 }));
  }
  assert.throws(() => displayBox([0, 0, 20, 20], 0, 200, { x: 0, y: 0, width: 10, height: 10 }));
  assert.throws(() => displayBox([0, 0, 20, 20], 20.5, 200, { x: 0, y: 0, width: 10, height: 10 }));
});
