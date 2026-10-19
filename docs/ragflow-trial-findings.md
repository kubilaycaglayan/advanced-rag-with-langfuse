# RAGFlow trial findings (2026-10-18 to 2026-10-19)

This trial tested whether RAGFlow v1.0.0-rc1, used as a configurable advanced RAG, can answer the questions that millenium fails. The plan is in [plans/2026-10-19-ragflow-toggles.md](plans/2026-10-19-ragflow-toggles.md). The tooling lives outside this repo in `~/dev/millenium-archive/ragflow-trial/poc/`; see its `README.md`.

## Setup

- RAGFlow ran locally with `gemma4:26b` as the answer model and `bge-m3` for embeddings, both on Ollama.
- Every variant was scored by millenium's Langfuse judges (`qwen3:8b`), using answer correctness on the same Langfuse datasets as millenium.
- Each question's RAGFlow spans are nested under its Langfuse experiment trace. Run names are `ragflow-<variant>-<hash>`, so pipelines and configurations can be compared side by side.
- Index profiles and query toggles are named in `poc/variants.json`. Built profiles are recorded in `poc/state.json`, and all of them stay in RAGFlow as selectable options.
- Book-1 profiles were scored on the 23 book-1 questions from QA.csv, right-set-3 and set3. On those questions millenium averages 0.478.
- Runs used 4 questions at a time. In the noise test, runs of the same variant differed by up to about 0.05 in mean score, so smaller differences are not meaningful.

## Results on book 1 (23 questions, mean correctness)

| Variant | Index | Query settings | Score | Runs |
|---|---|---|---|---|
| b1-summary-kw | 1024-token chunks + LLM chunk summaries | keyword expansion | **0.652** | 1 |
| b1-base-vec07 | 1024-token chunks | keyword expansion, vector weight 0.7 | **0.641** | 2 |
| b1-base-vec09 | 1024-token chunks | keyword expansion, vector weight 0.9 | 0.630 | 1 |
| b1-base-kw | 1024-token chunks | keyword expansion, vector weight 0.5 | 0.598 | 2 |
| b1-base | 1024-token chunks | no keyword expansion | 0.587 | 1 |
| b1-keyq-kw | + LLM keywords and questions per chunk | keyword expansion | 0.565 | 1 |
| b1-small-kw | 384-token chunks, top 24 | keyword expansion | 0.565 | 1 |
| all-on | trilogy, all templates (graph, RAPTOR tree, TOC, etc.) | all on | 0.548 | up to 7 |
| b1-chapter-kw | chapter (title) chunks | keyword expansion | 0.543 | 1 |
| b1-base-vec03 | 1024-token chunks | vector weight 0.3 | 0.543 | 1 |
| b1-base-minilm-kw | 1024-token chunks | MiniLM reranker | 0.543 | 1 |
| b1-base-rr32-kw | 1024-token chunks | bge reranker, 32 candidates | 0.543 | 1 |
| b1-pc-kw | parent/child chunks | keyword expansion | 0.522 | 1 |
| b1-base-rr-kw-top24 | 1024-token chunks | bge reranker, top 24 | 0.522 | 1 |
| b1-base-rr-kw | 1024-token chunks | bge reranker, 64 candidates | 0.478 | 1 |
| b1-base-rr-kw-rewrite | 1024-token chunks | bge reranker + millenium-style query rewrite | 0.478 | 1 |
| plain | trilogy, Book parser | defaults | 0.478 | 2 |
| b1-base-detail | 1024-token chunks | "every detail" answer prompt | 0.457 | 1 |

## Findings

1. **Plain RAGFlow already beats millenium on book 1.** A simple 1024-token index with hybrid search scores 0.59–0.60 against millenium's 0.478, and it improves on 12 questions while doing worse on 4.
2. **Leaning toward vector similarity helps.** Weight 0.7 repeated at 0.652 and 0.630 (mean 0.641), and weight 0.9 scored 0.630; weight 0.3 scored 0.543.
3. **Per-chunk LLM summaries look promising (0.652) but need a repeat run.** Building them took about 10 minutes of `gemma4:26b` for book 1.
4. **Cross-encoder reranking hurts.** bge-reranker-v2-m3 cut the score from 0.598 to 0.478 and cost about 26 s per question on CPU. MiniLM and a smaller candidate pool hurt less, but neither helped.
5. **Bigger chunks win.** 384-token, chapter and parent/child chunking all scored below the plain 1024-token index.
6. **Index-time extras did not pay off.** The all-templates trilogy index (knowledge graph, RAPTOR tree, TOC and the rest), which took hours to build, scored 0.548 on book 1. LLM keywords and questions per chunk scored 0.565.
7. **Millenium-style query rewrite gave no gain.** Adding translation, grammar and name correction (Michael → Mikael) to the reranker variant left its score at 0.478. It may still help on misspelled questions, and it is kept as the `preprocess: rewrite` toggle.
8. **Prompt length:** the longer "every detail" prompt made answers worse.
9. **Questions that every variant still struggles with** (0 or 0.5): "who killed Harriet?", the book summary, Gottfried's death, and "why Harriet went to Australia". These need several scenes put together, and a single retrieval pass does not find them.

## RAGFlow notes

- RAGFlow's HTTP client gives up when response headers take more than 60 s. Slow local models therefore need a keepalive. The trial used `poc/ollama_proxy.py` for Ollama, and `poc/rerank_server.py` sends early headers.
- The ingestion Extractor stage has a fixed 600 s limit for the whole document (`internal/ingestion/component/extractor.go`). Because results are cached per chunk, re-parsing a timed-out document resumes where it stopped; `ragflow_variants.py wait` does this automatically.
- RAGFlow has no local rerank backend that works with Ollama. `poc/rerank_server.py` serves sentence-transformers cross-encoders in the LocalAI rerank format.

## Not done

- Separate per-template indexes (graph, RAPTOR tree, timeline, wiki): skipped, because the all-templates index did not beat the plain one.
- Repeat runs for b1-summary-kw and b1-base-vec09.
- Combining summary + vector weight 0.7.
- Indexing books 2 and 3 for the winning profiles.
- The multi-query preprocessing mode.

## Next steps

The candidate to offer as a selectable `/ask` pipeline is RAGFlow with a 1024-token index (optionally with chunk summaries), keyword expansion, vector weight 0.7–0.9, and no reranker. First run summary + vector weight 0.7 with repeat runs, then index books 2 and 3 and score the result on all four datasets.

## Restarting the trial

The cleanup restored the machine. To run more experiments:

1. Start the keepalive proxy instead of the socat relay: `docker stop docker-ollama-relay-1`, then `python3 -I poc/ollama_proxy.py 172.17.0.1 11455`.
2. For parallel runs, re-add `OLLAMA_NUM_PARALLEL=4` in an Ollama systemd drop-in, and `KC_COMPILE_CONCURRENCY=4` and `MAX_CONCURRENT_CHATS=4` in RAGFlow's `docker/.env`.
3. Start the reranker container if a variant uses one; the command is in the docstring of `poc/rerank_server.py`.
4. Then run `poc/queue.sh <queue file>`.
