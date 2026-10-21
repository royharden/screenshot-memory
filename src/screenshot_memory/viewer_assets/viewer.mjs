import { CollectionClient } from "./client.mjs";
import { displayBox } from "./model.mjs";

const $ = id => document.getElementById(id);
let imageURL = null;
const downloads = new Set();
function clearImage() {
  if (imageURL) URL.revokeObjectURL(imageURL);
  imageURL = null; $("source-image").removeAttribute("src"); $("image-stage").hidden = true;
  $("boxes").replaceChildren(); $("ocr-text").replaceChildren();
}
function render() {
  const connected = client.connected, busy = client.busy;
  $("create").disabled = !connected || busy;
  $("open").disabled = !connected;
  $("import").disabled = !client.collection || busy;
  $("original").disabled = !client.selected || busy;
  $("delete").disabled = !client.selected || busy;
  $("current").textContent = client.collection ? `Collection ${client.collection.id} · ${client.items.length} visible items` : "No collection selected.";
  if (client.collection) $("collection-id").value = client.collection.id;
  $("items").replaceChildren(...client.visible().map(item => {
    const li = document.createElement("li"), button = document.createElement("button");
    button.textContent = `${item.item_id} · ${item.width_px}×${item.height_px} · ${item.state}`;
    button.disabled = busy; button.setAttribute("aria-pressed", String(client.selected === item.item_id));
    button.addEventListener("click", () => action(async () => {
      const result = await client.select(item.item_id);
      if (client.detail !== result.detail) return;
      showSource(result);
    })); li.append(button); return li;
  }));
  if (!client.detail) { clearImage(); $("stages").textContent = "Select an image."; $("overlay-state").textContent = ""; }
  const phase = client.deletion.phase;
  $("confirmation").hidden = !["confirming", "pending", "cleanup_pending"].includes(phase);
  $("confirm-delete").hidden = phase !== "confirming";
  $("cancel-delete").hidden = phase !== "confirming";
  $("retry-delete").hidden = phase !== "cleanup_pending" && !(phase === "pending" && !busy);
  $("confirm-delete").disabled = $("retry-delete").disabled = busy;
  $("delete-text").textContent = phase === "confirming" ? `Delete managed item ${client.deletion.item.id}? The imported source file is preserved.` :
    phase === "cleanup_pending" ? "Cleanup is pending. The item is hidden; deletion is not complete. Retry after the file lock or storage issue is resolved." : busy ? "Waiting for a verified deletion receipt…" : "No verified receipt was received. The operation may have completed; retry this same confirmed item to obtain its status.";
}
const client = new CollectionClient(globalThis.fetch.bind(globalThis), render);
async function action(operation) {
  try { await operation(); }
  catch (error) { if (error.name !== "AbortError") $("message").textContent = error.message; }
  finally { render(); }
}
function showSource({ detail, blob }) {
  clearImage();
  imageURL = URL.createObjectURL(blob); $("source-image").src = imageURL;
  const { width_px: width, height_px: height } = detail.item;
  $("source-image").width = width; $("source-image").height = height;
  $("boxes").setAttribute("viewBox", `0 0 ${width} ${height}`);
  for (const [kind, regions] of [["line", detail.lines], ["word", detail.words]]) for (const region of regions) {
    const [x0, y0, x1, y1] = displayBox(region.box, width, height, { x: 0, y: 0, width, height });
    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    for (const [name, value] of Object.entries({ x: x0, y: y0, width: x1 - x0, height: y1 - y0 })) rect.setAttribute(name, String(value));
    rect.setAttribute("class", kind);
    const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
    title.textContent = `${kind}: ${region.text} (confidence ${region.confidence ?? "unknown"})`;
    rect.append(title); $("boxes").append(rect);
  }
  for (const line of detail.lines) { const li = document.createElement("li"); li.textContent = line.text; $("ocr-text").append(li); }
  $("image-stage").hidden = false;
  $("stages").textContent = detail.item.stages.map(stage => `${stage.stage}: ${stage.status} (${stage.provenance ?? "unavailable"})`).join(" · ");
  $("overlay-state").textContent = `Overlay: ${detail.overlay_status}${detail.engine ? ` · ${detail.engine.name} ${detail.engine.version}` : ""}${detail.truncated ? " · display capped at 500 lines and 500 words" : ""}. Retained geometry is not an accuracy measurement.`;
  $("message").textContent = "Showing verified source pixels. Missing model stages remain unexecuted.";
}
$("access").addEventListener("submit", event => { event.preventDefault(); action(() => {
  const token = $("token").value; $("token").value = ""; client.connect(token);
  $("message").textContent = "Token held in memory. Create or open a collection.";
}); });
$("disconnect").addEventListener("click", () => { client.disconnect(); clearImage(); for (const url of downloads) URL.revokeObjectURL(url); downloads.clear(); $("message").textContent = "Disconnected; page session cleared."; });
$("create").addEventListener("click", () => action(() => client.create()));
$("open").addEventListener("click", () => action(() => client.open($("collection-id").value.trim())));
$("upload-form").addEventListener("submit", event => { event.preventDefault(); action(async () => { const file = $("upload").files[0]; if (!file) throw new Error("Select one PNG or JPEG."); await client.upload(file); $("upload").value = ""; $("message").textContent = "Image imported. Model stages are not run by this viewer."; }); });
$("original").addEventListener("click", () => action(async () => {
  const id = client.selected, blob = await client.original(), url = URL.createObjectURL(blob); downloads.add(url);
  const link = document.createElement("a"); link.href = url; link.download = id + (blob.type === "image/png" ? ".png" : ".jpg"); link.click();
  setTimeout(() => { URL.revokeObjectURL(url); downloads.delete(url); }, 30000);
}));
$("delete").addEventListener("click", () => action(() => client.prepareDelete()));
$("cancel-delete").addEventListener("click", () => client.cancelDelete());
async function deleteItem(retry) {
  const result = await client.deleteConfirmed(retry);
  $("message").textContent = result.status === "deleted" ? "Verified managed-copy deletion complete." : result.status === "cleanup_pending" ? "Cleanup pending; deletion is not complete." : "Item not found; no completed deletion is attested.";
}
$("confirm-delete").addEventListener("click", () => action(() => deleteItem(false)));
$("retry-delete").addEventListener("click", () => action(() => deleteItem(true)));
window.addEventListener("pagehide", () => { client.disconnect(); clearImage(); for (const url of downloads) URL.revokeObjectURL(url); });
render();
