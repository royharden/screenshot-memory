/** Pure presentation state. No server, decode, relevance or access authority. */

export type Selection = Readonly<{ id: string; version: string }>;
export type ItemView = Readonly<{
  collectionId: string;
  id: string;
  version: string;
  state: "pending" | "partial" | "ready" | "failed" | "deleting" | "cleanup_pending";
}>;
export type SearchEpoch = Readonly<{
  collectionId: string;
  collectionVersion: string;
  requestId: string;
  query: string;
}>;

export function visibleItems(selection: Selection | null, items: readonly ItemView[]): ItemView[] {
  if (!selection) return [];
  return items.filter(item => item.collectionId === selection.id &&
    item.state !== "deleting" && item.state !== "cleanup_pending");
}

export function canSearch(query: string, selection: Selection | null, availableLeg: boolean): boolean {
  return selection !== null && availableLeg === true && Array.from(query).length <= 1000 &&
    query.trim().length > 0;
}

export function acceptsSearchResponse(
  current: SearchEpoch | null, response: SearchEpoch, selection: Selection | null,
): boolean {
  return current !== null && selection !== null && current.collectionId === selection.id &&
    current.collectionVersion === selection.version && current.collectionId === response.collectionId &&
    current.collectionVersion === response.collectionVersion && current.requestId === response.requestId &&
    current.query === response.query;
}

type FileHint = Readonly<{ size: number; type: string }>;
export type UploadProblem = "empty_batch" | "item_cap" | "image_bytes" |
  "gallery_bytes" | "unsupported_format";
const MiB = 1024 * 1024;

function integer(value: number, minimum: number, maximum: number): boolean {
  return Number.isSafeInteger(value) && value >= minimum && value <= maximum;
}

export function uploadProblem(
  files: readonly FileHint[], existingCount: number, existingBytes: number, cap = 30,
): UploadProblem | null {
  if (!integer(cap, 1, 30) || !integer(existingCount, 0, cap) ||
      !integer(existingBytes, 0, 100 * MiB)) throw new Error("invalid collection display counters");
  if (files.length === 0) return "empty_batch";
  if (existingCount + files.length > cap) return "item_cap";
  let total = existingBytes;
  for (const file of files) {
    if (!integer(file.size, 1, 8 * MiB)) return "image_bytes";
    // Browser MIME is only a hint; unknown type proceeds to authoritative decode.
    if (!["", "image/png", "image/jpeg"].includes(file.type)) return "unsupported_format";
    total += file.size;
  }
  return total > 100 * MiB ? "gallery_bytes" : null;
}

export type DeleteState =
  | Readonly<{ phase: "idle" }>
  | Readonly<{ phase: "confirming"; collection: Selection; item: ItemView }>
  | Readonly<{ phase: "pending" | "cleanup_pending" | "deleted";
      collection: Selection; item: ItemView; requestId: string }>;

export function confirmDelete(selection: Selection, item: ItemView): DeleteState {
  if (item.collectionId !== selection.id || ["deleting", "cleanup_pending"].includes(item.state)) {
    throw new Error("item cannot enter deletion confirmation");
  }
  return { phase: "confirming", collection: { ...selection }, item: { ...item } };
}

export function sendConfirmedDelete(
  state: DeleteState, confirmed: boolean, selection: Selection | null, requestId: string,
): DeleteState {
  if (state.phase !== "confirming" || confirmed !== true || !selection || !requestId ||
      selection.id !== state.collection.id || selection.version !== state.collection.version) {
    throw new Error("current explicit deletion confirmation required");
  }
  return { ...state, phase: "pending", requestId };
}

export function receiveDeleteStatus(
  state: DeleteState, identity: Readonly<{ collectionId: string; itemId: string; requestId: string }>,
  status: "deleted" | "cleanup_pending" | "not_found",
): DeleteState {
  if (!["deleted", "cleanup_pending", "not_found"].includes(status)) {
    throw new Error("unknown deletion status");
  }
  if ((state.phase !== "pending" && state.phase !== "cleanup_pending") ||
      identity.collectionId !== state.collection.id || identity.itemId !== state.item.id ||
      identity.requestId !== state.requestId) return state;
  // not_found does not attest an all-store completed deletion.
  if (status === "not_found") return { phase: "idle" };
  return { ...state, phase: status };
}

export type SourceBox = readonly [number, number, number, number];
type DisplayRect = Readonly<{ x: number; y: number; width: number; height: number }>;

export function displayBox(
  source: SourceBox, sourceWidth: number, sourceHeight: number, imageRect: DisplayRect,
): SourceBox {
  if (![...source, sourceWidth, sourceHeight, imageRect.x, imageRect.y,
    imageRect.width, imageRect.height].every(Number.isFinite) ||
    !Number.isSafeInteger(sourceWidth) || !Number.isSafeInteger(sourceHeight) ||
    sourceWidth <= 0 || sourceHeight <= 0 || imageRect.width <= 0 || imageRect.height <= 0 ||
    source[0] < 0 || source[1] < 0 || source[0] >= source[2] || source[1] >= source[3] ||
    source[2] > sourceWidth || source[3] > sourceHeight) {
    throw new Error("valid source pixels and actual displayed image rectangle required");
  }
  const sx = imageRect.width / sourceWidth;
  const sy = imageRect.height / sourceHeight;
  return [imageRect.x + source[0] * sx, imageRect.y + source[1] * sy,
    imageRect.x + source[2] * sx, imageRect.y + source[3] * sy];
}
