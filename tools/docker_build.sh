#!/usr/bin/env bash
# Build the Linux port in the container (docker/Dockerfile), then test-boot it on the host.
#
#   tools/docker_build.sh            # build in the container + 60 s test boot here
#   tools/docker_build.sh --no-run   # build only
#   tools/docker_build.sh --shell    # interactive shell in the build environment
#
# The xbla folder (this project and ../deps) is mounted at the same absolute path, so the
# paths CMake records stay valid on the host, and the container runs as you, so everything
# it writes is yours. Output: out/linux-docker (its own CMake tree, apart from out/linux).
# The test boot runs on the host: it needs the GPU, the display and the controller.
# Other settings (JOBS=, BOOT_SECONDS=, SKIP_INTRO=, ...) pass through to tools/build_linux.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
XBLA="$(cd "$ROOT/.." && pwd)"
DEPS="$XBLA/deps"
IMAGE=segarally-recomp-build
export BUILD_DIR="${BUILD_DIR:-out/linux-docker}"

# Rebuild the image when the Dockerfile or ps3recomp's Python requirements change.
ctx="$(mktemp -d)"; trap 'rm -rf "$ctx"' EXIT
cp "$ROOT/docker/Dockerfile" "$DEPS/ps3recomp/requirements.txt" "$ctx/"
tag="$(cat "$ctx"/* | sha256sum | cut -c1-12)"
if ! docker image inspect "$IMAGE:$tag" >/dev/null 2>&1; then
  echo "== Building the $IMAGE:$tag image"
  docker build -t "$IMAGE:$tag" -t "$IMAGE:latest" "$ctx"
fi

run=(docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp
     -v "$XBLA:$XBLA" -w "$ROOT"
     -e BUILD_DIR -e JOBS -e SKIP_INTRO)
if [[ "${1:-}" == "--shell" ]]; then
  exec "${run[@]}" -it "$IMAGE:$tag" bash
fi

# git refuses a repository owned by another uid unless told; the uid is the same here,
# but HOME=/tmp has no config, so say it once for the ps3recomp checkout.
"${run[@]}" "$IMAGE:$tag" bash -c \
  "git config --global --add safe.directory '$DEPS/ps3recomp' && tools/build_linux.sh --no-run"
echo "build log: logs/build.log"

[[ "${1:-}" == "--no-run" ]] && exit 0
"$ROOT/tools/build_linux.sh" --no-build
