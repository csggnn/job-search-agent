#!/usr/bin/env bash
# Remove the default profile's evaluations.db, compatibility_rubric.json and
# search_queries.json, in the checkout that holds this script. Its resume.md,
# job_preferences.md and evals/ are kept. The personal profile is not touched. Runs on the
# host or in the container.
set -euo pipefail

checkout="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
default_profile="$checkout/profiles/default"

rm -f "$default_profile/evaluations.db" \
      "$default_profile/compatibility_rubric.json" \
      "$default_profile/search_queries.json"
echo "reset $default_profile"
