# Pipeline improvement log

One entry per tuning round, newest first. Each round targets one failing question, uses general changes only (nothing
from the reference answer in prompts, queries or code) and checks the full QA.csv dataset (35 items) for regressions.
Scores are means of the Langfuse judges `answer_correctness_v1` / `citation_support_v1` (from 2026-10-19 new runs
use `answer_correctness_v2`, see the first row; compare against older rounds with `correctness_evaluator: answer_correctness_v1`). Raw run outputs, per-run
configs and the analysis scripts live in `data/tuning/` (not tracked; full notes in `data/tuning/LOG.md`).

## Methodology

1. **Diagnose before changing anything.** Read the failing run's answer, cited evidence, judge comment and generated
   queries. Confirm the reference answer exists in the corpus and find the passages that hold it. Locate the failing
   stage (retrieval, fusion, reranking, generation), e.g. "the answer passage never reaches the candidates, but the
   reranker ranks it first when present" means a recall problem, so prompt changes are ruled out.
2. **Keep the fix general.** Nothing from the reference answer or the question goes into prompts, queries or code;
   answer text is used only in offline scripts that check whether the right passage was retrieved. A fix must be a
   rule that makes sense for any question. Thresholds tuned on this dataset are configurable and documented as
   calibrated on it.
3. **Test offline first.** Replay the recorded queries through retrieval, fusion and reranking (no LLM), after checking
   that the replay reproduces the recorded run exactly. For each candidate change measure:
   - *Fix:* does the answer passage reach the evidence?
   - *Blast radius:* how many other questions get different evidence? Unchanged evidence gives a byte-identical answer,
     so this bounds how many questions can regress.
   Re-check the target with a second set of generated queries so the fix does not depend on one phrasing.
4. **Narrow the change.** Drop options that change evidence for most questions. When something regresses, find out
   why and add a principled condition, not a special case (e.g. admit only passages that beat every candidate, are
   confident matches, and are added in front of the existing evidence rather than displacing it).
5. **Validate on the full dataset, repeatedly.** Run all QA.csv items and compare each one against the previous
   defaults' run, by score and by whether the answer text is identical. Repeat runs to separate real regressions from
   judge noise. Accept only zero drops; a higher mean with drops is rejected (see 88d26af). After promoting a change to
   the defaults, confirm with a run that passes no config.
6. **Record and ship.** Add tests, update the README, and write a commit message that states the evidence. Add an entry
   here: diagnosis, what was tried and failed, the final change, and the improved/regressed questions. Deploy only
   after approval, then check `/health` and ask the target question through the live service.

In short: find the stage that actually failed, fix it with a general rule, measure offline how many other questions it
can touch, shrink that to only what it should touch, then confirm on the full dataset with repeat runs.

## Rounds

