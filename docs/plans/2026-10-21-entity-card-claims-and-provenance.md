# Entity cards: claims, unresolved events, and reliable provenance

Status: proposed plan for joint review. No implementation changes are included in this document.

## Why

Entity cards and event records are useful search leads, but their current flat representation can make an allegation
look like a confirmed event and can attach citations that do not support the displayed fact. The Harriet investigation
is a concrete example: an event extracted from an accusation says Martin Vanger killed Harriet, while the surrounding
story corrects that interpretation: he says he arrived too late, and later the story reveals that Harriet is alive.

The question-time agent needs to find the eventual account when the question calls for it, while preserving what a
particular character believed or said at an earlier point. Cards should help find that evidence; they must not turn
an intermediate claim into story truth.

## Observed issues to address

1. **Speech acts become events.** The extraction prompt asks for events and participants but does not consistently
   distinguish narration from an accusation, belief, question, denial, rumor, or reported claim. A line such as
   “You killed her” can therefore be stored as if the killing occurred.
2. **No local attribution or epistemic label.** Event rows retain a fact, people, and passage-window members, but do
   not encode who asserted the fact or what kind of assertion it was.
3. **Flat facts lose provenance.** Entity merging aggregates fact strings and card-wide member IDs. It does not retain
   the exact source passages for every fact. `_fact_sources` keeps only the first window for duplicate facts.
4. **Card citations can be unrelated.** `entity_card` returns question-ranked facts but its top-level passage IDs come
   from the card-wide member list, sorted by UUID. Those passages may not support the selected facts.
5. **Relationship explanations can mismatch their sources.** An edge's explanatory text may be taken from an
   arbitrary entity fact, while its member IDs come from relation windows.
6. **Story order is lost.** UUID sorting is not narrative order. Aggregated cards do not say where a fact falls in the
   book, so early belief and later correction can be shown together without a reliable sequence.
7. **Identity joins are heuristic.** The one-word-to-full-name pairing rule can merge mentions incorrectly. This is
   a known risk to measure and expose, not a demonstrated cause of the Harriet error.
8. **Cards are leads, not a resolution mechanism.** The event-graph path has previously ranked noisy extracted events
   below official story evidence and remains off by default. A flat card should not claim a global event is resolved.

## Design principles

- Keep extraction local to the text window. It may classify what the window states and who says it; it cannot decide
  global story truth from one window.
- Preserve the distinction between **a character asserts X** and **X happened**.
- Preserve conflicting claims instead of deduplicating them into one fact.
- Attach source passage IDs to each fact and relation. Only those passages may be returned as evidence for that item.
- Treat global resolution as a later evidence-reconciliation/search step. A later passage can correct an earlier claim,
  but the earlier claim remains a valid answer when the question asks what someone believed at that time.
- Keep book passages as the answer's evidence. Cards and graph records are navigation aids, not citations that prove
  the answer by themselves.

## Proposed data model

Migrate flat card facts and event rows to structured records, with a schema version so caches can be invalidated safely.

Each fact/claim should retain at least:

- `text`: concise statement faithful to the source;
- `source_passage_ids`: exact passages that support this record;
- `assertion_type`: one of `narration`, `reported_claim`, `accusation`, `belief`, `question`, `denial`, `rumor`,
  `uncertain` (extend only when real examples require it);
- `attributed_to`: speaker or source when identifiable, otherwise null;
- `subject`, `predicate`, and `object` when extraction can identify them without guessing;
- `book_id`, `section`, and passage/paragraph order for chronological display;
- optional `supersedes` or `responds_to` relation only when the text explicitly supports it.

Do not put a global `confirmed`/`resolved` status on a single extracted record. If later reconciliation is added, it
should produce a separate, traceable conclusion with links to the supporting and conflicting records and passages.

## Work plan

### 1. Establish data and failure baselines

- Record the current entity/event cache schema and counts for the default index.
- Trace Harriet's accusation, immediate response, and later reveal through their source passage IDs.
- Inspect representative cards and edges for unrelated citations, mixed aliases, flat contradictions, and out-of-order
  facts. Include controls that currently work so changes do not damage ordinary entity lookup.
- Keep event-graph search off during this work; its prior retrieval results do not justify enabling it by default.

### 2. Fix provenance before broadening retrieval

