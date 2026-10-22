# The Alienist Backend Setup

## Goal

Serve *The Alienist* through the shared RAG backend while keeping its corpus files, indexes, caches, experiment records, Langfuse assets, sessions, and traces isolated from Millennium. Corpus IDs are the human-readable `millennium` and `thealienist`. Only one corpus is active in the existing Compose deployment at a time. This phase does not add an Alienist UI.

Millennium is the compatibility boundary: do not edit released pipeline definitions or their fingerprints. If shared implementation code contains Millennium-specific behavior, keep its current effect for Millennium and put other-corpus behavior in the selected corpus profile or a clearly scoped implementation branch.

## Alienist Configuration

The corpus manifest is `corpora/thealienist/corpus.yaml`. It selects the `thealienist` profile, reads `books/`, maps `set-1.csv` to the Langfuse dataset `set-1`, and selects the Langfuse project and evaluator prefix `thealienist`. The EPUB and CSV were already supplied locally; the CSV remains ignored by Git under the current ignore rules.

The profile provides a separate agent system prompt, name patterns, synthesis instructions, translation prompt, and the Alienist wording for the chapter-reading tool. The shared retrieval, embedding, reranking, scene, entity-card, and answer orchestration code remains in use. Shared prompts fall back to the existing text for Millennium; Alienist-specific prompt overrides are included in its profile identity.

The seed importer accepts `Question`/`Answer` or lowercase `question`/`answer` headers (case-insensitive), and still rejects malformed columns, blank values, and duplicate normalized questions. Seed mappings and run artifacts are written under `data/thealienist/`.

## Isolation and Tracing

- Qdrant collection names include the corpus ID and the content/config fingerprint. Local SQLite execution and index-manifest state, entity artifacts, cache identities, and rate-limit files resolve under the selected corpus's data directory.
- Langfuse uses project-scoped keys from `.env`. Switch to keys for the `thealienist` project before selecting Alienist. Its prompt catalog is bootstrapped inside that project; evaluator names use the `thealienist-` prefix. The answer correctness and citation support definitions remain versioned as in Millennium.
- With `thealienist` selected, `/ask` requires enabled Langfuse credentials that can access the configured project, and refuses to answer if it cannot start a trace. A question's normalized text determines its `question-…` interactive session, so client-supplied session IDs cannot group multiple questions. Experiment traces use the existing stable session derived from the dataset item, allowing the same question to be compared across runs.
- Question traces carry the question, answer, corpus and pipeline identities, and the pipeline's nested retrieval/model/tool observations. Experiment runs additionally link evaluator observations and scores to the item trace. The experiment runner uses `answer_correctness_v2` by default and `citation_support_v1`, with one authoritative score per evaluator and item; it does not require a separate Langfuse rule that would duplicate those scores.
- Interactive `/ask` records the question lifecycle trace. Automatic evaluator scores are produced by the hosted-dataset experiment flow; its preflight requires the managed evaluator objects before it starts processing dataset questions.

## Setup and First Run

1. Create a Langfuse project named `thealienist` and create project-scoped API keys. Ensure its local-model connection matches the existing evaluator setup. Put the Alienist keys in the local `.env`; never put credentials in the corpus manifest.
2. In `.env`, set `CORPUS_ID=thealienist`, `DATASET_NAME=set-1`, `LANGFUSE_ENABLED=true`, and the `thealienist` project keys. Compose now mounts `corpora/${CORPUS_ID}` at the matching corpus root. Stop the Millennium frontend and tunnel while operating the Alienist backend: `docker compose stop frontend cloudflared`.
3. Restart the API with the selected corpus: `docker compose up -d --build app`.
4. Bootstrap missing prompts and evaluator objects in the selected Langfuse project: `docker compose exec app python -m app.prompt_assets --create-missing`. Then inspect the catalog with `docker compose exec app python -m app.prompt_assets`. Reconciliation reports definition mismatches; it does not silently replace existing versions.
5. Import the local question set: `docker compose exec app python -m app.seed_dataset`. Verify project and dataset access with `docker compose exec app python -m app.seed_dataset --check-only`.
6. Build the default pipeline index: `POST http://127.0.0.1:8001/index` with `{"pipeline":"v2.12"}`. This builds passage extraction, embeddings and Qdrant vectors plus the scene/context/entity artifacts enabled by the selected pipeline configuration. Check the returned collection and artifact results; `/ask` validates that the configured index artifacts exist and match the selected corpus/config.
7. Ask a first interactive question with `POST http://127.0.0.1:8001/ask` and `{"question":"…","pipeline":"v2.12"}`. Confirm the returned trace ID in the `thealienist` Langfuse project and inspect the `question-…` session and nested spans.
8. Before a dataset run, confirm the default correctness and citation evaluators are present, active, versioned, and use the expected 0–1 output contract. Start a smoke experiment with `docker compose exec app python -m app.experiments --dataset set-1 --pipeline v2.12 --variant alienist-smoke --item-id ITEM_ID`. Confirm the item has a trace and both evaluation results before running the full set.

To return to Millennium, switch `.env` to `CORPUS_ID=millennium`, `DATASET_NAME=QA.csv`, and Millennium's project keys, then restart the app. Compose resolves its book mount, API title, index identity, and artifact namespace from the selected corpus. Do not leave the Millennium UI running against the Alienist backend.

## Indexing Behavior

`POST /index` runs the configured build synchronously. It always extracts passages, loads the embedding model, creates normalized vectors, writes passage payloads to the corpus-specific Qdrant collection, and records a ready index manifest only after count verification. It also builds scene vectors when scene indexing is enabled, scene context vectors when context is enabled, entity cards when name/matrix/graph features require them, and entity event artifacts when graph indexing is enabled. A prior matching ready passage index is reused. The endpoint does not import the Langfuse dataset or configure evaluator assets; those are separate setup steps above.

## Acceptance Checks

- Selecting `thealienist` resolves only its EPUB, profile, question set, Langfuse project, and `data/thealienist/` artifacts; switching back resolves Millennium's current resources.
- The Alienist Qdrant collection has the `thealienist_books_` prefix, corpus checksum, and passage count matching its manifest. Every optional artifact required by `v2.12` is ready before asking.
- Alienist prompt/evaluator assets and dataset are available only in its Langfuse project. The importer validates the lowercase CSV headers and imports the expected question count.
- An interactive Alienist answer cannot proceed without project access and an active Langfuse trace. Its trace contains the input, answer output, pipeline observations, and one-question session. Experiment item traces share the stable item session across runs and link the versioned evaluator observations and scores.
- Pipeline catalog and release fingerprint files are unchanged, and Millennium's existing profile and effective prompt text remain unchanged.
