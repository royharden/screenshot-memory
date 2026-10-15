# Vector validation and explicit alignment

This is an implemented local mathematical and metadata core. No ML SDK or model
is installed or loaded by it. Native OCR, embeddings, paired-model admission,
gallery indexing, retrieval and model quality remain separate work.

Vectors are exact little-endian float32 bytes, exactly four bytes per declared
dimension. Reads reject non-finite values, zero vectors and a declared L2 norm
outside absolute tolerance 0.00001. Reads never normalize silently. The explicit
normalizer takes bounded Python float tuples, casts to float32 first, normalizes,
rounds to float32 and validates the result. Overflow and cast-to-zero fail.
Search cosine requires L2 spaces; it divides by the measured rounded norms and
clamps only final floating point drift to [-1, 1]. No NumPy/model dependency is
needed for this core; future SDK adapters convert and bind their actual outputs.

Ordinary comparisons require identical validated FeatureSpace IDs. Existing
feature-space descriptors, digests and equality have not changed. Equal
dimensions cannot authorize comparison across models, tokenizers, prefixes,
weights or preprocessing.

CrossModalAlignment explicitly binds one ordered 512-dimensional text-query and
image-target pair. Its complete descriptor includes both full FeatureSpaces,
their exported checkpoint/weights and tokenizer/preprocessor identities, matching
normalization identities, original joint checkpoint, export revisions, full
export config digests, paired source-metadata digest and provenance. The ID uses
SHA256 over ASCII `s7-cross-modal-alignment/1`, LF, then the complete descriptor's
sorted compact UTF8 JSON, with defaults/nulls and no Unicode normalization.
Both exported revisions must agree with their space declarations. Different
metadata needs a new binding/reindex; reversing the pair is unsupported.

Observed metadata requires observed paired spaces and an opaque actual capability
receipt reference. The validator does not fetch or authenticate those references
and cannot establish a common encoder from hashes or names. The model admission
layer must verify actual model cards, revisions, source/config/tokenizer/weights
bytes and a real paired capability receipt before admitting the pair. Matching
dimensions, structurally valid receipts and successful synthetic cosine do not
fulfil that obligation.

Cosine functions default to requiring observed declarations. Labelled synthetic
or declared mathematical checks require explicit `require_observed=False`.
Neither mode proves inference. Tests use synthetic data only; even their
syntactically observed variants contain explicitly fake receipt references.
There is no fallback to synthetic embeddings when a native model is missing.

Reusable source closure: `screenshot_memory.contracts`, this `spaces.py`,
Python 3.12 stdlib and Pydantic 2.14.1 plus its pinned runtime dependencies.
Loading the module performs no IO or model/provider import. Do not substitute
metadata validation for external provenance, storage generation or execution
checks. The generated CrossModalAlignment JSON schema describes structural
constraints; cross-field and exact-ID validators also run in Python.
