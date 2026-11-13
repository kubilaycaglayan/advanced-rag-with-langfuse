# Best-performing pipeline versions

Ranked by mean answer correctness score for each regular Millennium dataset. Citation-support scores are not included.

## Method

- Included runs covering at least 80% of the items in that run's pinned dataset snapshot.
- Excluded single-item runs.
- Counts in parentheses show how many questions contributed to each score.
- The remaining runs were evaluated against their saved traces with qrels v4 and `qwen3.6:35b`. A dash means the metric was unavailable or not applicable; faithfulness can be unavailable when the recorded answer path or context cannot be verified.
- Coverage is completed result items over the pinned snapshot size. Dataset snapshots can differ in size across runs.
- `Qwen` is mean `answer_correctness_v2` (`qwen3:8b`); `Codex` is mean `answer_correctness_codex_v1` (`gpt-5.6-luna`). `Faith` and `Rel` cover 36 items; `P5` 28; `P10` 5; `SetP` and `CtxR` 30; `H5` and `H10` 2. Retrieval skips the broad item and three items without direct gold passages. Names containing `openai` or `gpt-6-luna` identify the answer pipeline's query agent, not the evaluator.
- On 2026-11-13, retrieval, faithfulness, and answer-relevancy metrics were added for the top-ranked run in `set3`, `right-set-3`, and `Additional Questions`. These scores use qrels v4 and `qwen3.6:35b` for faithfulness/relevancy. P@K is averaged only over item traces with a search call returning at least K hits; set precision and context recall omit undefined items. Faithfulness is omitted when trace guards reject the stored context/path; it is not scored as zero. The 23 traces previously rejected by the context limit were rescored after that limit was raised. `Rel` measures topical responsiveness, not factual correctness.

## QA.csv

<table>
  <thead>
    <tr>
      <th rowspan="2">Rank</th>
      <th rowspan="2">Experiment</th>
      <th rowspan="2">Pipeline</th>
      <th colspan="2">Correctness</th>
      <th colspan="4">Retrieval results</th>
      <th colspan="2">Assembled context</th>
      <th colspan="2">Answer quality</th>
      <th rowspan="2">Coverage</th>
      <th rowspan="2">Experiment ID</th>
      <th rowspan="2">Execution ID</th>
    </tr>
    <tr>
      <th>Qwen</th>
      <th>Codex</th>
      <th>P5</th>
      <th>P10</th>
      <th>H5</th>
      <th>H10</th>
      <th>SetP</th>
      <th>CtxR</th>
      <th>Faith</th>
      <th>Rel</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <th>1</th>
      <td>`openai-gpt-6-luna-high-QA`</td>
      <td>v2.12</td>
      <td>0.91(36)</td>
      <td>0.81(36)</td>
      <td>0.34(28)</td>
      <td>0.12(5)</td>
      <td>0.50(2)</td>
      <td>0.75(2)</td>
      <td>0.16(30)</td>
      <td>0.61(30)</td>
      <td>0.91(36)</td>
      <td>0.89(36)</td>
      <td>36/36</td>
      <td>`764cc2418408a4ea`</td>
      <td>`d5e9c5ad`</td>
    </tr>
    <tr>
      <th>2</th>
      <td>`v2.1-query-aware-rerank-only`</td>
      <td>v2.1</td>
      <td>0.88(36)</td>
      <td>—</td>
      <td>0.18(30)</td>
      <td>0.16(5)</td>
      <td>0.75(2)</td>
      <td>0.50(1)</td>
      <td>0.10(33)</td>
      <td>0.49(30)</td>
      <td>—</td>
      <td>0.85(36)</td>
      <td>36/36</td>
      <td>`40346a8d399ed2c7`</td>
      <td>`1693c551`</td>
    </tr>
    <tr>
      <th>3</th>
      <td>`kubilay`</td>
      <td>v2.2</td>
      <td>0.87(36)</td>
      <td>—</td>
      <td>0.18(30)</td>
      <td>0.16(5)</td>
      <td>0.75(2)</td>
      <td>0.50(1)</td>
      <td>0.10(33)</td>
      <td>0.49(30)</td>
      <td>—</td>
      <td>0.85(36)</td>
      <td>36/36</td>
      <td>`4ff5ebd1a66dbfb8`</td>
      <td>`33c78788`</td>
    </tr>
    <tr>
      <th>4</th>
      <td>`2026-10-22-v2.13-luna-high-QA.csv`</td>
      <td>v2.13</td>
      <td>0.87(36)</td>
      <td>—</td>
      <td>0.26(31)</td>
      <td>0.08(3)</td>
      <td>1.00(2)</td>
      <td>1.00(1)</td>
      <td>0.12(33)</td>
      <td>0.62(30)</td>
      <td>0.99(23)</td>
      <td>0.89(36)</td>
      <td>36/36</td>
      <td>`fd52e12721de3536`</td>
      <td>`8dc3ef0b`</td>
    </tr>
    <tr>
      <th>5</th>
      <td>`story-graph-reasoning-v2.14-QA`</td>
      <td>v2.14</td>
      <td>0.87(36)</td>
      <td>—</td>
      <td>0.22(24)</td>
      <td>0.16(5)</td>
      <td>0.50(2)</td>
      <td>—</td>
      <td>0.10(33)</td>
      <td>0.48(30)</td>
      <td>0.87(17)</td>
      <td>0.91(36)</td>
      <td>36/36</td>
      <td>`9957eaa7b41ed87b`</td>
      <td>`61b3467c`</td>
    </tr>
  </tbody>
