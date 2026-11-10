# Repository agent notes

## One-off app containers

Run repository commands from the repository root. The app image does not install `git`, but experiment manifests call it to record the source tree. A bind-mounted worktree also needs a Git safe-directory setting inside the container. Include both from the start when running a one-off app container:

```bash
docker compose run --no-deps --rm -T \
  -v "$PWD:/workspace" \
  -v "$(command -v git):/usr/local/bin/git:ro" \
  -w /workspace \
  -e GIT_CONFIG_COUNT=1 \
  -e GIT_CONFIG_KEY_0=safe.directory \
  -e GIT_CONFIG_VALUE_0=/workspace \
  app python -m app.experiments --dataset set3 --pipeline v2.4 --item-id ITEM_ID
```

Replace the command after `app` as needed. This runs in a separate container and leaves the live app container untouched. Do not omit the Git mount or safe-directory variables for experiment runs; either omission causes the run to fail before answering a question.

## Pipeline diagrams

Include the represented pipeline version as a visible signature in every diagram that depicts a pipeline. Keep that signature aligned with the pipeline catalog (`pipelines.md`) when updating or recreating the diagram.
