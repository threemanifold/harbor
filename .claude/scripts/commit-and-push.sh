#!/usr/bin/env bash
# Stage all changes, commit with the provided message, push the current branch.
# Usage: commit-and-push.sh "<commit message>"
# On nothing-to-commit: prints "nothing to commit" and exits 0.
# On success: prints "pushed: <short-sha>".
set -euo pipefail

if [ $# -lt 1 ] || [ -z "$1" ]; then
  echo "usage: commit-and-push.sh \"<commit message>\"" >&2
  exit 2
fi

git add -A

if git diff --cached --quiet; then
  echo "nothing to commit"
  exit 0
fi

git commit -m "$1" >/dev/null
SHA=$(git rev-parse --short HEAD)
git push -u origin HEAD >/dev/null 2>&1
echo "pushed: $SHA"
