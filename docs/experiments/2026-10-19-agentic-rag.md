# Agentic retrieval: the model chooses among the pipeline's instruments (2026-10-19)

Status: completed experiment. **Not promoted** to the interactive pipeline. The agent answered one of the two target
questions reliably and failed the other. Code lives in `app/agent.py` (not imported by `app/main.py`); the runner and
raw traces are in `data/tuning/agentic/` (untracked).

## Question

The fixed pipeline runs one order: translate → HyDE/expansion/grammar → dense search → RRF → rerank → wide/keyword/
scene/entity admission → answer. This experiment asks whether a local model can instead choose the instruments itself
— dense search, BM25, query expansion, the scene-summary index, entity cards, and direct reading — and answer a
question the fixed order gets wrong.

Two questions that fail on the current defaults were provided by the user and reproduced here:

| # | Question | Baseline answer (`run_pipeline`, defaults) | Verdict |
|---|---|---|---|
| Q1 | How did Mikhail first know about Salander? | "Mikhail first knew about Salander through the media coverage of her involvement in Bjurman's murder, as he followed every report on TV and read all the daily papers [E1]." | wrong |
| Q2 | Why Mikael messed up in Wennerstrom case? | "…because he was threatened and someone made him aware of his investigation, leading to a series of strange events including anonymous calls and the eventual downfall of his story. [E10]" | wrong |

The reference answer is built from the books, not from a dataset (neither question is in QA.csv):

* **Q1.** Vanger had Blomkvist checked before hiring him ("We wanted to check up on you before we hired you",
  Dragon Tattoo, ch. 17, p173); Salander wrote the roughly eighty-page report on him, and Frode gave it to Blomkvist
  when he demanded it (p179–180); reading it, Blomkvist learned who she was, judged her "one hell of an investigator"
  (p181) and discovered she had been in his iBook (p184–187). The passage the baseline never reaches is p179–187.
* **Q2.** Wennerström learned of Blomkvist's investigation and set a trap (ch. 27, p253–256): a "Deep Throat" source
  led to further sources, the documents were "skilful forgeries", the photograph a montage (p262–266), "everything
  seemed verifiable. So we published" (p263), and Wennerström could "pick apart" the story "point by point" (p267).
  The baseline only reaches p253, the start of the conversation, and answers with the threats.

## Setup

| Item | Value |
|---|---|
| Index | `millennium_books_b8e1d14641085b406440` — 5,522 passages, 1,786 scene summaries, 5,522 scene-context passages, 4,043 entity cards / 3,255 edges (default config, built 2026-10-19; scene and entity caches reused) |
| Embedding / reranker | `sentence-transformers/multi-qa-MiniLM-L6-cos-v1` / `cross-encoder/ms-marco-MiniLM-L-6-v2` (CPU, as in the pipeline) |
| Agent models | `qwen3:8b` (default), `qwen3.6:35b`, `gemma4:26b`; `qwen3-thinking:30b-a3b` was dropped (no tool calls) |
| Baseline | `run_pipeline` with `ResolvedPipelineConfig()` on the same collection, `qwen3:8b` |
| Control | the same fixed pipeline with `qwen3.6:35b` as the generation model (`baseline-qwen3.6_35b.json`) |
| Tool protocol | native Ollama `tools`, with a JSON-text fallback (`{"tool": …}` printed in content) |
| Run record | `data/tuning/agentic/{baseline,agent-*,repeat-*}.json`; every tool call has a Langfuse `tool:` observation |

Model choice came from the local benchmark (`~/llm-comparison-benchmark.md`): qwen3.6:35b was the strongest reasoner
among the local models (correct in 51 s / 3,036 tokens), gemma4:26b the fastest (29 s), qwen3:8b much slower on
reasoning (219 s / 7,266 tokens). The agent is a different workload, so each candidate was also probed for native tool
calls before use.

## The tools

Each wraps existing code; none reimplements retrieval.

