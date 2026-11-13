# Native quality evaluation rules

`rules.py` defines two persistent Langfuse rules for v2.12 measurement observations:

| Rule | Eligible questions | Evaluators |
| --- | --- | --- |
| millennium-qm-retrieval-rule | normal, single_evidence | millennium-qm-retrieval |
| millennium-qm-answer-quality-rule | all three types | millennium-qm-faithfulness, millennium-qm-relevancy |

Run `python -m app.quality_evaluators.rules` to compare definitions with Langfuse;
add `--write` to create or update these two rules through the public API. Use the
repository's one-off container instructions when running inside Docker.
Reconciliation does not submit observations, execute judges, or modify old rules.

Prepared observations must use `OBSERVATION_NAME` and
`observation_metadata(qrels_item, ...)` from `rules.py`. The helper adds
`pipeline_version`, `question_type`, and `retrieval_evaluation` metadata. The last
field is `skip` for broad questions and `enabled` otherwise. This installed
Langfuse rejects category-list filters on metadata, so the retrieval rule uses
that derived flag with a string equality filter. Unknown or conflicting labels
raise before submission. Keep the same question type in the observation input
because the retrieval evaluator uses it to select Hit@K or precision/recall.

Langfuse stores the applied rules and assignments in PostgreSQL. Historical
rules, scores, errors and retries remain there; these rules match only the new
prepared observation name. The QA1 submission utility now uses these shared
rules and writes a uniquely named manifest for each run, recording rule snapshots,
evaluator versions, run ID, source trace, and observation ID.

Changing routing does not change the pipeline.

The faithfulness and relevancy judges use `qwen3.6:35b-judge-16k`, derived from
`qwen3.6:35b` with `num_ctx 16384`. `Modelfile.judge` records the model definition.
Create it on the Ollama host with
`ollama create qwen3.6:35b-judge-16k -f app/quality_evaluators/Modelfile.judge`,
then run `python -m app.quality_evaluators --write` to version the Langfuse judge
definitions. The variant shares existing weights. It does not change the base
model or Ollama's service-wide default. Historical evaluator versions and scores
remain available in Langfuse.

## Scoring existing traces with `quality_metrics.py`

With `--write`, each evaluation creates a `quality evaluation` parent under the
source experiment trace. Child spans measure source extraction, retrieval,
faithfulness, and relevancy; retrieval has a child for each search call. Scores
are attached to the span that produced them and include `duration_seconds` in
their metadata. Per-call spans retain the source search observation ID. The
parent output records component durations and errors; skipped judges have a
reason and no numeric score. A failed judge does not prevent the other judge
from running, and the command exits nonzero if either judge fails.

The source trace must be fetched before its root can be identified. Fetch time
is included in the parent output's total and source durations, while the
parent's Langfuse span starts after that fetch. Historical scores retain their
original attachments; past per-metric durations cannot be recovered from the
older combined timings.
