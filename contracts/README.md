# Owned metadata contracts

`src/screenshot_memory/contracts.py` is the source for Collection, Item,
StageStatus and FeatureSpace. DeleteReceipt is defined in shared/vindex/deletion.py.
`generated/` contains all five derived JSON Schema2020-12 documents:

```sh
python scripts/generate_schemas.py
python scripts/generate_schemas.py --check
```

Use the pinned Python3.12/Pydantic environment. Regeneration is deterministic in
that environment; `--check` reports drift without writing. The old unvalidated
proposal schemas have been retired. JSON Schema captures individual field shapes
and bounds. Pydantic validators additionally enforce products/totals, stage sets,
generation, outcome coherence and descriptor digests; schema-only validation does
not establish those cross-field rules.

IDs and counters are strict, immutable values. No coercion from strings, floats
or booleans is permitted for integer fields. Item limits are8MiB encoded and20M
decoded pixels; collections declare at most30items and100MiB. Metadata cannot
prove the declared counts/bytes match any actual store. MIME signatures, actual
decoded pixel limits require the later ingestion implementation. The separate
vindex Store atomically enforces admitted record totals and verifies original
file size/hash; these model declarations alone enforce nothing on files/stores.

Raw encoded source hash, opaque owner raw revision, retained source-grid hash,
evidence-artifact hash, stage processing revision and item generation are separate
fields. Source object IDs are logical handles, never file paths or capabilities.
Docio/Page/Pointer/provider wire types and their codecs remain owned elsewhere;
there is no second implementation here. References are not fetched or verified.

Every item has exactly one status for each of decode, OCR, caption, text embedding
and image embedding. Missing/blocked/failed/stale/partial/not-applicable are
explicit. Reusable output requires current generation and a processing/result
identity; an old generation cannot become a current ready result. An item cannot
declare itself ready while a required leg is missing. Only the text-embedding
leg may be explicitly not applicable on a ready item (for successful empty OCR).
Neither these enums nor a valid Item constitute execution or deletion evidence.

A FeatureSpaceDescriptor binds model/version, checkpoint and weights digests,
implementation, modality/dimensions, preprocessing, tokenizer/token limits,
query/document prefixes, float32 dtype, normalization policy and provenance.
Normalization identity is SHA256 over `s7-normalization/1`, one LF, then UTF8
sorted compact JSON with keys dtype/method/version. Feature-space identity uses
the same construction with domain `s7-feature-space/1` and the complete descriptor
model dump (including schema version, nulls and defaults). JSON uses
ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False.
Prefix text is preserved exactly without trimming/Unicode normalization and has
a512UTF8-byte cap. No vector normalization or embedding occurs here.

Compatibility requires exact feature-space IDs. Equal dimensions alone cannot
make different checkpoint, prefix, tokenizer or preprocessing configurations
compatible. A declared model name or synthetic hash does not establish an
installed checkpoint or verified execution. The observed provenance variant
requires opaque checkpoint/weights/receipt references, but validation does not
read or authenticate any of them. Current tests use synthetic declarations only.

These are internal metadata contracts with closed fields, not general-purpose
public serialization or logging of user data. Query text, gold labels and target
sets are absent. Do not log full validation errors with input payloads; the models
hide inputs in their string errors, but structured error objects need an explicit
safe projection. Revalidate untrusted data with model_validate/model_validate_json;
model_construct/model_copy are not trusted validation entrypoints.
