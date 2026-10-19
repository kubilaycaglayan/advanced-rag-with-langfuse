# Agentic retrieval: the model chooses among the pipeline's instruments (2026-10-19)

Status: completed experiment; **now the default engine for `/ask`** (send `engine: "fixed"` for the old pipeline).
A local model drives the pipeline's instruments as tools, answers questions the fixed pipeline gets wrong, and was run
over all four datasets. Code lives in `app/agent.py`; runners, traces and the dataset results are in
`data/tuning/agentic/` (untracked).

## Questions

The fixed pipeline runs one order: translate → HyDE/expansion/grammar → dense search → RRF → rerank → wide/keyword/
scene/entity admission → answer. Two questions that fail on the current defaults were provided by the user:

| # | Question | Fixed pipeline (defaults) | Agent |
|---|---|---|---|
| Q1 | How did Mikhail first know about Salander? | wrong: media coverage of Bjurman's murder | **correct** (report she wrote, given by Frode) |
| Q2 | Why Mikael messed up in Wennerstrom case? | wrong (qwen3:8b) / vague "he was set up" (35b) | **correct 4/4** (forged sources, p263/p266) |

The reference answers are built from the books (neither question is in a dataset):

* **Q1.** Vanger had Blomkvist checked before hiring him ("We wanted to check up on you before we hired you",
  Dragon Tattoo, ch. 17, p173); Salander wrote the roughly eighty-page report on him, and Frode gave it to Blomkvist
  when he demanded it (p179–180). Reading it, Blomkvist learned who she was, judged her "one hell of an investigator"
  (p181) and discovered she had been in his iBook (p184–187).
* **Q2.** Wennerström learned of Blomkvist's investigation and set a trap (p253–256): a "Deep Throat" source led to
  further sources, the documents were "skilful forgeries", the photograph a montage (p262–266), and "everything
  seemed verifiable. So we published" (p263). Wennerström could then "pick apart" the story "point by point" (p267).

## Setup

| Item | Value |
|---|---|
| Index | `millennium_books_b8e1d14641085b406440` — 5,522 passages, 1,786 scene summaries, 5,522 scene-context passages, 4,043 entity cards / 3,255 edges (default config, built 2026-10-19; scene and entity caches reused) |
| Embedding / reranker | `sentence-transformers/multi-qa-MiniLM-L6-cos-v1` / `cross-encoder/ms-marco-MiniLM-L-6-v2` (CPU) |
| Agent models | `qwen3:8b` (default), `qwen3.6:35b`, `gemma4:26b`; `qwen3-thinking:30b-a3b` dropped (no tool calls) |
| Control | the fixed pipeline with `qwen3.6:35b` as generation model (`baseline-qwen3.6_35b.json`) |
| Tool protocol | native Ollama `tools`, JSON-text fallback |
| QA judge | local fact judge over `datasets/answer-facts.json` (see "Judging") |

Model choice came from the local benchmark (`~/llm-comparison-benchmark.md`): qwen3.6:35b was the strongest reasoner
(correct in 51 s / 3,036 tokens), gemma4:26b the fastest (29 s), qwen3:8b much slower on reasoning (219 s / 7,266
tokens). Each candidate was also probed for native tool calls before use.

## The tools

Each wraps existing code; none reimplements retrieval.

| Tool | Instrument | Returns |
|---|---|---|
| `semantic_search` | dense search + cross-encoder | 5 hits with id, book, chapter, paragraph, score, 300-char text; `name_hints` |
| `keyword_search` | BM25 | 5 hits |
| `expand_query` | HyDE + alternatives + grammar | the rewrites, marked "not evidence" |
| `search_scenes` | scene-summary collection | 2 scene summaries + member passages; `people` adds their full names to the query |
| `entity_card` | entity cards | facts ranked by the question (or `about`), other names/links, source ids |
| `find_connections` | entity cards | facts and edges that name both people, with the passages behind each fact |
| `find_names` | the books' name vocabulary | close spellings and full names; states the likely person |
| `read_passage` | passage + neighbours | full text and adjacent passages |
| `read_chapter` | sequential passages of a chapter | a page of the chapter, with ids |
| `submit_answer` | ends the loop | answer + ids the answer relies on |

