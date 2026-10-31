#!/usr/bin/env bash
# One-time setup for the PS3 recomp: decrypted EBOOT, then the recompile pipeline.
# Safe to run again.
#   tools/setup_ps3.sh
# Log: setup_ps3.log next to this project's README.
set -uo pipefail

here=$(cd "$(dirname "$0")/.." && pwd)
deps=$(cd "$here/../deps" && pwd)
src="$deps/segarally_ps3"
keys="$deps/rpcs3src"
rap="$src/pkg/UP0177-NPUB30375_00-SEGARALLYARCADE1.RAP"
exec > >(tee "$here/setup_ps3.log") 2>&1

step() { printf '\n== %s\n' "$*"; }
die()  { printf '\nFAILED: %s\nSee %s/setup_ps3.log\n' "$*" "$here" >&2; exit 1; }

step "1/3 Decrypt EBOOT.BIN (1.01) with your RAP"
if [ ! -f "$here/game/EBOOT.elf" ]; then
    [ -f "$rap" ] || die "missing $rap"
    mkdir -p "$keys"
    for f in key_vault.cpp key_vault.h; do     # keys come from RPCS3's source, not from this repo
        [ -s "$keys/$f" ] || curl -fsSL -o "$keys/$f" "https://raw.githubusercontent.com/RPCS3/rpcs3/master/rpcs3/Crypto/$f" ||
            die "could not download RPCS3's $f"
    done
    [ -f "$src/update/USRDIR/EBOOT.BIN" ] ||
        python3 -I "$here/tools/ps3_pkg_extract.py" "$src/pkg/UPDATE1.01.pkg" "$src/update" --keys "$keys" ||
        die "update extraction failed"
    mkdir -p "$here/game"
    python3 -I "$here/tools/ps3_unself.py" "$src/update/USRDIR/EBOOT.BIN" "$here/game/EBOOT.elf" \
        --rap "$rap" --keys "$keys" || die "decryption failed"
fi
head -c 4 "$here/game/EBOOT.elf" | grep -q $'\x7fELF' || die "game/EBOOT.elf is not an ELF"
echo "ok: $here/game/EBOOT.elf"

step "2/3 Python environment for ps3recomp"
if [ ! -x "$deps/ps3-venv/bin/python" ]; then
    python3 -m venv "$deps/ps3-venv" &&
    "$deps/ps3-venv/bin/pip" install -q -r "$deps/ps3recomp/requirements.txt" || die "venv setup failed"
fi
echo "ok: $deps/ps3-venv"

step "3/3 Recompile pipeline (analysis, functions, PPU lift)"
"$here/tools/recomp_pipeline.sh" "$here/game/EBOOT.elf" || die "pipeline failed (the ELF is in place; Claude can take it from here)"

printf '\nAll done. Tell Claude: "setup_ps3 finished".\n'
