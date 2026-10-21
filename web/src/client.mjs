/** Same-origin lifecycle controller. Presentation versions are local epochs, not server counters. */
import { confirmDelete, receiveDeleteStatus, sendConfirmedDelete, uploadProblem, visibleItems } from "./model.mjs";

const validId = value => typeof value === "string" && /^[0-9a-f]{32}$/.test(value);
const superseded = () => new DOMException("Operation superseded", "AbortError");

export class CollectionClient {
  #token = "";
  #fetch;
  #abort = new AbortController();
  #epoch = 0;
  constructor(fetcher = globalThis.fetch.bind(globalThis), changed = () => {}) {
    this.#fetch = fetcher;
    this.changed = changed;
    this.collection = null;
    this.items = [];
    this.selected = null;
    this.detail = null;
    this.deletion = { phase: "idle" };
    this.busy = false;
  }
  get connected() { return this.#token !== ""; }
  connect(token) {
    if (!/^[A-Za-z0-9_-]{32,256}$/.test(token)) throw new Error("Enter the local host's session token.");
    this.disconnect();
    this.#token = token;
    this.changed();
  }
  disconnect() {
    this.#abort.abort(); this.#epoch++; this.#token = "";
    this.collection = this.selected = this.detail = null;
    this.items = []; this.deletion = { phase: "idle" }; this.busy = false;
    this.changed();
  }
  #begin(keepSelection = false) {
    if (!this.connected) throw new Error("Connect using the local host's session token.");
    this.#abort.abort(); this.#abort = new AbortController(); this.#epoch++;
    if (!keepSelection) { this.selected = this.detail = null; this.deletion = { phase: "idle" }; }
    this.busy = true; this.changed();
    return { epoch: this.#epoch, token: this.#token, signal: this.#abort.signal };
  }
  #current(op) {
    if (op.epoch !== this.#epoch || op.token !== this.#token || op.signal.aborted) throw superseded();
  }
  #end(op) { if (op.epoch === this.#epoch) { this.busy = false; this.changed(); } }
  async #request(op, path, method = "GET", body, media, binary = false) {
    this.#current(op);
    const headers = { Authorization: "Bearer " + op.token };
    if (media) headers["Content-Type"] = media;
    const response = await this.#fetch(path, { method, body, headers, signal: op.signal,
      mode: "same-origin", credentials: "omit", redirect: "error", cache: "no-store" });
    this.#current(op);
    const result = binary && response.ok ? await response.blob() : await response.json();
    this.#current(op);
    if (!response.ok && !(method === "DELETE" && result.status === "not_found")) {
      throw new Error(`Local server refused the operation (${response.status}).`);
    }
    return result;
  }
  #base(id = this.collection?.id) {
    if (!validId(id)) throw new Error("A valid collection ID is required.");
    return "/collections/" + id + "/items";
  }
  async #load(op, id) {
    const result = await this.#request(op, this.#base(id));
    if (!Array.isArray(result.items) || result.items.length > 30 || result.items.some(item =>
      item.collection_id !== id || !validId(item.item_id))) throw new Error("Invalid collection response.");
    if (new Set(result.items.map(item => item.item_id)).size !== result.items.length) throw new Error("Duplicate item response.");
    this.collection = { id, version: String(op.epoch) }; // Exact local presentation epoch only.
    this.items = result.items;
  }
  visible() {
    const views = this.items.map(item => ({ collectionId: item.collection_id, id: item.item_id,
      version: this.collection?.version ?? "", state: item.state }));
    const ids = new Set(visibleItems(this.collection, views).map(item => item.id));
    return this.items.filter(item => ids.has(item.item_id));
  }
  async open(id) {
    this.#base(id);
    const op = this.#begin();
    this.collection = null; this.items = []; this.changed();
    try { await this.#load(op, id); } finally { this.#end(op); }
  }
  async create() {
    const op = this.#begin(); this.collection = null; this.items = []; this.changed();
    try {
      const result = await this.#request(op, "/collections", "POST");
      if (!validId(result.collection_id)) throw new Error("Invalid collection response.");
      await this.#load(op, result.collection_id);
    } finally { this.#end(op); }
  }
  async upload(file) {
    const id = this.collection?.id; this.#base(id);
    const problem = uploadProblem([file], this.items.length,
      this.items.reduce((sum, item) => sum + item.encoded_bytes, 0));
    if (problem) throw new Error(`Upload refused: ${problem}.`);
    const op = this.#begin();
    try {
      const bytes = new Uint8Array(await file.slice(0, 8).arrayBuffer()); this.#current(op);
      const png = [137, 80, 78, 71, 13, 10, 26, 10].every((value, index) => bytes[index] === value);
      const jpeg = bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255;
      if (!png && !jpeg) throw new Error("Select a PNG or JPEG image.");
      await this.#request(op, this.#base(id), "POST", file, png ? "image/png" : "image/jpeg");
      await this.#load(op, id);
    } finally { this.#end(op); }
  }
  async select(id) {
    const item = this.visible().find(value => value.item_id === id);
    if (!item) throw new Error("Select a current visible item.");
    const base = this.#base(); const op = this.#begin();
    this.selected = id; this.changed();
    try {
      const detail = await this.#request(op, base + "/" + id + "/detail");
      if (detail.item?.item_id !== id || detail.item.collection_id !== this.collection?.id) throw new Error("Foreign item response.");
      const blob = await this.#request(op, base + "/" + id + "/render", "GET", undefined, undefined, true);
      this.detail = detail; return { detail, blob, epoch: op.epoch };
    } finally { this.#end(op); }
  }
  async original() {
    const id = this.selected; if (!validId(id)) throw new Error("Select an item.");
    const op = this.#begin(true);
    try { return await this.#request(op, this.#base() + "/" + id + "/original", "GET", undefined, undefined, true); }
    finally { this.#end(op); }
  }
  prepareDelete() {
    const item = this.visible().find(value => value.item_id === this.selected);
    if (!item || !this.collection) throw new Error("Select a current item.");
    this.deletion = confirmDelete(this.collection, { collectionId: item.collection_id,
      id: item.item_id, version: this.collection.version, state: item.state });
    this.changed();
  }
  cancelDelete() { if (this.deletion.phase === "confirming") { this.deletion = { phase: "idle" }; this.changed(); } }
  async deleteConfirmed(retry = false) {
    const intent = this.deletion;
    if (retry ? !["cleanup_pending", "pending"].includes(intent.phase) || this.busy : intent.phase !== "confirming") throw new Error("Explicit deletion confirmation required.");
    if (!this.collection || intent.collection.id !== this.collection.id || intent.collection.version !== this.collection.version) throw new Error("Collection changed.");
    const op = this.#begin(true);
    this.deletion = retry ? intent : sendConfirmedDelete(intent, true, this.collection, String(op.epoch));
    this.items = this.items.map(item => item.item_id === intent.item.id ? { ...item, state: "deleting" } : item);
    this.selected = this.detail = null;
    this.changed();
    try {
      const result = await this.#request(op, this.#base() + "/" + intent.item.id,
        "DELETE", JSON.stringify({ confirm: true }), "application/json");
      if (!["deleted", "cleanup_pending", "not_found"].includes(result.status)) throw new Error("Invalid deletion receipt.");
      const updated = receiveDeleteStatus(this.deletion, { collectionId: result.collection_id,
        itemId: result.item_id, requestId: this.deletion.requestId }, result.status);
      if (updated === this.deletion) throw new Error("Foreign deletion receipt.");
      if (result.status === "deleted" && (result.wal_checkpointed !== true ||
        !Array.isArray(result.stores_verified) || result.stores_verified.length === 0 ||
        result.files_absent !== result.files_planned)) throw new Error("Incomplete deletion receipt.");
      this.deletion = updated;
      if (result.status !== "not_found") {
        this.items = this.items.filter(item => item.item_id !== intent.item.id);
        this.selected = this.detail = null;
      }
      return result;
    } finally { this.#end(op); }
  }
}
