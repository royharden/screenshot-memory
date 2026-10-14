# Original synthetic fixture corpus

There are30 original PNGs per split,60 total, with authored source-element boxes
and opaque filenames. Each split has132 query/case references and27 resampling
groups. Strata cover injected text, confuser pairs, blank/icon, dense/faint and
ordinary scenes. These are agent-authored synthetic references, not human gold.

The first data edition is bound by gold/manifest.json and heldout/FROZEN, before
original-gallery feature generation or tuning. They are data seals, not a model,
config, experiment or measured-result lock. Never silently rewrite original
images, boxes, labels, retained canon bytes or these seals.

`python scripts/make_fixtures.py --check` verifies all retained source bytes and
label links without fonts, rerendering or an exact Python patch requirement.
Explicit `--check --rerender` additionally requires the actual recorded original
runtime/fonts and compares the fixed original producer in memory without writes.
Unavailable rerender capability returns nonzero; portable checks remain mandatory.
See templates/PROVENANCE.md for source ownership, runtime and geometry limits.

No model outputs or measured retrieval results follow from these data checks.
