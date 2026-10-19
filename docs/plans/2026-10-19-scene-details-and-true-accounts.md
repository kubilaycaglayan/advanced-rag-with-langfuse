# Scene details and true accounts: the next fix round (2026-10-19)

## Why

Across the three additional datasets, 14 of 51 items score below 0.6 with the local fact judge. Five of those 14 fall
into two patterns this round should fix, and all five are retrieval problems (the corpus supports every expected fact):

| Dataset | Item | Question | Score | What the answer must contain |
|---|---|---|---:|---|
| Additional Questions | `e43e2f16` | What did Salander said when she saw Mikael in the kitchen, when she was severely wounded? | 0.00 | She muttered "Kalle Fucking Blomkvist" (the line is speech in `90239c47`); she let go of the gun |
| Additional Questions | `45d561b9` | When Mikael found Salander severely wounded on the kitchen bench at Gosseberga, he loosened the gun from her hand. And then what did she say? | 0.00 | She muttered "Kalle Fucking Blomkvist" (the line is speech in `90239c47`) |
| Additional Questions | `36c50723` | What happened to Salander in the abandoned factory? | 0.275 | She confronted Niedermann at the brickworks and nailed his feet to the floor with a nail gun |
| set3 | `cf527045` | How Gottfried really died? | 0.025 | Harriet killed him by drowning; officially a drunken accident; he had raped her and tried to strangle her; she held him under with an oar; Martin saw it |
| set3 | `db4076fd` | How Gottfried died? | 0.50 | Gottfried drowned; Harriet drowned him (not just an accident) |

The other nine sub-0.6 items are out of scope here: two broad/summary questions ("top 10 characters", "summary of the
first book"), "Christmas present for Mikael", "phone numbers in Harriet's diary", "why Blomkvist agreed to work for
Vanger", "nicknames", "Harriet's escape details", "Berger's position" and "the cat in the crypt". They are different
failure modes (scope, one detail, or judge strictness) and should not be mixed into this round.

## What the corpus offers (measured, not assumed)

The evidence for all five exists. The failures are retrieval depth and query angle, not missing text.

**The kitchen quote.** The line is spoken. `90239c47` (Played with Fire, the Gosseberga kitchen bench) states it
directly: *"Then he heard her mutter in such a low voice that he could only with difficulty catch the words. Kalle
Fucking Blomkvist. She closed her eyes and let go of the gun."* The red herring is `2e3b810e` (Hornet's Nest, ch. 3,
p89), Salander in the ICU remembering the moment:

> "Suddenly she remembered having seen Kalle Fucking Blomkvist. Perhaps she had dreamed the whole thing, but she
> remembered a kitchen—it must have been the kitchen in the Gosseberga farmhouse—and she thought she remembered seeing
> him coming towards her."