| Tool | Instrument | Returns |
|---|---|---|
| `semantic_search` | dense search + cross-encoder (`pipeline._embedder`, `_reranker`) | 5 hits with id, book, chapter, paragraph, score, 300-char text; `name_hints` |
| `keyword_search` | BM25 (`pipeline._keyword_search`) | 5 hits |
| `expand_query` | HyDE + alternatives + grammar (`pipeline._transform`) | the rewrites, marked "not evidence" |
| `search_scenes` | scene-summary collection (`scenes.scene_collection`) | 2 scene summaries + member passage ids |
| `entity_card` | entity cards (`entities.entity_cards_path`) | facts, other names/links, source ids |
| `find_names` | the books' name vocabulary (`pipeline._name_pairs`) | close spellings and full names |
| `read_passage` | passage + neighbours, from the keyword index | full text and adjacent passages |
| `read_chapter` | sequential passages of one chapter | a page of the chapter, with ids |
| `submit_answer` | ends the loop | answer + ids the answer relies on |

`semantic_search` and `keyword_search` attach `name_hints`: capitalised query words the books do not use (or use
under another full name) are matched against the corpus vocabulary, so "Mikhail" comes back with "Mikael (367
mentions)". Every model followed this hint; without it weaker models either abstained or invented "Mikhail
Vanger"/"Mikhail Zalachenko".

## The loop

Ten turns and sixteen tool calls at most, 16,384-token context. Older tool results are compacted to their ids once the
conversation passes 22,000 characters. `submit_answer` is refused before three tool calls, and its answer is checked
once (twice at most) by a verification request that shows the cited passages **with one neighbour on each side**: a
passage that only mentions the topic, states the opposite, or could be about another person is not support. A final
answer without `submit_answer` is accepted only if it cites collected ids and passes the same check. Full traces were
saved for every run.

## Runs

| Run | Model | Thinking | Q1 | Q2 |
|---|---|---|---|---|
| control | fixed pipeline, `qwen3.6:35b` | — | abstains ("no passage states how he first knew") | partly right: "set up", "outmaneuvered", but says the evidence does not state the error |
| 1 | `qwen3:8b` | no | wrong (reads a witness statement about an attack as the answer) | wrong ("set up", cites the trial report) |
| 2–5 | `qwen3.6:35b` | no | **0/4** (two abstentions, one "Mikhail Vanger", one partial) | **4/4 correct** |
| 6 | `qwen3.6:35b` | yes | wrong (Palmgren as "his former editor") | wrong (Svensson's desk / Salander's car) |
| 7 | `gemma4:26b` | no | wrong (chased "Mikhail Zalachenko", abstained) | not run |

Q2, four runs, all correct in substance and all citing chapter 27:

> Mikael Blomkvist messed up in the Wennerström case because he published a story based on forged evidence provided
> by a source who was part of a setup orchestrated by Wennerström. […] he waited for more sensational material linking
> Wennerström to weapons deals, which turned out to be fake. This allowed Wennerström to easily disprove the
> allegations in court, leading to Blomkvist's conviction for libel and imprisonment [E1] [E2].

The cited passages were p263 ("It was all a fake from beginning to end. The documents were skilful forgeries…";
"everything seemed verifiable. So we published") and p253 (the start of the account), found by reading around the first
hit; one run added an irrelevant sentence and passage about the separate Dag Svensson investigation (E3), which the
verifier did not catch.

Q1, best attempt (still wrong):

> Mikhail (likely Mikael Blomkvist) first knew about Salander when she submitted a report on him as part of her
> assignment to research his background for his article on the Vanger family. At that time, he had never heard of her
> before receiving this report [E1].

It has the report but invents its purpose and direction. The other runs abstained (twice) or answered about a
non-existent "Mikhail Vanger".

## Why Q1 failed

The answer passage exists and is reachable, but not by the queries the models wrote:

