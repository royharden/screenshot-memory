# Portable lexical reference and fixed rank fusion

These two pure components accept caller-declared anonymous text or ranks. They
do not read files, SQLite, images, models, Gold, providers or current generations.
They do not establish a completed search pipeline or a quality measurement.

`shared.retrievaleval.bm25.bm25` searches every document in a supplied corpus of
1–30 items, including empty documents in corpus size and average token length.
Version `s7-nfkc-casefold-unicode-alnum/1` applies NFKC, casefold and contiguous
Unicode alphanumeric runs. Underscores and punctuation delimit; numbers and
accents remain; there is no stemming or stopword removal. CJK runs remain whole
tokens. This is a portable reference with documented differences from production
SQLite `unicode61 remove_diacritics 2`, whose migration/integration is pending.

The fixed reference uses IDF `log(1+(N-df+.5)/(df+.5))`, k1=1.2, b=.75 and unique
query terms. It returns every positive-score match sorted by descending score,
then opaque item ID. It returns an empty tuple for no matching terms. It never
pads zero-score items or silently truncates oversized input. Caller text has a
25,000-character document bound and query a 1–1,000-character bound. This bound
and tokenizer are reference metadata, separate from model tokenizer limits.

`shared.vindex.fusion.fuse` requires exactly keyword, combined and image legs.
Each item contributes once per leg with `1/(60+rank)`, beginning at rank1.
It returns the full union, at most30 items, sorted by descending score then ID.
OCR-only and caption-only ablations are not additional production votes.
Duplicate ranks and items outside the caller-eligible gallery are rejected.
An executed empty leg is active; `None` means unavailable. Result status records
available/degraded/unavailable independently of whether any hit was produced.
Weights are not probabilities or calibrated no-answer scores.

Actual namespace/current-generation checks, full-corpus execution, incomplete
feature coverage, SQLite escaping/migration, native embeddings, guards, region
resolution, persistence, dev tuning and the one held-out event remain separate
integration requirements. These anonymous hand-computed controls touch neither
the original corpus nor the frozen evaluation data.
