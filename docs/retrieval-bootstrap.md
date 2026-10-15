# Retrieval callback to canonical paired resampling

`shared.retrievaleval.bootstrap` adds only S7 private domain assembly and metric
callbacks. It imports the unchanged canonical GoldRecord, Prediction, Outcome,
Statistic, ResamplingSpec and paired_group_resample. It contains no random draw,
percentile or generic resampling implementation.

The reference is a canonical GoldRecord with domain_kind `s7-retrieval/1` and a
closed domain payload containing `gallery` and `relevant` lists. Query IDs differ
from asset IDs. Each successful Prediction has a closed `ranking` list payload.
Assembly retains actual status, origin, issues, ledger references and human-input
flag, and binds the original prediction hash, method/config and source references.
The ranking is the machine domain output; a human-effective output does not
silently replace it. These references remain scorer-private.

Assembly requires an injected coverage resolver to inspect the exact prediction,
config, fixed gallery and recorded feature lineage. A nonempty inspected receipt
reference is required; absent/incomplete coverage refuses scoring. There is no
default permissive resolver and no production feature-coverage authority supplied
by this module. A receipt string or caller-created record alone authenticates
nothing. The initial tests explicitly inject a synthetic resolver. A resolver
that mutates its bound prediction or reference is rejected. Native feature/run
controllers must supply the actual admission implementation later.

Unexecuted, stale and unavailable predictions refuse measured resampling.
Executed eligible failures retain their closed status and count as zero misses.
Each recall1/3/5, hit1/3/5 or full-MRR callback is the equal mean over positive
queries. Empty relevant sets contribute no retrieval support; an all-negative
sample returns null with `no_positive_queries`. Correctness remains null rather
than coercing fractional recall into a boolean. Repeated groups repeat all their
queries, preserving multiplicity and support.

One canonical resampling call per metric supplies2000 common whole-group draws
with95% percentile intervals, minimum1positive query, minimum1900 valid draws and
the canonical minimum2 independent groups. The exact statistic version, seed,
ordered groups and optional strata must be frozen before tuning. Undefined draws
are not redrawn. Every paired method must retain the same fixed query/reference
axes; the gallery must remain identical throughout the population. The actual
canonical draw digest and valid/undefined interval metadata are returned.

These anonymous hand-computed controls are not a native retrieval measurement or
uncertainty estimate for the original corpus. Corpus conversion, recorded feature
admission, method execution, model/config/price locks, human/source authenticity,
dev selection and one-time heldout history/controller remain separate obligations.
No fixture or Gold file is read or changed by this module.
