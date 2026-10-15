# S7 domain metric core

This slice computes mathematics on caller-declared ranks and reference asset IDs.
It performs no retrieval, feature/model work, dataset reading or benchmark run.
It does not replace the owner's generic GoldRecord, MethodRunner, manifest,
experiment/report or resampling framework. Query/case IDs differ from gallery
asset IDs. References and per-case rows are scorer-private; no text is needed.

`score_ranking` accepts only unique produced IDs from a declared gallery of up
to30 assets. It never inserts missing IDs or pads rankings. Positive-case
recall@1/@3/@5 is the fraction of relevant assets retrieved; hit@k is separately
one or zero. MRR uses the first relevant position anywhere in the full produced
ranking, including positions11–30. A missing relevant ID contributes zero.
Empty target sets are explicit negative cases and have no retrieval denominator.
They cannot become fabricated zero recall; no-answer guards need separate checks.

`score_method` averages equally over positive queries, not pooled relevant assets.
Every declared query needs an explicit produced entry. `None` means not executed;
any such entry makes aggregate metrics unmeasured/incomplete. An empty tuple
means an executed empty ranking and counts as a miss. An executor may use that
for an eligible recorded failure, while retaining its real failure status in its
own private run record. These declarations alone do not prove any method ran.

`grouped_mean` is a domain callback for a supplied whole-image-group draw. A
repeated group repeats all its cases. Eligible query values are averaged over
the resulting cases, so groups with different case counts retain their actual
weight. `None` in this callback means no metric denominator; it must never hide
a failed attempt that should count as zero. No eligible case yields no estimate.
`paired_draw` applies exactly the same draw and eligibility to every method and
returns arithmetic deltas. Incomplete methods must first be rejected by the run
adapter; eligibility mismatches fail. These helpers do not choose random draws
or calculate confidence intervals.

The canonical owner evalkit source is now retained separately under shared/evalkit,
including its 2000-draw paired whole-group engine. The original synthetic corpus
has a recorded data-only freeze. Still pending: S7 execution/manifest/scorer
adapters, native feature/ranking integration, guard and region metrics, retrieval
callbacks with frozen support policy, actual dev tuning and one sealed held-out
event. No quality, uncertainty, latency or cost measurement follows from these
synthetic unit controls or from importing the generic evaluation framework.
