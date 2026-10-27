#!/bin/sh
# Per-run context settings. Keep the user's model, permissions and credentials.
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"
exec codex \
  -c project_doc_max_bytes=16384 \
  -c tool_output_token_limit=4000 \
  "$@"