</table>

2026-11-13 evaluator coverage for QA.csv rank 2: P@5 30/36, P@10 5/36, H@5 2/36, H@10 1/36, SetP 33/36, CtxR 30/36, Faith 0/36, Rel 36/36. Faithfulness was unavailable because the recorded traces lacked sufficient agent input or used unsupported or rewritten answer paths.

## set3

<table>
  <thead>
    <tr>
      <th rowspan="2">Rank</th>
      <th rowspan="2">Experiment</th>
      <th rowspan="2">Pipeline</th>
      <th colspan="2">Correctness</th>
      <th colspan="4">Retrieval results</th>
      <th colspan="2">Assembled context</th>
      <th colspan="2">Answer quality</th>
      <th rowspan="2">Coverage</th>
      <th rowspan="2">Experiment ID</th>
      <th rowspan="2">Execution ID</th>
    </tr>
    <tr>
      <th>Qwen</th>
      <th>Codex</th>
      <th>P5</th>
      <th>P10</th>
      <th>H5</th>
      <th>H10</th>
      <th>SetP</th>
      <th>CtxR</th>
      <th>Faith</th>
      <th>Rel</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <th>1</th>
      <td>`openai-gpt-6-luna-high-set3`</td>
      <td>v2.12</td>
      <td>0.77(15)</td>
      <td>—</td>
      <td>0.06(12)</td>
      <td>0.10(2)</td>
      <td>—</td>
      <td>—</td>
      <td>0.02(13)</td>
      <td>0.65(13)</td>
      <td>1.00(8)</td>
      <td>0.97(15)</td>
      <td>15/15</td>
      <td>`8451bbff73197241`</td>
      <td>`77f54b4d`</td>
    </tr>
    <tr>
      <th>2</th>
      <td>`entity-cards-reasoning-v2.13-set3`</td>
      <td>v2.13</td>
      <td>0.72(15)</td>
      <td>—</td>
      <td>0.04(11)</td>
      <td>0.00(2)</td>
      <td>—</td>
      <td>—</td>
      <td>0.03(13)</td>
      <td>0.62(13)</td>
      <td>0.77(8)</td>
      <td>0.94(15)</td>
      <td>15/15</td>
      <td>`163cfd81374ea8b8`</td>
      <td>`436795ab`</td>
    </tr>
    <tr>
      <th>3</th>
      <td>`v2.3-gpt-6-luna-set3`</td>
      <td>v2.3</td>
      <td>0.72(15)</td>
      <td>—</td>
      <td>0.05(13)</td>
      <td>0.00(2)</td>
      <td>—</td>
      <td>—</td>
      <td>0.03(13)</td>
      <td>0.50(13)</td>
      <td>0.97(13)</td>
      <td>0.94(15)</td>
      <td>15/15</td>
      <td>`ee483532e4d14912`</td>
      <td>`a46dbdf5`</td>
    </tr>
    <tr>
      <th>4</th>
      <td>`kubilay`</td>
      <td>v2.2</td>
      <td>0.68(15)</td>
      <td>—</td>
      <td>0.03(12)</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>0.04(13)</td>
      <td>0.46(13)</td>
      <td>—</td>
      <td>0.97(15)</td>
      <td>15/15</td>
      <td>`9dd9500d0dcb8588`</td>
      <td>`9eb12349`</td>
    </tr>
    <tr>
      <th>5</th>
      <td>`v2.12`</td>
      <td>v2.12</td>
      <td>0.67(15)</td>
      <td>—</td>
      <td>0.07(12)</td>
      <td>0.05(4)</td>
      <td>—</td>
      <td>—</td>
      <td>0.03(13)</td>
      <td>0.46(13)</td>
      <td>0.89(8)</td>
      <td>0.95(15)</td>
      <td>15/15</td>
      <td>`71198828c3c0c970`</td>
      <td>`039abfb9`</td>
    </tr>
  </tbody>
