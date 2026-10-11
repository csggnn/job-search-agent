#!/usr/bin/env bash
# Validate docs/structurizr/workspace.dsl and render its "Containers" view to
# docs/structurizr/containers.png.
#
#   scripts/export_diagram.sh [source-dir]
#
# source-dir holds workspace.dsl and workspace.json; it defaults to docs/structurizr.
# The pre-commit hook passes a directory holding the staged versions.
#
# Structurizr and the browser run in one podman pod, so no host port is used and a
# Structurizr server already running on the host is not disturbed. Structurizr reads a
# copy of the source files: the server writes to its data directory.
set -euo pipefail

repo=$(git rev-parse --show-toplevel)
src=${1:-$repo/docs/structurizr}
out_dir=$repo/docs/structurizr
view=Containers
structurizr_image=docker.io/structurizr/structurizr
ui_image=job-search-agent-ui:diagram

work=$(mktemp -d)
pod=structurizr-export-$$
cleanup() {
    podman pod rm -f "$pod" >/dev/null 2>&1 || true
    rm -rf "$work"
}
trap cleanup EXIT

mkdir "$work/workspace" "$work/out"
cp "$src/workspace.dsl" "$src/workspace.json" "$work/workspace/"

podman run --rm -v "$work/workspace:/usr/local/structurizr:Z" "$structurizr_image" \
    validate -workspace /usr/local/structurizr/workspace.dsl

podman build -q -t "$ui_image" -f "$repo/ui/Dockerfile" "$repo" >/dev/null

podman pod create --name "$pod" --userns=keep-id >/dev/null
podman run -d --pod "$pod" --user "$(id -u):$(id -g)" \
    -v "$work/workspace:/usr/local/structurizr:Z" "$structurizr_image" local >/dev/null
podman run --rm --pod "$pod" --user "$(id -u):$(id -g)" \
    -v "$repo/scripts/export_diagram.py:/export_diagram.py:ro,Z" \
    -v "$work/out:/out:Z" \
    "$ui_image" python3 /export_diagram.py "http://localhost:8080/workspace/1/diagrams#$view" /out/containers.png

cp "$work/out/containers.png" "$out_dir/containers.png"
echo "wrote $out_dir/containers.png"
