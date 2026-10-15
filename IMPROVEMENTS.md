# Pipeline improvement log

One entry per tuning round, newest first. Each round targets one failing question, uses general changes only (nothing
from the reference answer in prompts, queries or code) and checks the full QA.csv dataset (35 items) for regressions.
Scores are means of the Langfuse judges `answer_correctness_v1` / `citation_support_v1`. Raw run outputs, per-run
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