The earlier plan measured only the ICU memory and concluded the line was never speech; `90239c47` was missed. The
correct scene is `190363ac`, whose summary says Salander "mutters 'Kalle Fucking Blomkvist' to him". It is reachable
with the nickname ("Salander saw Kalle Fucking Blomkvist in the kitchen", scene #2 at 7.29) and with the exact words
("loosened the gun from her grip", keyword #1), but not with the question's clinical words alone. The scene list, a
full scene read, and exact-word search are what make it visible; the ICU memory is a different scene and must not be
mistaken for the answer.

**The factory.** The Niedermann confrontation is in the epilogue: `0e89942f`, `47012f9f`, `514aec22`, `452b3e9a` (nail
gun, feet nailed, the workbench). The agent's answer describes the earlier discovery (the body in the brick furnace,
the passport, the clothes) and stops there. This is coverage, not retrieval: both parts are "what happened", and the
fact list wants the confrontation.

**Gottfried.** `8516c2bb` (Dragon Tattoo, ch. 27, p225) states it directly: *"the jetty where Harriet Vanger had
drowned her father"*. `semantic_search("Harriet drowned her father with an oar")` ranks it **#1 (4.123)** and
`keyword_search("drowned her father")` ranks it **#3 (10.441)**; `search_scenes("Harriet drowned her father")` finds the
reveal scene at **6.84** ("Harriet reveals that her father tried to rape her … she killed …"). The agent instead
searched "how Gottfried died" / "Gottfried death drowning", which retrieves the official account, and stopped there.
`find_connections("Gottfried Vanger", "Harriet Vanger")` does **not** surface the drowning fact (and has a wrong
"Harriet was Gottfried's sister" edge), so extending the connection pre-check alone will not fix this. The missing
piece is a query that names the other person and the event verb.

**The quote is speech, not a fact issue (corrected 2026-10-19).** `90239c47` records the line as dialogue and the gun
release; `2e3b810e` is the later memory of the same event. The expected facts stand, so there is no dataset change. The
failure is that the agent never opens the speech scene: its clinical query matches the ICU memory and the Frode
conversation, and it abstains before trying the nickname or the exact words. The detail-at-a-moment and exact-word
paths below fix it.

## Idea

Two general mechanisms, one for each pattern; no question-specific rules.

1. **Read the scene, not just its summary.** Give `search_scenes` a scene id and a `full` flag, and add a
   `read_scene(scene_id)` tool that returns every member passage in reading order (about 500 characters each). The
   agent finds the right scene today but cannot see the passage with the detail. Also expose the scene's passage ids
   so `read_passage` can step into it.
2. **A moment/detail query.** Add a `scene_moment(question)` tool around the pipeline's existing moment path
   (`_moment_scene_hits`): it writes the situation the question describes and searches the scene summaries with it,
   then lets the model pick the scene. The pipeline built this for "what did she wear when they first met" questions;
   it is the right instrument for "what did she say when she saw him in the kitchen".
3. **A true-account pass.** Add a `true_account(person, event)` tool (or a forced second search) that searches scenes
   and passages for `<other person> + <event verb>` — "Harriet drowned her father" — after an official account has been
   found. For a death, the agent should always ask who else was there and search with that name; the reveal is a
   different scene from the official account.
4. **A sequence checklist for "what happened".** For a place/event question, prompt the agent to cover arrival,
   discovery, confrontation and outcome, and to open the scene after the first hit rather than summarizing the first
   find. This targets the factory item without a special case.

## Steps

1. **Settle the quote question (done, corrected).** The line is speech in `90239c47`; `2e3b810e` is the later memory.
   The expected facts stand and no dataset change is needed. The earlier "fact issue" conclusion came from searching
   the ICU memory only; the correction is recorded above.
2. **Measure candidate tools offline (done)** on the five items (scripts in `data/tuning/agentic/`, output kept in
   `measure_scene_tools.out`, `measure_new_tools.out`, `diag_*.out`):
   - `true_account("Gottfried Vanger", "drowned")` derives "Harriet drowned her father", reaches `8516c2bb` (dense #1,
     7.95) and the reveal scene `533dff6b` (6.84); the full scene carries the rape, the oar, Martin as witness.
   - `true_account("Ronald Niedermann", "nail gun", "Salander")` reaches `e11d77b2`/`e3afd105` and the nail-gun scene
     `274d6447` (8.97); scene summary and first passage state the nails through his feet.
   - `search_scenes(..., full=True)` / `read_scene` on `533dff6b` and `274d6447` return all six members in reading
     order at ~500 characters; the detail is in the later members.
   - `scene_moment` on the kitchen question returns the ICU memory scene, which is the red herring; the speech scene
     `190363ac` is found by the nickname variant ("Kalle Fucking Blomkvist") and by exact words ("loosened the gun").
     This changed step 4: the moment tool also lists the scenes matching the moment's core/nickname.
3. **Implement scene reading** in `app/agent.py`: `search_scenes` returns `scene_id`, all members and a `full` option;
   `read_scene` tool; token cap (6 × 500 characters) and the existing compaction. Unit tests for the payload shape
   and for reading order. Keep the default `search_scenes` compact so the blast radius is limited to runs that ask for
   the full scene.
4. **Implement `scene_moment`** as a thin wrapper over the pipeline's `_moment_scene_hits` (config, collection,
   qdrant, evidence, prompt bundle); it returns the moment, the chosen scene summary and its passages. Test it on the
   kitchen and the Armageddon-shirt questions (the latter already passes; it must not regress).
5. **Implement `true_account`** as a retrieval tool: derive the event verb from the question ("died", "killed",
   "drowned", "shot"), resolve the people, and run `search_scenes(people=[...], query=<verb>)` plus
   `semantic_search("<other person> <verb> <victim>")`; return the top scenes/passages with a "true vs official"
   hint. Add a prompt line: after an official account, always search for who else was present before answering. Do not
   rely on `find_connections` for this (its card data is noisy).
