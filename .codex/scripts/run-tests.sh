#!/usr/bin/env bash
# Run all project test suites and print a terse, deterministic result.
# On pass: prints one "OK: ..." summary line and exits 0.
# On fail: prints "FAIL (<suite>, exit <code>)" + the last 20 lines of that
# suite's output and exits non-zero.
#
# Suites:
#   backend  -> backend       (uv run pytest)
#   frontend -> apps/frontend (pnpm test:run, vitest)
set -uo pipefail

ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)

# --- backend ---
BACK_OUT=$(cd "$ROOT/backend" && uv run pytest -q 2>&1)
BACK_EC=$?
if [ "$BACK_EC" -ne 0 ]; then
  echo "FAIL (backend, exit $BACK_EC)"
  printf '%s\n' "$BACK_OUT" | tail -20
  exit "$BACK_EC"
fi
BACK_SUMMARY=$(printf '%s\n' "$BACK_OUT" | tail -1)

# --- frontend ---
FRONT_OUT=$(cd "$ROOT/apps/frontend" && pnpm test:run 2>&1)
FRONT_EC=$?
if [ "$FRONT_EC" -ne 0 ]; then
  echo "FAIL (frontend, exit $FRONT_EC)"
  printf '%s\n' "$FRONT_OUT" | tail -20
  exit "$FRONT_EC"
fi
FRONT_SUMMARY=$(printf '%s\n' "$FRONT_OUT" \
  | grep -E "Tests[[:space:]]+[0-9]+[[:space:]]+passed" \
  | tail -1 | sed -E 's/^[[:space:]]+//')
[ -z "$FRONT_SUMMARY" ] && FRONT_SUMMARY=$(printf '%s\n' "$FRONT_OUT" | tail -1)

echo "OK: backend [$BACK_SUMMARY] | frontend [$FRONT_SUMMARY]"
exit 0