## The loop

Ten turns and sixteen tool calls at most, 16,384-token context; older tool results are compacted to their ids. Before
the loop:

* **Name normalization.** A capitalised word the books do not use is replaced with the closest book name
  ("Mikhail" → "Mikael Blomkvist"), so a misspelling cannot derail the run.
* **Connection pre-check.** For a two-person question with a connection cue (know, meet, hire, give, affair…), the
  entity cards' facts and source passages go in front of the model.

During the loop, at least four tool calls are required (including for content-only answers), and the prompt asks the
agent to cover every part of the question, check false premises, and look for the passage that reveals what really
happened after an official account. `submit_answer` is verified once against the cited passages with their neighbours.
When the loop abstains or answers without citations while holding evidence, a clean synthesis request over the
collected evidence answers instead.

## Default in `/ask`

`AskRequest.engine` defaults to `"agent"`; `"fixed"` runs the old pipeline. The agent result is mapped to the frontend's
shape: `reranked` is the evidence in `[E1]` order, citations are bracketed, and `trace_id`, `pipeline_id`,
`latency_seconds` and `agent_trace` (the tool calls) are attached. `AGENT_MODEL` selects the agent model (default
`qwen3.6:35b`). `/ask/stream` runs the agent in the request thread, emits a `status` event per tool and turn, then the
finished answer as one token; token-by-token streaming would require streaming the final answer request itself.

## Results

### Round 1 (tools only)

| Run | Model | Thinking | Q1 | Q2 |
|---|---|---|---|---|
| control | fixed pipeline, `qwen3.6:35b` | — | abstains | partly right: "set up", no mechanism |
| 1 | `qwen3:8b` | no | wrong | wrong |
| 2–5 | `qwen3.6:35b` | no | **0/4** | **4/4 correct** |
| 6 | `qwen3.6:35b` | yes | wrong (Palmgren) | wrong (Svensson's desk) |
| 7 | `gemma4:26b` | no | wrong ("Mikhail Zalachenko") | not run |

Q1 failed because the question never mentions the middle term ("the report"). Dense search returns two decoys — p260
("when he'd first heard the news…", about Björck) and p48 ("Blomkvist had never heard of Lisbeth Salander…", the
opposite of the answer) — and no model wrote a "report" query. The scene summary that states the answer is only found
with "Mikael reads Salander's report about himself". The fixed pipeline retrieves p180 but answers from the decoy.

### Round 2 (connection tools, normalization, synthesis)

| Run | Q1 |
|---|---|
| after the fixes | **3/3 correct** (report she wrote → Frode gave it → he read it → learned who she was) |

Example: *"Mikael Blomkvist first knew about Salander through a report she had written on him. He obtained this report
from Frode after demanding it. Upon reading the eighty-page document … he realized who Salander was and recognized her
as an investigator of high quality."*

The fixes were surface-level over data that already existed: the bridge fact *"Lisbeth Salander wrote a report about
Mikael Blomkvist"* is fact 163 of 763 in her entity card, and the entity cache maps it to the six report-scene
passages. Nothing was re-indexed.

### QA.csv (35 questions)

Run with `qwen3.6:35b`, one question at a time (`run_qa.py`), then re-scored with a local fact judge. Two runs:

| Run | Mean | Median | Perfect 1.0 | ≥0.9 | <0.6 | Mean time | Mean tools |
|---|---:|---:|---:|---:|---:|---:|---:|
| v1 (round-1 harness) | 0.8817 | 0.95 | 10 | 30 | 5 | 25.9 s | 5.2 |
| v2 (round-2 harness) | **0.8974** | 0.95 | 12 | 30 | 5 | 25.4 s | 6.6 |

Notable v2 fixes: "Who killed Harriet?" 0.025 → 1.0 (she is alive, not murdered), "when was she wearing the armageddon
shirt?" 0.025 → 1.0 (the Lundagatan first visit), "Why does Salander first go to Bjurman for money?" 0.5 → 1.0 (the
new computer). Regressions: "What does Salander ultimately demand from Bjurman?" 0.93 → 0.47 (it now says she demands
nothing), "what happened to Martin Vanger?" 0.93 → 0.5 (car crash right, "no one killed him" missing).

