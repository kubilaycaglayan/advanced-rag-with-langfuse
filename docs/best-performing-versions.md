# Best-performing pipeline versions

Grouped by corpora and datasets.

Values are means per group.

## Corpora: Millennium Series

### Dataset: QA.csv

<table>
  <thead>
    <tr>
      <th rowspan="2">Rank</th>
      <th rowspan="2">Pipeline-model</th>
      <th colspan="1">Correctness</th>
      <th colspan="4">Retrieval results</th>
      <th colspan="2">Assembled context</th>
      <th colspan="2">Answer quality</th>
      <th rowspan="2">Latency (s)</th>
      <th rowspan="2">Est. cost (USD/question)</th>
      <th rowspan="2">Experiment ID</th>
      <th rowspan="2">Execution ID</th>
    </tr>
    <tr>
      <th>Qwen</th>
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
      <td>v2.12-gpt-6-luna</td>
      <td>0.91(36)</td>
      <td>0.34(28)</td>
      <td>0.12(5)</td>
      <td>0.50(2)</td>
      <td>0.75(2)</td>
      <td>0.16(30)</td>
      <td>0.61(30)</td>
      <td>0.91(36)</td>
      <td>0.89(36)</td>
      <td>23.23</td>
      <td>0.002</td>
      <td><a href="764cc2418408a4ea">764c</a></td>
      <td><a href="d5e9c5ad">d5e9</a></td>
    </tr>
    <tr>
      <th>2</th>
      <td>v2.16-gpt-6-luna</td>
      <td>0.90(36)</td>
      <td>0.29(31)</td>
      <td>0.15(3)</td>
      <td>1.00(2)</td>
      <td>—</td>
      <td>0.14(33)</td>
      <td>0.64(30)</td>
      <td>0.98(24)</td>
      <td>0.91(36)</td>
      <td>22.40</td>
      <td>0.002</td>
      <td><a href="4dc5a0a71e072c74">4dc5</a></td>
      <td><a href="2a7000ac">2a70</a></td>
    </tr>
    <tr>
      <th>3</th>
      <td>v2.1-qwen3:8b</td>
      <td>0.88(36)</td>
      <td>0.18(30)</td>
      <td>0.16(5)</td>
      <td>0.75(2)</td>
      <td>0.50(1)</td>
      <td>0.10(33)</td>
      <td>0.49(30)</td>
      <td>—</td>
      <td>0.85(36)</td>
      <td>31.01</td>
      <td>—</td>
      <td><a href="40346a8d399ed2c7">4034</a></td>
      <td><a href="1693c551">1693</a></td>
    </tr>
    <tr>
      <th>4</th>
      <td>v2.2-qwen3:8b</td>
      <td>0.87(36)</td>
      <td>0.18(30)</td>
      <td>0.16(5)</td>
      <td>0.75(2)</td>
      <td>0.50(1)</td>
      <td>0.10(33)</td>
      <td>0.49(30)</td>
      <td>—</td>
      <td>0.85(36)</td>
      <td>30.87</td>
      <td>—</td>
      <td><a href="4ff5ebd1a66dbfb8">4ff5</a></td>
      <td><a href="33c78788">33c7</a></td>
    </tr>
    <tr>
      <th>5</th>
      <td>v2.13-gpt-6-luna</td>
      <td>0.87(36)</td>
      <td>0.26(31)</td>
      <td>0.08(3)</td>
      <td>1.00(2)</td>
      <td>1.00(1)</td>
      <td>0.12(33)</td>
      <td>0.62(30)</td>
      <td>0.99(23)</td>
      <td>0.89(36)</td>
      <td>29.60</td>
      <td>0.003</td>
      <td><a href="fd52e12721de3536">fd52</a></td>
      <td><a href="8dc3ef0b">8dc3</a></td>
    </tr>
  </tbody>
</table>

2026-11-13 evaluator coverage for QA.csv rank 3: P@5 30/36, P@10 5/36, H@5 2/36, H@10 1/36, SetP 33/36, CtxR 30/36, Faith 0/36, Rel 36/36. Faithfulness was unavailable because the recorded traces lacked sufficient agent input or used unsupported or rewritten answer paths.

### Dataset: set3