</table>

2026-11-13 evaluator coverage for this winner: P@5 12/15, P@10 2/15, SetP 13/15, CtxR 13/15, Faith 8/15 (seven traces failed faithfulness path guards), Rel 15/15.

## right-set-3

<table>
  <thead>
    <tr>
      <th rowspan="2">Rank</th>
      <th rowspan="2">Experiment</th>
      <th rowspan="2">Pipeline</th>
      <th colspan="2">Correctness</th>
      <th colspan="4">Retrieval results</th>
      <th colspan="2">Assembled context</th>
      <th colspan="2">Answer quality</th>
      <th rowspan="2">Coverage</th>
      <th rowspan="2">Experiment ID</th>
      <th rowspan="2">Execution ID</th>
    </tr>
    <tr>
      <th>Qwen</th>
      <th>Codex</th>
      <th>P5</th>
      <th>P10</th>
      <th>H5</th>
      <th>H10</th>
      <th>SetP</th>
      <th>CtxR</th>
      <th>Faith</th>
      <th>Rel</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <th>1</th>
      <td>`entity-cards-reasoning-v2.13-right-set-3`</td>
      <td>v2.13</td>
      <td>0.91(28)</td>
      <td>—</td>
      <td>0.09(18)</td>
      <td>0.08(4)</td>
      <td>—</td>
      <td>—</td>
      <td>0.02(24)</td>
      <td>0.48(23)</td>
      <td>0.92(17)</td>
      <td>0.98(28)</td>
      <td>28/28</td>
      <td>`99b35b171b966af9`</td>
      <td>`3d8897b7`</td>
    </tr>
    <tr>
      <th>2</th>
      <td>`v2.3-gpt-6-luna-right-set-3`</td>
      <td>v2.3</td>
      <td>0.89(28)</td>
      <td>—</td>
      <td>0.11(21)</td>
      <td>0.15(2)</td>
      <td>—</td>
      <td>—</td>
      <td>0.05(24)</td>
      <td>0.62(23)</td>
      <td>0.96(24)</td>
      <td>0.97(28)</td>
      <td>28/28</td>
      <td>`833fe4ec4d1f8528`</td>
      <td>`7e6ac174`</td>
    </tr>
    <tr>
      <th>3</th>
      <td>`v2.12`</td>
      <td>v2.12</td>
      <td>0.85(28)</td>
      <td>—</td>
      <td>0.08(19)</td>
      <td>0.05(5)</td>
      <td>—</td>
      <td>—</td>
      <td>0.03(24)</td>
      <td>0.46(23)</td>
      <td>0.91(15)</td>
      <td>0.93(28)</td>
      <td>28/28</td>
      <td>`3ceb0071bf8d62a4`</td>
      <td>`c07f1c5b`</td>
    </tr>
    <tr>
      <th>4</th>
      <td>`baseline-v2.12-default-right-set-3`</td>
      <td>v2.12</td>
      <td>0.84(28)</td>
      <td>—</td>
      <td>0.08(17)</td>
      <td>0.05(6)</td>
      <td>—</td>
      <td>—</td>
      <td>0.03(24)</td>
      <td>0.48(23)</td>
      <td>0.78(18)</td>
      <td>0.95(28)</td>
      <td>28/28</td>
      <td>`b247cd5d9ce9da1d`</td>
      <td>`8b30a2d7`</td>
    </tr>
    <tr>
      <th>5</th>
      <td>`story-graph-reasoning-v2.14-right-set-3`</td>
      <td>v2.14</td>
      <td>0.84(28)</td>
      <td>—</td>
      <td>0.09(15)</td>
      <td>0.11(4)</td>
      <td>—</td>
      <td>—</td>
      <td>0.02(24)</td>
      <td>0.41(23)</td>
      <td>0.89(20)</td>
      <td>0.97(28)</td>
      <td>28/28</td>
      <td>`25790c44c054508a`</td>
      <td>`25b489d9`</td>
    </tr>
  </tbody>
</table>

2026-11-13 evaluator coverage for this winner: P@5 18/28, P@10 4/28, SetP 24/28, CtxR 23/28, Faith 17/28, Rel 28/28. Faithfulness was unavailable on 11 traces because of answer-path or rewrite guards.

## Additional Questions

