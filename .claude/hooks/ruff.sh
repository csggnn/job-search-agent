#!/usr/bin/env bash
# Claude Code PostToolUse hook for Edit and Write. Applies ruff fixes and formatting to the
# edited Python file. Findings ruff cannot fix go to stderr with exit status 2, which Claude
# Code returns to Claude. Files outside the project directory are skipped.
set -uo pipefail

file=$(jq -r '.tool_input.file_path // empty')
repo=${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}
[[ $file == "$repo"/*.py && -f $file ]] || exit 0

cd "$repo" || exit 0
findings=$(scripts/ruff.sh check --fix --force-exclude --quiet "$file" 2>&1)
check=$?
scripts/ruff.sh format --force-exclude --quiet "$file" >/dev/null 2>&1
if [[ $check -ne 0 ]]; then
    printf 'ruff findings in %s:\n%s\n' "$file" "$findings" >&2
    exit 2
fi
