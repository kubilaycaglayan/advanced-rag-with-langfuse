# Millennium RAG experiment setup

This repository root is the implementation target for the Langfuse hosted dataset experiment workflow. The plan and current preparation findings are in [the integration handoff](LANGFUSE_INTEGRATION_PLAN.md). The legacy repository is reference material only; the target project is implemented directly here.

## Stage 1 tools

Create a Python environment and install the SDK release verified against this machine's Langfuse instance:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r app/requirements.txt
cp .env.example .env
```

Set the project-scoped `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` in `.env`. Keep `.env` local. Langfuse should be reachable at `http://127.0.0.1:28420` from the host. The required hosted project is named `millenium`; the dataset is named `QA.csv`.

Check project/dataset access without changing Langfuse, then seed the target-root CSV once:

```bash
set -a; . ./.env; set +a
python app/seed_dataset.py --check-only
python app/seed_dataset.py
```

The seed command validates all rows before it writes, assigns deterministic UUIDv5 item IDs, maps questions to `input.question` and references to `expected_output.answer`, and records the CSV checksum and row provenance. It saves its import mapping under `EXPERIMENT_DATA_DIR` (default `./data`). On a later invocation it verifies the original rows without updating them. If a dataset already contains items but has no local seed mapping, the command refuses by default; `--reconcile-existing` permits an explicit check of deterministic seed IDs and provenance and can finish a partial first import. Once the original mapping exists, added Langfuse items are allowed, while missing seeded items are reported and never recreated. Edit live QA cases in Langfuse after the initial import.

The two evaluator definitions and the typed pipeline configuration/identity helpers live in `app/evaluator_specs.py`, `app/resolved_config.py`, and `app/identity.py`. Scores are `answer_correctness_v1` and `citation_support_v1`, each numeric in `[0, 1]`; their prompt templates and rubrics are versioned in code. `EVALUATOR_MODEL` is separate from `GENERATION_MODEL` and defaults to `qwen3:8b`.

## Callback routing

The current Langfuse Docker web and worker containers reached the host API through `http://172.18.0.1:8000`. After stage 2 adds the async trigger endpoint, configure the remote experiment URL as `http://172.18.0.1:8000/experiments/run`, send the shared token in `X-Experiment-Trigger-Token`, and enable Langfuse request signing if available (the SDK endpoint should verify `x-langfuse-signature`). This gateway is specific to the current Docker network and must be rechecked after deployment changes. UI trigger setup and end-to-end acknowledgement remain pending until the endpoint is implemented and project access is valid.

## Inputs and reference material

| Source | Target | Purpose / disposition |
| --- | --- | --- |
| Legacy RAG application's `app/main.py` and `tracing.py` | Reference only | Consult selected source behavior while implementing the API and tracing directly in this root project. |
| Locally supplied book files (`*.epub`) | `books/` (stage 2) | Three corpus inputs needed to build the index; use the target copy once staged. |
| Target-root `QA.csv` | Used directly by `app/seed_dataset.py` | Authoritative 35-row seed; checksum is recorded in the handoff. |
| Legacy notebooks, results, HTML, indexes, caches, `.env`, and unrelated files | Reference/excluded | Exploratory, generated, secret, or outside the runtime workflow. |

Stage 1 is not complete until the `millenium` project is verified, the 35-item dataset is seeded, and the actual remote trigger is configured and checked. See the status table in the handoff.
