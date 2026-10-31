#!/usr/bin/env bash
# ps3recomp phases 3-5 (docs/GAME_PORTING_GUIDE.md) on the decrypted EBOOT.
#   tools/recomp_pipeline.sh [EBOOT.elf]
# Default ELF: game/EBOOT.elf (the 1.01 update's EBOOT.BIN, decrypted by RPCS3).
set -euo pipefail

here=$(cd "$(dirname "$0")/.." && pwd)
deps=$(cd "$here/../deps" && pwd)
elf=$(realpath "${1:-$here/game/EBOOT.elf}")
# -s/-E, not -I: the tools import sibling modules from their own folder.
py="$deps/ps3-venv/bin/python -s -E"
t="$deps/ps3recomp/tools"

head -c 4 "$elf" | grep -q $'\x7fELF' || { echo "$elf is not a decrypted ELF" >&2; exit 1; }

cd "$here"
mkdir -p analysis generated

# Phase 3: ELF + imports
$py "$t/elf_parser.py" "$elf" --all     > analysis/elf_info.json
$py "$t/elf_parser.py" "$elf" --imports > analysis/imports.json

# Phase 4: function boundaries (OPD table, then heuristic scan seeded from it)
$py "$t/ppu_loader.py" "$elf" -o analysis/
$py "$t/find_functions.py" "$elf" --seed-json analysis/EBOOT.functions.json \
    --output analysis/functions.json
$py "$t/extract_spu_images.py" "$elf" --output analysis/spu_programs/

# Phase 5: PPU -> C++, HLE import stubs, HLE handler table
$py "$t/ppu_lifter.py" "$elf" --functions analysis/EBOOT.functions.json \
    --hle-stubs analysis/EBOOT.imports.json --output generated/
$py "$t/gen_hle_nids.py" --all --out generated/ppu_hle_nids.cpp

echo "functions: $(python3 -I -c 'import json,sys; print(len(json.load(open(sys.argv[1]))))' analysis/EBOOT.functions.json)"
ls generated | wc -l
