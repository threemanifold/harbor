#!/usr/bin/env bash
# Run Playwright e2e tests and collect the recorded walkthrough videos.
#
# On pass: copies every produced .webm into $WALKTHROUGHS_DIR with a stable
# filename and prints "OK: <N> walkthrough(s) -> <dir>" followed by each path.
# On fail: prints "FAIL (e2e, exit <code>)" + the last 20 lines of test output
# and exits non-zero.
#
# Output dir resolution (first match wins):
#   1. $WALKTHROUGHS_DIR if explicitly set
#   2. /home/symphony/walkthroughs if it exists and is writable
#      (Symphony container's bind-mount path — videos land on the host)
#   3. <repo-root>/walkthroughs (local-laptop fallback)
#
# Any args are passed through to `pnpm e2e` (e.g. `e2e/chat.spec.ts` to record
# only one spec).
set -uo pipefail

ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
FRONTEND="$ROOT/apps/frontend"

if [ -n "${WALKTHROUGHS_DIR:-}" ]; then
  :
elif [ -d /home/symphony/walkthroughs ] && [ -w /home/symphony/walkthroughs ]; then
  WALKTHROUGHS_DIR=/home/symphony/walkthroughs
else
  WALKTHROUGHS_DIR="$ROOT/walkthroughs"
fi
mkdir -p "$WALKTHROUGHS_DIR"

OUT=$(cd "$FRONTEND" && pnpm e2e "$@" 2>&1)
EC=$?
if [ "$EC" -ne 0 ]; then
  echo "FAIL (e2e, exit $EC)"
  printf '%s\n' "$OUT" | tail -20
  exit "$EC"
fi

TS=$(date +%Y%m%d-%H%M%S)
COUNT=0
COPIED=()
while IFS= read -r -d '' VIDEO; do
  PARENT_DIR=$(basename "$(dirname "$VIDEO")")
  # Strip the trailing project name (e.g. "-chromium") for readability.
  SAFE_NAME="${PARENT_DIR%-chromium}"
  DEST="$WALKTHROUGHS_DIR/${TS}-${SAFE_NAME}.webm"
  cp "$VIDEO" "$DEST"
  COPIED+=("$DEST")
  COUNT=$((COUNT + 1))
done < <(find "$FRONTEND/test-results" -name 'video.webm' -print0 2>/dev/null)

if [ "$COUNT" -eq 0 ]; then
  echo "OK: e2e green, no videos produced (video recording disabled?)"
  exit 0
fi

echo "OK: $COUNT walkthrough(s) -> $WALKTHROUGHS_DIR"
for P in "${COPIED[@]}"; do
  echo "  $P"
done