<table>
  <thead>
    <tr>
      <th rowspan="2">Rank</th>
      <th rowspan="2">Pipeline-model</th>
      <th colspan="1">Correctness</th>
      <th colspan="4">Retrieval results</th>
      <th colspan="2">Assembled context</th>
      <th colspan="2">Answer quality</th>
      <th rowspan="2">Latency (s)</th>
      <th rowspan="2">Est. cost (USD/question)</th>
      <th rowspan="2">Experiment ID</th>
      <th rowspan="2">Execution ID</th>
    </tr>
    <tr>
      <th>Qwen</th>
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
      <td>v2.16-gpt-6-luna</td>
      <td>0.90(15)</td>
      <td>0.09(13)</td>
      <td>0.07(3)</td>
      <td>—</td>
      <td>—</td>
      <td>0.04(13)</td>
      <td>0.85(13)</td>
      <td>0.97(9)</td>
      <td>0.94(15)</td>
      <td>29.97</td>
      <td>0.003</td>
      <td><a href="37ebe85de2796617">37eb</a></td>
      <td><a href="2bfa8acb">2bfa</a></td>
    </tr>
    <tr>
      <th>2</th>
      <td>v2.12-gpt-6-luna</td>
      <td>0.77(15)</td>
      <td>0.06(12)</td>
      <td>0.10(2)</td>
      <td>—</td>
      <td>—</td>
      <td>0.02(13)</td>
      <td>0.65(13)</td>
      <td>1.00(8)</td>
      <td>0.97(15)</td>
      <td>26.60</td>
      <td>0.003</td>
      <td><a href="8451bbff73197241">8451</a></td>
      <td><a href="77f54b4d">77f5</a></td>
    </tr>
    <tr>
      <th>3</th>
      <td>v2.13-qwen3.6:35b</td>
      <td>0.72(15)</td>
      <td>0.04(11)</td>
      <td>0.00(2)</td>
      <td>—</td>
      <td>—</td>
      <td>0.03(13)</td>
      <td>0.62(13)</td>
      <td>0.77(8)</td>
      <td>0.94(15)</td>
      <td>47.47</td>
      <td>N/A</td>
      <td><a href="163cfd81374ea8b8">163c</a></td>
      <td><a href="436795ab">4367</a></td>
    </tr>
    <tr>
      <th>4</th>
      <td>v2.3-gpt-6-luna</td>
      <td>0.72(15)</td>
      <td>0.05(13)</td>
      <td>0.00(2)</td>
      <td>—</td>
      <td>—</td>
      <td>0.03(13)</td>
      <td>0.50(13)</td>
      <td>0.97(13)</td>
      <td>0.94(15)</td>
      <td>14.09</td>
      <td>0.002</td>
      <td><a href="ee483532e4d14912">ee48</a></td>
      <td><a href="a46dbdf5">a46d</a></td>
    </tr>
    <tr>
      <th>5</th>
      <td>v2.2-qwen3:8b</td>
      <td>0.68(15)</td>
      <td>0.03(12)</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>0.04(13)</td>
      <td>0.46(13)</td>
      <td>—</td>
      <td>0.97(15)</td>
      <td>37.08</td>
      <td>—</td>
      <td><a href="9dd9500d0dcb8588">9dd9</a></td>
      <td><a href="9eb12349">9eb1</a></td>
    </tr>
  </tbody>
</table>

2026-11-18 evaluator coverage for this winner: P@5 13/15, P@10 3/15, SetP 13/15, CtxR 13/15, Faith 9/15 (six traces failed faithfulness path guards), Rel 15/15.

### Dataset: right-set-3

