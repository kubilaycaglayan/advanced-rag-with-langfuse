# Entity matrix: use the entity cards from any end (2026-10-17)

## Why

`entity_names` (d5d9a70) only starts from a person the question names and only adds that person's other names. It
returns nothing for questions that name no one or ask about a kind of thing:

- "What are the nicknames used in the book?" (trace 3619600d…): no anchor → `[]`; answer "Kalle Blomkvist and Lovisa".
- "Are there any police officers with nicknames?" (trace 29877247…): no anchor → `[]`; answer "no police nicknames".

The cards hold the answers (Officer Bubble/Bublanski, Miss Marple/Modig, Herr Figuerola, Ricky, Zala, Mimmi, …).
Decision (user): use the entity matrix from every end — any entity, any kind — not special paths per question type.

## Idea

The cards are a matrix: **rows** are entities (with their card text), **columns** are kinds of link (the edge's type:
nickname, false identity, vehicle, tattoo, clothing, place, …), **cells** are edges ("Officer Bubble — nickname of
Bublanski"), each pointing to the passages that state it.

A question constrains one or more ends:

| Question | column | row constraint |
|---|---|---|
| What car does Blomkvist drive? | vehicle | Blomkvist (either end) |
| Who has a dragon tattoo? | tattoo | "dragon" (either end) |
| What is Salander's fake identity? | false identity / alias | Salander |
| Are there any police officers with nicknames? | nickname | people whose cards say police |
| What are the nicknames used in the book? | nickname | none (whole column) |

Answer cells = matched columns ∩ cells whose ends match the remaining constraints, ranked by how many windows state
them; each brings its best passage with a `Link:` line (as `entity_names` does).

Offline check (2026-10-17, before this plan): scoring every edge with both end cards against the question, no
anchor, already works for specific questions (car, tattoo, fake identity) but not set questions (police nicknames:
Curt and "the Firm" lead; book nicknames: "book" pulls in Pippi Longstocking). Hence matching the question's parts to
columns and rows separately.

## Steps

1. **Measure offline (no LLM):** column matching (question phrases ↔ edge type labels, MiniLM similarity), row
   matching (names via the existing anchors; other words via card text), intersection, ranking; on the five questions
   above, the QA.csv and Additional Questions sets (how many does it fire on — blast radius).
2. **General noise rule:** a cell whose name is part of the other end's own name (Curt/Andersson, Sonja/Modig) or a
   title plus it is the same entity; cells stated in one window only count after cells stated in two or more.
3. **Pipeline path** behind a new flag `entity_matrix` (default off; off = identical to today). When on it runs
   after the `entity_names` path, only when that adds nothing (see Progress). Tests.
4. **Validate:** targets, then QA.csv and Additional Questions vs the current defaults. Turn on by default only with
   no regressions and the user's approval.

## Progress

- 2026-10-17: plan written.
- **Step 1, offline (scripts-2026-10-17-entity-matrix/: columns.py, match.py, decompose.py, fullfacts.py, probe.py,
  blast.py).** Columns: question phrases (1–2 content words, "in the book(s)" scope removed) vs the 55 edge type labels,
  MiniLM cosine ≥ 0.75 ("nicknames"→nickname 0.94, "car"→vehicle 0.88, "fake identity"→false identity 0.83,
  "tattoo"→tattoo 1.0). Named entities expanded to their name variants (Blomkvist, Mikael, Mikael Blomkvist are split
  by the merge). Residual words are scored against each end's facts; with cards holding only 4 facts the police
  question failed (Modig's card had nothing about police), with all facts the cross-encoder's best fact separates
  police ends (Bublanski 3.2, Modig 3.7, Figuerola 3.6) from others (≤ −1.3). Residual alone fails "dragon" (0.28);
  residual + column word ("dragon tattoo") 6.4, so each end takes the better of the two.
- **Noise rules (general):** a cell from part of the other end's own name or a title (Curt → Curt Andersson); a
  one-word name that is part of another person's full name; one window's claim about an entity the cards otherwise
  treat as a person of its own (≥ 20 mentions, mostly typed person: Dragan Armansky, Jerker Holmberg as "nicknames"
  of Bublanski). Real one-window names (Miss Marple, 1 mention) stay.
- **Step 2/3, pipeline (`entity_matrix`, default off; `entity_matrix_similarity` 0.75, `entity_matrix_max_hits` 8).**
  Runs after `entity_names` and only when that adds nothing (a named person's other names stay its case: it keeps
  V. Kulla, which no column of "fake identity" reaches). Cards now keep all facts and their types (index-time, no
  LLM: rebuilt from the cache). Gates: whole column needs a cell stated in ≥ 2 windows; other cases a cross-encoder
  score ≥ `low_confidence_score`; nothing when the evidence already names the best cell or, for a named entity, any
  confident cell (whitespace-normalised). Cells stated in ≥ 2 windows rank first; one passage per name, `Link:` line.
- **Blast radius on recorded evidence (exp146 AQ, exp147 QA.csv):** fires on 1 of 43 items — the second Armageddon
  question, whose evidence lacks the slogan (its citation scored 0.0); 2 items go to `entity_names` as before.
- **Targets end to end (answers.py, local prompts):** police nicknames "no nicknames" → Bubble, Officer Bubble, Miss
  Marple (Modig); book nicknames 3 (one wrong) → Ricky, Zala, Micke, Mimmi, Kalle Blomkvist, Bubble, Magge Lundin;
  fake identity, car and dragon tattoo answers unchanged (car: a misread "Japanese toy car" was added until the
  named-entity rule above). 78 tests pass.
- **Step 4, validation (`{"scene_context": true, "entity_matrix": true}` vs the current defaults' runs).** exp150
  Additional Questions 0.562 / 0.938 (== exp146; only the fake-identity evidence differs, from the rebuilt cards; same
  answer and scores). exp151 QA.csv 0.708 → 0.694 / 0.861 → 0.861: evidence identical on 35/36; the one changed item
  is the second Armageddon question, where the matrix added the answer passage: exp147 abstained ("the evidence does
  not mention an Armageddon shirt") and the judge gave it 1.0; exp151 answers with the shirt's slogan (citation 1.0)
  and gets 0.5 for leaving out the context of Blomkvist’s visit (exp152 repeat: same answer, 0.5 / 1.0). A judge
  artifact, not lost evidence. The flag stays
  off pending the user's approval.
- **2026-10-17, approved:** committed off (1cdc2b1), then the user approved the Armageddon drop and asked for the
  flag on: `entity_matrix` is on by default and deployed.
