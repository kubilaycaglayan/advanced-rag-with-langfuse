# Entity cards: an index of named things and how they relate to the characters

Status: prototype (offline), agreed 2026-10-16. Run the full datasets only once retrieval on the targets is clearly better.

## Why

"What is Salander's fake identity?" (Additional Questions ba2fffee) fails on recall. The books never call Irene Nesser,
Monica Sholes, Wasp or V. Kulla Salander's "fake identity"; each is stated once, in a passage that says "she", in
other words ("under the name of", "known online only as", "the nameplate"). MiniLM (dense and cross-encoder) cannot link
the two. The scene summaries showed that text which names the person and states the fact outright scores well
("Salander ... adopt the identity of Monica Sholes" 2.73 vs about −11 for the passage). Many failing questions share
this entity–attribute shape (T-shirt slogan, doorplate name, nicknames, cigarette case, Salander's mother).

Plain NER is not enough: it tags "Irene Nesser" as a person and does not say she is Salander's identity.

## Design

1. **Extraction (index time, gemma4:26b, per scene window).** For each window, a JSON list of entities: name as
   written, open type (person, alias, nickname, handle, place, company, vehicle, brand, clothing, tattoo, object, …),
   the person it belongs to or names (`of`, full name, pronouns resolved from the excerpt), the relation
   (`false identity`, `nickname`, `owns`, `wears`, …) and one short fact from the excerpt, with the window's passages.
2. **Merge (per entity, across the books).** Group mentions of one entity (case, possessives, a surname alone when it
   is unambiguous), keep its types, relations and facts with mention counts and source passages. Relations are edges
   between entities, so a person collects every name linked to them (Salander → Wasp, Irene Nesser, Monica Sholes,
   V. Kulla; Mikael Blomkvist → Kalle Blomkvist), and one nickname can link to several people.
3. **Cards.** One card per entity (what it is, whose it is, how it is used), and one line per edge
   ("Irene Nesser — false identity of Lisbeth Salander: …"). Embedded like the scene summaries.
4. **Retrieval.** Search cards and edges with the question (dense + cross-encoder). A matching edge or card brings its
   source passages, and an anchor entity in the question (Salander) can follow its edges to the linked entities.
   An admission rule like the other paths is needed before anything enters the evidence.

## Prototype steps

1. Extract over *The Girl with the Dragon Tattoo* and *The Girl Who Played with Fire* (whole books, no cherry-picked
   windows), non-overlapping windows. Cache the raw JSON.
2. Merge; inspect the Salander, Mikael Blomkvist and alias entries by hand (wrong links, e.g. the summaries' "Irene
   Nesser, a blond woman").
3. Measure: rank of the cards/edges for the four aliases for "What is Salander's fake identity?", then the nickname
   and doorplate questions. No answer-model runs until the ranks are good.
4. If good: extract the third book, design admission, run the target, then QA.csv and Additional Questions.

## Risks

- One window often cannot tell an alias is the protagonist; the merge step must combine evidence across mentions.
- Fixed type lists miss things; types stay open.
- Build cost about the scene summaries' (hours with gemma4:26b); never while experiments use Ollama.

## Where it sits in the pipeline

- **Index time (`/index`):** after the passage and scene-summary indexes, the same scene windows go through entity
  extraction (gemma4:26b) and the merge; cards and edges are cached (JSONL) and embedded into their own Qdrant
  collection, built once per passage index, then the model is unloaded.
- **Question time:** an entity path after reranking, beside the wider-pool and keyword paths: (a) names in the question
  (Salander) → the edges pointing to that entity, reranked against the question; (b) dense search of all cards and
  edges. The best ones bring their source passages in front of the evidence. The answer model still reads and cites
  book passages, never cards. Admission rule to be designed from the offline ranks (questions that work today should
  keep their evidence).

## Progress notes

### 2026-10-16

- **Diagnosis** (`data/tuning/LOG.md`, scripts in `data/tuning/scripts-2026-10-16-fake-identity/`): the target abstains;
  its only confident passage is off point ("individuals whose identity she had stolen", 3.69). The alias passages rank
  36–4,300 in dense search. "as fake as Monica Sholes' identity" is BM25 #2 and the reranker's best (5.32), but the
  keyword path needs best + 4.0. "rent a car in Irene Nesser's name … the fake identity" is BM25 #1 but scores −7.16
  (merged with a motorcycle paragraph, and the name is in another sentence than "fake identity").
- **Recall, not ranking, is the gap:** the current reranker would put Sholes (5.32), Nesser ¶40 (0.31) and Wasp
  (−0.36) in the top 10 if they were candidates; Kulla (−2.05) just misses.
- **Tried and dropped:** LLM "facet" rewrites (qwen3:8b invents names, makes Salander "he", leaks prompt examples);
  BM25 rankings inside RRF (single-list hits never reach the 30 candidates); summary-pooled passages (gold passages in
  the pool, but MiniLM prefers other "Salander + identity" passages); bge-reranker-v2-m3 (ranks all four aliases above
  the off-point passage, but CPU-only here: 12–44 s per question, and the Wasp/Kulla passages still never reach the pool);
  qwen3:8b has no knowledge of the aliases (lists "Lisbeth Salander" eight times).
- **Implemented, opt-in, uncommitted:** `keyword_rare_share` (default null). A keyword hit with one sentence holding every
  content word of the question that is not a name and occurs in < 1% of passages (two or more such words) is added in
  front of the evidence at any score, not joined with the passage before it. Target: Nesser (¶55–56) and Sholes (¶56)
  now in the evidence; the answer still names only Monica Sholes. Offline it fires on 0/36 QA.csv items and 2/7
  Additional Questions ("severely wounded", "abandoned factory"). 66 tests pass. The regression batch was stopped at the
  user's request after the control run (exp121); retrieval comes first.
- **Decision (user):** fix retrieval first with this entity-card index; no full-dataset runs until retrieval on the
  targets is clearly better.
- **Extraction** (`data/tuning/scripts-2026-10-16-entity-cards/extract.py`): non-overlapping 6-passage windows,
  gemma4:26b, JSON mode, ~10–13 s per window; *Dragon Tattoo* + *Played with Fire* = 611 windows (~2 h), running.
  The prompt was tightened after a trial (skip ordinary objects and unnamed people). Early output already links
  `Wasp → online handle of Salander` ("Salander was known online only as Wasp").
- **Merge** (`merge.py`): names grouped by normalised form, a one-word name joins the multi-word proper name most of its
  pairings use (Salander → Lisbeth Salander; descriptions like "Salander shirt" excluded), `of: unknown` and self-links
  dropped. Known issue: Wasp Enterprises (her company) typed as a false identity.
- **Next:** when extraction finishes, `eval.py` measures the ranks of the four aliases' cards/edges for the target
  (direct search and via the Salander anchor), then the nickname and doorplate questions.
- **First ranks (100/606 windows, *Played with Fire* opening; MiniLM only).** Direct search of cards and edges: the Irene
  Nesser card is #1 (6.72) and its edge #2. Via the Salander anchor (159 edges): Irene Nesser #1, Wasp #5/#7, V. KULLA
  #9 ("nameplate on Salander's apartment"). Sholes's chapter is not extracted yet. Noise: windows type unrelated names
  as "false identity" (Palmgren's foster daughter 5.69, Dr. Johansson); counting mentions across windows should help.
  Merge fix: only person names join a longer name (Wasp had been folded into Wasp Enterprises).
- **Full *Played with Fire* (329 windows).** Salander now has 351 incoming edges, so single-edge reranking loses Wasp and
  V. Kulla below noise ("Palmgren's foster daughter", "Superintendent Douglas Skiöld"). New **group step (C)**: the
  extraction prompt's own category, *the names a person goes by* (types/relations with identity, alias, nickname,
  handle, pseudonym, name on a door …), forms one class. When the best anchor edge is in it, every edge of that class
  into the anchor is returned, ordered by how many windows state that link. Filters: the name must be a proper name
  (drops "terminator mode", "world-class hacker"), must not contain the person's own name (Fröken Salander), and class
  membership comes from the types of the mentions behind that edge (entity-level types let Miriam Wu and Zala in).
  Result: Wasp #1, Sally #2, Irene Nesser #3, V. Kulla #4 of 14 (Sholes's book still extracting).
- **Group → passages.** For each of the first N entities of the group, the passage of its edges' windows that names
  it and scores best against the edge text ("Wasp — online name used by Salander") becomes evidence. Picks: Wasp → PwF
  ¶24 "known online only as Wasp"; V. Kulla → PwF ¶2 "read V. KULLA … Villa Villekulla"; Irene Nesser → PwF ¶70.
- **Both books extracted** (611 windows, 6,151 s ≈ 10 s/window; 8,843 mentions → 2,790 entities, 2,115 edges).
  Target, offline: all four aliases lead Salander's other-names group (Wasp #1, Irene Nesser #2, Monica Sholes #3,
  Sally #4, V. Kulla #5 of 18), and the passages picked are exactly the ones that state them (PwF ¶24 "known online
  only as Wasp"; DT ch29 ¶51 "under the name of Irene Nesser … Norwegian passport"; DT ch29 ¶56 "as fake as Monica
  Sholes' identity"; PwF ¶2 "read V. KULLA … Villa Villekulla"). **Retrieval goal for the target met offline.**
  Next: offline check of what the path would do on the other questions (no pipeline change yet).
- **Offline blast radius (all 44 recorded questions, `eval_all.py` → `eval_all.out`).** First version fired on 5: the
  target, the doorplate question, both Mikael-nickname questions, and falsely on "Who tried to shoot Mikael?" (best edge
  1.15). Kalle Blomkvist was missing (own-name filter dropped names sharing the surname) and "Christer Malm — nickname
  of Mikael" got in on its relation wording alone. Fixes: the best edge must be a confident match (≥ 2.0, the
  pipeline's `low_confidence_score`); group membership from the mention *types* only; exclude only names made of the
  person's own name parts; the entity the question matched best leads the group. Now fires on **4/44**, all name
  questions: target (Irene Nesser first, plus Wasp, Monica Sholes, V. Kulla), doorplate (V. Kulla first), both nickname
  questions (Kalle Blomkvist first). Evidence for the other 40 is unchanged by construction. Remaining noise: "Fröken
  Salander" (a greeting typed as a false identity).
- **Next:** opt-in pipeline hook reading the prototype cards; run only the 4 affected items end to end.
- **Pipeline hook (opt-in, uncommitted):** `entity_names` (default false) with cards read from `ENTITY_CARDS`
  (prototype file `data/entity-cards.prototype.json`). Runs after the keyword path; its passages go in front of the
  evidence. It adds no LLM request (about 1.1 s of reranking on CPU). Tests: 67 pass.
- **Judged runs, affected items only.** exp124/exp125: target 0 → 0.5 (answer names Monica Sholes and Irene Nesser;
  the judge wants Wasp and V. Kulla too, which are in the evidence but the answer model leaves out). "What was the
  nickname of Mikael?" dropped 1.0 → 0.5, reproduced twice (exp126a/b): the extra nicknames (Micke, Practical Pig,
  Master Detective Blomkvist) changed the answer's wording although its evidence already named Kalle Blomkvist.
  **Fix:** add nothing when the evidence already names the best-matched entity (retrieval found it; this path is for
  recall failures). exp127/exp128: target 0.5; nickname, doorplate and media-nickname questions 1.0 / 1.0, path not
  fired (doorplate and media nickname: evidence and answer identical to exp119; nickname: evidence differs from exp119
  by run-to-run variation in the rewrites, path not fired).
- **Status:** retrieval goal for the target met (all four aliases in the evidence); no regression on the items the
  path can affect; the 40 other recorded questions are unaffected by construction (offline check).
  Limits: *Hornet's Nest* not extracted; cards built offline, not yet by `/index`; noise names in the group
  ("Fröken Salander", "Sally"); answer model lists only two aliases.

### 2026-10-17

- **Full-dataset check, `entity_names` on** (`data/tuning/scripts-2026-10-16-entity-cards/batch.sh`):
  exp129 QA.csv 0.736 / 0.875 vs exp119 0.736 / 0.875 — the path fired on no item; evidence and answers identical on
  35/36 (the other, "What was the nickname of Mikael?", got different query alternatives run to run; path not fired,
  1.0 both). exp130 Additional Questions 0.438 / 0.938 vs exp121 0.375 / 0.938 — fired only on the target
  (0 → 0.5); evidence and answers identical on the other 7/8. Latency +1.4 s mean. **No regressions.**
- **Answer step for the target.** The answer model named only two aliases although all four passages were in the
  evidence (they say "she" and never "identity"). Each entity passage now carries a `Link:` line in the evidence
  (the edge it was found by, e.g. "Wasp — alias used by Salander"). Two noise filters: a name made only of the person's
  own name parts and a title (Fröken Salander) is not another name; besides the best match, a name must be linked in at
  least two windows (dropped "Magnus", one window). exp131: all four named but Magnus/Sally extra (0.5); exp132: answer
  "Irene Nesser, Monica Sholes and Wasp … the nickname Sally … V. KULLA on her apartment door", 0.5 / 1.0 — the judge
  marks down Sally (a real nickname) and the V. Kulla wording; not tuned further (judge-fitting). These changes touch
  only entity passages, which appear only on the target, so exp129/exp130 stand for every other item. 67 tests pass.
- ***Hornet's Nest* extracted** (376 windows, 3,936 s); all three books: 14,581 mentions → 4,044 entities, 3,245 edges.
  exp133 QA.csv 0.736 / 0.875 (== exp119; path fired on "What media nickname…" adding "Kalle Fucking Blomkvist", answer
  identical); exp134 Additional Questions 0.438 / 0.938, only the target changed (0 → 0.5). Target evidence still holds
  all four aliases, but *Hornet's Nest* links **Plague** (her hacker friend) to Salander as a name in two windows, so he
  passes the two-window rule; the answer lists Irene Nesser, Monica Sholes, Wasp, Plague, Sally and drops V. Kulla.
- **Open:** keep other people out of a person's names (Plague is a person with his own links, Irene Nesser is not);
  the "already named" check should treat name variants as named (Kalle Fucking Blomkvist vs Kalle Blomkvist);
  build cards in `/index`; commit after review.
- **Other people kept out of a person's names:** an entity also linked to the person as a person by a relation that is
  not a name ("friend of", "contact of") is another person (Plague), whatever a window called it. exp135 (three books):
  answer "Irene Nesser, Monica Sholes, and Wasp … the nickname Sally and the name V. Kulla on her apartment door",
  0.5 / 1.0 (judge: Sally extra, purposes missing). exp136: the three QA.csv name questions 1.0 / 1.0 with answers
  identical to exp133. 67 tests pass. **Goal met: all four fake identities retrieved and named; no regressions on
  QA.csv or Additional Questions.**
- **2026-10-17, approved, built by `/index` and on by default.** `app/entities.py` runs the same extraction prompt
  (`entity_extraction_system`) and merge as the scripts; `/index` builds the cards when `entity_names` is on and
  `validate_index` refuses to answer without them. The 987 extractions were moved into the new cache
  (`/data/entities.jsonl`), so building them made no model call; the cards are identical to the prototype's (4,044
  entities, 3,245 edges, 138 joined names). `ENTITY_CARDS` is gone: the pipeline reads the cards of its passage index.
  exp137 (no config): target 0.5 / 1.0, same answer as exp135. All 86 tests pass.

