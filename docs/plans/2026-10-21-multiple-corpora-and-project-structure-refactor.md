# Refactor for Multiple Corpora and Project Structure

## Summary

Reorganize the project so corpus data, corpus-specific behavior, and shared pipeline code have clear boundaries. Split the Python app by responsibility, give each corpus its own data and frontend deployment, and remove only code confirmed to be unused. Preserve current Millennium behavior and existing in-progress edits during the migration.

## Implementation Changes

- Put each corpus's source material in `corpora/<id>/`: books, question sets, and a `corpus.yaml` describing its title, language, available sets, and profile ID. Move Millennium's EPUBs, `QA.csv`, and answer facts into `corpora/millennium/`.
- Keep corpus-specific Python code in `app/corpus_profiles/<id>/`, separate from corpus files. Each profile supplies corpus-specific prompts, name handling, and domain rules needed by the shared pipeline. Keep profile loading and a small common interface in `app/corpus_profiles/`; put reusable ingestion, indexing, retrieval, answering, API, evaluation, experiment, and storage code in responsibility-based app packages.
- Select a corpus explicitly through deployment configuration. Resolve its profile and data paths from that selection, remove the fixed three-EPUB requirement, and keep generated indexes, caches, and experiment artifacts in the separate `data/<id>/` namespace.
- Put frontend deployments in `frontends/<id>/`. Move the existing frontend to `frontends/millennium/` and update submodule, Docker, Compose, and documentation references. Add another frontend there when the Alienist UI exists.
- Move `IMPROVEMENTS.md` and `Notes.md` under `docs/`. Keep shared technical and pipeline documentation at the project level; put corpus-specific guidance with the relevant corpus.
- Audit before deleting: remove only code confirmed unused across runtime imports, tests, CLI entry points, and documented workflows. Retain uncertain historical experiment material.

## Test Plan

- Confirm Millennium still indexes and answers with its existing three books and profile; confirm a one-book corpus can be selected and indexed.
- Check that corpus selection resolves the matching books, question set, profile, and isolated generated-data paths.
- Run the existing Python and frontend suites, adding focused coverage for profile loading, path resolution, corpus isolation, and one-book indexing.
- Verify API and experiment workflows use the selected corpus, and the frontend builds and deploys from its new location.
- Check imports and entry points after the app split, and review each deletion for remaining references.

## Assumptions

- Corpus IDs are `millennium` and `the-alienist`; each corpus can have multiple named question sets.
- `corpus.yaml` holds declarative metadata and selects a Python profile; corpus-specific behavior lives in `app/corpus_profiles/`.
- Generated data remains outside `corpora/`, under `data/<id>/`.
- Frontends are independently deployable per corpus; the Alienist frontend is added when available.
- Preserve existing uncommitted changes while carrying out the refactor.
