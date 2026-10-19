# Performance improvement proposal: faster query-to-answer

Status: implemented and measured; parallel rewrites remain opt-in, streaming is implemented, reranker/embedding changes were not adopted. Prepared 2026-10-19 (UTC+3).

## Context
A question takes about 21 s on average. Most of that is qwen3:8b: about 7.5 s for three query rewrites run one after another, and about 10 s for the answer. Reranking adds about 1.4 s on the CPU. The user asked for three things:
- (1) an experiment that runs the rewrites in parallel;
- (2) streaming the answer without breaking Langfuse;
- (6) reranker/embedding speedups, explored and tested, then implemented if they work.

Item 5 (the Ollama context-size reloads) is answer-only and is not implemented here.
Follow the tuning-round rules (general fixes only, no regressions) and the rule to keep one Ollama model loaded at a time:
- Every trial stays a named config toggle so it can later be picked from the UI.
- Experiments run in `millenium-tuning`, never overlapping other Ollama jobs.
- Log in `IMPROVEMENTS.md`.
- Deploy only after approval.

## A. Parallel query rewrites (item 1): experiment
- `app/resolved_config.py`: add `parallel_transformations: bool = False` (field, validation, `allowed` set).
- `app/pipeline.py` `_transform` (l.129): when the flag is on, submit the HyDE, expansion and grammar calls to a `ThreadPoolExecutor(3)`.
  - Each call is wrapped in `contextvars.copy_context().run`, so its Langfuse spans still nest under the trace.
  - Results are joined in the same order, and the existing expansion-count check is kept.
  - Translation stays sequential before them, because its output feeds them.
- Ollama: run the trial with `OLLAMA_NUM_PARALLEL=3` set through a systemd override, then restart.
  - Needs sudo and affects every Ollama client on the machine, so I'll confirm before applying it and revert it afterwards unless the trial is adopted.
- Measure on set3 against production's last run, then on QA.csv, Additional Questions and right-set-3:
  - `transformation_seconds`, total latency, and per-item correctness.
- Decision:
  - Make it the default only with a clear speed-up and 0 drops.
  - Otherwise keep it off as an opt-in toggle and record the result.

## B. Streaming the answer (item 2)
- `app/pipeline.py` `_ollama`: add an optional `on_token` callback.
  - When it is set, send `stream: True`, read the NDJSON lines, and pass each content chunk to the callback (thinking chunks are not passed on).
  - Collect the full text, then take `prompt_eval_count`/`eval_count` from the final chunk.
  - The `_update(obs, output=…, usage_details=…)` call stays as it is, so the Langfuse generation is unchanged.
  - The budget and think fallbacks still work: an empty attempt has streamed nothing.
- `run_pipeline` gets `on_token=None` (plus an optional `on_status`, used only for a "thinking" or "searching" hint). Only the final answer call passes it on.
- `app/main.py`: move the body of `/ask` into a helper, and add `POST /ask/stream`:
  - It runs that helper in a worker thread inside a copied context, so `propagate_attributes` and the `rag ask` root span behave exactly as in `/ask`.
  - Events go through a `queue.Queue` to a `StreamingResponse` (`application/x-ndjson`): `{"type":"trace","trace_id"}` first, then `token` events, then `done` with the same result dict `/ask` returns, or `error`.
  - The root span still gets its output when the pipeline ends, even if the client disconnects.
  - The rate limit and 429 checks run before the stream starts. `/ask` itself is unchanged.
- `frontend/server.js` `/api/ask`:
  - Call `/ask/stream` and forward `token` events.
  - Turn `done` into the current final payload (`citedSources`, `traceUrl`, `pipelineSeconds`) as one last event.
  - Keep `activeAskIps` held until the stream ends. Keep the timeout and error mapping.
  - Update `frontend/tests/server.test.js`.
- `frontend/ui` submodule (Lovable repo):
  - `src/lib/api.ts` `askQuestion` takes an `onToken` callback and reads the stream with `response.body.getReader()`.
  - The ask view shows the partial answer as it grows; sources and feedback appear on `done`.
  - The editor's sample route `src/routes/api/ask.ts` returns the same event format.
  - Update `src/test/ask-flow.test.tsx`.
  - Push the submodule first, then commit the pointer.