<table>
  <thead>
    <tr>
      <th rowspan="2">Rank</th>
      <th rowspan="2">Pipeline-model</th>
      <th colspan="1">Correctness</th>
      <th colspan="4">Retrieval results</th>
      <th colspan="2">Assembled context</th>
      <th colspan="2">Answer quality</th>
      <th rowspan="2">Latency (s)</th>
      <th rowspan="2">Est. cost (USD/question)</th>
      <th rowspan="2">Experiment ID</th>
      <th rowspan="2">Execution ID</th>
    </tr>
    <tr>
      <th>Qwen</th>
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
      <td>v2.13-qwen3.6:35b</td>
      <td>0.91(28)</td>
      <td>0.09(18)</td>
      <td>0.08(4)</td>
      <td>—</td>
      <td>—</td>
      <td>0.02(24)</td>
      <td>0.48(23)</td>
      <td>0.92(17)</td>
      <td>0.98(28)</td>
      <td>47.71</td>
      <td>N/A</td>
      <td><a href="99b35b171b966af9">99b3</a></td>
      <td><a href="3d8897b7">3d88</a></td>
    </tr>
    <tr>
      <th>2</th>
      <td>v2.3-gpt-6-luna</td>
      <td>0.89(28)</td>
      <td>0.11(21)</td>
      <td>0.15(2)</td>
      <td>—</td>
      <td>—</td>
      <td>0.05(24)</td>
      <td>0.62(23)</td>
      <td>0.96(24)</td>
      <td>0.97(28)</td>
      <td>12.46</td>
      <td>0.001</td>
      <td><a href="833fe4ec4d1f8528">833f</a></td>
      <td><a href="7e6ac174">7e6a</a></td>
    </tr>
    <tr>
      <th>3</th>
      <td>v2.16-gpt-6-luna</td>
      <td>0.88(28)</td>
      <td>0.10(22)</td>
      <td>0.06(3)</td>
      <td>—</td>
      <td>—</td>
      <td>0.04(24)</td>
      <td>0.63(23)</td>
      <td>0.99(18)</td>
      <td>1.00(28)</td>
      <td>27.47</td>
      <td>0.003</td>
      <td><a href="c2cde1e05faa6f40">c2cd</a></td>
      <td><a href="52b29974">52b2</a></td>
    </tr>
    <tr>
      <th>4</th>
      <td>v2.12-qwen3.6:35b</td>
      <td>0.85(28)</td>
      <td>0.08(19)</td>
      <td>0.05(5)</td>
      <td>—</td>
      <td>—</td>
      <td>0.03(24)</td>
      <td>0.46(23)</td>
      <td>0.91(15)</td>
      <td>0.93(28)</td>
      <td>48.35</td>
      <td>N/A</td>
      <td><a href="3ceb0071bf8d62a4">3ceb</a></td>
      <td><a href="c07f1c5b">c07f</a></td>
    </tr>
    <tr>
      <th>5</th>
      <td>v2.12-qwen3.6:35b</td>
      <td>0.84(28)</td>
      <td>0.08(17)</td>
      <td>0.05(6)</td>
      <td>—</td>
      <td>—</td>
      <td>0.03(24)</td>
      <td>0.48(23)</td>
      <td>0.78(18)</td>
      <td>0.95(28)</td>
      <td>38.10</td>
      <td>N/A</td>
      <td><a href="b247cd5d9ce9da1d">b247</a></td>
      <td><a href="8b30a2d7">8b30</a></td>
    </tr>
  </tbody>
</table>

2026-11-13 evaluator coverage for this winner: P@5 18/28, P@10 4/28, SetP 24/28, CtxR 23/28, Faith 17/28, Rel 28/28. Faithfulness was unavailable on 11 traces because of answer-path or rewrite guards.

### Dataset: Additional Questions

<table>
  <thead>
    <tr>
      <th rowspan="2">Rank</th>
      <th rowspan="2">Pipeline-model</th>
      <th colspan="1">Correctness</th>
      <th colspan="4">Retrieval results</th>
      <th colspan="2">Assembled context</th>
      <th colspan="2">Answer quality</th>
      <th rowspan="2">Latency (s)</th>
      <th rowspan="2">Est. cost (USD/question)</th>
      <th rowspan="2">Experiment ID</th>
      <th rowspan="2">Execution ID</th>
    </tr>
    <tr>
      <th>Qwen</th>
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
      <td>v2.16-gpt-6-luna</td>
      <td>1.00(9)</td>
      <td>0.09(6)</td>
      <td>0.10(1)</td>
      <td>—</td>
      <td>—</td>
      <td>0.06(9)</td>
      <td>0.94(9)</td>
      <td>0.92(6)</td>
      <td>1.00(9)</td>
      <td>28.71</td>
      <td>0.003</td>
      <td><a href="4411d1a1728f4990">4411</a></td>
      <td><a href="4bcb3bce">4bcb</a></td>
    </tr>
    <tr>
      <th>2</th>
      <td>v2.12-qwen3.6:35b</td>
      <td>0.99(8)</td>
      <td>0.08(4)</td>
      <td>0.03(2)</td>
      <td>—</td>
      <td>—</td>
      <td>0.04(8)</td>
      <td>0.69(8)</td>
      <td>0.74(6)</td>
      <td>0.94(8)</td>
      <td>54.50</td>
      <td>N/A</td>
      <td><a href="b2e7fb1676745447">b2e7</a></td>
      <td><a href="090606b4">0906</a></td>
    </tr>
    <tr>
      <th>3</th>
      <td>v2.2-qwen3:8b</td>
      <td>0.98(8)</td>
      <td>0.10(6)</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>0.04(8)</td>
      <td>0.81(8)</td>
      <td>—</td>
      <td>1.00(8)</td>
      <td>36.06</td>
      <td>—</td>
      <td><a href="4a467771e91507c9">4a46</a></td>
      <td><a href="a684db5d">a684</a></td>
    </tr>
    <tr>
      <th>4</th>
      <td>v2.3-gpt-6-luna</td>
      <td>0.95(8)</td>
      <td>0.13(4)</td>
      <td>0.05(2)</td>
      <td>—</td>
      <td>—</td>
      <td>0.30(8)</td>
      <td>0.88(8)</td>
      <td>1.00(6)</td>
      <td>0.91(8)</td>
      <td>11.09</td>
      <td>0.001</td>
      <td><a href="49f6f90f2223667a">49f6</a></td>
      <td><a href="6494f50f">6494</a></td>
    </tr>
    <tr>
      <th>5</th>
      <td>v2.13-gpt-6-luna</td>
      <td>0.90(8)</td>
      <td>0.12(5)</td>
      <td>0.03(3)</td>
      <td>—</td>
      <td>—</td>
      <td>0.06(8)</td>
      <td>1.00(8)</td>
      <td>1.00(4)</td>
      <td>0.83(8)</td>
      <td>24.95</td>
      <td>0.003</td>
      <td><a href="96ab190ac570dbe8">96ab</a></td>
      <td><a href="98e9df42">98e9</a></td>
    </tr>
  </tbody>
