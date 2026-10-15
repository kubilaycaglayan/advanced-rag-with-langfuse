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
| 2026-10-15 | Completed names score<br>the wider pool | 0.708 → 0.722<br>(36 items) | 0.861 → 0.861 | "What was the nickname of Mikael?" 0 → 0.5 | — | 31b95f1 |
| 2026-10-15 | Wider pool when<br>fused is weak | 0.700 → 0.729 | 0.857 → 0.857 | Blomkvist's media nickname 0 → 1 | — | 34eb712 |
| 2026-10-15 | More evidence +<br>reasoning when weak | 0.614 → 0.700 | 0.838 → 0.857 | Salander's fortune 0 → 1<br>Cecilia: event that changed Harriet 0 → 1<br>table salt formula 0.5 → 1<br>Armageddon shirt 0.5 → 1 | — | 2d7b030 |
| 2026-10-14 | 15 passages + reasoning<br>always (superseded) | 0.614 → 0.757 | 0.838 → 0.871 | Salander's fortune 0 → 1<br>Blomkvist's media nickname 0 → 1<br>Cecilia: event that changed Harriet 0 → 1<br>affair 0 → 0.5<br>table salt 0.5 → 1<br>Niedermann's pain 0.5 → 1<br>Dag Svensson's murderer 0.5 → 1<br>prison sentence 0.5 → 1<br>Martin Vanger 0.5 → 1<br>Armageddon shirt 0.5 → 1 | Berger's position 0.5 → 0<br>who killed Harriet 0.5 → 0<br>who tried to shoot Mikael 0.5 → 0 | 88d26af |
| 2026-10-14 | Paragraph merging,<br>tuned prompts | 0.529 → 0.614 | 0.848 → 0.838 | Mona Lisa 0 → 1<br>Fiskargatan doorplate name 0 → 1<br>Harriet flees to 0 → 1<br>Dag Svensson's murderer 0 → 0.5<br>who killed Harriet 0 → 0.5<br>who tried to shoot Mikael 0 → 0.5<br>police after assault 0.5 → 1<br>Henrik hires Blomkvist 0.5 → 1 | table salt 1 → 0.5<br>Berger's position 1 → 0.5<br>Salander's fortune 0.5 → 0<br>affair 0.5 → 0<br>Bjurman demand — → 0 (not scored before) | 7224441 |

Each row compares the round's defaults against the defaults it replaced: 2d7b030 is measured against 7224441's
defaults (0.614), not against 88d26af, whose defaults it reverted. The correctness judge is noisy on reworded answers
(identical answers have scored 0 and 1 in different runs), so single 0.5 steps in rows without a repeat run are
weak evidence.

## 2026-10-15 — Completed names score the wider pool (31b95f1)

**Target:** "What was the nickname of Mikael?" (item 58343746, added to the Langfuse dataset on 2026-10-15; dataset now
36 items), scored 0: the answer said the evidence mentions no nickname.

**Diagnosis:** retrieval and reranking, caused by the bare first name. The books call him "Blomkvist"; the answer
passage ("nicknamed Kalle Blomkvist ... to his dismay") ranks >250 for every generated query, and the cross-encoder
scores it -6.47 against the question as asked but 6.9 against "What was the nickname of Mikael Blomkvist?". The
existing opt-in name completion produces that wording, but it only appended the completed search's top 5 hits (the
passage is 14th) and changed the fused evidence of the 7 questions it completes.

**Tried (offline replay of exp64/exp65 queries, `data/tuning/name_sim.py`; replay reproduces both with 0 diffs):**
- Scoring all candidates against the completed wording, or the max of both wordings: target not fixed, evidence
  changes on 5–7 items.
- Fusing the completed search into the wider pool by RRF: the passage appears in one ranking only and drops out.
- Adding the completed search's hits to the wider pool, scored against the completed wording: passage at E1, but
  completed-wording scores run higher overall, so 35–46 passages were admitted. Measuring the admission bar on the
  same wording (best fused candidate scored against the completed question) cut this to 6–9, mostly off-topic.

**Change:** `name_completion` on by default. The completed search does not enter fusion; its hits join the wider
pool, which is scored against the completed wording, and an admitted passage must also beat the best fused candidate
scored against it. At most `wide_max_hits` (3) passages are admitted; 3 is the most any question admitted before, so
the cap alone changes no evidence (checked offline). Fused candidates, their scores and the usual evidence are as
before.

**Result:** exp66 (full dataset, no config) and exp67 (repeat of the 4 changed items): correctness 0.708 → 0.722,
citation 0.861 → 0.861, 0 failures. Target 0 → 0.5 in both runs ("Kalle" [E1]; the judge wants the origin and his
reaction too). 32 answers byte-identical; Cecilia (1.0), savior complex (0.5) and who tried to shoot Mikael (0.5)
changed wording but kept their scores in both runs.

**Follow-up, rejected (not committed):** the origin of the nickname is in the passage just before the admitted one.
- Adding that preceding passage (same EPUB section) to each admitted passage, separately or joined into one
  passage: the evidence then held the origin, but the answer model still wrote one line under "Keep the answer
  concise". Joined (exp69, full dataset): target 1.0 once, then 0.5 in two repeats (exp71a/b); savior complex
  citation 1.0 → 0.5 in all three runs (the joined context added a "Practical Pig complex" line that the model
  over-read).
- Answer prompt "keep it concise, but include the context the evidence gives (origin or cause, reactions)"
  (`rag-answer` v11, label `tuning9`), with the joined passage (exp70): target 1.0 but 0.708 → 0.681, 6 items
  dropped (Zalachenko, Salander's fortune, Dag Svensson's murderer, police after assault, Henrik hires Blomkvist,
  Blomkvist's conviction). The production prompt is unchanged.

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
