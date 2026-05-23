#!/usr/bin/env bash
# Manage the Symphony "## Claude Workpad" comment on a Linear issue.
# Subcommands:
#   ensure <ISSUE-IDENTIFIER>          -> prints existing or newly-created comment ID
#   update <COMMENT-ID> <BODY-FILE>    -> replaces comment body with file contents, prints "OK"
#
# Reads LINEAR_API_KEY from the environment.
set -euo pipefail

if [ -z "${LINEAR_API_KEY:-}" ]; then
  echo "LINEAR_API_KEY not set" >&2
  exit 1
fi

linear_call() {
  local query="$1"
  local vars="$2"
  curl -sS -X POST https://api.linear.app/graphql \
    -H "Authorization: $LINEAR_API_KEY" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg q "$query" --argjson v "$vars" '{query:$q, variables:$v}')"
}

cmd="${1:-}"

case "$cmd" in
  ensure)
    issue_id="${2:-}"
    if [ -z "$issue_id" ]; then
      echo "usage: linear-workpad.sh ensure <ISSUE-IDENTIFIER>" >&2
      exit 2
    fi

    q='query($id: String!) { issue(id: $id) { id comments(first: 50) { nodes { id body } } } }'
    resp=$(linear_call "$q" "$(jq -n --arg id "$issue_id" '{id:$id}')")

    existing=$(printf '%s' "$resp" | jq -r '.data.issue.comments.nodes[]? | select(.body | startswith("## Claude Workpad")) | .id' | head -n1)

    if [ -n "$existing" ]; then
      echo "$existing"
      exit 0
    fi

    internal_id=$(printf '%s' "$resp" | jq -r '.data.issue.id')
    if [ -z "$internal_id" ] || [ "$internal_id" = "null" ]; then
      echo "issue not found: $issue_id" >&2
      exit 1
    fi

    template=$'## Claude Workpad\n\n### Plan\n\n### Acceptance Criteria\n\n### Validation\n\n### Notes\n'
    m='mutation($input: CommentCreateInput!) { commentCreate(input: $input) { comment { id } success } }'
    vars=$(jq -n --arg iid "$internal_id" --arg body "$template" '{input:{issueId:$iid, body:$body}}')
    new=$(linear_call "$m" "$vars")
    new_id=$(printf '%s' "$new" | jq -r '.data.commentCreate.comment.id')

    if [ -z "$new_id" ] || [ "$new_id" = "null" ]; then
      echo "comment create failed: $new" >&2
      exit 1
    fi
    echo "$new_id"
    ;;

  update)
    comment_id="${2:-}"
    body_file="${3:-}"
    if [ -z "$comment_id" ] || [ -z "$body_file" ]; then
      echo "usage: linear-workpad.sh update <COMMENT-ID> <BODY-FILE>" >&2
      exit 2
    fi
    if [ ! -r "$body_file" ]; then
      echo "cannot read body file: $body_file" >&2
      exit 1
    fi

    body=$(cat "$body_file")
    m='mutation($id: String!, $input: CommentUpdateInput!) { commentUpdate(id: $id, input: $input) { success } }'
    vars=$(jq -n --arg id "$comment_id" --arg body "$body" '{id:$id, input:{body:$body}}')
    resp=$(linear_call "$m" "$vars")
    ok=$(printf '%s' "$resp" | jq -r '.data.commentUpdate.success')

    if [ "$ok" = "true" ]; then
      echo "OK"
    else
      echo "comment update failed: $resp" >&2
      exit 1
    fi
    ;;

  *)
    echo "usage: linear-workpad.sh ensure <ISSUE-IDENTIFIER> | update <COMMENT-ID> <BODY-FILE>" >&2
    exit 2
    ;;
esac
