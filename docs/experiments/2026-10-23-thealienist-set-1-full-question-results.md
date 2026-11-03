# The Alienist set-1 full-question experiment results

## Scope

These results cover the same 14-question Alienist set-1 snapshot (dataset version `2026-10-22T08:23:48.493000+00:00`, SHA-256 `9fec3f33de15d1070198f74be15b2645f15671330970b8e7ad3f87270ee0f1ba`) and pipeline v2.12. All scores use `answer_correctness_v2` and `citation_support_v1`, judged with `qwen3:8b`. Runs and retries are in the Langfuse `thealienist` project.

“Full set, reconciled” means every question has a final scored answer, but one or more item results came from a separate one-question retry or judge repair. The aggregate is computed across those traces; it is not the score shown on one Langfuse run.

## Results

| Experiment | Model and reasoning | Full-set coverage | Answer correctness | Citation support | Elapsed time | Langfuse run(s) |
|---|---|---:|---:|---:|---:|---|
| Earlier baseline (`v2.12`; before the planned variants) | Ollama Qwen 3.6 35B, thinking off | 14/14, single run | 0.7143 | 0.7857 | 14m 43s | [run](http://127.0.0.1:28420/project/cmvj9vofj001jmj7t7ng23o63/datasets/cmvj9y4060029mj7t4s82us89/runs/fe23660ee9855bdb) |
| OpenAI Luna high | GPT-6 Luna, high reasoning effort | 14/14, single run | 0.8214 | 0.7143 | 10m 09s | [run](http://127.0.0.1:28420/project/cmvj9vofj001jmj7t7ng23o63/datasets/cmvj9y4060029mj7t4s82us89/runs/edfdc512a36c8a81) |
| Ollama Qwen 3.6 35B thinking | Thinking on | 14/14, reconciled | 0.8214 | 0.4643 | 35m 51s | [original run](http://127.0.0.1:28420/project/cmvj9vofj001jmj7t7ng23o63/datasets/cmvj9y4060029mj7t4s82us89/runs/8cf247970106ba60); [answer retry](http://127.0.0.1:28420/project/cmvj9vofj001jmj7t7ng23o63/datasets/cmvj9y4060029mj7t4s82us89/runs/f00a90fec9fec8d1) |
| DeepSeek R1 70B Q8 thinking | Thinking on | 14/14, reconciled | 0.3929 | 0.6786 | 6h 43m 51s | [original run](http://127.0.0.1:28420/project/cmvj9vofj001jmj7t7ng23o63/datasets/cmvj9y4060029mj7t4s82us89/runs/ed4c8750733c3890); [four one-item recovery runs](../../data/thealienist-comparisons/alienist-set-1-provider-comparison-v2.12.md#langfuse-runs) |
| DeepSeek R1 70B Q8 thinking off | Thinking off | 14/14, single run | 0.4643 | 0.7500 | 5h 43m 55s | [run](http://127.0.0.1:28420/project/cmvj9vofj001jmj7t7ng23o63/datasets/cmvj9y4060029mj7t4s82us89/runs/297967565777fb86) |

## Reconciliation details

- The Qwen thinking-on run had one Ollama HTTP 500 answer failure. Its retry completed. Five citation-judge outputs failed JSON validation; they were repaired on their original traces, and all five repaired scores were 0.0.
- The DeepSeek thinking-on run had four Ollama HTTP read timeouts at 600 seconds. Each item was retried separately, one at a time, with the request timeout aligned to the existing 900-second agent limit. All four retries completed.
- The other full-set runs completed 14/14 in one run with zero answer, evaluation, or telemetry failures.
- Every run used the Alienist corpus, Alienist Langfuse project, and the same set-1 snapshot. No Millennium corpus data or project was used.

## Takeaways

- OpenAI Luna high and Qwen thinking-on tie for the highest answer-correctness score at 0.8214.
- DeepSeek thinking-off has the strongest citation-support score at 0.7500 among the planned variants; its correctness score is 0.4643.
- Within this 14-question set, DeepSeek thinking-off exceeds reconciled thinking-on by 0.0714 on both metrics. Treat this as descriptive evidence from one small question set.
- The DeepSeek 70B runs took several hours. Thinking-off took about 5h44m; thinking-on plus the four recovery runs took about 6h44m.