- Change merge output so every fact stores all exact supporting passage IDs, not just card-wide members.
- Preserve source IDs for every edge from the same windows that establish that relation.
- Fix `_fact_sources` to keep all source windows for repeated facts.
- Make `entity_card` return fact-level sources alongside each selected fact. Add only those source rows to evidence.
- Derive edge text from the edge's own supporting extraction, never from a fallback entity fact.
- Order evidence by corpus/book/section/paragraph metadata rather than UUID. Retain stable ordering for ties.

**Acceptance:** every displayed card fact and edge can be traced to at least one returned source passage; no unrelated
card-wide passage is admitted as support for a selected fact.

### 3. Make extraction preserve claims and attribution

- Update entity/event extraction prompts to identify the assertion type and speaker/source.
- Instruct extraction not to turn quoted accusations, questions, suspicions, or denials into narrated events.
- Require `uncertain` or omission when the excerpt cannot establish who said a claim or whether it is narration.
- Keep extraction text grounded in the provided window; use preceding context only to resolve references, not to
  invent an event or infer its truth.
- Preserve separate records when two characters or passages make conflicting claims.

**Acceptance:** “You killed her” is stored as an accusation attributed to Mikael, not as a confirmed killing; the
counterstatement and later reveal remain separate records with their own citations.

### 4. Add chronology-aware reconciliation as a separate layer

- First expose source order on card facts and event records.
- Then prototype a query-time or indexing-time reconciliation view that groups records about the same event while
  retaining every claim and its source.
- Represent “unresolved in available text” separately from “resolved by later text.” Do not infer resolution just
  because one claim is newer; require a passage that explicitly corrects, confirms, or reveals the matter.
- Return the sequence of evidence to the answer agent, with earlier and later statements clearly distinguished.
- Keep the initial implementation as a targeted lookup over existing retrieval and card indexes. Revisit graph search
  only if evaluation shows that explicit claim-to-correction links improve recall and precision.

**Acceptance:** for “Who killed Harriet?” retrieval reaches the later account that she survived and was killed by her
father, while “What did Mikael accuse Martin of?” can still retrieve the earlier accusation. A query about the state of
knowledge before the reveal should not leak the later resolution unless the question asks for the eventual account.

### 5. Validate merges and uncertainty

- Audit alias/name joins against known cases, including shared surnames, nicknames, aliases, and people linked by
  non-name relations.
- Make ambiguous joins visible or keep them separate instead of silently merging on a weak pairing heuristic.
- Check that card summaries label attributed claims and unresolved conflicts rather than flattening them into fact.
- Ensure unknown attribution and uncertain chronology survive serialization and agent-tool formatting.

## Regression and evaluation set

Use a small manually reviewed set before rebuilding all caches:

- Harriet: accusation, Martin's response that he arrived too late, later reveal she survived, and the eventual account
  of her death;
- Gottfried's death: official accident account versus the later account that Harriet killed him, with both sources
  represented and correctly ordered;
- a control where narration directly states an uncomplicated event;
- a question specifically about what a character said, suspected, or believed;
- an unresolved accusation with no later correction in the available corpus;
- entity/alias controls from the existing entity-card evaluation to catch identity-join regressions.

Measure source passage recall, citation support precision, claim-type accuracy, chronology accuracy, and answer quality.
Include a negative check that a card's unrelated member passages do not become evidence for a selected fact.

## Cache and rollout plan

- Add a schema/prompt fingerprint to entity and event caches. A schema change must not silently reuse old flat records.
- Run extraction on a small representative sample and manually inspect raw structured output before full regeneration.
- Estimate full rebuild time and resource use from that sample; the previous event extraction covered 972 windows and
  took about 2h47m, so schedule it outside active experiment runs.
- Rebuild caches for the current passage index after the schema is accepted.
- Keep the graph path off by default until the evaluation set shows a meaningful gain without citation or answer
  regressions.
- Compare default-pipeline behavior on existing QA and Additional Questions sets, plus the targeted claim-resolution
  cases. Review regressions before enabling any new retrieval path.

## Decisions for joint review

1. Should assertion labels stay a small fixed enum, or allow an `other` value with a short explanation?
2. Should reconciliation run at question time over retrieved records, or be materialized during indexing after local
   extraction? The initial proposal is to preserve local records first and defer this choice until the data is reliable.
3. What minimum evidence should permit a record to be called resolved: explicit correction only, or also an unambiguous
   later narration/reveal?
4. Should ambiguous identity joins remain separate by default, even if that reduces recall?
