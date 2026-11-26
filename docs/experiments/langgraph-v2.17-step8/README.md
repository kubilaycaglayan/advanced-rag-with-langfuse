# v2.17 Step 8 — serial live validation

In progress. Starting revision: c107e224fe310218c4c726f2798a1104b30694cd.

Uses the frozen Step 1 sample and provider-specific recorded item results. OpenAI settings select high reasoning as frozen; Ollama retains the catalog settings. Every invocation selects exactly one item, explicit v2.17 and cache bypass in the Step 2 isolated Python 3.12 app image. The repository/Git mounts and safe-directory configuration follow AGENTS.md. The live application and default pipeline remain unchanged.

The first run is OpenAI question 1, the frozen mathematics-book smoke check. Each completed run must be reviewed before advancing; retain all attempts and allow at most two additional diagnostic attempts for a regressed item. Correctness and latency must refer to the same selected attempt. Step 9 aggregate acceptance and release are outside this work.

## Review notes

OpenAI Q1 attempt 1: correctness 0.95 versus 0.90; citation support 1.0; answer identifies Dimensions in Mathematics. No tool, evaluation or telemetry errors. The live trace has graph-node parents under agent graph, sequential tool spans under tool processing, model spans nested through turns/verification, provider prompt usage on all five calls, and exactly one finalization. Selected attempt 1, latency 18.59 seconds (baseline 16.09).

OpenAI Q2 attempt 1: correctness 0.95 versus 0.975; citation support 1.0; correctly rejects the killing premise. The evaluator assigns partial supporting details; no execution or trace error was found. A diagnostic retry was started before advancing.

The first OpenAI manifest's evaluator differs from its historical evaluator only in code_fingerprint and derived evaluator_id; all managed definitions are identical. This distinction stays visible in retained manifests. The historical local fallback/model/evaluator differences from Step 1 remain applicable.

The retained manifests record exact Git revisions and dirty flags. Documentation and evidence commits during validation do not alter the pipeline source fingerprint. Acceptance evidence must use one unchanged executable source/configuration; any executable change requires superseding affected results.
