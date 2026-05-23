---
name: pull
description: Sync the current branch with latest origin/main.
---

# Pull

Run:

    git fetch origin
    git -c merge.conflictstyle=zdiff3 merge origin/main

If conflicts: resolve them, then `git add <files>` and `git commit`. After: confirm `./.claude/scripts/run-tests.sh` prints `OK`.
