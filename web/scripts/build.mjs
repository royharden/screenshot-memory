/** Deterministic assets from public source only; no package download or application data. */
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { createHash } from "node:crypto";
import { stripTypeScriptTypes } from "node:module";
import { fileURLToPath } from "node:url";

if (process.version !== "v24.18.0") throw new Error("Viewer build requires the recorded Node v24.18.0 toolchain.");
const root = new URL("../../", import.meta.url);
const output = new URL("src/screenshot_memory/viewer_assets/", root);
const sources = {}, assets = {};
const sha = data => createHash("sha256").update(data).digest("hex");
for (const name of ["index.html", "style.css", "client.mjs", "viewer.mjs", "model.ts"]) {
  const source = "web/src/" + name;
  const raw = Buffer.from((await readFile(new URL(source, root))).toString("utf8").replaceAll("\r\n", "\n"));
  sources[source] = sha(raw);
  assets[name === "model.ts" ? "model.mjs" : name] = name === "model.ts" ?
    Buffer.from(stripTypeScriptTypes(raw.toString("utf8"), { mode: "strip" }).replace(/[ \t]+$/gm, "")) : raw;
}
const manifest = Buffer.from(JSON.stringify({ node_version: process.version, source_profile: "utf8-lf/1", sources,
  assets: Object.fromEntries(Object.entries(assets).map(([name, bytes]) => [name, sha(bytes)])) }, null, 2) + "\n");
const all = { ...assets, "manifest.json": manifest };
if (process.argv.includes("--check")) {
  for (const [name, expected] of Object.entries(all)) {
    const actual = Buffer.from((await readFile(new URL(name, output))).toString("utf8").replaceAll("\r\n", "\n"));
    if (!actual.equals(expected)) throw new Error("Viewer build differs: " + name);
  }
} else {
  await mkdir(output, { recursive: true });
  for (const [name, bytes] of Object.entries(all)) await writeFile(new URL(name, output), bytes);
}
console.log(JSON.stringify({ status: "ok", mode: process.argv.includes("--check") ? "check" : "build",
  node: process.version, directory: fileURLToPath(output), assets: Object.keys(assets),
  model_types_stripped: true, typescript_typecheck: false }));
