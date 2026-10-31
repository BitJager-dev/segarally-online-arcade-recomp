#!/usr/bin/env python3
"""Install /dev_flash from an official PS3 firmware update (PS3UPDAT.PUP).

Follows RPCS3's firmware installer (rpcs3qt/main_window.cpp, Crypto/unself.cpp SCEDecrypter):
update_files.tar (PUP entry 0x300) holds dev_flash_*.tar.aa.* packages; each is an SCE package
whose metadata decrypts with the SCEPKG key, and whose third section is a tar of dev_flash files.
As with ps3_unself.py, the key is read at run time from RPCS3's key_vault.h (--keys); none is
stored here.

    ps3_pup_devflash.py PS3UPDAT.PUP <out dir> --keys <dir with key_vault.h>

The files land in <out dir>/dev_flash/...
"""
import argparse
import io
import re
import sys
import tarfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ps3_unself import aes, modes, u  # noqa: E402


def load_pkg_key(folder):
    h = (folder / "key_vault.h").read_text()

    def const(name, n):
        m = re.search(rf"\b{name}\s*\[{n:#x}\]\s*=\s*\{{([^}}]*)\}}", h)
        if not m:
            sys.exit(f"{name} not found in key_vault.h")
        return bytes(int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{2})", m.group(1)))

    return const("SCEPKG_ERK", 0x20), const("SCEPKG_RIV", 0x10)


def pup_entry(d, entry_id):
    if d[:5] != b"SCEUF":
        sys.exit("not a PS3UPDAT.PUP")
    count, = u("Q", d, 0x18)
    for i in range(count):
        eid, off, size = u("QQQ", d, 0x30 + i * 0x20)
        if eid == entry_id:
            return d[off:off + size]
    sys.exit(f"PUP has no entry {entry_id:#x}")


def sce_sections(d, erk, riv):
    """SCEDecrypter: every metadata section, decrypted and inflated, in order."""
    magic, _, flags, _, se_meta, hsize = u("IIHHIQ", d, 0)
    if magic != 0x53434500:
        sys.exit("package is not an SCE file")
    mi_off = 0x20 + se_meta
    info = d[mi_off:mi_off + 0x40]
    if not flags & 0x8000:
        info = aes(erk, modes.CBC(riv), info)
    if info[0x10] or info[0x30]:
        sys.exit("SCE metadata did not decrypt (wrong key_vault.h?)")
    hdrs = aes(info[:0x10], modes.CTR(info[0x20:0x30]), d[mi_off + 0x40:hsize], encrypt=True)
    _, _, sec_count, key_count = u("QIII", hdrs, 0)
    keys_off = 0x20 + sec_count * 0x30
    keys = [hdrs[keys_off + i * 16:keys_off + (i + 1) * 16] for i in range(key_count)]
    out = []
    for i in range(sec_count):
        data_off, data_size, _, _, _, _, enc, kidx, ividx, comp = u("QQIIIIIIII", hdrs, 0x20 + i * 0x30)
        blob = d[data_off:data_off + data_size]
        if enc == 3:
            blob = aes(keys[kidx], modes.CTR(keys[ividx]), blob, encrypt=True)
        if comp == 2:
            try:
                blob = zlib.decompress(blob)
            except zlib.error:
                continue          # RPCS3 drops a section that does not inflate, too
        out.append(blob)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pup")
    ap.add_argument("out", type=Path)
    ap.add_argument("--keys", required=True, type=Path)
    a = ap.parse_args()
    erk, riv = load_pkg_key(a.keys)

    update_files = tarfile.open(fileobj=io.BytesIO(pup_entry(Path(a.pup).read_bytes(), 0x300)))
    pkgs = [m for m in update_files.getmembers() if "dev_flash_" in m.name and m.isfile()]
    if not pkgs:
        sys.exit("no dev_flash_* packages in update_files.tar")
    a.out.mkdir(parents=True, exist_ok=True)
    files = 0
    for m in pkgs:
        secs = sce_sections(update_files.extractfile(m).read(), erk, riv)
        if len(secs) < 3:
            sys.exit(f"{m.name}: fewer than 3 sections")
        with tarfile.open(fileobj=io.BytesIO(secs[2])) as t:
            members = t.getmembers()
            t.extractall(a.out, filter="data")      # refuses absolute paths and ../
            files += sum(1 for x in members if x.isfile())
        print(f"{m.name}: {len(members)} entries")
    print(f"{len(pkgs)} packages, {files} files -> {a.out}")


if __name__ == "__main__":
    main()