Residual failures (<0.6):

| Question | Score | Diagnosis |
|---|---:|---|
| Who tried to shoot Mikael? | 0.50 | finds Miro Nikolich, not Martin Vanger with the rifle; the corpus has a "marksman with a rifle looking for Mikael" passage (p134) but no explicit "Martin shot at him", so this may also be a reference issue |
| what happened to Martin Vanger? who killed him? | 0.50 | car crash and the truck are right; misses "no one killed him" and the fire, adds a motorcycle chase |
| How does Gottfried Vanger die? | 0.475 | answers the official account (drowned drunk, 1965); the reveal that Harriet drowned him is in p225 ("the jetty where Harriet Vanger had drowned her father") but was never retrieved |
| What does Salander ultimately demand from Bjurman? | 0.467 | says she demands nothing and took control by blackmail; misses the reports, keys, no psychiatric interference and "no other women" |
| Why did Amazon women allegedly cut off one of their breasts, and where did they live? | 0.50 | says Anatolia (= Asia Minor) and Libya; the required fact names "Asia Minor (Thermodon River) or Scythia"; "Thermodon"/"Scythia" do not occur in the corpus, so the reference relies on outside knowledge and the judge marks Anatolia missing |

**Judging.** The repo's `answer_correctness_v2` managed judge (qwen3:8b) was unreliable on these answers: it marked
facts "missing" although its own explanation said they were present (it wanted verbatim quotes), gave an abstention
1.0, and gave a correct answer 0.0. `datasets/answer-facts.json` was used with a simpler local judge (present/partial/
missing, no quote copying), and out-of-scope items were scored by an abstention rule. These scores are therefore not
directly comparable to the pipeline's Langfuse scores; they are consistent across the two runs.

### Langfuse

