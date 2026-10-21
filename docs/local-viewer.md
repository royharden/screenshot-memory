# Explicit local viewer and foreground host

The minimal viewer uses the existing TypeScript presentation helpers, a small
same-origin ESM lifecycle controller and the guarded WSGI collection API. It does
not run OCR, captions, embeddings or a semantic search. Existing observed-tagged
OCR artifacts can supply source-bound word/line overlays; absent or unverified
evidence is explicitly unavailable. Stored provenance is not a new model-rights,
native-recognition or accuracy certification.

Build with the recorded Node **24.18.0** toolchain from the repository root:

```powershell
node web/scripts/build.mjs
node web/scripts/build.mjs --check
node --test web/tests/model.test.ts web/tests/client.test.mjs
```

There are no npm dependencies to install and no invented dependency lockfile.
The build calls Node's built-in type stripping on unchanged `web/src/model.ts`;
it does **not** typecheck TypeScript. `web/src/` is canonical public source.
`src/screenshot_memory/viewer_assets/` is generated product output, including
a source/output digest manifest. Text digest profile `utf8-lf/1` normalizes CRLF
to LF for portable Git checkouts; it is distinct from raw source-file digests in
delivery records. Never edit generated assets by hand. The host validates all
five fixed public assets against that manifest before it opens a listener.
Changing Node versions requires an explicit toolchain/build requalification.

After preparing the existing Python3.12 environment, start the host explicitly:

```powershell
$env:PYTHONPATH = "src"
python -m screenshot_memory serve --root ../private-viewer-data --port PORT
```

Replace `PORT` with an explicitly allocated loopback port. Storage must be an
exclusively managed private directory outside any Git repository. Use a
cryptographically random URL-safe session token of 32–256 characters from a
trusted local generator/password manager. Enter the same token at the hidden
host prompt and the viewer's password field. Noninteractive callers must supply
`SMEM_VIEWER_TOKEN` in the foreground process environment; it is removed from
that environment at startup. No token is printed, embedded in page source, put
in a URL, logged or saved in browser storage by this implementation.

The host binds only `127.0.0.1` at the explicit port. It runs in the foreground;
Ctrl-C closes it. It starts no browser, watcher, model, child worker or background
service. Importing its module opens no socket or store. Static assets are public
code only, with exact Host/loopback checks, a restrictive CSP, no-store and no
CORS. Every private route retains Bearer admission and the API's exact Host,
peer, scheme and mutation-Origin policy.

The request handler accepts one request per connection, at most16KiB of request
line/headers, one Host and no duplicate framing/auth/origin headers. It rejects
Transfer-Encoding and malformed/oversized Content-Length before dispatch. Reads
share an absolute20-second budget; individual socket reads/writes wait at most
five seconds and response writes recheck the connection budget. This is an IO
deadline, not interruption of CPU-bound decoding. Original encoded input remains
bounded at8MiB and20MP. The single foreground server serializes requests. It is
an explicit local host, not a public/multi-user production server or proxy target.

Create a collection or open its opaque32-character ID. Import **one image per
request**, select an item, and inspect stage status and actual source pixels.
`/detail` returns only canonically resolved retained geometry. `/render` verifies
the stored original and produces the canonical encoded-axis pixel grid as PNG,
avoiding JPEG EXIF display rotation. Encoded display output is capped at8MiB;
an image that exceeds this render bound refuses rather than weakening input
limits. The original download remains the verified original bytes.

At most500 lines and500 words are displayed, with an explicit truncation label.
Missing/model-claimed geometry is never replaced with invented boxes. Text uses
DOM text nodes, images use authenticated fetch and revocable blob URLs, and
selection/collection changes abort requests and reject late responses. Client
versions are opaque local request epochs, never conversions of server counters
or authority to access data. The backend remains authoritative.

Deletion first asks for explicit confirmation of the selected collection/item.
`cleanup_pending` remains incomplete; a lost receipt also remains unverified.
The same confirmed operation can be retried while that collection is current.
Only an identity-matching completed receipt with store/file/checkpoint fields
shows completed deletion. Switching collections/disconnecting clears local
intent; pending server cleanup survives and can be recovered through the
existing explicit collection-scoped CLI recovery. No completed deletion is
inferred from `not_found` or an aborted request. Delivered/downloaded bytes,
browser/OS caches and backups cannot be recalled by backend deletion.

Direct Python tests use real tiny generated images, SQLite and synthetic retained
OCR binding controls. Client/state tests use synthetic transport responses.
These checks are distinct from a real HTTP/browser journey, native OCR,
model/semantic capability, quality evaluation and whole-application acceptance.
