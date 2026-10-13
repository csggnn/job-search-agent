#!/usr/bin/env bash
# Run ruff from a pinned container image. Arguments pass through to ruff.
#
#   scripts/ruff.sh check .
#   scripts/ruff.sh check --fix jobsearch/storage.py
#
# The repository is mounted at its host path, so absolute host paths and paths relative to
# the current directory resolve inside the container. Configuration is read from
# pyproject.toml. The container has no network access and runs as the calling user, so
# fixed files and .ruff_cache/ keep the caller's ownership.
set -euo pipefail

# The tag names the version; the digest fixes the image, since a tag can be re-pushed.
image=ghcr.io/astral-sh/ruff:0.16.9@sha256:fd4a00e8f586c07495822a1c93702737b9a98d826b76d460caa514df7794f259
repo=$(git rev-parse --show-toplevel)

exec podman run --rm -i --network none --userns=keep-id --security-opt label=disable \
    -v "$repo:$repo" -w "$PWD" "$image" "$@"