* Dense search on the question puts "When he'd first heard the news about Bjurman's murder…" (Played with Fire p260)
  first, then p48 ("Blomkvist had never heard of Lisbeth Salander and was happily innocent of her report delivered
  earlier that day"). Both read like the answer and neither is.
* All four rewrites of the question (`expand_query`) put p48 or unrelated investigation passages above the report
  scene; the HyDE passage invents an "underworld contact".
* `search_scenes` finds the right window (summary: "Mikael demands a report from Frode… Blomkvist discovers Lisbeth
  Salander has investigated his biography … concludes she hacked him") only under a query such as "Mikael reads
  Salander's report about himself". No model generated "report".
* The entity cards are too noisy to bridge it: Blomkvist's card mixes correct relations with "Mikael — son of Berger",
  "Blomkvist — nickname of Mikael", etc.

The fixed pipeline has the same blind spot: it retrieves p180 (E7) but answers from the media passage. The agent
inherits it and adds a second failure mode — premature confidence in a plausible passage.

## Findings

1. **Q2 shows the value of the agent shape, not only of a stronger model.** The explanation is one long dialogue
   spread over twenty paragraphs; one search reaches its beginning, and reading around it plus a second pass reaches
   p263/p266. The fixed pipeline, given the same `qwen3.6:35b`, gets only as far as "he was set up"/"outmaneuvered"
   and says the evidence does not state the error; with `qwen3:8b` it answers with the threats. Its six fused queries
   left p263 out of the top twelve; the agent's first search returned it, and reading around it found p266.
2. **Question formulation is the bottleneck, not tool availability.** All instruments were present in every run; the
   failing runs used two to six searches and never read the scene summary that contained the answer. The model's
   prior ("how did he first know" → first meeting/first hearing) beat the evidence.
3. **A stronger model helps, but unevenly.** qwen3:8b answers after two tools; qwen3.6:35b iterates and solves Q2 4/4;
   gemma4:26b confabulates confidently. Thinking mode made qwen3.6 worse on Q2 (1/1 wrong) and did not fix Q1.
4. **LLM self-verification is not a guardrail.** The same-model verifier accepted the Palmgren misreading and
   hallucinated a quote to justify it; it also accepted the wrong thinking-mode Q2 answer. Passing the passage with
   neighbours sometimes helps (a manual check rejects the Palmgren reading), but it is not reliable enough to trust.
5. **Cost.** Agent runs took 20–72 s and 21k–76k prompt tokens (4–10 tool calls); the fixed pipeline took 13–19 s and
   one answer request. The scene/entity/read tools are milliseconds; generation and re-reading dominate.

## Verdict and next steps

Do not promote to `/ask`: the win is real but narrow, the failure mode is confident wrong answers, and the agent is
1.5–4× slower. Keep `app/agent.py` as the experiment and, if pursued:

* add an opt-in `/ask/agent` with streaming and the same trace, rather than changing the default;
* replace LLM verification with a mechanical check (quote containment in the cited passage + the question's named
  person appearing in it), which would have caught both the Palmgren answer and the Dag Svensson addendum;
* give the agent a "document" angle for questions about how someone learned something — a scene query built from the
  two people plus words such as *report, letter, file, interview* — or a small index of "who learned what from whom"
  events;
* cap prompt tokens per run (e.g. 30k) and stop the loop when only already-read passages come back, which would have
  cut Q1's 65–77k-token runs.

## Reproduce

Inside `millenium-tuning` (host network, `app/` and `data/` mounted, Qdrant on `127.0.0.1:6334`):

```bash
PYTHONPATH=/workspace python /data/tuning/agentic/run_agent.py qwen3.6:35b
AGENT_THINK=1 PYTHONPATH=/workspace python /data/tuning/agentic/run_agent.py qwen3.6:35b
PYTHONPATH=/workspace python /data/tuning/agentic/repeat_agent.py qwen3.6:35b 4 1   # Q2, four repeats
PYTHONPATH=/workspace python /data/tuning/agentic/run_baseline.py                      # fixed pipeline
PYTHONPATH=/workspace python -m unittest tests.test_agent                             # 16 tests
```

`run_baseline.py` also records the full evidence list and timings. The index was rebuilt with
`build_index.py`; scene and entity caches were reused from `/data`, so the build took 138 s.
