# Original synthetic fixture inputs

This collection is an agent-authored provisional S7 fixture subset. It is not a
canonical owner manifest, real screenshot corpus, human gold set, or evidence of
native OCR/model/retrieval execution. All UI shapes, text, scenarios and queries
were authored originally for this collection by blinded fixture author 0039.
The author did not inspect features, ranking logic, retrieval outputs or tuning.

There are thirty scenes in each split. Each split has three injected-text scenes,
three two-image confuser groups, one blank field, one icon-only scene, four dense
worksheets (two deliberately faint) and fifteen ordinary scenes. These strata are
disjoint. Each image has four positive cases; text-free cases explicitly replace
exact/paraphrase text cases with visual/mixed cases. Each split also has twelve
labeled empty-target negatives with private contextual resampling groups.

Development scenes use handcraft/garden work surfaces with heading cards, shelves,
columns, ledgers or boards. Held-out scenes use fictional field-science content
with left rails, timelines, folios or orbit diagrams. Distinct families, titles,
focus texts and layout names are checked across splits. Exact image hashes and a
bounded 900-pair 64x40 RGB structural comparison are checked too. Shared ordinary
words are reported; this is an authored topical separation, not a learned semantic
or independently adjudicated similarity guarantee. Confuser likeness within each
declared two-image group is intentional.

Pillow 10.4.0 on Python 3.12.13 draws the retained PNGs in RGBA mode. The generator
records actual Arial/Consolas source-file hashes and font metrics. Font files are
Windows-provided inputs and are not copied or distributed. Cross-machine consumers
should use the original PNG bytes; rerender verification requires the recorded
local fonts and exact runtime. A seed changes only deterministic decorative marks;
seeds alone are not treated as evidence of split independence.

Boxes record actual `ImageDraw.textbbox` or authored shape positions in displayed
source-pixel, top-left coordinates, page zero. They are target-element boxes,
not native OCR word/line detections. A blank image has explicit null spatial
targets. Native OCR word/line capability remains required in later delivery.

The grid digest hashes compact sorted UTF-8 JSON for the exact owner header,
then LF, then top-to-bottom row-major decoded RGBA bytes. Each retained header
`.canon` file and original PNG recovers that entire preimage. Raw encoded PNG
digests remain separate. Asset/query/label/group/scenario/source/gallery IDs are
opaque 32-hex values from distinct namespaces; only opaque IDs appear in filenames.

The original producer generated once with `scripts/make_fixtures.py --split dev
--seed 731701` and `--split heldout --seed 731702` in the managed Windows runtime.
Its exact historical source bytes are retained as `producer-v1.source`, SHA256
`d5afd012a74a4b0d25c06ef7913055c8ffad156ff358a984cfe4edf243d8455a`. That is the
producer hash in the untouched original manifests. The current active script is
a successor auditor; its separate source hash is reported without claiming that
it generated those originals. Original source/test/document evidence is also
preserved in the outer-shell pre-edit receipt.

`--check` now audits the retained original PNG/box/header/canon/inventory bytes,
dimensions, caps, label linkage and public projections without opening fonts,
executing the producer, rerendering, or requiring an exact Python patch version.
It validates retained producer metrics through their frozen source-box hashes;
it does not claim to have independently recomputed font metrics. This portable
default always runs in the fixture tests, including with absent font paths and
font/build entrypoints explicitly forbidden. That simulation is distinct from
an actual Linux execution receipt.

`--check --rerender` explicitly requests a separate in-memory comparison using
only the fixed hash-verified historical producer source. No manifest selects a
code path. Real original font files/hashes, Python 3.12.13 and Pillow 10.4.0 are
required for this optional operation. Missing/different inputs produce a
requested-but-unavailable report and a nonzero exit, after the portable audit;
there is no fallback font or skipped-rerender pass. No originals are overwritten.
The default verifies the archive bytes without executing them.

Any existing output artifact makes generation refuse before font/runtime/build
work or writes. A changed renderer/template/font/runtime requires an explicit
successor appointment; there is no silent overwrite/reseal route. Earlier
32-pass fixture evidence applies only to its actual Windows/font-present runtime;
successor audit and rerender evidence must state their actual capabilities.

Private `gold/*.PROVISIONAL.json` files contain provisional references. Separate
`*.public.PROVISIONAL.json` files allow only query text, opaque query ID and declared
gallery configuration. Negative contextual groups, labels, traps, strata, target
boxes, families and scenario IDs stay out of the public projections. Retained
canon/1 byte files accompany the manifests and actual file hash inventories.

The parent must audit the raw corpus and exclusively produce the final owner
`gold/manifest.json` and held-out freeze marker before any feature outputs. Actual
owner scorer/config/experiment/model/price enrichment is unavailable here and is
listed explicitly in each provisional subset. The author does not claim a final
seal or finished-app acceptance.
