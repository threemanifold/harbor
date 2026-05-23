#!/usr/bin/env bash
# Open a PR for the current branch with the "symphony" label.
# Usage: open-pr.sh ["<title>"] ["<linear-issue-id>"]
# Idempotent: if a PR already exists for the branch, prints its URL and exits 0.
#
# Why this script doesn't use `gh pr create`:
# When the authenticated user has push access to the repo but isn't its owner,
# `gh pr create` sometimes mis-resolves --head into a fork reference and fails on
# slash-containing branch names. The GitHub API endpoint accepts head as a plain
# branch name and works reliably in that case.
set -euo pipefail

TITLE="${1:-$(git log -1 --pretty=%s)}"
ISSUE="${2:-}"

BODY="Automated PR from Symphony orchestration."
if [ -n "$ISSUE" ]; then
  BODY+=$'\n\nLinear: '"$ISSUE"
fi

BRANCH=$(git branch --show-current)
if [ -z "$BRANCH" ]; then
  echo "open-pr.sh: not on a branch" >&2
  exit 1
fi

gh label create symphony --description "Created by Symphony orchestration" --color FF6B35 >/dev/null 2>&1 || true

# Idempotent: return existing PR if one is already open for this branch.
if URL=$(gh pr view "$BRANCH" --json url -q .url 2>/dev/null); then
  gh pr edit "$BRANCH" --add-label symphony >/dev/null 2>&1 || true
  echo "$URL"
  exit 0
fi

# Ensure the branch is on the remote.
git push -u origin "$BRANCH" >/dev/null 2>&1 || true

REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
BASE=$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name)

if URL=$(gh api "repos/${REPO}/pulls" \
    -f title="$TITLE" \
    -f head="$BRANCH" \
    -f base="$BASE" \
    -f body="$BODY" \
    --jq .html_url 2>/dev/null); then
  gh pr edit "$BRANCH" --add-label symphony >/dev/null 2>&1 || true
  echo "$URL"
  exit 0
fi

echo "open-pr.sh: failed to create PR for branch $BRANCH on $REPO" >&2
exit 1
