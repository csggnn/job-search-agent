#!/usr/bin/env bash
# Profile maintenance for the checkout that holds this script. Runs on the host or in the
# container.
#
#   scripts/profile.sh reset-default
#       Remove the default profile's evaluations.db, compatibility_rubric.json and
#       search_queries.json. Its resume.md, job_preferences.md and evals/ are kept. The
#       personal profile is not touched.
set -euo pipefail

checkout="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
default_profile="$checkout/profiles/default"

case "${1:-}" in
    reset-default)
        rm -f "$default_profile/evaluations.db" \
              "$default_profile/compatibility_rubric.json" \
              "$default_profile/search_queries.json"
        echo "reset $default_profile"
        ;;
    *)
        echo "usage: $0 reset-default" >&2
        exit 2
        ;;
esac
