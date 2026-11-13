# Best-performing pipeline versions

Ranked by mean answer correctness score for each regular Millennium dataset. Citation-support scores are not included.

## Method

- Included runs covering at least 80% of the items in that run's pinned dataset snapshot.
- Excluded single-item runs.
- Coverage is completed result items over the pinned snapshot size. Dataset snapshots can differ in size across runs.
- `Qwen` is mean `answer_correctness_v2` (`qwen3:8b`); `Codex` is mean `answer_correctness_codex_v1` (`gpt-5.6-luna`). `Faith` and `Rel` cover 36 items; `P5` 28; `P10` 5; `SetP` and `CtxR` 30; `H5` and `H10` 2. Retrieval skips the broad item and three items without direct gold passages. Names containing `openai` or `gpt-6-luna` identify the answer pipeline's query agent, not the evaluator.

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
      <td>0.9086</td>
      <td>0.8141</td>
      <td>0.338</td>
      <td>0.120</td>
      <td>0.500</td>
      <td>0.750</td>
      <td>0.162</td>
      <td>0.611</td>
      <td>0.911</td>
      <td>0.894</td>
      <td>36/36</td>
      <td>`764cc2418408a4ea`</td>
      <td>`d5e9c5ad`</td>
    </tr>
    <tr>
      <th>2</th>
      <td>`v2.1-query-aware-rerank-only`</td>
      <td>v2.1</td>
      <td>0.8824</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>36/36</td>
      <td>`40346a8d399ed2c7`</td>
      <td>`1693c551`</td>
    </tr>
    <tr>
      <th>3</th>
      <td>`kubilay`</td>
      <td>v2.2</td>
      <td>0.8748</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>36/36</td>
      <td>`4ff5ebd1a66dbfb8`</td>
      <td>`33c78788`</td>
    </tr>
    <tr>
      <th>4</th>
      <td>`2026-10-22-v2.13-luna-high-QA.csv`</td>
      <td>v2.13</td>
      <td>0.8745</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>36/36</td>
      <td>`fd52e12721de3536`</td>
      <td>`8dc3ef0b`</td>
    </tr>
    <tr>
      <th>5</th>
      <td>`story-graph-reasoning-v2.14-QA`</td>
      <td>v2.14</td>
      <td>0.8727</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>36/36</td>
      <td>`9957eaa7b41ed87b`</td>
      <td>`61b3467c`</td>
    </tr>
  </tbody>
</table>

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
      <td>0.7675</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>15/15</td>
      <td>`8451bbff73197241`</td>
      <td>`77f54b4d`</td>
    </tr>
    <tr>
      <th>2</th>
      <td>`entity-cards-reasoning-v2.13-set3`</td>
      <td>v2.13</td>
      <td>0.7239</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>15/15</td>
      <td>`163cfd81374ea8b8`</td>
      <td>`436795ab`</td>
    </tr>
    <tr>
      <th>3</th>
      <td>`v2.3-gpt-6-luna-set3`</td>
      <td>v2.3</td>
      <td>0.7158</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>15/15</td>
      <td>`ee483532e4d14912`</td>
      <td>`a46dbdf5`</td>
    </tr>
    <tr>
      <th>4</th>
      <td>`kubilay`</td>
      <td>v2.2</td>
      <td>0.6763</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>15/15</td>
      <td>`9dd9500d0dcb8588`</td>
      <td>`9eb12349`</td>
    </tr>
    <tr>
      <th>5</th>
      <td>`v2.12`</td>
      <td>v2.12</td>
      <td>0.6742</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>15/15</td>
      <td>`71198828c3c0c970`</td>
      <td>`039abfb9`</td>
    </tr>
  </tbody>
</table>

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
      <td>0.9135</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>28/28</td>
      <td>`99b35b171b966af9`</td>
      <td>`3d8897b7`</td>
    </tr>
    <tr>
      <th>2</th>
      <td>`v2.3-gpt-6-luna-right-set-3`</td>
      <td>v2.3</td>
      <td>0.8920</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>28/28</td>
      <td>`833fe4ec4d1f8528`</td>
      <td>`7e6ac174`</td>
    </tr>
    <tr>
      <th>3</th>
      <td>`v2.12`</td>
      <td>v2.12</td>
      <td>0.8539</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>28/28</td>
      <td>`3ceb0071bf8d62a4`</td>
      <td>`c07f1c5b`</td>
    </tr>
    <tr>
      <th>4</th>
      <td>`baseline-v2.12-default-right-set-3`</td>
      <td>v2.12</td>
      <td>0.8405</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>28/28</td>
      <td>`b247cd5d9ce9da1d`</td>
      <td>`8b30a2d7`</td>
    </tr>
    <tr>
      <th>5</th>
      <td>`story-graph-reasoning-v2.14-right-set-3`</td>
      <td>v2.14</td>
      <td>0.8388</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>28/28</td>
      <td>`25790c44c054508a`</td>
      <td>`25b489d9`</td>
    </tr>
  </tbody>
</table>

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
      <td>0.9875</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>8/8</td>
      <td>`b2e7fb1676745447`</td>
      <td>`090606b4`</td>
    </tr>
    <tr>
      <th>2</th>
      <td>`kubilay`</td>
      <td>v2.2</td>
      <td>0.9792</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>8/8</td>
      <td>`4a467771e91507c9`</td>
      <td>`a684db5d`</td>
    </tr>
    <tr>
      <th>3</th>
      <td>`v2.3-gpt-6-luna-Additional-Questions`</td>
      <td>v2.3</td>
      <td>0.9500</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>8/8</td>
      <td>`49f6f90f2223667a`</td>
      <td>`6494f50f`</td>
    </tr>
    <tr>
      <th>4</th>
      <td>`2026-10-22-v2.13-luna-high-Additional-Questions`</td>
      <td>v2.13</td>
      <td>0.9021</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>8/8</td>
      <td>`96ab190ac570dbe8`</td>
      <td>`98e9df42`</td>
    </tr>
    <tr>
      <th>5</th>
      <td>`story-graph-reasoning-v2.14-Additional-Questions`</td>
      <td>v2.14</td>
      <td>0.8563</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>8/8</td>
      <td>`d97ba1ac2f66173f`</td>
      <td>`6914235c`</td>
    </tr>
  </tbody>
</table>

The Additional Questions runs used pinned snapshots of eight items. Some QA.csv runs have a `partial` overall execution status because a non-correctness evaluator failed; correctness scores were available for all 36 items and were included here.

## Metric abbreviations

- **P5 / P10 (Precision@5 / Precision@10)**: The proportion of relevant passages among the top 5 / 10 retrieved results (signal-to-noise ratio).
- **H5 / H10 (Hit@5 / Hit@10)**: Whether at least one relevant passage appears in the top 5 / 10 retrieved results (1 for a hit, 0 otherwise).
- **Recall@K**: The proportion of all relevant passages that appear within the top K retrieved results. This is a retrieval diagnostic; it is not one of the table columns.
- **SetP (Context Precision / Set Precision)**: The proportion of retrieved passages in the deduplicated set that are relevant to the query (signal-to-noise ratio).
- **CtxR (Context Recall)**: Whether retrieval surfaced all the necessary information or ground-truth passages required to answer the question; measured here as the share of direct gold passages found in the retrieved set.
- **Faith (Faithfulness)**: The share of answer claims supported by the retrieved evidence.
- **Rel (Relevancy)**: The judge score for whether the answer addresses the question, regardless of factual correctness.

