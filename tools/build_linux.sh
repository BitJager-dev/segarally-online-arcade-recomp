#!/usr/bin/env bash
# Native Linux build of the recompiled game, then a short test boot.
#
#   tools/build_linux.sh            # build + 60 s test boot (log: logs/boot.log)
#   tools/build_linux.sh --no-run   # build only
#   tools/build_linux.sh --no-build # test boot of an existing build only (log: logs/run.log)
#   tools/docker_build.sh           # the same, building in the container (docker/Dockerfile)
#   BOOT_SECONDS=300 tools/build_linux.sh
#
# Needs: clang, ninja, sdl2 (or sdl2-compat); vulkan-headers for the Vulkan renderer
# (without them the build uses ps3recomp's headless "null" renderer). CMake comes from
# ../deps/tools-venv if it is not installed. Each lifted file is ~600k lines, so the
# default is 6 parallel jobs (several GB of RAM each); override with JOBS=.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPS="$(cd "$ROOT/../deps" && pwd)"
JOBS="${JOBS:-6}"
MODE="${1:-}"
BUILD="${BUILD_DIR:-$ROOT/out/linux}"
[[ "$BUILD" = /* ]] || BUILD="$ROOT/$BUILD"
PY="${PS3_PYTHON:-$DEPS/ps3-venv/bin/python}"   # ps3recomp's Python tools
LOG="$ROOT/logs/build.log"
[[ "$MODE" == "--no-build" ]] && LOG="$ROOT/logs/run.log"
mkdir -p "$ROOT/logs"
exec > >(tee "$LOG") 2>&1
export CC="${CC:-clang}" CXX="${CXX:-clang++}"
command -v cmake >/dev/null || export PATH="$DEPS/tools-venv/bin:$PATH"
die() { printf '\nFAILED: %s\nLogs: %s/logs/\n' "$*" "$ROOT" >&2; exit 1; }

EXE="$BUILD/segarally_online_arcade"
if [[ "$MODE" != "--no-build" ]]; then
[[ -f "$ROOT/generated/ppu_recomp.h" ]] || die "no generated/ppu_recomp.h: run tools/setup_ps3.sh first"

# Runtime fixes this title needs in ps3recomp (patches/), applied once to ../deps/ps3recomp.
for p in "$ROOT"/patches/ps3recomp-*.patch; do
  [[ -f "$p" ]] || continue
  if git -C "$DEPS/ps3recomp" apply --reverse --check "$p" 2>/dev/null; then continue; fi
  echo "== Applying $(basename "$p")"
  git -C "$DEPS/ps3recomp" apply "$p" || die "patch $(basename "$p") does not apply to ps3recomp"
done

# SPU programs (the game uses cellSpurs). Extraction only; lifting them comes later.
if [[ ! -d "$ROOT/analysis/spu_programs" ]]; then
  echo "== SPU programs"
  "$PY" -s -E "$DEPS/ps3recomp/tools/extract_spu_images.py" \
    "$ROOT/game/EBOOT.elf" --output "$ROOT/analysis/spu_programs/" || echo "(SPU extraction failed; continuing)"
fi

echo "== Configure"
VULKAN=OFF
[[ -f /usr/include/vulkan/vulkan.h ]] && VULKAN=ON
echo "Vulkan renderer: $VULKAN"
cmake -S "$ROOT" -B "$BUILD" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_C_COMPILER="$CC" -DCMAKE_CXX_COMPILER="$CXX" \
  -DPS3RECOMP_RSX_VULKAN="$VULKAN" \
  -DPython3_EXECUTABLE="$PY" \
  -DPORT_SPU_INPUTS="$ROOT/game/EBOOT.elf" || die "configure"   # lift the embedded SPU programs

echo "== Build ($JOBS jobs; the lifted files take a while)"
start=$(date +%s)
cmake --build "$BUILD" --parallel "$JOBS" || die "build"
echo "build time: $(( ($(date +%s) - start) / 60 )) min"
[[ -x "$EXE" ]] || die "no executable at $EXE"
ls -la "$EXE"

[[ "$MODE" == "--no-run" ]] && exit 0
fi
[[ -x "$EXE" ]] || die "no executable at $EXE (build first)"

# Game data: /dev_hdd0/game/NPUB30375 = base game + 1.01 update (reflink copies on btrfs,
# so no extra disk space there).
HDD0="$ROOT/run/dev_hdd0"
TITLE="$HDD0/game/NPUB30375"
if [[ ! -f "$TITLE/.staged" ]]; then
  echo "== Staging game data in $TITLE"
  mkdir -p "$TITLE" "$HDD0/home/00000001/exdata"
  cp -a --reflink=auto "$DEPS/segarally_ps3/game/." "$TITLE/"
  cp -a --reflink=auto "$DEPS/segarally_ps3/update/." "$TITLE/"
  cp -a "$DEPS/segarally_ps3/pkg/UP0177-NPUB30375_00-SEGARALLYARCADE1.RAP" \
    "$HDD0/home/00000001/exdata/UP0177-NPUB30375_00-SEGARALLYARCADE1.rap"
  touch "$TITLE/.staged"
fi

# SKIP_INTRO=1 skips the intro movie (LOGOS.USM): the game skips a movie it cannot open, so only
# the run/ copy is renamed. Off by default since the audio engine runs.
MOV="$TITLE/USRDIR/MOVIES/LOGOS.USM"
if [[ "${SKIP_INTRO:-0}" == 1 ]]; then [[ -f "$MOV" ]] && mv "$MOV" "$MOV.skip"
else [[ -f "$MOV.skip" ]] && mv "$MOV.skip" "$MOV"; fi

BOOT_SECONDS="${BOOT_SECONDS:-60}"
echo "== Test boot (${BOOT_SECONDS} s) -> logs/boot.log"
cd "$ROOT/run"
# PS3_VERBOSE=1 logs every syscall: gigabytes a minute, and it changes the timing enough to
# hide or cause hangs. Off by default here.
# PS3RECOMP_VK_GUEST_PROGRAMS=1: translate the game's own shaders (without it every frame is black).
# PS3RECOMP_VK_WINDOW=1 shows the output when a display is available; every 60th frame is also
# written to logs/frame.ppm (converted to logs/frame.png below).
rm -f "$ROOT/logs/frame.ppm" "$ROOT/logs/frame.png"
[[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]] && export PS3RECOMP_VK_WINDOW="${PS3RECOMP_VK_WINDOW:-1}"
# /dev_flash from your firmware (tools/ps3_pup_devflash.py): the MultiStream audio SPU program
# loads its ATRAC decoder (flashATRAC.pic) from it. The build lifts that decoder at the address
# it runs at (tools/lift_spu_overlays.py); SPU_INTERP_UNLIFTED=1 interprets any run-time SPU
# code that has no lifted copy instead of stopping the SPU there.
FLASH="$DEPS/ps3fw/root/dev_flash"
[[ -d "$FLASH" ]] && export PS3_DEV_FLASH="${PS3_DEV_FLASH:-$FLASH}"
PS3RECOMP_VK_GUEST_PROGRAMS="${PS3RECOMP_VK_GUEST_PROGRAMS:-1}" \
PS3RECOMP_VK_DUMP="$ROOT/logs/frame.ppm" PS3RECOMP_VK_DUMP_EVERY=60 \
SPU_INTERP_UNLIFTED="${SPU_INTERP_UNLIFTED:-1}" PS3_VERBOSE="${PS3_VERBOSE:-0}" PS3_HDD0_ROOT="$HDD0" PS3_VFS_ROOT="$TITLE" PS3_STDIO_UNBUFFERED=1 \
  timeout -s KILL "$BOOT_SECONDS" "$EXE" "$ROOT/game/EBOOT.elf" > "$ROOT/logs/boot.log" 2>&1
rc=$?
echo "exit code: $rc (137 = stopped by the ${BOOT_SECONDS} s timer)"
echo "boot log: $(wc -l < "$ROOT/logs/boot.log") lines"
tail -25 "$ROOT/logs/boot.log"
echo "== How far it got"
grep -E "^\[fs\] open '" "$ROOT/logs/boot.log" | tail -5
if [[ -f "$ROOT/logs/frame.ppm" ]]; then
  python3 -I - "$ROOT/logs/frame.ppm" "$ROOT/logs/frame.png" <<'PY' && echo "last frame: logs/frame.png"
import sys, zlib, struct
b = open(sys.argv[1], 'rb').read()
hdr = b.split(b'\n', 3); w, h = map(int, hdr[1].split()); px = hdr[3]
raw = b''.join(b'\x00' + px[y * w * 3:(y + 1) * w * 3] for y in range(h))
def chunk(t, d): return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
open(sys.argv[2], 'wb').write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
                              + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))
PY
fi
printf '\nDone. Tell Claude: "build_linux finished".\n'
