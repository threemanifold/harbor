---
name: walkthrough
description: Produce a video walkthrough of a UI flow via Playwright (recording + delivery).
---

# Walkthrough

## Run

    ./.claude/scripts/record-walkthrough.sh

Pass a spec path to record one test only:

    ./.claude/scripts/record-walkthrough.sh e2e/chat.spec.ts

The script runs `pnpm e2e`, copies each produced `.webm` to the delivery dir, and prints a path list. Exits non-zero with `FAIL ...` if any test fails.

## Deliver: attach the video to the Linear issue

Every video is a deliverable — link it on the ticket so reviewers don't have to chase paths.

    ./.claude/scripts/attach-walkthrough.sh <ISSUE-IDENTIFIER> <VIDEO-PATH>

Example, using the path printed by `record-walkthrough.sh`:

    ./.claude/scripts/attach-walkthrough.sh SYM-29 /home/symphony/walkthroughs/20260511-173540-multi-chat-lifecycle.webm

The script uploads to Linear's file store and attaches the resulting URL to the issue's Attachments rail. Prints `OK: <issue> attached <linear-url>` on success. Run it once per produced `.webm` after `record-walkthrough.sh` exits clean and **before** flipping the ticket to `Human Review`.

## Writing a watchable narrative test

Walkthrough tests are **narrative scripts**, not regression checks. Different rules from `vitest`:

- Place under `apps/frontend/e2e/`. One spec per walkthrough.
- **Pace the flow.** After each visible action (fill, click), add `await page.waitForTimeout(500)` so the viewer can read the screen. End every test with `await page.waitForTimeout(1500)` so the recording doesn't cut mid-render.
- **No mid-flow asserts.** A walkthrough that fails halfway leaves a useless clip. Drive the UI all the way through, then assert at the end.
- **Mock external calls** with `page.route('**/chat', ...)` unless the test specifically targets backend integration. Real backend = slow, costs tokens, flaky video.
- **Scroll into view** before clicking off-screen elements: `await target.scrollIntoViewIfNeeded()`.
- **Locator priority:** `getByRole` > `getByLabel` > `getByText` > CSS. Stable across refactors.
- Don't override the viewport per-test; the config default (1280×720) is the walkthrough standard.

Follow the rules above for every walkthrough you write — not just the first one.
