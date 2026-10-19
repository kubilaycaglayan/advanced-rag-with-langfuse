# RAGFlow toggles trial

Status: approved 2026-10-19; trial ended 2026-10-19 (see Outcome). Prepared 2026-10-19 (UTC+3).

## Goal

Try RAGFlow's untested settings against the questions millenium fails, without adopting any of them yet. Each setting is a toggle; a run picks a set of toggles, and Langfuse compares runs with each other and with millenium. Most of millenium's failures come from retrieval, so the trial targets retrieval and indexing. RAGFlow's own query side is thinner than millenium's (only keyword expansion), so millenium's query preprocessing is a toggle too. Answer-model swaps are out of scope.

## Decisions

- New index profiles are built on book 1 (*The Girl with the Dragon Tattoo*) only. Whenever a profile shows an improvement, it is also indexed for books 2 and 3 and scored on the full datasets.
- Test a few sensible combinations instead of a full one-at-a-time sweep. A single toggle may also be flipped for one specific question.
- Everything stays optional: the existing all-templates trilogy index and its chats stay as they are.

## Design

A variant file (JSON) holds named variants. Each variant has:

- `index`: the name of an index profile, which maps to one RAGFlow dataset. The runner builds the dataset on first use and reuses it after that.
- `query`: chat settings applied at question time.

The runner (`ragflow_experiment.py`) takes `--variant <name>`. It creates or updates the matching chat, then runs the Langfuse experiment as it does now. The pipeline id is `ragflow-<variant>-<hash of toggles and setup>`, and every toggle is written to the run metadata.

Book-1 runs filter the existing Langfuse datasets down to book-1 questions (the current 24-item list, minus the Richard Forbes question, which belongs to book 2). This keeps per-question comparison with millenium and with earlier RAGFlow runs.

The trial tooling moves out of the session scratchpad into `~/dev/millenium-archive/ragflow-trial/poc/`, so it survives this session.

## Query toggles (no re-indexing)

| Toggle | Values to try |
| --- | --- |
| reranker | off; bge-reranker-v2-m3 (about 26 s per question on CPU); ms-marco-MiniLM-L-6-v2 (millenium's, about 1 s), both served by poc/rerank_server.py (Ollama cannot serve rerankers, and RAGFlow's TEI provider has no rerank) |
| rerank candidates | 64 (RAGFlow default), 32 |
| `top_n` / `top_k` | 6, 12 (current), 24 / 1024 |
| similarity threshold | 0.1 (current), 0.2 |
| vector vs keyword weight | 0.3, 0.5 (current), 0.7 |
| keyword expansion | on / off |
| knowledge-graph retrieval (`use_kg`) | on / off |
| table-of-contents enhancement (`toc_enhance`) | on / off |
| agentic reasoning (`reasoning`) | on / off |
| metadata filter | none; restrict to the asked book |
| system prompt | current; one variant that asks for every matching detail |
| millenium query preprocessing | off; `rewrite`: send one question after millenium's translation, grammar correction and name completion/correction (e.g. Michael -> Mikael Blomkvist); `multi-query`: also search with millenium's literary alternatives and HyDE answer through RAGFlow's retrieval API, merge with RRF, then answer |

## Index profiles (book 1)

| Profile | Contents | Rough indexing cost |
| --- | --- | --- |
| `b1-base` | 1024-token chunks, no compilation templates | minutes (embeddings only) |
| `b1-keyq` | `b1-base` plus `auto_keywords` 5 and `auto_questions` 3 per chunk | about 30–60 min |
| `b1-small-pc` | 512-token chunks with parent/child retrieval | minutes |
| `b1-chapter` | chunks split on chapter and scene headings | minutes |
| `b1-graph` | graph template with entity types, entity resolution and community reports | about 1 h |
| `b1-tree` | tree/RAPTOR template only | about 1.5 h |
| `b1-timeline` | timeline template only | about 30 min |
| `b1-wiki` | wiki template (needs its own template group) | unknown |
| `b1-all` | every template, as in the current trilogy index | about 3 h |

Tag sets and other embedding models are left for later, if earlier rounds point at them.

## Order

1. Wait for the running plain trilogy runs to finish; plain vs all-on shows whether the compiled indexes earn anything.
2. Move the tooling, add the variant file, and extend the runner to build profiles and chats from it.
3. Build `b1-base` and `b1-small-pc`, start the reranker container, and run the query-toggle combinations on them.
4. Build `b1-keyq` and `b1-chapter` and run the best query settings on them.
5. Build the template profiles one at a time, in the order the earlier results suggest.
6. Flip single toggles on the hard questions ("How did Mikhail first know about Salander?", "What present Salander bought for Mikael?", "Who helped Mikael solved the phone numbers mystery in Harriet's diary?") wherever a trace shows the toggle could matter.
7. Repeat promising runs 2–3 times. Index books 2 and 3 for any profile that keeps its gain, then run the full datasets.

## Rules

- One Ollama job at a time: indexing and experiment runs never overlap, and models are unloaded after each job.
- A gain counts only if it holds on repeat runs and its traces show where it came from.
- Every run is recorded in Langfuse with its toggles. Ideas worth porting go to millenium as general fixes, through the usual tuning-round process.

## Cleanup when the trial ends

Remove `/etc/systemd/system/ollama.service.d/90-ragflow-poc.conf` and restart Ollama. Stop the keepalive proxy and restore `docker-ollama-relay-1`. Restore RAGFlow's `docker/.env` and stop the reranker container.

## Later: selectable pipelines

The end goal is that a user picks a pipeline and configuration in the UI, served through `/ask`. Not every configuration has to be served, but some will be. So every variant here keeps a stable name, and its RAGFlow dataset and chat are kept rather than deleted. The variant file is written so that `/ask` can later take a variant name and route the question to millenium or to the matching RAGFlow chat.

## Outcome

The trial ended on 2026-10-19 after rounds 1–3. Results, findings and next steps are in [../ragflow-trial-findings.md](../ragflow-trial-findings.md).