</table>

## Corpora: The Alienist

### Dataset: set-1

<table>
  <thead>
    <tr>
      <th rowspan="2">Rank</th>
      <th rowspan="2">Pipeline-model</th>
      <th colspan="1">Correctness</th>
      <th colspan="4">Retrieval results</th>
      <th colspan="2">Assembled context</th>
      <th colspan="2">Answer quality</th>
      <th rowspan="2">Latency (s)</th>
      <th rowspan="2">Est. cost (USD/question)</th>
      <th rowspan="2">Experiment ID</th>
      <th rowspan="2">Execution ID</th>
    </tr>
    <tr>
      <th>Qwen</th>
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
      <td>v2.12-gpt-6-luna</td>
      <td>0.82(14)</td>
      <td>0.09(13)</td>
      <td>0.08(5)</td>
      <td>—</td>
      <td>—</td>
      <td>0.04(14)</td>
      <td>0.49(14)</td>
      <td>0.95(7)</td>
      <td>0.91(14)</td>
      <td>33.67</td>
      <td>0.003</td>
      <td><a href="edfdc512a36c8a81">edfd</a></td>
      <td><a href="f5eddd27">f5ed</a></td>
    </tr>
    <tr>
      <th>2</th>
      <td>v2.12-qwen3.6:35b</td>
      <td>0.81(13)</td>
      <td>0.10(14)</td>
      <td>0.05(5)</td>
      <td>—</td>
      <td>—</td>
      <td>0.05(14)</td>
      <td>0.53(14)</td>
      <td>0.88(5)</td>
      <td>1.00(8)</td>
      <td>131.52</td>
      <td>N/A</td>
      <td><a href="8cf247970106ba60">8cf2</a></td>
      <td><a href="43d7cdf4">43d7</a></td>
    </tr>
    <tr>
      <th>3</th>
      <td>v2.16-gpt-6-luna</td>
      <td>0.64(14)</td>
      <td>0.10(12)</td>
      <td>0.04(4)</td>
      <td>—</td>
      <td>—</td>
      <td>0.05(14)</td>
      <td>0.52(14)</td>
      <td>0.84(14)</td>
      <td>0.99(14)</td>
      <td>35.99</td>
      <td>0.003</td>
      <td><a href="0f71d5a9a184ffbf">0f71</a> + <a href="2b9a46f6f6f76077">2b9a</a></td>
      <td><a href="b34a7191">b34a</a> + <a href="4afdd853">4afd</a></td>
    </tr>
  </tbody>
</table>


### Metric abbreviations

- **P5 / P10 (Precision@5 / Precision@10)**: The proportion of relevant passages among the top 5 / 10 retrieved results (signal-to-noise ratio).
- **H5 / H10 (Hit@5 / Hit@10)**: Whether at least one relevant passage appears in the top 5 / 10 retrieved results (1 for a hit, 0 otherwise).
- **Recall@K**: The proportion of all relevant passages that appear within the top K retrieved results. This is a retrieval diagnostic; it is not one of the table columns.
- **SetP (Context Precision / Set Precision)**: The proportion of retrieved passages in the deduplicated set that are relevant to the query (signal-to-noise ratio).
- **CtxR (Context Recall)**: Whether retrieval surfaced all the necessary information or ground-truth passages required to answer the question; measured here as the share of direct gold passages found in the retrieved set.
- **Faith (Faithfulness)**: The share of answer claims supported by the retrieved evidence.
- **Rel (Relevancy)**: The judge score for whether the answer addresses the question, regardless of factual correctness.
- **Latency (s)**: Mean per-question query-and-answer time in seconds.
- **Est. cost (USD/question)**: Recorded query-agent inference cost divided by the number of questions with recorded usage.
