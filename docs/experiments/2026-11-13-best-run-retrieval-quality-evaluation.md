# Retrieval, relevancy, and faithfulness on the best runs

**Run date:** 2026-11-13  
**Qrels:** version 4 (`millennium_books_a7ebc5a988df037cd2ee`)  
**Faithfulness/relevancy judge:** `qwen3.6:35b`

Evaluators ran on the existing top-ranked experiment for each dataset. I did not rerun the pipelines. All 51 available experiment traces completed evaluator processing without execution errors, and their question-level metric scores were verified in Langfuse with qrels version 4.

| Dataset | Best run | Pipeline | Items scored | P@5* | P@10* | Set precision | Context recall | Faithfulness | Answer relevancy |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Additional Questions | `b2e7fb1676745447` | v2.12 | 8/8 | 0.080 (4) | 0.025 (2) | 0.041 (8) | 0.688 (8) | 0.679 (4) | 0.944 (8) |
| set3 | `8451bbff73197241` | v2.12 | 15/15 | 0.056 (12) | 0.100 (2) | 0.024 (13) | 0.654 (13) | — (0) | 0.967 (15) |
| right-set-3 | `99b35b171b966af9` | v2.13 | 28/28 | 0.085 (18) | 0.084 (4) | 0.024 (24) | 0.478 (23) | 0.892 (4) | 0.982 (28) |

* P@K averages include only traces with at least one search call returning K hits; the count in parentheses is the number of item traces with a score. Broad questions omit retrieval headline metrics. Set precision and context recall also omit items where the metric is undefined. Faithfulness “—” means the judge did not run, not a zero score. Relevancy scores topical responsiveness and does not measure answer correctness.

## Problems found

- **The top Additional Questions run is an older 8-item snapshot.** The current Langfuse dataset and qrels have 9 items. Item `8acd68c6-d285-42c3-b33b-ac2fb9833565` has no trace in this best run, so it could not be evaluated.
- **Faithfulness coverage is limited by trace guards.** Only 8/51 answers received faithfulness scores (4/8 Additional Questions, 0/15 set3, 4/28 right-set-3). The rest failed closed because the final answer path was rewritten/unsupported or the stored agent context exceeded 12,000 characters. The exact reason counts are in the raw JSON artifact.
- **Additional Questions, “What is ‘no compromises’?” (item `1e785ac0-34a9-4b22-95c1-dd83cfff1764`) received faithfulness 0.0.** The judge found that the retrieved evidence contradicted the answer’s interpretation of the phrase.
- **Additional Questions, “What happened in the abandoned factory?” (item `36c50723-3b65-49f6-9d9b-70574cc9471c`) received relevancy 0.55.** The judge reports that the answer ends mid-sentence; context length also prevented faithfulness scoring, and no direct qrel passage was retrieved.
- **set3, “Who helped Mikael solve the phone-numbers mystery?” (item `7e3cbf3d-3e08-52f2-a0c9-7ad276b0d9ae`) received relevancy 0.5.** The answer denied that anyone helped, while the reference identifies his daughter Pernilla.
- **right-set-3, “Who was Andersson?” (item `84c345fd-c701-580e-88d7-4ea0bbf4b1d9`) received relevancy 0.5.** The answer described Lena Andersson rather than detective Curt Andersson; no direct qrel passage was retrieved.
- **The qrels likely need more equivalent evidence passages.** Several answers were judged faithful to retrieved context while direct-passage context recall was 0, including the memory and hacker questions. Since the newly created qrels are hand-labeled but not exhaustive, low recall/precision can reflect missing gold passages as well as retrieval misses. Treat these retrieval scores as diagnostic until those cases are reviewed.
- Other judged faithfulness issues: the mother answer scored 0.714 because it misstated timing/years; the “girl with the dragon tattoo” answer scored 0.667 because it added an unsupported claim about the title’s meaning.

## Best-run references

- Additional Questions: v2.12, execution `090606b4-8d95-4785-b0d3-ba9626635ec3`, dataset run `b2e7fb1676745447`.
- set3: v2.12, execution `77f54b4d-feaa-4739-9489-a98c58e2cef7`, dataset run `8451bbff73197241`.
- right-set-3: v2.13, execution `3d8897b7-97dc-45d4-93bc-c37389f34ebb`, dataset run `99b35b171b966af9`.

Raw per-item results, evaluator explanations, search counts, and trace IDs: `data/millennium/quality-evaluations/best-performing-experiments-2026-11-13.json`.
