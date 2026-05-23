#!/usr/bin/env bash
# Move a Linear issue to a named workflow state.
# Usage: linear-state.sh <ISSUE-IDENTIFIER> "<STATE-NAME>"
# Reads LINEAR_API_KEY from the environment.
# On success: prints "OK: <issue-identifier> -> <state-name>" and exits 0.
# On failure: forwards the Linear API response on stderr and exits non-zero.
set -euo pipefail

if [ -z "${LINEAR_API_KEY:-}" ]; then
  echo "LINEAR_API_KEY not set" >&2
  exit 1
fi

issue_id="${1:-}"
state_name="${2:-}"
if [ -z "$issue_id" ] || [ -z "$state_name" ]; then
  echo "usage: linear-state.sh <ISSUE-IDENTIFIER> \"<STATE-NAME>\"" >&2
  exit 2
fi

linear_call() {
  local query="$1"
  local vars="$2"
  curl -sS -X POST https://api.linear.app/graphql \
    -H "Authorization: $LINEAR_API_KEY" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg q "$query" --argjson v "$vars" '{query:$q, variables:$v}')"
}

# Resolve issue's internal UUID and team key.
q='query($id: String!) { issue(id: $id) { id team { id key } } }'
resp=$(linear_call "$q" "$(jq -n --arg id "$issue_id" '{id:$id}')")

internal_id=$(printf '%s' "$resp" | jq -r '.data.issue.id // empty')
team_key=$(printf '%s' "$resp" | jq -r '.data.issue.team.key // empty')

if [ -z "$internal_id" ] || [ -z "$team_key" ]; then
  echo "issue not found: $issue_id" >&2
  echo "$resp" >&2
  exit 1
fi

# Resolve the workflow state ID for the named state in this team (case-insensitive).
q='query($key: String!) { workflowStates(filter: { team: { key: { eq: $key } } }) { nodes { id name } } }'
resp=$(linear_call "$q" "$(jq -n --arg key "$team_key" '{key:$key}')")

state_id=$(printf '%s' "$resp" \
  | jq -r --arg name "$state_name" '
      .data.workflowStates.nodes[]?
      | select((.name | ascii_downcase) == ($name | ascii_downcase))
      | .id' \
  | head -n1)

if [ -z "$state_id" ]; then
  available=$(printf '%s' "$resp" | jq -r '[.data.workflowStates.nodes[]?.name] | join(", ")')
  echo "state not found: '$state_name' (team: $team_key)" >&2
  echo "available: $available" >&2
  exit 1
fi

# Apply the transition.
m='mutation($id: String!, $stateId: String!) { issueUpdate(id: $id, input: { stateId: $stateId }) { success issue { identifier state { name } } } }'
vars=$(jq -n --arg id "$internal_id" --arg stateId "$state_id" '{id:$id, stateId:$stateId}')
resp=$(linear_call "$m" "$vars")

ok=$(printf '%s' "$resp" | jq -r '.data.issueUpdate.success // empty')
new_state=$(printf '%s' "$resp" | jq -r '.data.issueUpdate.issue.state.name // empty')
new_ident=$(printf '%s' "$resp" | jq -r '.data.issueUpdate.issue.identifier // empty')

if [ "$ok" = "true" ]; then
  echo "OK: $new_ident -> $new_state"
  exit 0
fi

echo "state transition failed: $issue_id -> $state_name" >&2
echo "$resp" >&2
exit 1