| Date | Round | QA.csv correctness | Citation | Improved (answer correctness) | Regressed | Commit |
|---|---|---|---|---|---|---|
| 2026-10-19 | Judge: deepseek through<br>`opencode` (`answer_correctness_v3`,<br>optional, local-only) | saved QA.csv answers:<br>deepseek 0.677 (v2 rubric + tweak) | — | 14/14 disagreements with qwen v1:<br>deepseek right or very close | Q19 under-scored by ~0.2;<br>opencode free tier blocked this host's IP<br>during the live check | this commit |
| 2026-10-19 | Judge: fact-based<br>`answer_correctness_v2` (default;<br>v1 selectable), facts in all 4 datasets | saved answers re-scored:<br>0.694 → 0.736 (v1 → v2) | — | nickname 0.5 → 0.92, police after assault 0.5 → 0.925,<br>Berger's position 0.5 → 0.9 (plus 22 more across datasets) | wrong answers v1 scored 0.5 now ≈ 0<br>(Dag's murderer, the Section, who killed Harriet);<br>judge noise: backpack, Berger/Mikael | this commit |
| 2026-10-18 | Entity graph: PPR over cards,<br>passages and carried-context events<br>(`entity_graph`, rejected, off) | passages: set3 0.477 → 0.432<br>event lines: 0.694 → 0.639 | 0.861 → 0.903 | event lines: 7 of 94 items<br>(S3-10 toner, QA20 Cecilia, QA21, QA29, R3-4, R3-13) | passages: S3-9, S3-20<br>event lines: 16 of 94 items (QA1, QA9, QA12, QA25, QA27, QA28, QA35, R3 ×5, AQ ×2, S3 ×2) | not adopted (code kept, off) |
| 2026-10-18 | Entity anchors skip a leading<br>question word ("How Gottfried") | unchanged<br>(entity hits identical 94/94, offline) | — | — (graph-only effect) | none | this commit |
| 2026-10-17 | Chapter tails joined (index)<br>+ scene context for each passage<br>(`scene_context`, on by default) | tails: 0.736 → 0.736<br>scene context: 0.736 → 0.708<br>(usual evidence unchanged; 2 passages added after it) | 0.833 → 0.861 | Gun at Gosseberga, "what Salander said" (Additional Questions) 0 → 1<br>(Additional Questions 0.438 → 0.562)<br>Niedermann's pain 0.5 → 1, affair 0.5 → 1 | scene context: Cecilia 1 → 0 (judge error: control also abstains),<br>Henrik hires Blomkvist 1 → 0.5, Martin Vanger 1 → 0.5 (answer drift; reproducible)<br>tails: nickname 1 → 0.5 (same fact, less detail) | this commit |
| 2026-10-17 | Entity matrix: entity cards<br>from any end (`entity_matrix`,<br>on by default) | 0.708 → 0.694<br>(evidence identical 35/36) | 0.861 → 0.861 | police nicknames, book nicknames<br>(not in a dataset): "none" / 3 → listed | Armageddon #2 1 → 0.5: abstention scored 1.0,<br>now answers with the shirt (judge artifact) | this commit |
| 2026-10-17 | Entity cards: a person's<br>other names (`entity_names`,<br>on by default, built by `/index`) | 0.736 → 0.736<br>(evidence identical but<br>one added passage, answer identical) | 0.875 → 0.875 | "What is Salander's fake identity?" (Additional Questions) 0 → 0.5<br>(all four identities retrieved and named) | none | this commit |
| 2026-10-16 | Keyword (BM25) search<br>for words dense search misses<br>(`keyword_hits`, on by default) | 0.722 → 0.736<br>(evidence identical 36/36) | 0.875 → 0.875 | "What is 'no compromises'?" (Additional Questions) 0 → 0.5<br>nickname 0.5 → 1 (answer drift, same evidence) | none in correctness<br>(target's citation 1.0 → 0.5: its old abstention scored 1.0) | see section |
| 2026-10-16 | English translation of<br>non-English questions<br>(`query_translation`) | 4 random items:<br>0.75 → 0.75 | 0.875 → 0.875 | Turkish and Spanish questions<br>abstained → answered | none (English path unchanged) | see section |
| 2026-10-16 | Moment scene path on +<br>no translation request<br>for plainly English questions | 0.694 → 0.722<br>(exp100: 0.764) | 0.833 → 0.875<br>(exp100: 0.861) | T-shirt at the first meeting (Additional Questions) 0 → 1<br>Martin Vanger citation 0.5 → 1 | vs exp100, identical evidence: nickname 1 → 0.5, Zalachenko's killer 1 → 0.5 (answer-text drift)<br>police after assault 1 → 0.5 (controlled A/B: key points kept) | this commit |
| 2026-10-16 | Answer model only:<br>qwen3.5:9b-q8_0, gemma4:26b<br>(controlled, rejected) | 0.736 (qwen3:8b control)<br>→ 0.667 / 0.597 | 0.792 → 0.764 / 0.765 | qwen3.5: 4 up<br>gemma4: 4 up | qwen3.5: 7 down<br>gemma4: 12 down | not adopted (no code change) |
| 2026-10-16 | Without HyDE<br>(ablation, rejected) | 0.764 → 0.722<br>(0.653 uncontrolled) | 0.861 → 0.806 | "Did Salander and Mikael have affair?" 0.5 → 1 | Zalachenko's killer 1 → 0.5<br>Salander's fortune 1 → 0.5<br>Henrik hires Blomkvist 1 → 0.5<br>who killed Harriet 0.5 → 0 | not adopted (`hyde` flag only) |
| 2026-10-15 | Scene summaries by<br>gemma4:26b | 0.764 → 0.764 | 0.847 → 0.861 | — (citation: "Henrik hires Blomkvist" 0.5 → 1.0) | — | 51b2554 |
| 2026-10-15 | Scene summaries for<br>unnamed dialogue | 0.750 → 0.764 | 0.847 → 0.847 | "What does Salander ultimately demand from Bjurman?" 0 → 0.5 | — | b36115a |
| 2026-10-15 | Wider passage over an<br>off-point strong match | 0.736 → 0.750 | 0.861 → 0.847 | "Did Salander and Mikael have affair?" 0 → 0.5 | — (that item's citation 1.0 → 0.5) | e0c98f8 |
| 2026-10-15 | Bare first names<br>("Mikael") | 0.708 → 0.736<br>(36 items) | 0.861 → 0.861 | "What was the nickname of Mikael?" 0 → 1 | — | 31b95f1<br>95588dd<br>625f100 |
| 2026-10-15 | Wider pool when<br>fused is weak | 0.700 → 0.729 | 0.857 → 0.857 | Blomkvist's media nickname 0 → 1 | — | 34eb712 |
| 2026-10-15 | More evidence +<br>reasoning when weak | 0.614 → 0.700 | 0.838 → 0.857 | Salander's fortune 0 → 1<br>Cecilia: event that changed Harriet 0 → 1<br>table salt formula 0.5 → 1<br>Armageddon shirt 0.5 → 1 | — | 2d7b030 |
| 2026-10-14 | 15 passages + reasoning<br>always (superseded) | 0.614 → 0.757 | 0.838 → 0.871 | Salander's fortune 0 → 1<br>Blomkvist's media nickname 0 → 1<br>Cecilia: event that changed Harriet 0 → 1<br>affair 0 → 0.5<br>table salt 0.5 → 1<br>Niedermann's pain 0.5 → 1<br>Dag Svensson's murderer 0.5 → 1<br>prison sentence 0.5 → 1<br>Martin Vanger 0.5 → 1<br>Armageddon shirt 0.5 → 1 | Berger's position 0.5 → 0<br>who killed Harriet 0.5 → 0<br>who tried to shoot Mikael 0.5 → 0 | 88d26af |
| 2026-10-14 | Paragraph merging,<br>tuned prompts | 0.529 → 0.614 | 0.848 → 0.838 | Mona Lisa 0 → 1<br>Fiskargatan doorplate name 0 → 1<br>Harriet flees to 0 → 1<br>Dag Svensson's murderer 0 → 0.5<br>who killed Harriet 0 → 0.5<br>who tried to shoot Mikael 0 → 0.5<br>police after assault 0.5 → 1<br>Henrik hires Blomkvist 0.5 → 1 | table salt 1 → 0.5<br>Berger's position 1 → 0.5<br>Salander's fortune 0.5 → 0<br>affair 0.5 → 0<br>Bjurman demand — → 0 (not scored before) | 7224441 |

Each row compares the round's defaults against the defaults it replaced: 2d7b030 is measured against 7224441's
defaults (0.614), not against 88d26af, whose defaults it reverted. The correctness judge is noisy on reworded answers
(identical answers have scored 0 and 1 in different runs), so single 0.5 steps in rows without a repeat run are
weak evidence.

## 2026-10-19 — Parallel rewrites (opt-in), streamed answers, reranker benchmark

Two independent speed items were measured after the 2026-10-19 proposal.

**Parallel query rewrites (`parallel_transformations`, default off).** HyDE, the three alternatives and grammar
correction run in a thread pool. With `OLLAMA_NUM_PARALLEL=3`, three QA questions took 9.8/13.5/15.6 s in parallel
vs 23.6/17.4/20.5 s sequentially (transformation time 4.6/5.5/3.7 s vs 9.4/6.7/5.5 s). Repeated runs at temperature 0
still changed rewrites, evidence or answers — sequential repeats differ too — so the 3-question trial cannot prove
zero drops. The toggle stays off by default; the global `OLLAMA_NUM_PARALLEL=3` override was reverted. Full QA.csv
adoption needs a controlled run.

**Streamed answers (`/ask/stream`, frontend NDJSON).** `/ask/stream` emits `trace`, `status`, `token` and `done`
events, and the UI shows the answer as it is written. With Ollama idle, plain and streamed answers were identical
in 3/3 pairs on a normal question and 3/3 on the low-confidence thinking question; token text joined to the same
answer and both traces had the same 30-observation tree. First token arrived ~11.2 s (normal) and ~18.0 s (thinking)
after the request. The earlier 2/3 mismatches did not reproduce and were likely affected by concurrent benchmark
load.

**Reranker/embedding.** No change adopted. Recorded QA calls: torch16 104.5 s, torch32 219.8 s, batch 64 102.6 s,
ONNX 123.0 s, ONNX-O3 97.3 s (7 top-10 changes), int8 90.9 s (168 top-10 changes). Embedding ONNX was slower
(14.4 s vs 7.2 s). The current torch fp32 path stays. Scripts and JSON results: `data/tuning/scripts-2026-10-19-speed/`.

Verification: 95 Python tests, 14 Express tests and 19 UI tests pass.

## 2026-10-18 — Entity graph (GraphRAG-style), rejected; entity anchor fix

**Target:** set3, whose largest failure group (8 of 12) is passages that name their subject only as "my father", "the
patient" or "him" (gold dense rank 100–2000, cross-encoder −7…−11 against fused candidates at 3–7).

**Stage 1, the cards as a graph:** passages, entity cards and their links as one graph, Personalized PageRank from the
question's entities (1/√passages each) and the evidence. Offline the gold passages rank 65–722 and still score far
below the bar: 0 of 8 admitted. The cards do not hold the answers ("Mikael said the word Gottfried to Harriet").
`_entity_anchors` also read "How Gottfried" as one name, so S3-1/2 had no anchor at all.

**Stage 2, carried-context events:** a new index-time extraction (`entity_events_system`, gemma4:26b, the 4,000
characters before each window used only to name "he"/"my father"; 972 windows, 9,843 events, 2 h 47 min) added event
nodes joined to their people and passages. The answers now exist ("Harriet Vanger killed Gottfried Vanger by using an
oar to hold him under the water", the Heartbreak Hotel sign, Henrik's Wennerström promise), but rank below the official
story they contradict ("Gottfried died in a banal way …", 8.6 vs 4.3).
- *Passages of the best events after the evidence* (`entity_graph_max_hits` 2, pool 30): replay 0 of 8 gold
  passages; exp164 set3 0.477 → 0.432, 0 up, 2 down (S3-9 followed the "contract for a book" cover story).
- *The 10 best events as one-line evidence* (`entity_graph_facts` 10, pool 100; the oar event is 8th): exp165 set3
  0.477 → 0.455 (2 up, 2 down), exp166 Additional Questions 0.562 → 0.438 (0 / 2), exp167 right-set-3 0.732 → 0.679
  (2 / 5), exp168 QA.csv 0.694 → 0.639 (3 / 7). The usual evidence was identical everywhere; ten loosely related
  event lines distract qwen3:8b ("Plague … known by the alias Wasp"), and with the oar event in evidence it still
  followed the six official-story lines.

**Kept:** the code, off by default (`entity_graph`, `entity_graph_damping`, `entity_graph_pool`,
`entity_graph_max_hits`, `entity_graph_facts`; `/index` builds the events only when `entity_graph` is on), and the
built events (`ENTITY_EVENTS_CACHE`, default `/data/entity-events.jsonl`). The anchor fix (a capitalised question word
before a name is dropped) gives 17 recorded questions their entity but leaves `entity_names` and `entity_matrix` hits
identical on all 94 recorded items, so no answer changes. Notes: `docs/plans/2026-10-17-graph.md`, scripts in
`data/tuning/scripts-2026-10-17-graph/`.

## 2026-10-17 — Chapter tails and scene context: "When Mikael Blomkvist found Lisbeth Salander ... what Salander said to him?"

**Target:** Additional Questions item 45d561b9, scored 0 in all eight earlier runs (abstains).

**Diagnosis:** the answer ("Kalle Fucking Blomkvist") is the last lines of *The Girl Who Played with Fire*. `_merge`
emitted a section's remainder as its own 160-char passage, cut off from its setup ("carefully loosened the gun ... heard
her mutter"). Neither half matched: the setup has the question's words but not the answer (dense rank 504-1399, rerank
-5.51), the tail has the answer but names no scene (dense 520-1591). Given the two as one passage, qwen3:8b answers
correctly; given them as two, it does not. 81 of 110 sections ended in a passage under 400 chars. The scene summary
states the line, but the scene path's bar (7.30) and the moment path's overlap rule kept it out.

**Tried:** the whole scene summary in front of every passage, swapped in for search and reranking (target rank 1 offline,
but only ~1.8 of 10 QA.csv evidence passages kept and a cited passage lost on 18/36); contextual rankings added to the
fusion (misses the target); "beat every candidate by a margin" (never fires: the summary lifts the scene's other
passages too); the whole summary as context on the new chunks (exp139: the target sits at the end of one six-passage
window whose summary is mostly about other passages; contextual dense rank 47-211); hits in front of the evidence
(exp142/exp144: Dag Svensson's murderer answered "Henrik Vanger", and the hits shifted the scene path's bar so "Henrik
hires Blomkvist" lost its chronicle passage).

**Change:**
- `_merge`: a section's last passage shorter than `min_passage_chars` joins the passage before it (or, if they do not fit
  together, takes that passage's last units in front of it). 5,594 → 5,522 passages; 72 scene summaries and 72 entity
  windows rebuilt.
- `scene_context` (on by default): a second collection of every passage embedded with its scene summary cut to the
  `scene_context_sentences` (2) sentences nearest the passage. Contextual search; every row reranked with its context in
  front; up to `scene_context_max_hits` (2) passages not already in the evidence are added after the usual evidence (and
  before scene passages) when they rank in the top `scene_context_rank` (3) and score above `low_confidence_score`. Later
  paths do not see them, so the usual evidence and the scene path stay exactly as without it. The answer model reads
  book text only, never the summary.

**Result:** target 0 → 1.0 (exp140, exp145: "Kalle Fucking Blomkvist ... letting go of the gun [E11]"). Additional
Questions 0.438 → 0.562, none down (exp141 → exp146). QA.csv on the new chunks 0.736 → 0.708 / 0.833 → 0.861 (exp143 →
exp147): 2 up, 3 down; no item lost a passage, and reruns (exp148/exp149) reproduce the three drops exactly. Checked by hand: Cecilia's
1 → 0 is a judge error (the answer, Gottfried's drowning, is in neither run's evidence and both answers say so); for
Henrik hires Blomkvist and Martin Vanger the answer passages are in both runs' evidence and the answers keep the facts
(one adds an unsupported remark, one repeats the book's "He committed suicide"). With no retrieval regression, the user
accepted the two answer-drift drops and `scene_context` is on by default. Chapter tails alone: QA.csv 0.736 → 0.736 (exp133 → exp143). 76
tests pass.

## 2026-10-17 — Entity matrix: the entity cards from any end (`entity_matrix`)

**Target:** "Are there any police officers with nicknames?" and "What are the nicknames used in the book?" (asked
in the UI, traces 29877247 / 3619600d). The first answered that no police officer has a nickname, the second named
Kalle Blomkvist and a middle name. `entity_names` returned nothing: it starts only from a person the question names.

**Diagnosis:** the cards held the answers (Officer Bubble for Bublanski, Miss Marple for Modig, Ricky, Zala, Micke,
Mimmi, …); dense search found the copyright notice ("Names, characters …"). Scoring every edge against the question
works for specific questions (car, tattoo, fake identity) but not for questions about a set, whose words constrain
different parts of a link ("nicknames" the kind of link, "police officers" the person).

**Change:** the cards as a matrix: rows are entities, columns kinds of link (the edges' types), cells edges. The
question's phrases pick columns (MiniLM similarity to a type label ≥ `entity_matrix_similarity`, 0.75; "in the
book(s)" removed as scope). Named entities, with their name variants, restrict the cells; the words left over are
scored against every fact of each end (and together with the column word: "dragon tattoo"); with neither, the column's
cells stated in the most windows come first. General noise rules drop cells from part of the other end's own name, a
one-word name that is part of another person's full name, and one window's claim about an entity the cards otherwise
treat as a person of its own. The best cells, one per name, up to `entity_matrix_max_hits` (8), add the passage that
states them with a `Link:` line; nothing is added when the evidence already names the best cell (or, for a named
entity, any confident cell). It runs only when `entity_names` adds nothing. Cards now keep all their facts and types
(built by `/index` from the extraction cache, no model call).

**Result:** police question → Bubble, Officer Bubble, Miss Marple; book question → Ricky, Zala, Micke, Mimmi, Kalle
Blomkvist, Bubble, Magge Lundin; fake identity, car and dragon tattoo unchanged. Offline it fires on 1 of 43 dataset
items. exp150 Additional Questions 0.562 / 0.938 (== exp146). exp151 QA.csv 0.694 / 0.861 vs exp147 0.708 / 0.861:
evidence identical on 35/36; the second Armageddon question got its answer passage, and its abstention (scored 1.0)
became a correct answer scored 0.5 for missing context (reproduced by exp152). Approved with that drop and turned on by default on 2026-10-17. Notes:
`docs/plans/2026-10-17-entity-matrix.md`.

## 2026-10-17 — Entity cards: the other names of a person the question names (`entity_names`)

**Target:** "What is Salander's fake identity?" (Additional Questions, item ba2fffee), scored 0 in exp121: the
answer named none of Irene Nesser, Monica Sholes, Wasp or V. Kulla.

**Diagnosis** (`data/tuning/scripts-2026-10-16-fake-identity/`, offline): a recall failure. The passages say "she ...
under the name of Irene Nesser", "Monica Sholes", "known online only as Wasp", "V. Kulla on the door"; none uses the
question's words, most say "she", and they are spread over three books. MiniLM ranks them in the hundreds or
thousands; the cross-encoder scores them below the evidence when they are present (and bge-reranker-v2-m3 does not
bring them all either). Scene summaries leave the names out.

**What was tried:** query rewrites and facets, co-occurrence and summary searches (no gain); `keyword_rare_share`
(opt-in, default null, kept): a keyword hit with one sentence holding every rare non-name question word (each in under
1% of passages) is added at any score. It brought Nesser and Sholes but not Wasp or Kulla, so it stays off.

**Change:** an entity index. `/index` reads each non-overlapping window of 6 passages once with the index-time model
(`scene_summary_model`, gemma4:26b), which lists its people, other names of people (false identities, aliases,
nicknames, handles, names on doors), places, companies, vehicles, clothing and objects, each with the person it belongs
to and how. The mentions are merged into entities (one-word person names joined to the full name; "Wasp" kept apart
from "Wasp Enterprises") and edges ("Irene Nesser — false identity used by Lisbeth Salander") that point back to their
passages (`app/entities.py`; extractions cached in `ENTITY_CACHE`, cards written per passage index under
`ENTITY_CARDS_DIR`; about 2.8 hours for the three books on this machine, once). When answering, the edges into a person
the question names are reranked against the question; when the best one (score at least `low_confidence_score`, 2.0)
is another name of that person and the evidence does not already name it, the passages stating the person's other
names are added in front of the evidence: the best match first, then by how many windows state each name, leaving out
the person's own name and titles, other people linked as people ("friend of": Plague), and names stated in only one
window. Each added passage carries a `Link:` line saying whose name it is, since the passage says "she".

**Result:** exp133 QA.csv 0.736 / 0.875 (== exp119); the path fired on one item ("What media nickname…", adding a
"Kalle Fucking Blomkvist" passage) with an identical answer. exp134 Additional Questions 0.438 / 0.938 vs exp121
0.375 / 0.938, only the target changed. exp135/exp137: the target's evidence holds all four identities and the answer
names Irene Nesser, Monica Sholes, Wasp and V. Kulla (and the nickname Sally), 0.5 / 1.0; the judge asks for the
purposes of each and marks down Sally, which is answer-step work. exp136: the three QA.csv name questions 1.0 / 1.0.
exp137 confirms the target with no config (cards built by `/index`, identical to the prototype's). Full notes:
`docs/plans/2026-10-16-entity-cards.md`.

## 2026-10-16 — Keyword (BM25) search for words dense search misses (opt-in `keyword_hits`)

**Target:** "What is \"no compromises\"?" (Additional Questions, item 1e785ac0), scored 0 in exp113: "the term is not
explicitly defined or directly referenced in the provided evidence".

**Diagnosis** (`data/tuning/scripts-2026-10-16-keyword/`, offline, no answer model): the phrase is Salander's inner
line at her trial (*Hornet's Nest* ch. 28 ¶11, ¶22, ¶47). All retrieval is dense; MiniLM ranks those passages
132–3,715 for the six queries, so none reaches the 30 fused candidates, the question goes down the low-confidence
path (best fused −6.59) and scene search is skipped. When scored, the passages rank far above the evidence (1.93,
1.55, −0.45). BM25 on the question ranks them 1st–3rd. The scene summaries leave out the line, so they don't help.

**Blast radius, measured offline on all 43 questions (exp112/exp113 recorded candidates):** with keyword hits
competing for the low-confidence evidence, or admitted like the wider pool when they only beat every fused candidate,
evidence changed on 13–14 of 36 QA.csv items, including off-corpus questions (table salt, solar eclipse) that got
passages scoring around −11. The target's best keyword passage beats the best fused candidate by 8.52; the largest
margin on any other question is 3.57 (an unrelated coffee passage for the Armageddon question). Only the target clears
4.0.

**What was tried on the target (single-item runs):**
- exp114, the three exact-phrase passages admitted in score order: 0.5. The answer said the phrase "appears" but is
  not explained. Each passage holds the line but not what it answers.
- exp115, each admitted passage joined with the passage before it (¶14–21 Giannini demands immediate acquittal; ¶40–46
  Salander refuses any condition): 0.5, the answer now explains the stance but garbles it.
- exp116, the same in reading order: 0.5, a correct answer with citation 1.0.
- exp117/exp118, plural stemming ("compromises" also matches "compromise") and, once the margin has fired, every
  keyword hit that beats every fused candidate (up to 5): adds "at least you don't compromise" (*Dragon Tattoo*
  ch. 27) and "OK. A little compromise" (ch. 28): 0.5. The judge asks for the trial stance, the personal trait and the
  single exception every time. In six offline replays of the answer request on three evidence variants, qwen3:8b never
  used the "little compromise" passage, so the rest of the gap is in the answer step, not retrieval.

**Change:** `keyword_hits` (default 0 = off; 30 in the runs below), `keyword_margin` (4.0, calibrated on these 43
questions: it sits in the gap 3.57 → 8.52) and `keyword_max_hits` (5). An in-memory BM25 index over the indexed
passages (stop words dropped, plural -s stemmed) is searched with the question. Hits not already pooled are reranked.
When one beats every fused candidate by `keyword_margin`, the hits that beat every fused candidate are added in front
of the evidence in reading order, each joined with the passage before it. No LLM request is added. Keyword search
takes about 0.2 s per question (the index is built once per process).

**Result:** exp119 QA.csv 0.736 / 0.875 vs exp112 0.722 / 0.875: evidence identical on 36/36, answers identical on
35/36; the one changed answer (nickname, same evidence) is answer drift and went 0.5 → 1. exp120 Additional Questions
0.429 / 0.929 vs exp113 0.357 / 1.0: only the target changed (0 → 0.5 correctness; citation 1.0 → 0.5 because the
judge would not credit *Dragon Tattoo* "you don't compromise" as support for the trait). Approved and turned on by
default (`keyword_hits` 30) on 2026-10-16, the setting of exp119/exp120.

## 2026-10-16 — English translation of questions asked in another language (`query_translation`)

**Target:** questions asked in another language. The embedder and cross-encoder are English-only, so "Salander'a
sigara tabakasını kim verdi?" (Turkish for QA4, "Who gave the cigarette case to Salander?") and "¿Salander y Mikael
tuvieron una aventura?" (Spanish for QA1) both went to the low-confidence path and abstained or hedged.

**Change:** one generation request (`rag-query-translation`) replies `LANGUAGE:` and `ENGLISH:` lines. Names are kept
as written; only translated forms of the novels' own names (a translated book title or nickname) become the English
edition's. For a non-English question the translation is searched next to the question as asked and replaces it for
the rewrites, name completion, reranking and scene search; the answer model still sees the question as asked. When the
model says the question is English, its wording is never used, so English questions search exactly as before; a
version that only asked for "ENGLISH or the translation" reworded English questions ("Mikael" → "Blomkvist") and was
dropped.

**Result:** 4 random QA.csv items (QA1, QA4, QA10, QA28), on (execution `6ba652d1`) vs off (`2b0b7829`): correctness
0.75 / 0.75, citation 0.875 / 0.875, 0 failures, no translation made; the per-item swaps (QA1 1 vs 0.5, QA28 0.5 vs 1
with identical evidence) are Ollama run-to-run noise. Foreign questions: the Turkish one now answers Miriam Wu (was
"no evidence"), the Spanish one now cites the half-year affair (was hedged); both left the low-confidence path and
took about 14 s instead of 22–47 s. Cost: one more short generation request per question.

## 2026-10-16 — Moment scene path for "a detail at a specific moment" (opt-in `scene_moment`)

**Target:** "What t-shirt was Salander wearing when they first met with Mikael in her house?" (Additional Questions,
item dece0abd), scored 0: the model abstained in run `7d83909e`; with only the usual evidence it answers the E.T.
T-shirt from chapter 2.

**Diagnosis** ([subplan](docs/plans/2026-10-16-additional-questions-recall-scene-path.md)): the question names the
moment (their first meeting at her apartment, *Dragon Tattoo* ch. 18) and the detail (the T-shirt); the T-shirt
passage (¶18) names neither Blomkvist nor the meeting. Measured offline, without the answer model
(`data/tuning/scripts-2026-10-16-scene-path/`):
- Deeper scene search alone (step 1) does not help: with the whole question the gold scene is not in the summary
  search's top 100, and the scene that holds the current evidence (Martin Vanger's crash, where Salander wipes
  fingerprints with a T-shirt) scores 4.26, above any summary found.
- With the moment written out on its own ("Salander first met with Mikael Blomkvist in her house") the right scene is
  in the top 3–7 of 1,809 summaries, but the cross-encoder ranks other Salander/Blomkvist home scenes above it and
  scores the crash scene almost as high (5.6 vs 5.2), so no score margin or "earliest scene" rule separates them.
- The generation model, given the ten summaries found in reading order, picked the scene that opens the meeting in
  6 of 6 trials (three phrasings × depth 10/20); the T-shirt passage is just past that window's end.

**Change:** `scene_moment` (default off). When the summary search adds nothing, one request splits the question into
a MOMENT and a DETAIL line (`rag-scene-moment`; asking for the detail separately keeps it out of the moment); names
in the moment are completed as in retrieval; the moment searches the scene index (`scene_search_hits`); a second
request (`rag-scene-select`) picks the summary that shows the moment, or none. The chosen window and the window that
continues it are added after the usual evidence in reading order, unless the evidence already holds one of their
passages. Questions that name no moment ("MOMENT: none") add nothing. Two new Langfuse prompts, created with
`python app/prompt_assets.py --create-missing`.

**Result:** target 0 → 1.0 (citation 1.0) in two judged runs (exp104 `1fae1c65`, exp105 `1db283ad`, identical
answers): "When Salander first met Mikael in her house, she was wearing a T-shirt with the slogan 'ARMAGEDDON WAS
YESTERDAY—TODAY WE HAVE A SERIOUS PROBLEM' [E19]." Two rephrasings of the question gave the same answer (unjudged).
Cost: two generation requests (about 1–3 s) on non-low-confidence questions where the summary search adds nothing.
**Regression check** (current code, `query_translation` on; control and treatment twice each, repeats identical):
QA.csv control exp106/exp108 0.694 / 0.833, `scene_moment` exp107/exp109 0.722 / 0.847, 3 up / 0 down; the moment
path added passages on 4 of 36 items (doorplate name, Säpo unit, police after assault, Martin Vanger), and 30/36
answers are identical. Additional Questions exp110 0.214 → exp111 0.357, T-shirt 0 → 1, nothing lower. Latency +0–2 s
(median 15.2 → 17.4 s). Turned on by default (user approval, 2026-10-16), together with the fix below.

**Side finding:** the control on the current code is 0.694 / 0.833 against exp100's 0.764 / 0.861 (2 up, 7 down),
although no English question was translated: the extra translation request comes first, and qwen3:8b's output depends
on the previous request, so HyDE changed on 27/36 items and evidence on 19/36.

**Fix:** `english_word_share` (default 0.6). A question skips the translation request when at least 60% of its
non-name words (names: words the books write capitalised more often than not) are words the books use at least twice.
All 43 dataset questions score 0.67–1.0 and skip it; eight foreign test questions (Turkish, Spanish, German, Swedish,
French, Italian, with and without names) score 0–0.33 and are still translated (the Turkish cigarette-case question
still answers Miriam Wu). Calibrated on this corpus; `null` always asks the model.

**Confirmation, no config** (exp112 QA.csv, exp113 Additional Questions): QA.csv 0.722 / 0.875, evidence identical to
exp100 on 33/36 items (19/36 differed with the translation request), 1 up / 3 down vs exp100. Two downs (nickname,
Zalachenko's killer) have identical evidence and differ only in answer wording (the nickname item takes the
low-confidence path, where the moment step does not even run); the third (police after assault) got four moment
passages, and a controlled A/B of its answer request with and without them (same warm-up request, twice each) kept the
key points (distrust, legal incapacity, handling it herself) both ways. Additional Questions 0.357 / 1.0 (T-shirt 1.0).
QA.csv mean latency 18.9 s (exp100 18.1 s).

## 2026-10-16 — Answer model only: qwen3.5:9b-q8_0 and gemma4:26b (controlled, not adopted)

**Question:** is another local model better or faster at writing the final answer, with retrieval held fixed? The
earlier qwen3.5 run (exp76, 0.764, 9 items lower) changed `generation_model`, which also writes the HyDE document,
query alternatives and grammar-corrected question, so it tested retrieval and answers together.

**Setup** (`data/tuning/scripts-2026-10-16-answer-model/`): every arm replays exp100's recorded queries, so retrieval,
reranking, scene search and the evidence are the same; only the model behind the answer request changes (same
`rag-answer` v1 prompt, temperature 0, 8192 context, budgets, reasoning rules).
1. *Answers, no judging, one model loaded:* the evidence was byte-identical to exp100 on 36/36 items in all six runs,
   and each model's repeat run gave byte-identical answers. Timing is warm (the model is loaded before the first item).
2. *Official judging:* a normal experiment run per arm (managed qwen3:8b judges) whose answer call returns the stored
   answer only if the request matches it exactly.
qwen3:8b runs through the same harness as the control. Without the preceding query requests it writes different text
on 23/36 items (the order sensitivity noted in the HyDE ablation), so the control scores 0.736 / 0.792, not exp100's
0.764 / 0.861.

| Answer model | Correctness | Citation | vs control | Answer time mean / median / p90 | Reasoning path (13 items) | Decode |
|---|---|---|---|---|---|---|
| qwen3:8b (control, exp101) | 0.736 | 0.792 | — | 10.6 / 4.7 / 21.5 s | 22.6 s | 35 tok/s |
| qwen3.5:9b-q8_0 (exp102) | 0.667 | 0.764 | 4 up / 7 down | 90.0 / 14.6 / 417 s | 229 s | 21 tok/s |
| gemma4:26b (exp103) | 0.597 | 0.765 | 4 up / 12 down | 7.5 / 4.1 / 14.2 s | 14.6 s | 69 tok/s |

Retrieval and the other steps add about 8.7 s per question, so end-to-end latency would be about 19 s (qwen3:8b),
about 99 s (qwen3.5) and about 16 s (gemma4).

**Findings:**
- *qwen3.5:9b-q8_0:* reasons about 7× longer on the weak-evidence path (≈4800 tokens per item against ≈670); 7 answer
  calls hit the 4096-token budget and 5 items needed the 8192 retry or the no-reasoning fallback (400–460 s each).
  Gains (prison months, who killed Harriet, digging tool, affair) are offset by losses on Cecilia, Armageddon shirt,
  what is Armageddon, Henrik's family, Henrik hires Blomkvist, Dag Svensson's murderer, cigarette case.
- *gemma4:26b:* faster than qwen3:8b everywhere (reasoning path 22.6 → 14.6 s) and never hit a budget, but it commits
  less: with the same evidence it lists every candidate instead of choosing (Säpo unit: "Zalachenko club / unit /
  faction / inner circle"; Dag Svensson's murderer: several suspects), says the evidence lacks the answer or gives
  an off-point one where qwen3:8b scored (Cecilia, Armageddon shirt, Bjurman money), and some drops are judge strictness (libel conviction
  1 → 0.5 for adding "fifteen counts"). The judge is qwen3:8b, so a preference for its own style cannot be excluded;
  the earlier gemma4 second-judge diagnostic suggests the judge matters.
- Both candidates raise the same three items 0.5 → 1 (prison months, who killed Harriet, digging tool; plus affair
  for qwen3.5 and Niedermann for gemma4), so qwen3:8b's partial answers there are a weakness the evidence can fix.

**Decision:** keep qwen3:8b for answers (default unchanged; no code change). gemma4:26b is the only faster option;
it would need prompt work on committing to one supported answer before it is worth another round. Runs: exp101
http://127.0.0.1:28420/project/millenium/datasets/cmv7zo6nw0007pa7t55mno068/runs/ce11af8cf5a7cdbc, exp102
.../runs/3ed1b61b954f2b24, exp103 .../runs/e51e6d747b155e35.

## 2026-10-16 — Ablation: no hypothetical document (HyDE) (not adopted)

**Question:** what does the HyDE query (a generated passage that "could answer" the question, searched alongside the
question, three literary alternatives and the grammar-corrected question) contribute to retrieval and answers?

**Setup:** new `hyde` setting (default true); `{"hyde": false}` drops only that query. The `query_expansion` mode was
not used because it also drops grammar correction. Same-day control exp100 (defaults) reproduced exp94 (35 of 36
answers byte-identical, same scores), so exp94/exp100 is the baseline.
- exp98, `{"hyde": false}` as deployed: 0.653 / 0.861, 8 down (1 → 0.5: Zalachenko's killer, fortune, Palmgren's
  condition, why not go to police, Henrik hires Blomkvist; who killed Harriet 0.5 → 0; Armageddon shirt 1 → 0;
  what is Armageddon 1 → 0.5), 1 up (affair 0.5 → 1).
- exp99, controlled: the same alternatives and grammar-corrected query as exp100, replayed from the recorded run
  (`data/tuning/scripts-2026-10-16-no-hyde/replay_no_hyde.py`), so the only difference is the missing query:
  0.722 / 0.806, 5 down / 2 up.

**Findings:**
- *Retrieval:* HyDE is a minor contributor. Without it 21 of 36 items get different evidence, almost always one
  passage swapped out of 10–15; the best reranker score is unchanged on every item but one. On two items (QA13, QA16)
  the scene gate no longer admits a scene (16 → 10 passages), with no score change. In the four items that dropped
  in the controlled run, the lost passage was not one the HyDE-on answer cited.
- *Answers:* the drops come from the 8B answer model reacting to small evidence changes, not from losing the passage
  with the answer: e.g. "Henrik hires Blomkvist" still has the Harriet passage but now answers only "family chronicle".
  Answers are slightly shorter (48.5 → 44–46 words); citations per answer and the low-confidence (reasoning) path
  (13 items) are unchanged.
- *Order sensitivity:* qwen3:8b's greedy (temperature 0) output depends on the request before it (llama.cpp prompt
  cache). Replaying a recorded answer request after its recorded HyDE → expansion → grammar sequence reproduces the
  recorded answer; after only a grammar request it does not (`sequence_probe.py`). So removing any LLM call changes
  some answers even with identical evidence (exp99: 4 such items, correctness 1 up / 1 down), and in exp98 it also
  changed the query alternatives of 18 items. That is why the uncontrolled run (0.653) is worse than the controlled
  one (0.722): part of the difference is this instability, not HyDE's retrieval value.
- *Speed:* mean latency 18.06 → 15.38 s (exp98; median 14.5 → 10.7 s); query transformation 7.0 → 3.9 s.

**Decision:** keep HyDE on (default unchanged). The `hyde` flag stays as an opt-out for latency-sensitive use. Runs:
exp98 http://127.0.0.1:28420/project/millenium/datasets/cmv7zo6nw0007pa7t55mno068/runs/ad1026f5143e167b, exp99
.../runs/2f935c488054ab73, exp100 .../runs/cbd669e81da30a74.

## 2026-10-15 — Scene summaries for answers spread over unnamed dialogue (b36115a)

**Target:** "What does Salander ultimately demand from Bjurman?" (item 72d2d675), scored 0 in every run where the
evidence did not hold the answer: "she wants him to disappear from her life" (from the chapter where she plans his
death). Earlier 1.0 scores were "the evidence does not state ..." answers (judge noise).

**Diagnosis:** retrieval at both stages, and no single-passage fix can reach it.
- *Answer passages:* Dragon Tattoo ch. 14, six consecutive passages (bank access, no contact, faked welfare reports,
  rescinding her incompetence declaration, spare keys, no other women). They are dialogue ("you will ...", "I want your
  spare set of keys") that never name Salander or Bjurman.
- *Dense search:* ranks 140 to over 1000 for every generated query.
- *Cross-encoder:* −6.2 to −11.5 against the question; the best fused (off-point) passage scores 3.30. No other local
  reranker (MiniLM-L12, bge-reranker-base, bge-reranker-v2-m3, mxbai-rerank-base) ranks an answer passage first.
- *Answer:* with those passages in the evidence, the production prompt lists the reports, keys and incompetence
  declaration, cited. Generation is not the problem.

**Change:** a second index of LLM summaries over windows of `scene_window` (6) consecutive passages of one EPUB section,
every `scene_stride` (3) passages (1809 windows; qwen3:8b, one call per window, about 2 h once, cached in
`/data/scene-summaries.jsonl`). The summaries name who does what. The question is searched against them
(`scene_search_hits` 10) and the summaries are scored with the cross-encoder. Summaries score systematically higher
than passages, so the bar compares like with like: the best scene must beat every scene that holds one of the top
evidence passages by more than `scene_margin` (1.0, calibrated on this dataset, configurable, null disables), and score
above `low_confidence_score`. Its passages that are not already in the evidence go after the usual evidence, which is
unchanged. No scene search on the low-confidence path, which already widens the evidence and reasons. Latency
+0.11 s per question (17.83 s → 18.14 s).

**Tried and rejected (offline replay of exp83, reproduces it with 0 diffs):**
- Names from neighbouring passages as a header ("Also in this scene: ..."), for embedding and/or reranking: answer
  passages rise to about +0.5 in the reranker but not in dense search; evidence changes on 36 of 36 questions.
- An LLM description of each passage: an answer passage rises to 3.66, but the off-point candidates rise as much (4.26).
- Including neighbouring passages: the nearest retrieved passage is 17 passages before the answer, with a flashback in
  between.
- Scene margin over the best fused *passage*: admits 8–23 questions at margins 3–0.
- Scene passages in front of the evidence: "Who tried to shoot Mikael?" drops Miro Nikolich in offline replay; after
  the evidence it keeps him.
- Scene search on the low-confidence path (exp86): "Harriet flees to what country?" 1.0 → 0.5 (the scene added
  unsupported details).
- exp85 is invalid: another job used Ollama at the same time, and answers changed with identical evidence.

**Result:** exp84a (target, fresh queries): 0.5 / 1.0. exp87 (QA, `scene_margin` 1.0): 0.764 / 0.847, 0 failures;
the 4 predicted questions changed (target 0 → 0.5: "monthly reports on her welfare ... declaration of incompetence
rescinded ... spare keys ... video public" [E12–E15]; still missing bank control and "no other women"; "Who gave the
cigarette case", "Who tried to shoot Mikael?", "Why does Salander first go to Bjurman for money?" kept their scores),
the other 32 answers byte-identical to exp83. exp88 (the 4 changed questions, repeat): identical answers and scores.
exp89 (new defaults, no config): byte-identical to exp87.

**Follow-up, name check (not adopted for the index):** 373 of the 1809 summaries name someone the excerpt does not
(first names it knows from the books, "Martin" for Mikael Blomkvist, an invented "Elin Wästberg"), and 11 open with an
invented "Chapter N". `app/scenes.py` now checks each new summary: names are written as the excerpt writes them, and a
summary with a name that cannot be traced to the excerpt is summarised again with the excerpt's names listed
(`python app/scenes.py` repairs a cache once). On this cache: 373 → 6 untraced (all places or adjectives), 376 summaries
changed. Rebuilt on the repaired summaries, QA.csv (exp90) gave 0.750 / 0.861: "Did Salander and Mikael have
affair?" 0.5 → 1.0, but the target went back to 0 (a Bjurman assault scene now beats the answer scene, 6.28 vs 6.16)
and "Why does Salander decide not to go to the police?" went 1.0 → 0.5. Picking a single scene is fragile when scenes
about the same people score this close. Admitting two scenes, or scoring each scene against the question's rewordings,
did not fix it. The index keeps the validated summaries (restored; exp91 reproduces exp89 on the changed questions);
the repaired cache is kept in `data/tuning/` for a later round.

**Follow-up, summarising model (adopted, see the next paragraph):** on 60 sample windows (the target's 10 retrieved scenes,
15 with known name errors, 35 random), same prompt, thinking off:

| | qwen3:8b | gemma4:26b |
|---|---|---|
| Seconds per window (warm mean / median) | 5.77 / 3.94 | 3.28 / 3.30 |
| Summaries naming someone absent from the excerpt | 29 / 60 | 3 / 60 |
| Target: answer scene vs best other scene | 6.00 vs 6.01 | 8.05 vs 6.61 |

qwen3.6:35b and nemotron-3.5-lightning:30b each got a fact wrong in a 3-window smoke test and were not run further.
A full rebuild with gemma4:26b (about 1.7 h) was then validated:

**Adopted: gemma4:26b writes the summaries** (`scene_summary_model`, default `gemma4:26b`; null uses the generation
model). Full build: 1809 windows in about 1.7 h; 11 summaries keep a capitalised word the excerpt lacks, all ordinary
words ("Amidst", "Separately", "Swedish"), against 373 untraced names in the qwen3:8b summaries. The summarising model
is unloaded when the build ends and is never used while answering, so answer latency is unchanged (17.98 s). exp92
(QA, gemma summaries): 0.764 / 0.861, 0 failures, 0 drops against exp89 and exp83; target unchanged (0.5, same
answer); "Henrik hires Blomkvist" citation 0.5 → 1.0; "Who gave the cigarette case" no longer gets an unrelated scene
(answer as in exp83); 3 other answers changed with the same scores. exp93 (the 6 changed questions, repeat): identical.
exp94 (new defaults, no config): byte-identical to exp92.

**Follow-up, the remaining gap (opt-in, not default):** with gemma4:26b summaries the target's evidence already holds
the bank-access and "no other women" passages; the answer model lists only some demands from six unnamed dialogue
passages. Joining the scene into one evidence item, or a note that the passages are one scene, changed nothing alone
(joining dropped the Harriet investigation from "Henrik hires Blomkvist"). The note plus reasoning (`scene_thinking`)
recovered the bank demand: exp95 (QA): 0.750 / 0.875; target still 0.5 (the judge wants "full financial control", "no
psychiatric interference" and "no abuse of other women" stated); "Why does Salander first go to Bjurman for money?"
citation 0.5 → 1.0; "What was the nickname of Mikael?" 1.0 → 0.5 from different generated queries (Ollama
nondeterminism, no scene); mean latency 17.98 s → 25.28 s. Kept as an option, off by default; exp96 (defaults, 6
changed questions) reproduces exp94.

**Diagnostic, a second judge (official scores unchanged):** the same correctness prompt run with gemma4:26b as the
judge scores the target's answer 0 before this round (exp83), 0.83 with the current defaults (exp94) and 1.0 with
`scene_thinking` (exp95); the official qwen3:8b judge gives 0.5 to the last two. The remaining 0.5 is partly the judge.

**Closed and deployed (2026-10-16):** the target's evidence (exp94) holds a passage for every point of the reference
answer: bank access (E11), welfare and faked meeting reports (E12, E13), the shrink who will swear she is normal (E13),
spare keys (E15) and no other women (E16). The answer cites E13–E15 only, so the remaining gap is in generation and
the judge, not retrieval. The round was closed with retrieval as the goal. Untried general ideas for a later round:
extract every supported claim and then answer from that list, or check the draft against the evidence for missed
points, only when a scene is admitted. Deployed at 42d3d32 (`docker compose up --build -d app`); the live `/ask` gives
the exp94 answer with the 6 scene passages in 17 s. gemma4:26b must stay installed to summarise new windows when the
index is rebuilt.

## 2026-10-15 — Wider passage over an off-point strong match: "Did Salander and Mikael have affair?" (e0c98f8)

**Target:** "Did Salander and Mikael have affair?" (item 785e319a), scored 0 in every run since 2d7b030: "there is no
direct indication that Salander and Mikael had an affair".

**Diagnosis:** retrieval found the answer, the wider-pool gate dropped it, and the answer model then needed the
completed name.
- *Answer passage:* Fire, paragraph 43, "Blomkvist and Salander had slept together ... the relationship had lasted for
  half a year ... end the affair". Dense ranks 45-277 for the six fused queries (outside the top 30 fused), rank 1 for
  the completed-name search; it is in the wider pool and scores 8.63 against the completed question (5.83 as asked).
- *Gate:* the best fused candidate (Hornet's Nest ch. 28, "you fell for him, didn't you?") scores 5.14, above
  `wide_trigger_score` (3.5), so the wider pool was not considered at all. That passage is on topic but does not
  answer; the same score also kept the low-confidence path off.
- *Answer:* with the passage admitted first, the model given the question as asked still answered "no direct
  indication" (2 of 2 runs, offline replay identical): the passage says "Blomkvist", the question "Mikael". Given the
  completed question it answers "yes ... [E1]".

**Change:** above `wide_trigger_score`, a wider-pool passage is still admitted when it beats the usual admission bar
(every fused candidate under both wordings, and `low_confidence_score`) by more than `wide_override_margin` (2.0,
calibrated on this dataset, configurable, null disables). When the evidence holds such a passage, the answer model
sees the completed question, as it already does for passages only the completed search found. No extra searches or
reranking: latency is unchanged (mean 17.73 s → 17.83 s, within run-to-run noise of 0.05 s).

**Tried and rejected (offline replay of d1353eb8, reproduces it with 0 diffs):**
- Margin 1.0: also admits a "Wennerström affair" passage on the target; 3.0: admits nothing.
- Letting only completed-search hits bypass the gate: misses the answer passage (it is a wider-pool hit) and admits
  "Wennerström affair" passages; also changes "Henrik hires Blomkvist".
- The completed question whenever any wider-pool passage is in the evidence: "According to Cecilia..." answers "her
  disappearance" (wrong) in replay, as in exp72.
- The completed question when it raises the passage's score by a margin: does not separate the target (+2.80) from
  "According to Cecilia..." (+2.39).

**Result:** exp80a/b (target, override only): 0, 0. exp81a/b (target, final): 0.5, 0.5, citation 0.5 ("Yes ... slept
together ... half a year [E1]"; an extra claim from E9; no Hedeby or New Year's Eve detail). exp82 (6 items with name
completion or wider-pool evidence): byte-identical answers and scores. exp83 (QA.csv, defaults): 0.750 / 0.847, 0
failures; the other 35 answers byte-identical with identical scores.

## 2026-10-15 — Bare first names: "What was the nickname of Mikael?" (31b95f1, 95588dd, 625f100)

**Target:** "What was the nickname of Mikael?" (item 58343746, added to the Langfuse dataset on 2026-10-15; dataset now
36 items), scored 0: the answer said the evidence mentions no nickname.

**Diagnosis:** the books call him "Blomkvist", so the bare first name failed at three stages.
- *Retrieval and reranking:* the answer passage ("nicknamed Kalle Blomkvist ... to his dismay") ranked >250 for every
  generated query, and the cross-encoder scored it -6.47 against the question as asked but 6.9 against "What was the
  nickname of Mikael Blomkvist?".
- *Answer:* even with that passage first, the answer model read "Blomkvist had never in life used the name Carl ...
  nicknamed Kalle Blomkvist" as being about a Carl and said there was no nickname (3 of 3 offline replays).
- *Evidence depth:* the passages about his reaction and the nickname's use (Salander naming a file "[Kalle
  Blomkvist]", "the nickname she knew he loathed") ranked 100–300 for the completed-name search, so two of the three
  admitted passages were off-topic.

**Change (three commits):**
1. *31b95f1:* name completion on by default (Mikael → Mikael Blomkvist, derived from name counts in the books). The
   completed search does not enter fusion; its hits join the wider pool, which is scored against the completed
   wording, and an admitted passage must also beat the best fused candidate scored against that wording. At most
   `wide_max_hits` (3) passages are admitted (3 is the most any question admitted before, so the cap alone changes no
   evidence). The fused candidates and usual evidence are unchanged.
2. *95588dd:* the answer model sees the completed question only when the evidence includes a passage that only the
   completed-name search found; otherwise the question as asked.
3. *625f100:* the completed-name search returns `name_completion_hits` (300) hits instead of 100, since it is a single
   query that does not compete in fusion. 300 and 500 gave the same admissions offline; calibrated on this dataset and
   configurable.

**Tried and rejected:**
- Scoring all candidates against the completed wording (or the max of both): target not fixed, 5–7 items changed.
- Unbounded admissions from the completed search: 35–46 passages, mostly off-topic.
- The completed question for all 7 completed questions: "According to Cecilia..." 1.0 → 0 twice.
- Adding the passage just before each admitted one (separate or joined): not reproducible on the target, and savior
  complex citation 1.0 → 0.5 in every run.
- Answer prompt asking for context (origin, reactions), globally (`rag-answer` v11, label `tuning9`): 6 items lower;
  only on the low-confidence path (`rag-answer-weak` v1, label `tuning10`): target unchanged, 2 items lower.
- Completing names in every generated query: no more answer passages reached the pool.
- Larger answer model `qwen3.5:9b-q8_0`: 0.722 → 0.764 but 9 items lower.

**Result:** target 0 → 0.5 (31b95f1) → 0.5 with an always-correct "Kalle Blomkvist" (95588dd) → 1.0 (625f100), in
every repeat: "Mikael Blomkvist's nickname was Kalle Blomkvist, which his peers used tauntingly ... he detested the
nickname [E1] ... Lisbeth Salander uses it to tease him [E2]". Final full runs exp78 and exp79: 0.736 / 0.861 each,
0 failures, the other 35 answers byte-identical to before the deeper search; no item lower than at the start of the
round in any accepted step.

## 2026-10-15 — Wider retrieval pool when the fused candidates are weak (34eb712)

**Target:** "What media nickname is given to Mikael Blomkvist that he intensely dislikes?" (item a1915174), scored 0
("journalist creep", an insult from one scene).

**Diagnosis:** retrieval, not generation. The answer passages ("nicknamed Kalle Blomkvist ... to his dismay") never
reached the 30 fused candidates; when present, the cross-encoder ranks one first (3.52 vs 3.04). Their dense ranks vary
14–120 with query wording, and RRF over six queries drops them. HyDE invented a nickname.

**Tried:**
- `candidate_count` 40–100: fixes the item but changes evidence on 28–34 of 35 items.
- Union of each query's top 5/10/20: needs 20, changes 28 items.
- Wider pool admitted only when a passage beats every fused candidate: a 50-hit pool depended on one query wording;
  100 hits was robust. Displacing evidence (0.686) or appending it lowered "police after assault" (1 → 0.5) and
  "who tried to shoot Mikael" (0.5 → 0), reproducibly.
- BM25 on the question also finds the passages (kept as an option, not adopted).

**Change:** each search returns 100 hits; fusion of the first 30 is unchanged. When the best fused candidate scores
below `wide_trigger_score` (3.5), wider-pool passages scoring above every fused candidate and above
`low_confidence_score` (2.0) are placed in front of the usual evidence. 3.5 sits in the widest gap of this dataset's
best-fused scores (3.30 → 3.81), so it is dataset-calibrated; configurable.

**Result:** two runs (exp63, exp64): 0.729 / 0.857, 0 failures. Target 0 → 1.0 ("Kalle Blomkvist"). 33 answers
byte-identical to before; the one other changed item kept its scores.

## 2026-10-15 — More evidence and reasoning only when retrieval is weak (2d7b030)

**Target:** "How does Lisbeth Salander acquire her massive personal fortune?" (item 2b47ac9a), scored 0.

**Diagnosis:** the one answer-bearing passage reranked 14th, below top_k 10; given only "inheritance" passages, the
answer model equated a small deposit with the fortune. Heist passages use her aliases, so no query reaches them.

**Tried:** pseudo-relevance feedback, BM25 hybrid, sentence-level retrieval, LLM follow-up queries, answer-prompt
wordings, bge-base embedder + bge reranker (fixes retrieval but 0.557 overall), corpus-derived name completion
(best 0.786 but with a systematic drop). 15 passages + reasoning for every question (88d26af) gave 0.757 but lowered
three items.

**Change:** defaults back to 10 passages without reasoning; when the best cross-encoder score is below 2.0, use 15
passages and let the model reason. Name completion and `answer_thinking` stay opt-in.

**Result:** two runs (exp56, exp57): 0.700 / 0.857, 4 up / 0 down; 23 items byte-identical to before.

## 2026-10-14 — Paragraph merging and tuned prompts (7224441)

**Target:** "Who is Salander's mother?" (Additional Questions dataset).

**Diagnosis:** name-bearing passages ranked >100; short "her mother" paragraphs outranked them.

**Change:** merge consecutive short paragraphs to at least 400 characters (`min_passage_chars`); HyDE prompt v3
(no invented names) and query-expansion v4 (keep names as written) promoted to `production`.

**Result:** target correct; QA.csv 0.529 → 0.614.
