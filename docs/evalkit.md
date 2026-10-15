# Canonical evaluation framework

The retained shared/evalkit implementation supplies canonical private GoldRecord,
public method input, Prediction and Outcome types; bounded frozen-corpus checks;
injected comparison; generic statistics; and paired 2000 whole-group resampling.
It is the same owner implementation, with no S7 statistics or bootstrap clone.
Its original README and schema are included as package data. Provenance and MIT
notice details are in docs/third-party/evalkit.md.

The engine checks fixed paired population axes before callbacks or random draws.
Methods share one group stream, preserving repeated groups and all their cases.
Undefined samples are not redrawn. The caller freezes support meaning, statistic
version, group order, seed and any strata before tuning. Insufficient independent
groups, support or valid draws yields no confidence interval.

The canonical corpus/runner separates scorer-only references from public input.
Structural private-key checks cannot authenticate arbitrary source content or
prevent every semantic label leak; the S7 adapter must assemble safe public views.
Matching reference hashes and synthetic history spies do not establish independent
Gold, human labels, source rights or durable heldout exposure control.

This component does not yet connect S7 retrieval ranks, original corpus records,
guard/region metrics, provider accounting or a one-time heldout controller. Its
authored tiny conformance cases are implementation controls. They are not an
application benchmark, native OCR result, uncertainty estimate or app acceptance.