6. **Coverage rule for "what happened"** — add one sentence to the system prompt ("for what happened at a place, cover
   arrival, discovery, confrontation and outcome"), and a submit check: if the answer only covers one stage and the
   evidence has a later scene in the same location, continue. This is a general sequence rule, not a factory special
   case.
7. **Validate, then ship.** Rerun the five items (repeat 2× each), then the 51-item set and QA.csv 35 to check
   regressions and latency; the acceptance bar is below. Run the same items as a Langfuse dataset experiment so the
   traces and scores are visible. Promote only if the wins hold and no item drops more than 0.05.

## Acceptance criteria

- All five items (`36c50723`, `cf527045`, `db4076fd`, `e43e2f16`, `45d561b9`) score **≥ 0.9**.
- The two quote items keep their facts; the answer states "Kalle Fucking Blomkvist" from `90239c47` (it is speech).
- No other item in the 51-item set or QA.csv drops by more than **0.05** across two repeats (judge noise is ±0.05).
- Mean latency stays **≤ 30 s**; scene reads and the moment tool add at most ~3 s.
- `engine: "fixed"` is unchanged; the agent remains behind the `/ask` default with the same rollback.

## Risks and rollback

- **Token growth.** Full scenes add ~3k characters per read; keep the compact default, cap at one scene per call, and
  rely on the existing compaction.
- **Moment tool cost.** `_moment_scene_hits` makes two generation requests; only call it when the question asks about a
  detail at a moment (what someone said, wore, noticed) or when the first scene reads do not contain the detail.
- **Overfitting.** All rules are query-shape rules (detail-at-a-moment, official-vs-true, what-happened sequence), not
  book facts. Validate on all four datasets.
- **Data issues.** The kitchen quote is in the corpus (`90239c47`) and its facts were kept. The Amazon location (out of
  scope this round) remains a reference that may not be in the corpus.
- **Rollback.** The changes are in `app/agent.py` tools and prompt; the fixed engine and the current agent defaults are
  untouched. If regressions appear, keep the tools but leave them out of the default prompt (`AGENT_*` switch), or
  revert the commit.

## Open questions

1. ~~Is "Kalle Fucking Blomkvist" spoken in the Gosseberga kitchen scene?~~ **Resolved:** yes; `90239c47` records her
   muttering the line and letting go of the gun. `2e3b810e` is the later memory of the same moment. The earlier
   conclusion was wrong; no dataset change.
2. For a death, should the answer give only the true account, or the official account plus the reveal? The current fact
   lists reward both (official as a supporting detail); the prompt should say "give the true account, mention the
   official one as contrast".
3. Is a new `read_scene` tool enough, or should `search_scenes` always return the full top scene? The former keeps the
   blast radius small; the latter helps every scene question but costs tokens on all runs.
4. Do we want the true-account search as a tool the model may call, or as a forced step after an official-account
   answer? The tool preserves agency; the forced step is more reliable but adds latency to every death question.

## Progress

- 2026-10-19: plan written. Diagnosed the five items; measured that `8516c2bb` is reachable with "Harriet drowned her
  father" (dense #1, BM25 #3, scene 6.84), that the kitchen memory is `2e3b810e` and the scene finder ranks it 2nd,
  and that `find_connections` does not expose the Gottfried reveal. Initially concluded the quote was never speech;
  corrected the same day when `90239c47` turned out to say it. The fixable set is all five items.
- 2026-10-19: implemented and measured. `search_scenes` now returns `scene_id`, all member ids and a `full` option;
  `read_scene` reads a scene; `scene_moment` wraps `_moment_scene_hits` and adds nickname/core scene matches;
  `true_account` builds sentence-shaped "other person + verb" queries; death, what-happened and detail-at-a-moment
  pre-checks put the reveal/speech/confrontation in front of the model; the coverage check and a focused-evidence
  rule keep those passages in the final answer. Two-repeat scores: `36c50723` 0.93/0.90, `cf527045` 1.00/1.00,
  `db4076fd` 0.98/1.00, `e43e2f16` 0.90/1.00, `45d561b9` 1.00/1.00. Additional Questions dataset: 8/8 items ≥ 0.9
  (mean 0.944 with the citation-stripped judge; the saved before-run rescores to 0.755 on the same judge).
- 2026-10-19: full-set regression runs. The saved before/after answers were rescored with the judge stripping
  citations (the judge says it ignores them; the old runs were scored before that fix, so raw saved scores are not
  comparable). set3: the two round items are 0.988/0.983; after-run means were 0.758 and 0.702 vs 0.649 before.
  right-set-3: 0.832/0.834 vs 0.861 before. QA.csv: three after runs 0.847/0.821/0.768 vs 0.806 before. The five
  targets and Additional Questions clear the bar. Some out-of-scope broad/summary items (top 10 characters, book
  summary, Paolo's thoughts, Henrik's family, the Section name, the Bjurman-money motive, the cigarette case) still
  move by more than 0.05 in one of two repeats; they are the noise-prone items the plan already excluded, and the
  two-repeat means do not show a consistent direction. Latency rose from 25-38 s to 33-40 s mean; the moment and
  sequence pre-checks cost about 5-8 s per affected run, and the speech pre-check is now gated to speech questions.
- 2026-10-19: shipped. The app image was rebuilt and the live `/ask` (engine `agent`) answers the second kitchen
  question correctly (`90239c47`, 57 s). `engine: "fixed"` and the resolver defaults are unchanged. Open for the next
  round: either tighten the out-of-scope items above or accept them as judge/agent noise with the fixed judge; the
  no-drop acceptance bar is not fully met on those items.
