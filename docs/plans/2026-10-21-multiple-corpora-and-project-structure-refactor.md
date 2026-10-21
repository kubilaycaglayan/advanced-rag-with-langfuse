# Refactor for Multiple Corpora and Project Structure

## Summary

Reorganize the project so corpus data, corpus-specific behavior, and shared pipeline code have clear boundaries. Make the pipeline corpus agnostic so the same implementation can work with any novel, rather than relying on Millennium-specific books or rules. Split the Python app by responsibility, support separate data and frontend deployments per corpus, and remove only code confirmed to be unused. The Alienist is only an example of possible future work; do not create Alienist-specific files now. Preserve current Millennium behavior and existing in-progress edits during the migration.

## Implementation Changes

- Put each corpus's source material in `corpora/<id>/`: books, question sets, and a `corpus.yaml` describing its title, language, available sets, and profile ID. Move Millennium's EPUBs, `QA.csv`, and answer facts into `corpora/millennium/`.
- Keep corpus-specific Python code in `app/corpus_profiles/<id>/`, separate from corpus files. Each profile supplies corpus-specific prompts, name handling, and domain rules needed by the shared pipeline. Keep profile loading and a small common interface in `app/corpus_profiles/`; put reusable ingestion, indexing, retrieval, answering, API, evaluation, experiment, and storage code in responsibility-based app packages.
- Select a corpus explicitly through deployment configuration. Resolve its profile and data paths from that selection, remove the fixed three-EPUB requirement, and keep generated indexes, caches, and experiment artifacts in the separate `data/<id>/` namespace.
- Share pipeline versions across corpora: a version defines the processing flow and shared settings, not a particular set of books. Remove the Millennium-only book checksum requirement from version selection. Resolve corpus-specific prompts and rules through the selected profile, and record corpus ID, source checksum, profile and prompt identities, and pipeline version on each run so results remain traceable. Keep generated indexes, including Qdrant collections, isolated by corpus.
- Put frontend deployments in `frontends/<id>/`. Move the existing frontend to `frontends/millennium/` and update submodule, Docker, Compose, and documentation references. Add other frontends only when they exist.
- Move `IMPROVEMENTS.md` and `Notes.md` under `docs/`. Keep shared technical and pipeline documentation at the project level; put corpus-specific guidance with the relevant corpus.
- Audit before deleting: remove only code confirmed unused across runtime imports, tests, CLI entry points, and documented workflows. Retain uncertain historical experiment material.
- Preserve Git tracking status during moves: files currently untracked or ignored, including local EPUBs and `Notes.md`, must remain untracked or ignored. Update ignore rules for their new paths; do not add previously untracked files to Git.

## Test Plan

- Confirm Millennium still indexes and answers with its existing three books and profile; use a temporary one-book test fixture to confirm another corpus can be selected and indexed without adding real second-corpus content.
- Check that corpus selection resolves the matching books, question set, profile, and isolated generated-data paths.
- Confirm the same pipeline version can run against different corpora while each run records its corpus and uses separate indexes and artifacts.
- Run the existing Python and frontend suites, adding focused coverage for profile loading, path resolution, corpus isolation, and one-book indexing.
- Verify API and experiment workflows use the selected corpus, and the frontend builds and deploys from its new location.
- Check imports and entry points after the app split, and review each deletion for remaining references.

## Assumptions

- `millennium` is the existing corpus ID; future IDs are not predetermined. Each corpus can have multiple named question sets.
- `corpus.yaml` holds declarative metadata and selects a Python profile; corpus-specific behavior lives in `app/corpus_profiles/`.
- Generated data remains outside `corpora/`, under `data/<id>/`.
- Frontends are independently deployable per corpus; only the existing Millennium frontend is moved now.
- Preserve existing uncommitted changes and the tracking status of all files while carrying out the refactor.
