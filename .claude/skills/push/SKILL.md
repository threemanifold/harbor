---
name: push
description: Push the current branch and open or update its pull request.
---

# Push

Push the branch (commit pending changes first if any):

    ./.claude/scripts/commit-and-push.sh "<commit message>"

Open or return the PR for the current branch (idempotent; applies the `symphony` label and references the Linear issue in the body):

    ./.claude/scripts/open-pr.sh "<title>" "<linear-issue-id>"

If a previous PR for this branch is `CLOSED` or `MERGED`, create a new branch off `origin/main` instead of reusing.
