#!/usr/bin/env bash
# Claude Code PostToolUse hook for Edit and Write. Applies the pre-commit Ruff hooks to the
# edited Python file: fixes, then formatting, then a check. Findings left after the fixes go
# to stderr with exit status 2, which Claude Code returns to Claude. Files outside the
# project directory are skipped.
set -uo pipefail

file=$(jq -r '.tool_input.file_path // empty')
repo=${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}
[[ $file == "$repo"/*.py && -f $file ]] || exit 0

cd "$repo" || exit 0
# A hook that modifies the file exits 1, so the fixing runs do not decide the result.
uvx pre-commit run ruff-check --files "$file" >/dev/null 2>&1
uvx pre-commit run ruff-format --files "$file" >/dev/null 2>&1
if ! findings=$(uvx pre-commit run ruff-check --files "$file" 2>&1); then
    printf 'ruff findings in %s:\n%s\n' "$file" "$findings" >&2
    exit 2
fi
