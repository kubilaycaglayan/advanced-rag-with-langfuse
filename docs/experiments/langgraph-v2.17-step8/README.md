# v2.17 Step 8 — serial live validation

In progress. Starting revision: c107e224fe310218c4c726f2798a1104b30694cd.

Uses the frozen Step 1 sample and provider-specific recorded item results. OpenAI settings select high reasoning as frozen; Ollama retains the catalog settings. Every invocation selects exactly one item, explicit v2.17 and cache bypass in the Step 2 isolated Python 3.12 app image. The repository/Git mounts and safe-directory configuration follow AGENTS.md. The live application and default pipeline remain unchanged.

The first run is OpenAI question 1, the frozen mathematics-book smoke check. Each completed run must be reviewed before advancing; retain all attempts and allow at most two additional diagnostic attempts for a regressed item. Correctness and latency must refer to the same selected attempt. Step 9 aggregate acceptance and release are outside this work.

## Review notes

OpenAI Q1 attempt 1: correctness 0.95 versus 0.90; citation support 1.0; answer identifies Dimensions in Mathematics. No tool, evaluation or telemetry errors. The live trace has graph-node parents under agent graph, sequential tool spans under tool processing, model spans nested through turns/verification, provider prompt usage on all five calls, and exactly one finalization. Selected attempt 1, latency 18.59 seconds (baseline 16.09).

OpenAI Q2 attempt 1: correctness 0.95 versus 0.975; citation support 1.0; correctly rejects the killing premise. The evaluator assigns partial supporting details; no execution or trace error was found. A diagnostic retry was started before advancing.

The first OpenAI manifest's evaluator differs from its historical evaluator only in code_fingerprint and derived evaluator_id; all managed definitions are identical. This distinction stays visible in retained manifests. The historical local fallback/model/evaluator differences from Step 1 remain applicable.

The retained manifests record exact Git revisions and dirty flags. Documentation and evidence commits during validation do not alter the pipeline source fingerprint. Acceptance evidence must use one unchanged executable source/configuration; any executable change requires superseding affected results.

## Serial gate pending

All three permitted OpenAI Q2 attempts completed at 0.95, below the historical 0.975. No later pair was started. See the decision request in HUMANS.md and the exact attempt selection/progress in progress.json. Step 8 is incomplete pending that decision and the remaining 18 pairs.

A read-only evidence audit verifies all four retained attempts against the fixed sample: exact question/item selection, fresh bypass mode, execution/trace identity, no item/evaluator/telemetry/tool errors, one shared executable source fingerprint, one finalization per run, and actual start/end containment of each observation in its parent. All managed evaluator definitions equal their OpenAI historical definitions. The audit preserves per-artifact hashes and per-attempt score/latency without changing baselines or calculating Step 9 aggregate acceptance. Reproduce with `python scripts/langgraph_audit_live_evidence.py`; evidence-audit.json is its saved output.

## Continued validation and factory gate

Developer resolved the Harriet and first-book-summary evaluator discrepancies in chat and authorized continuing; those decisions are retained in HUMANS.md and progress.json. OpenAI Q7 scores 1.0, and Q8 reaches 1.0 on its third and final attempt, selected with its own 32.95-second latency. Every prior attempt remains retained.

OpenAI Q9 exhausts all three attempts with best correctness 0.5167 versus 1.0 historically. It omits required nail-gun immobilization; one attempt confuses the brickworks and Gosseberga scenes. This is a substantive unresolved regression, escalated separately in HUMANS.md. Attempt 1 is provisionally selected as the earliest best-score tie with its own 41.12-second latency. No later item has started. The prior “serial gate pending” notes are historical; current progress.json and HUMANS.md identify the active gate.

## Factory scorer correction and final executable revision

The developer approved the selected factory answer as fully correct and requested an isolated scorer correction. The final rubric changes only factory item 36c50723-3b65-49f6-9d9b-70574cc9471c: its primary path requires being trapped with Niedermann, fighting/escaping, and alerting the police and bringing the bikers. Bodies and nail-gun details remain optional on this approved path. The original accepted alternative remains available. Other stored item rubrics and global scorer settings are protected by a hash regression test. Exactly one live dataset item changed; no managed evaluator prompt, generic scoring code or other item changed. The facts file retains its global version to avoid rewriting other items; rubric hashes in the rescore artifacts distinguish these specific revisions.

The initial alternative-only rubric rescore proved unreliable and is superseded by factory-rubric-rescore-v2.json. Original results are immutable: the final rescore artifact supplies effective correctness. Attempts 1/3 score 1.0; the scene-confused attempt 2 scores 0.5. Selected attempt 1 keeps its original 41.12-second answer latency. Rescoring makes judge calls only, never regenerates answers or historical baselines, and stores separately named Langfuse scores with rubric/source identities.

OpenAI Q10 exposed a genuine preparation failure: scene_moment passed seven arguments to a six-argument function. The signature-aware regression test fails before the fix; 94 agent/execution tests pass after removing the obsolete None argument. Final executable revision is 327674d. The successful Q10 retry scores correctness/citation support 1.0. moment-fix-impact.json identifies the failed Q10 attempt and an unselected Q8 diagnostic attempt as affected. Comparing complete source manifests proves the only changed executable file is app/agent/tools/scenes.py; selected earlier questions never call its changed moment helper. They remain applicable under the roadmap's affected-item-only rerun policy. All subsequent Ollama runs use the final source.

The audit now checks exact final source or that narrowly verified compatibility, separately archives the failed attempt, and verifies effective rescore values and original generation latencies. This does not constitute Step 9 acceptance or deployment approval.

## Local validation continuation

Developer authorized recording verified evaluator-only discrepancies without altering other scorers. Ollama Q1 is recorded under that authorization. Ollama Q2 exposes substantive unsupported claims in all three permitted attempts despite high numeric correctness scores. It is escalated separately in HUMANS.md, with eight local questions still pending. The saved correctness scores are not treated as proof of answer validity; progress.json identifies the active gate and provisional numeric selection.