`run_qa_langfuse.py` runs the same agent as a Langfuse dataset experiment over the project's `QA.csv` dataset. Each
item's task opens a trace (`agent run`) with one `agent turn` generation per model request, one `tool: <name>` span per
call, and an `answer_correctness_simple` evaluator score, all linked into a dataset run. A 3-item validation run
scored 0.92 / 0.50 / 0.90 and shows the full tree:
[run 6b62df8acb2b3147](http://127.0.0.1:28420/project/millenium/datasets/cmv7zo6nw0007pa7t55mno068/runs/6b62df8acb2b3147).
The full run (36 items) is
[run 4a970c046686d2ce](http://127.0.0.1:28420/project/millenium/datasets/cmv7zo6nw0007pa7t55mno068/runs/4a970c046686d2ce):
mean 0.7884 with the same local judge. The gap from the 35-item local run (0.8974) is judge/run variance (qwen3:8b
scores the same answer differently between runs) and one extra dataset item; treat the two means as a range, not a
precise ranking.

### Other datasets

The same Langfuse runner was used for the other three datasets, one at a time:

| Dataset | Items | Mean | Median | Perfect 1.0 | <0.6 | Langfuse dataset run |
|---|---:|---:|---:|---:|---:|---|
| Additional Questions | 8 | 0.6281 | 0.925 | 1 | 3 | [163f16fe957006ca](http://127.0.0.1:28420/project/millenium/datasets/cmv892lbn0005mj7u0q074bua/runs/163f16fe957006ca) |
| set3 | 15 | 0.6683 | 0.725 | 2 | 7 | [56c9d13907c2ecf1](http://127.0.0.1:28420/project/millenium/datasets/cmvcgm11i0003mj7tbjygxtlr/runs/56c9d13907c2ecf1) |
| right-set-3 | 28 | 0.8351 | 0.95 | 5 | 4 | [3342204497eb7c8d](http://127.0.0.1:28420/project/millenium/datasets/cmvcgsorw0005mj7tu0turtdo/runs/3342204497eb7c8d) |

Across the 51 items the weighted mean is 0.754. right-set-3 is the strongest (mostly factual lookups about people,
places and events); Additional Questions and set3 hold scene and comprehension questions that the agent answers
partially or abstains on.

Recurring failures:

* Two "wounded Salander in the kitchen" scene questions (Additional Questions) abstained: the agent found Mikael
  finding her on the bench, not the detail asked about.
* Gottfried's true cause of death again (two set3 items): the official drowning is answered, not Harriet drowning him.
* Broad or summary questions — "the top 10 most important characters", "a summary of the first book" — are outside
  what passage retrieval can do; the agent abstains, which the fact lists score as a miss.
* A few factual answers are close but judged low because a detail differs (Berger's position, the cat in the crypt,
  Harriet's escape details).

## Findings

1. **The agent shape wins on multi-hop questions.** Q2 and Harriet need reading around a first hit and re-searching;
   the fixed pipeline answers from the first-ranked passage or a decoy.
2. **Question formulation and the missing middle term are the bottleneck.** Q1 became solvable once the entity cards'
   connection fact and its source passages were put in front of the model. The data was already indexed.
3. **A stronger model is not enough.** The same fixed pipeline with qwen3.6:35b still says only "he was set up" on Q2
   and abstains on Q1. Thinking mode made qwen3.6 worse; gemma4:26b confabulated.
4. **LLM self-verification is not a guardrail.** The same-model verifier accepted the Palmgren misreading and
   hallucinated a quote; a neighbour-context check is better but still fallible.
5. **Coverage is the main QA failure mode.** Most residual failures are one missing part of a multi-part fact, not a
   wrong answer. The coverage checklist fixed three items and regressed one.
6. **Cost.** Agent runs are 20–45 s (median ~21 s) vs 13–19 s for the fixed pipeline, and 5–7 tool calls. The tools are
   milliseconds; model turns dominate.

## Verdict and next steps

Promoted: the agent is now the default `/ask` engine (2026-10-19), with the fixed pipeline kept as `engine: "fixed"`.
It is slower (≈25 s vs ≈18 s) and its failure mode is a confident partial answer, so the fixed engine remains the
fallback. If pursued further:

* stream the final answer request so `/ask/stream` is token-by-token;
* make verification mechanical (quote containment + the question's named person in the cited passage), which would
  catch "Gunnar Gullberg" and the ungrounded "Anatolia"/"ancient Greece" answers;
* add a coverage pass that lists the question's parts and searches each missing one (three residual failures are this);
* add the "true account" index/angle for mysteries: the reveal passages (Harriet drowned Gottfried, Harriet is alive)
  are in the corpus but are not reached by "how did X die" queries.

## Reproduce

Inside `millenium-tuning` (host network, `app/` and `data/` mounted, Qdrant on `127.0.0.1:6334`):

```bash
PYTHONPATH=/workspace python /data/tuning/agentic/run_agent.py qwen3.6:35b
AGENT_THINK=1 PYTHONPATH=/workspace python /data/tuning/agentic/run_agent.py qwen3.6:35b
PYTHONPATH=/workspace python /data/tuning/agentic/repeat_agent.py qwen3.6:35b 4 1   # Q2, four repeats
PYTHONPATH=/workspace python /data/tuning/agentic/run_baseline.py                      # fixed pipeline
PYTHONPATH=/workspace python /data/tuning/agentic/run_qa.py --out /data/tuning/agentic/qa-agent-v2.jsonl
PYTHONPATH=/workspace python /data/tuning/agentic/rescore_qa.py /data/tuning/agentic/qa-agent-v2.jsonl /data/tuning/agentic/qa-agent-v2-rescored.jsonl
PYTHONPATH=/workspace python /data/tuning/agentic/qa_stats.py
PYTHONPATH=/workspace python /data/tuning/agentic/run_qa_langfuse.py --limit 3   # Langfuse dataset run + traces
PYTHONPATH=/workspace python -m unittest tests.test_agent                             # 24 tests
```

`run_baseline.py` records the full evidence and timings. The index was rebuilt with `build_index.py`; scene and entity
caches were reused from `/data`, so the build took 138 s.