- Langfuse checks: run the same questions through `/ask` and `/ask/stream`. Both traces should match: same span tree, same generation output and token usage, and the root `rag ask` output set. The answer text should be identical (temperature 0). Feedback (`/api/feedback`) should still find the root span.

## C. Reranker and embedding speedups (item 6): explore → experiment → implement
Benchmark script in the scratchpad (copied to `data/tuning/scripts-2026-10-19-speed/` afterwards), run in `millenium-tuning` while nothing else is running:
- Workload: for every QA question, the real reranker pairs (about 30 fused + up to 100 wide + 30 named + 30 keyword), built from Qdrant with the question and its stored transformation queries, so no LLM is needed.
- Variants, each compared with the current fp32 torch run for time and score agreement (max |Δscore|, same top-10 order, same wide/keyword admit decisions):
  1. Score the keyword hits in the same `predict` call as the main pairs (`pipeline.py` l.263 and l.294); also try different `batch_size` values.
  2. Embed all queries in one `encode([...])` call instead of one per query (l.217).
  3. torch thread count: 16 (current) vs 32, and the fastest `batch_size`.
  4. ONNX fp32 backend (`CrossEncoder(..., backend="onnx")`; needs `onnxruntime`/`optimum` in requirements).
  5. ONNX int8 (dynamic quantisation).
- Decision:
  - A variant whose rankings and admit decisions match on every item is implemented straight away. Expected: 1, 2, 3, and probably 4.
  - Int8 is adopted only after a full multi-dataset run with 0 drops; otherwise it stays as an opt-in toggle (`reranker_backend`).
  - GPU (ROCm torch) is out of scope: the image would grow by several GB and need `/dev/kfd`. I'll only note it.
- Implement the winners in `_embedder`/`_reranker`/`run_pipeline`, and add tests in `tests/`.

## Verification
- `pytest tests/` in the tuning container; `node --test` for the frontend server; `vitest` in `frontend/ui`.
- A/C: a full experiment run for each adopted change compared per item with the previous defaults; timings come from `result.timings`.
- B: watch the answer stream in by running the app locally (`run`/`visual-verification` skills); check the Langfuse traces as described above.
- Unload models and check `free -g` afterwards. Add a row and section to `IMPROVEMENTS.md`.
- Deploy only on approval: `docker compose up --build -d app`, then `--no-deps frontend`.

## Outcome (2026-10-19)

- **A. Parallel rewrites**: implemented behind `parallel_transformations` (default `false`). With
  `OLLAMA_NUM_PARALLEL=3`, three questions took 9.8 vs 23.6 s, 13.5 vs 17.4 s and 15.6 vs 20.5 s
  (transformation time 4.6/5.5/3.7 s vs 9.4/6.7/5.5 s). Rewrites, evidence and answers vary
  between repeated runs at temperature 0, so this 3-question trial cannot prove 0 drops. The
  toggle remains off by default; the global `OLLAMA_NUM_PARALLEL=3` override was reverted. Full
  QA.csv adoption needs a controlled run.
- **B. Streaming**: `/ask/stream` and the Express/UI forwarding are implemented. With Ollama idle,
  plain and streamed answers were identical in 3/3 pairs on a normal question and 3/3 on the
  low-confidence thinking question; token text joined to the same answer and both traces had the
  same 30-observation tree. First token arrived ~11.2 s (normal) and ~18.0 s (thinking) after the
  request. The earlier 2/3 mismatches did not reproduce; they were likely affected by concurrent
  benchmark load.
- **C. Reranker/embedding**: no change adopted. Recorded QA calls: torch16 104.5 s; torch32
  219.8 s; batch 64 102.6 s (noise); ONNX 123.0 s; ONNX-O3 97.3 s but 7 top-10 changes; int8
  90.9 s but 168 top-10 changes. Embedding ONNX was slower (14.4 s vs 7.2 s). The small batching
  ideas were not worth the ordering risk; the current torch fp32 path stays.
- **Verification**: 95 Python tests, 14 Express tests and 19 UI tests pass. The 3-question scripts
  and JSON results are under `data/tuning/scripts-2026-10-19-speed/` (git-ignored).

## Item 5 (answer only, not part of this work)
Set `OLLAMA_CONTEXT_LENGTH=8192` on the Ollama service so the judge's calls use the same context size as the pipeline. Right now qwen3:8b reloads between them: 29 reloads of about 1.5 s each during one 8-question run on 2026-10-19.
