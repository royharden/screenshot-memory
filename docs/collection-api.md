# Local collection lifecycle API

`screenshot_memory.api.CollectionAPI(store, token=..., origin=...)` is an explicit
WSGI callable over the existing private `Store`. Importing or constructing the
callable starts no server, model, OCR worker or background task. It adds no dependency.
Use a cryptographically generated URL-safe token of at least 32 characters, retained
only by the trusted local host/client. Never put it in a URL, fixture, log or bundle.
The constructor validates its wire shape, not the token's entropy.

The embedding WSGI host must bind only the exact configured loopback address/port,
enforce bounded connection/body-read deadlines and supply correct WSGI framing and
peer metadata. No production server, command-line listener, reverse-proxy support
or browser viewer is supplied by this milestone. The private storage root must be
exclusively managed, outside any repository, as described in [storage.md](storage.md).

Every request requires the exact configured `Host`, `Authorization: Bearer <token>`,
an HTTP scheme and a loopback peer address. Mutation methods additionally require
the exact configured `Origin`. Read-only GET may omit Origin, as normal same-origin
browser fetches do; an explicitly supplied Origin must still match exactly. Empty,
`null` and foreign values refuse. For GET, any supplied `Sec-Fetch-Site` must equal
`same-origin`; missing Fetch Metadata is allowed for nonbrowser local clients.
Metadata is an additional refusal signal, never authentication. The token and
host/peer checks apply regardless of these headers.

No CORS permission is returned, and preflight without the required token/Origin
refuses. Admission precedes reading the request body or storage. Forwarded headers
do not supply authority. Responses use `no-store`, `nosniff` and same-origin resource
policy. These are request checks; they do not configure a host's network binding.
The Origin distinction follows [MDN's header description](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Origin).

| Method / path | Request | Response |
| --- | --- | --- |
| `POST /collections` | Empty body | 201, new opaque collection ID |
| `POST /collections/{collection}/items` | Raw `image/png` or `image/jpeg` body with Content-Length | 201, imported partial item; model execution false |
| `GET /collections/{collection}/items` | Empty body | Current visible metadata |
| `GET /collections/{collection}/items/{item}` | Empty body | Current item metadata |
| `GET /collections/{collection}/items/{item}/original` | Empty body | Verified owned original PNG/JPEG bytes |
| `DELETE /collections/{collection}/items/{item}` | `application/json`, exactly `{"confirm":true}` | Verified deletion receipt |

Uploads accept one image per request, never paths, URLs, folders, multipart bodies
or client filenames. A private temporary upload is removed after the canonical
importer copies it into managed storage. The existing decoder and transactional
admission retain 8 MiB/image, 20 MP/image, 30 images/collection and 100 MiB/collection
bounds. MIME and signature must agree; actual decoding still has to succeed.
Transfer-Encoding, malformed/oversized Content-Length and short bodies refuse.
Query strings, mounted prefixes and unrecognized/encoded path shapes refuse.

Deletion requires a boolean confirmation and explicit opaque collection/item IDs;
duplicate/extra JSON keys refuse. `deleted` (200) comes only from the existing
all-store/file/checkpoint verifier. `cleanup_pending` (202) remains hidden and can
be retried by the same confirmed DELETE. Missing items return 404. Foreign, deleted,
stale or tampered original/metadata reads refuse without returning source bytes.
Already delivered client bytes cannot be recalled. The guarantee remains active-store
logical removal, excluding forensic, backup and external-provider erasure.

Direct WSGI tests join this callable with real newly generated PNG/JPEG and SQLite.
They are distinct from a live server/browser test. Source overlays, OCR/model
execution, keyword/semantic endpoints, captions/features, a viewer and prescribed
DEV/heldout evaluation remain outside this lifecycle milestone.
