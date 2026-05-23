#!/usr/bin/env bash
# Attach a walkthrough video to a Linear issue.
# Usage: attach-walkthrough.sh <ISSUE-IDENTIFIER> <VIDEO-PATH>
# Reads LINEAR_API_KEY from the environment.
# On success: prints "OK: <issue-identifier> attached <linear-url>" and exits 0.
# On failure: forwards the Linear API / upload response on stderr and exits non-zero.
#
# Mechanics:
#   1. Resolve <ISSUE-IDENTIFIER> -> internal UUID.
#   2. fileUpload mutation -> presigned uploadUrl + permanent assetUrl + required headers.
#   3. PUT the binary to uploadUrl with those headers.
#   4. attachmentCreate(issueId, title, url=assetUrl) -> issue's Attachments rail.
set -euo pipefail

if [ -z "${LINEAR_API_KEY:-}" ]; then
  echo "LINEAR_API_KEY not set" >&2
  exit 1
fi

issue_id="${1:-}"
video_path="${2:-}"
if [ -z "$issue_id" ] || [ -z "$video_path" ]; then
  echo "usage: attach-walkthrough.sh <ISSUE-IDENTIFIER> <VIDEO-PATH>" >&2
  exit 2
fi
if [ ! -r "$video_path" ]; then
  echo "cannot read video: $video_path" >&2
  exit 1
fi

filename=$(basename "$video_path")
size=$(stat -c%s "$video_path" 2>/dev/null || stat -f%z "$video_path")
case "$filename" in
  *.webm) content_type="video/webm" ;;
  *.mp4)  content_type="video/mp4" ;;
  *.mov)  content_type="video/quicktime" ;;
  *)      content_type="application/octet-stream" ;;
esac

linear_call() {
  local query="$1"
  local vars="$2"
  curl -sS -X POST https://api.linear.app/graphql \
    -H "Authorization: $LINEAR_API_KEY" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg q "$query" --argjson v "$vars" '{query:$q, variables:$v}')"
}

# 1. Resolve issue identifier -> internal UUID.
q='query($id: String!) { issue(id: $id) { id identifier } }'
resp=$(linear_call "$q" "$(jq -n --arg id "$issue_id" '{id:$id}')")
internal_id=$(printf '%s' "$resp" | jq -r '.data.issue.id // empty')
if [ -z "$internal_id" ]; then
  echo "issue not found: $issue_id" >&2
  echo "$resp" >&2
  exit 1
fi

# 2. Request a signed upload URL.
m='mutation($ct: String!, $fn: String!, $size: Int!) {
  fileUpload(contentType: $ct, filename: $fn, size: $size) {
    success
    uploadFile { uploadUrl assetUrl headers { key value } }
  }
}'
vars=$(jq -n --arg ct "$content_type" --arg fn "$filename" --argjson size "$size" \
  '{ct:$ct, fn:$fn, size:$size}')
upload_resp=$(linear_call "$m" "$vars")
upload_ok=$(printf '%s' "$upload_resp" | jq -r '.data.fileUpload.success // false')
upload_url=$(printf '%s' "$upload_resp" | jq -r '.data.fileUpload.uploadFile.uploadUrl // empty')
asset_url=$(printf '%s' "$upload_resp" | jq -r '.data.fileUpload.uploadFile.assetUrl // empty')
if [ "$upload_ok" != "true" ] || [ -z "$upload_url" ] || [ -z "$asset_url" ]; then
  echo "fileUpload mutation failed" >&2
  echo "$upload_resp" >&2
  exit 1
fi

# 3. PUT the binary to the signed URL.
# Content-Type is part of the signed-header set on Linear's S3 URL, so it must
# match what we declared in the fileUpload mutation. Linear's `headers` array
# does not include it; everything else (e.g. Cache-Control) does.
header_args=(-H "Content-Type: $content_type")
while IFS=$'\t' read -r key value; do
  [ -z "$key" ] && continue
  header_args+=(-H "$key: $value")
done < <(printf '%s' "$upload_resp" | jq -r '.data.fileUpload.uploadFile.headers[]? | "\(.key)\t\(.value)"')

put_body=$(mktemp)
trap 'rm -f "$put_body"' EXIT
http_code=$(curl -sS -o "$put_body" -w "%{http_code}" \
  -X PUT --upload-file "$video_path" \
  "${header_args[@]}" \
  "$upload_url")
if [ "$http_code" -lt 200 ] || [ "$http_code" -ge 300 ]; then
  echo "upload PUT returned HTTP $http_code" >&2
  cat "$put_body" >&2
  exit 1
fi

# 4. Create the attachment on the issue.
m='mutation($iid: String!, $title: String!, $url: String!) {
  attachmentCreate(input: { issueId: $iid, title: $title, url: $url }) {
    success
    attachment { id url }
  }
}'
title="Walkthrough: $filename"
vars=$(jq -n --arg iid "$internal_id" --arg title "$title" --arg url "$asset_url" \
  '{iid:$iid, title:$title, url:$url}')
att_resp=$(linear_call "$m" "$vars")
att_ok=$(printf '%s' "$att_resp" | jq -r '.data.attachmentCreate.success // false')
att_url=$(printf '%s' "$att_resp" | jq -r '.data.attachmentCreate.attachment.url // empty')
if [ "$att_ok" != "true" ] || [ -z "$att_url" ]; then
  echo "attachmentCreate failed" >&2
  echo "$att_resp" >&2
  exit 1
fi

echo "OK: $issue_id attached $att_url"
