---
name: land
description:
  Squash-merge the PR for the current Merging issue. Use when the Symphony
  workflow enters the Merging state and the PR is ready to land.
---

# Land

Squash-merge the PR attached to the current Linear issue, then return so the
caller can move the ticket to Done.

## Preconditions

- `gh` CLI is authenticated for `__REPO__` (this placeholder is replaced at
  bootstrap time by `bootstrap/init-repo.sh`).
- The Linear issue has a GitHub PR attached (the workflow guarantees this on
  entry to `Merging`).

## Steps

1. Read the PR number from the issue's GitHub attachment URL
   (`https://github.com/<owner>/<repo>/pull/<number>`).
2. Confirm the PR is `MERGEABLE` and `mergeStateStatus` is `CLEAN`.
3. Squash-merge using the PR's title as the merge-commit subject and the PR's
   body as the merge-commit body. Delete the source branch on merge.
4. Move the Linear issue to `Done`.

## Commands

```sh
pr_number="<from issue attachment>"   # substitute the integer from the URL

pr_title=$(gh pr view "$pr_number" --repo __REPO__ --json title -q .title)
pr_body=$(gh pr view "$pr_number" --repo __REPO__ --json body -q .body)
mergeable=$(gh pr view "$pr_number" --repo __REPO__ --json mergeable -q .mergeable)
state=$(gh pr view "$pr_number" --repo __REPO__ --json mergeStateStatus -q .mergeStateStatus)

if [ "$mergeable" != "MERGEABLE" ] || [ "$state" != "CLEAN" ]; then
  echo "Not ready to merge: mergeable=$mergeable state=$state" >&2
  exit 1
fi

gh pr merge "$pr_number" --repo __REPO__ --squash --delete-branch \
  --subject "$pr_title" --body "$pr_body"
```

## Failure Handling

- If `mergeable` is `UNKNOWN`, sleep 5 seconds and re-check (up to 3 attempts).
- If `gh pr merge` errors, escalate per the workflow's per-step attempt budget:
  do NOT retry blindly. Record the error in the workpad and move the issue to
  `Human Review` with a blocker brief.
- This minimal skill intentionally does NOT handle CI failures, merge
  conflicts, or review-comment loops because the host repo has none of those
  configured. If any of them appear, escalate via `Human Review` instead of
  improvising.

## Post-merge

- After a successful merge, set the Linear issue to `Done` and exit. Do not
  post a separate "merged" comment; the issue's PR attachment plus the merge
  on GitHub are sufficient evidence.
