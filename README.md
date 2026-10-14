# Millennium RAG experiment setup

This repository root is the implementation target for the Langfuse hosted dataset experiment workflow. The plan and current preparation findings are in [the integration handoff](LANGFUSE_INTEGRATION_PLAN.md). The legacy repository is reference material only; the target project is implemented directly here.

## Stage 1 setup

Create a Python environment and install the SDK release verified against this machine's Langfuse instance:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r app/requirements.txt
cp -n .env.example .env
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

The current Langfuse Docker web and worker containers reached the host API through `http://172.18.0.1:8001`. Configure the remote experiment URL as `http://172.18.0.1:8001/experiments/run`, send the shared token in `X-Experiment-Trigger-Token`, and set `LANGFUSE_WEBHOOK_SECRET` to the Langfuse request-signing secret if signing is enabled. This gateway is specific to the current Docker network and must be rechecked after deployment changes. UI trigger setup and end-to-end acknowledgement remain Stage 3 acceptance work.

## Stage 2 implementation

The target app exposes `/ask`, `/index`, and the experiment API from `app/main.py`. Interactive calls and dataset tasks share `app/pipeline.py::run_pipeline(question, config)`. `/ask` keeps the reference defaults: baseline retrieval, 30 candidates, and 10 evidence passages. It requires the matching index to be ready and does not rebuild an index during a question request.

Start the Docker services after setting `.env` and the trigger token:

```bash
cp -n .env.example .env
# Set Langfuse project keys and a long random EXPERIMENT_TRIGGER_TOKEN in .env.
docker compose up --build -d
```

Build the default index once. Each indexing configuration receives its own content-addressed Qdrant collection; the manifest and point counts are stored in `data/experiments.sqlite3`.

```bash
curl -sS -X POST http://172.18.0.1:8001/index \
  -H 'Content-Type: application/json' -d '{}'
```

An interrupted or failed index is left incomplete and will not be silently reused. To explicitly rebuild that same index identity, pass `{"explicit_rebuild":true}` with the same `config` object. Existing other collections are retained.

Ask one interactive question through the shared pipeline:

```bash
curl -sS -X POST http://172.18.0.1:8001/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"Did Salander and Mikael have affair?"}'
```

Run all active items from the pinned QA dataset version through the CLI (on the host, activate the app environment and source `.env` first):

```bash
set -a; . ./.env; set +a
python app/experiments.py --dataset QA.csv --variant baseline
```

Use a configuration JSON file to change one component, for example `{"passage_chars":600}`. To run one item, add `--item-id <Langfuse-dataset-item-id>`. To rerun a historical snapshot, pass its UTC timestamp with `--dataset-version '2026-10-14T10:00:00+00:00'`. Every invocation creates a new execution ID, run name, and execution directory under `data/executions/`; an item's session ID remains stable across runs.

The HTTP trigger accepts Langfuse's `datasetName`/`datasetId` and `customPayload` fields. Custom payload fields are `variant_label`, `config`, optional `dataset_version`, and optional `item_ids`:

```json
{
  "datasetName": "QA.csv",
  "datasetId": "<Langfuse dataset id>",
  "customPayload": {
    "variant_label": "passages-600",
    "config": {"passage_chars": 600}
  }
}
```

The endpoint requires `X-Experiment-Trigger-Token`; configure the same `EXPERIMENT_TRIGGER_TOKEN` in Langfuse custom headers. If request signing is enabled, the endpoint validates the raw-body HMAC signature and timestamp using `LANGFUSE_WEBHOOK_SECRET`. It checks project/dataset access, queues the run, and returns `execution_id` and `status_url` without executing dataset items in the request. Poll `GET /experiments/{execution_id}` for state, item/scoring counts, manifest identifiers, and the Langfuse run URL. An optional `Idempotency-Key` makes transport retries return the existing execution.

The single worker uses the Langfuse Python SDK's hosted-dataset experiment runner at concurrency 1. It pins a historical dataset snapshot before selecting item IDs, writes a canonical snapshot checksum, resolves Hugging Face model commit SHAs when available, records pipeline and evaluator identities separately, and stores per-item evidence, outputs, errors, scores, and rationales. RAG latency and evaluator latency are recorded separately. An interrupted running job is marked failed on worker startup; a retry creates a new execution.

### Acceptance status

Automated tests have not been added in this stage. Python syntax compilation was checked during implementation. The single-item smoke run, full dataset run, variant comparison, live failure scenarios, and Langfuse UI trigger acknowledgement remain live/manual acceptance work for Stage 3. Report these as not run when their service prerequisites are unavailable.

This checkout publishes its app on host port `8001` because port `8000` is already used by the reference app in this environment. The UI callback address remains specific to the current Docker network. From the current Langfuse container use `http://172.18.0.1:8001/experiments/run`; after network or deployment changes, verify routing before enabling the trigger.

## Inputs and reference material

| Source | Target | Purpose / disposition |
| --- | --- | --- |
| Legacy RAG application's `app/main.py` and `tracing.py` | Reference only | Consult selected source behavior while implementing the API and tracing directly in this root project. |
| Locally supplied book files (`*.epub`) | local `corpus/` | Three corpus inputs copied into the target for indexing; excluded from Git. Their checksums are in the local integration handoff plan. |
| Target-root `QA.csv` | Used directly by `app/seed_dataset.py` | Authoritative 35-row seed; checksum is recorded in the handoff. |
| Legacy notebooks, results, HTML, indexes, caches, `.env`, and unrelated files | Reference/excluded | Exploratory, generated, secret, or outside the runtime workflow. |

Stage 1 preparation is complete: project `millenium` is verified, the 35-item dataset is seeded idempotently, and the three local EPUB inputs are in `corpus/`. Stage 2 code is implemented; verify the UI trigger acknowledgement, live run linkage, comparison visibility, and acceptance scenarios during Stage 3.
