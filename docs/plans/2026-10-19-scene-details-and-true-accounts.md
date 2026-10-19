# Scene details and true accounts: the next fix round (2026-10-19)

## Why

Across the three additional datasets, 14 of 51 items score below 0.6 with the local fact judge. Five of those 14 fall
into two patterns this round should fix. Two of the five turned out to be **fact issues** while writing this plan (the
corpus does not state the quoted line as speech), so the fixable target is three items plus a decision on those two
facts:

| Dataset | Item | Question | Score | What the answer must contain |
|---|---|---|---:|---|
| Additional Questions | `e43e2f16` | What did Salander said when she saw Mikael in the kitchen, when she was severely wounded? | 0.00 | **fact issue:** she said "Kalle Fucking Blomkvist"; she let go of the gun |
| Additional Questions | `45d561b9` | When Mikael found Salander severely wounded on the kitchen bench at Gosseberga, he loosened the gun from her hand. And then what did she say? | 0.00 | **fact issue:** she said "Kalle Fucking Blomkvist"; she let go of the gun |
| Additional Questions | `36c50723` | What happened to Salander in the abandoned factory? | 0.275 | She confronted Niedermann at the brickworks and nailed his feet to the floor with a nail gun |
| set3 | `cf527045` | How Gottfried really died? | 0.025 | Harriet killed him by drowning; officially a drunken accident; he had raped her and tried to strangle her; she held him under with an oar; Martin saw it |
| set3 | `db4076fd` | How Gottfried died? | 0.50 | Gottfried drowned; Harriet drowned him (not just an accident) |

The other nine sub-0.6 items are out of scope here: two broad/summary questions ("top 10 characters", "summary of the
first book"), "Christmas present for Mikael", "phone numbers in Harriet's diary", "why Blomkvist agreed to work for
Vanger", "nicknames", "Harriet's escape details", "Berger's position" and "the cat in the crypt". They are different
failure modes (scope, one detail, or judge strictness) and should not be mixed into this round.

## What the corpus offers (measured, not assumed)

The evidence for all five exists. The failures are retrieval depth and query angle, not missing text.

**The kitchen quote.** `2e3b810e` (Hornet's Nest, ch. 3, p89) is Salander in the ICU remembering the moment:

> "Suddenly she remembered having seen Kalle Fucking Blomkvist. Perhaps she had dreamed the whole thing, but she
> remembered a kitchen—it must have been the kitchen in the Gosseberga farmhouse—and she thought she remembered seeing
> him coming towards her."

`search_scenes` with the question text ranks the correct memory scene **2nd at 3.08**; the top scene (3.66) is
Salander telling Frode what happened, and its first four 110-character snippets do not include the quote. The agent
read other passages and abstained. So the scene finder works, but the agent cannot see the passage that matters:
`search_scenes` returns only the first four members with 110 characters and no scene id.

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

**The quote is a fact issue, not a retrieval failure.** We searched the corpus for the line: "Kalle Fucking Blomkvist"
appears five times (`2e3b810e`, `6aee7120`, `1024405d`, `22b78edc`, `2a558137`), never as dialogue in the Gosseberga
kitchen. `2e3b810e` is the closest: Salander in the ICU *remembering* having seen him in the kitchen. No passage says
she said it. The reference is paraphrasing the memory (or comes from outside the corpus). The honest fix is to change
the expected fact to "she remembered seeing Kalle Fucking Blomkvist in the kitchen" (which `2e3b810e` states), or to
accept the memory as the answer; the agent should not be taught to invent a quote. This is a dataset decision, not a
code change; the two items are therefore removed from the fixable set below.

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

1. **Settle the quote question (done).** The line is never dialogue; only the ICU memory `2e3b810e` states it. Change
   the expected facts for the two Additional Questions items to the memory, or mark them not applicable; do not add a
   quote-invention rule to the agent.
2. **Measure candidate tools offline** on the three fixable items (scripts in `data/tuning/agentic/`):
   - `true_account("Gottfried Vanger", "drowned")`: does it reach `8516c2bb` and the 6.84 reveal scene?
   - `true_account("Niedermann", "nail gun")` for the factory.
   - `search_scenes(query, full=True)` / `read_scene` on the Gottfried reveal scene and the factory confrontation:
     do the later members carry the detail the agent misses today?
   - The moment tool is still worth testing on the kitchen questions even though the fact is wrong: with the memory
     as the expected answer, does `scene_moment` return `2e3b810e`? If yes, the tool is still useful for other
     detail-at-a-moment questions.
   Record top-k, scores and blast radius (how many of the other 46 items change).
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

- The three fixable items (`36c50723`, `cf527045`, `db4076fd`) score **≥ 0.9**.
- The two quote items are re-scored against the memory fact or marked not applicable; if the fact is changed, the
  agent's answer that cites `2e3b810e` scores 1.0.
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
- **Data issues.** The kitchen quote and the Amazon location are references that may not be directly in the corpus.
  Fix the evaluation facts if the text does not support them; do not teach the agent to invent quotes.
- **Rollback.** The changes are in `app/agent.py` tools and prompt; the fixed engine and the current agent defaults are
  untouched. If regressions appear, keep the tools but leave them out of the default prompt (`AGENT_*` switch), or
  revert the commit.

## Open questions

1. ~~Is "Kalle Fucking Blomkvist" spoken in the Gosseberga kitchen scene?~~ **Resolved:** no; only the ICU memory
   `2e3b810e`. The two items are fact issues.
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
  and that `find_connections` does not expose the Gottfried reveal. Confirmed that the quoted line is never speech, so
  the two Additional Questions items are fact issues; the fixable set is three items. Next: run step 2.
