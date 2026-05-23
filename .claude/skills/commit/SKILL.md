---
name: commit
description: Create a git commit from current changes (also pushes the branch).
---

# Commit

Use the helper script:

    ./.claude/scripts/commit-and-push.sh "<commit message>"

Stages all changes, commits, and pushes the current branch in one call. Prints `pushed: <short-sha>` or `nothing to commit`.

Commit message format: `type: short subject` (e.g. `feat: add tell_age helper`, `fix: handle empty input in shout`). Use lower-case type prefixes: `feat`, `fix`, `chore`, `refactor`, `test`, `docs`.