<table>
  <thead>
    <tr>
      <th rowspan="2">Rank</th>
      <th rowspan="2">Experiment</th>
      <th rowspan="2">Pipeline</th>
      <th colspan="2">Correctness</th>
      <th colspan="4">Retrieval results</th>
      <th colspan="2">Assembled context</th>
      <th colspan="2">Answer quality</th>
      <th rowspan="2">Coverage</th>
      <th rowspan="2">Experiment ID</th>
      <th rowspan="2">Execution ID</th>
    </tr>
    <tr>
      <th>Qwen</th>
      <th>Codex</th>
      <th>P5</th>
      <th>P10</th>
      <th>H5</th>
      <th>H10</th>
      <th>SetP</th>
      <th>CtxR</th>
      <th>Faith</th>
      <th>Rel</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <th>1</th>
      <td>`baseline-v2.12-default-Additional-Questions`</td>
      <td>v2.12</td>
      <td>0.99(8)</td>
      <td>—</td>
      <td>0.08(4)</td>
      <td>0.03(2)</td>
      <td>—</td>
      <td>—</td>
      <td>0.04(8)</td>
      <td>0.69(8)</td>
      <td>0.74(6)</td>
      <td>0.94(8)</td>
      <td>8/8</td>
      <td>`b2e7fb1676745447`</td>
      <td>`090606b4`</td>
    </tr>
    <tr>
      <th>2</th>
      <td>`kubilay`</td>
      <td>v2.2</td>
      <td>0.98(8)</td>
      <td>—</td>
      <td>0.10(6)</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>0.04(8)</td>
      <td>0.81(8)</td>
      <td>—</td>
      <td>1.00(8)</td>
      <td>8/8</td>
      <td>`4a467771e91507c9`</td>
      <td>`a684db5d`</td>
    </tr>
    <tr>
      <th>3</th>
      <td>`v2.3-gpt-6-luna-Additional-Questions`</td>
      <td>v2.3</td>
      <td>0.95(8)</td>
      <td>—</td>
      <td>0.13(4)</td>
      <td>0.05(2)</td>
      <td>—</td>
      <td>—</td>
      <td>0.30(8)</td>
      <td>0.88(8)</td>
      <td>1.00(6)</td>
      <td>0.91(8)</td>
      <td>8/8</td>
      <td>`49f6f90f2223667a`</td>
      <td>`6494f50f`</td>
    </tr>
    <tr>
      <th>4</th>
      <td>`2026-10-22-v2.13-luna-high-Additional-Questions`</td>
      <td>v2.13</td>
      <td>0.90(8)</td>
      <td>—</td>
      <td>0.12(5)</td>
      <td>0.03(3)</td>
      <td>—</td>
      <td>—</td>
      <td>0.06(8)</td>
      <td>1.00(8)</td>
      <td>1.00(4)</td>
      <td>0.83(8)</td>
      <td>8/8</td>
      <td>`96ab190ac570dbe8`</td>
      <td>`98e9df42`</td>
    </tr>
    <tr>
      <th>5</th>
      <td>`story-graph-reasoning-v2.14-Additional-Questions`</td>
      <td>v2.14</td>
      <td>0.86(8)</td>
      <td>—</td>
      <td>0.08(4)</td>
      <td>0.03(3)</td>
      <td>—</td>
      <td>—</td>
      <td>0.05(8)</td>
      <td>0.69(8)</td>
      <td>0.83(2)</td>
      <td>1.00(8)</td>
      <td>8/8</td>
      <td>`d97ba1ac2f66173f`</td>
      <td>`6914235c`</td>
    </tr>
  </tbody>
</table>

The Additional Questions winner used a pinned 8-item snapshot. Current qrels contain 9 items; the ninth item has no trace in this run. Some QA.csv runs have a `partial` overall execution status because a non-correctness evaluator failed; correctness scores were available for all 36 items and were included here.

2026-11-13 evaluator coverage for this winner: P@5 4/8, P@10 2/8, SetP 8/8, CtxR 8/8, Faith 6/8, Rel 8/8. Faithfulness was unavailable on two traces because of answer-path guards.

## Metric abbreviations

- **P5 / P10 (Precision@5 / Precision@10)**: The proportion of relevant passages among the top 5 / 10 retrieved results (signal-to-noise ratio).
- **H5 / H10 (Hit@5 / Hit@10)**: Whether at least one relevant passage appears in the top 5 / 10 retrieved results (1 for a hit, 0 otherwise).
- **Recall@K**: The proportion of all relevant passages that appear within the top K retrieved results. This is a retrieval diagnostic; it is not one of the table columns.
- **SetP (Context Precision / Set Precision)**: The proportion of retrieved passages in the deduplicated set that are relevant to the query (signal-to-noise ratio).
- **CtxR (Context Recall)**: Whether retrieval surfaced all the necessary information or ground-truth passages required to answer the question; measured here as the share of direct gold passages found in the retrieved set.
- **Faith (Faithfulness)**: The share of answer claims supported by the retrieved evidence.
- **Rel (Relevancy)**: The judge score for whether the answer addresses the question, regardless of factual correctness.

