# Answer correctness v2: fact-based judging

Status: shipped 2026-10-19, default judge for new experiment runs.

## Problem

`answer_correctness_v1` asks qwen3:8b for a single 0 / 0.5 / 1 score against the reference answer. Three QA.csv
items showed how it under-scores correct answers:

- **Nickname** (`58343746`): "Kalle Blomkvist" is correct, but the reference's "key details" (origin, his dislike,
  Salander's usage) were treated as required: 0.5.
- **Police after assault** (`3206cb57`): claims supported by the evidence but absent from the reference were called
  "unsupported": 0.5.
- **Berger's position** (`360a9ab2`): "editor in chief" matches, but the extra (true) "chair of the board" was called
  an error: 0.5.

Two causes: the rubric never says that extra claims are fine, and the three-step scale turns any doubt into 0.5.

## Design

1. **Facts in the dataset.** Every item's expected output keeps `answer` and gains `required_facts` (the minimal
   facts that answer the question) and `supporting_details` (elaboration). Source of truth:
   `datasets/answer-facts.json`, uploaded with `python app/answer_facts.py --apply` (dry run without `--apply`).
2. **The judge gives verdicts, code gives the score.** For every fact ID (R1…, D1…) the judge quotes the answer's
   words and returns `present` / `partial` / `missing`; Ollama's JSON-schema `format` makes every ID required.
   `evaluation.fact_score`: required facts carry 90% of the score, details 10% (present 1, partial 0.5, missing 0);
   without details, required facts carry all of it. Extra information is never penalised. An item without facts
   is judged against one fallback fact: the reference's core answer.
3. **Selectable judge.** `correctness_evaluator` in the trigger payload (or `--correctness-evaluator` on the CLI)
   picks `answer_correctness_v2` (default) or `answer_correctness_v1`. The score name follows the judge, so v1 and v2
   scores never mix in Langfuse charts. The managed evaluator `millennium-answer_correctness_v2` holds the editable
   prompt, with `required_facts` and `supporting_details` mapped from the expected output.

## Versions and rollback

- Langfuse versions dataset items. Versions before the facts were added (snapshots also in
  `data/dataset-snapshots/2026-10-19-before-answer-facts/`):

  | Dataset | Version before facts | Items |
  |---|---|---|
  | QA.csv | 2026-10-15T15:17:02.446Z | 36 |
  | Additional Questions | 2026-10-16T21:30:29.874Z | 8 |
  | set3 | 2026-10-17T13:55:58.455Z | 15 |
  | right-set-3 | 2026-10-17T14:01:09.353Z | 28 |

  Facts version 1 was uploaded at 2026-10-19T11:21Z. Pass `dataset_version` to run against an earlier version.
- To go back to the old judge, run with `correctness_evaluator: answer_correctness_v1`. It reads only `answer`, so it
  behaves the same on the new dataset versions.
- To revise facts, edit `datasets/answer-facts.json`, bump its `version` and run `app/answer_facts.py --apply`. Each
  upload is a new dataset version, and items record `facts_version`.

## Trial (offline re-scoring of saved answers)

The latest saved run of each dataset was re-scored with three prototype prompts, with no new pipeline runs (scripts and
outputs: `data/tuning/scripts-2026-10-19-answer-facts/`). The shipped version is prototype c.

| Dataset | Items | v1 mean | v2 mean | v2 higher by >0.2 | v2 lower by >0.2 |
|---|---|---|---|---|---|
| QA.csv | 36 | 0.694 | 0.736 | 10 | 5 |
| Additional Questions | 8 | 0.562 | 0.564 | 1 | 1 |
| right-set-3 | 28 | 0.679 | 0.769 | 9 | 1 |
| set3 | 15 | 0.433 | 0.456 | 5 | 3 |

- The three examples: nickname 0.5 → 0.92, police 0.5 → 0.925, Berger 0.5 → 0.9.
- Most drops are wrong answers that v1 gave 0.5 by default: "Zalachenko" as Dag Svensson's murderer, "Zalachenko unit"
  for the Section, Harriet "killed", Gottfried's death as an accident.
- Prototype a (verdict lists, with a "contradicted" verdict and a wrong-claims cap) marked compatible extras as
  contradictions (Berger → 0). Prototype b (free-form ID lists) dropped or relabelled IDs.
- **Known limit:** qwen3:8b still flips on about 10 of 87 items between prompt wordings, e.g. backpack contents 0.9 ↔ 0,
  the Berger/Mikael relationship 0.74 ↔ 0.48. A larger judge model is the next step if this noise matters.
