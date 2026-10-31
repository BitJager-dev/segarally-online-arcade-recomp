#!/usr/bin/env python3
"""Extract a retail (finalized) PS3 .pkg.

The package body is AES-128-CTR with the PS3 package key; the counter starts at the
header's 16-byte IV plus the block index. The executables inside stay encrypted
(NPDRM SELF): this only unpacks the container. The key is read from RPCS3's own
key_vault.h (pass the folder holding it with --keys), not stored here.

    ps3_pkg_extract.py <in.pkg> <out_dir> --keys <dir with key_vault.h> [--list]
"""
import os
import re
import struct
import sys

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

CHUNK = 1 << 22


def load_pkg_key(folder):
    h = open(os.path.join(folder, "key_vault.h")).read()
    m = re.search(r"\bPKG_AES_KEY\s*\[0x10\]\s*=\s*\{([^}]*)\}", h)
    if not m:
        sys.exit("PKG_AES_KEY not found in key_vault.h")
    return bytes(int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{2})", m.group(1)))


class Pkg:
    def __init__(self, path, key):
        self.key = key
        self.f = open(path, "rb")
        h = self.f.read(0x80)
        if h[:4] != b"\x7fPKG":
            sys.exit(f"{path}: not a PKG")
        rev, ptype = struct.unpack_from(">HH", h, 4)
        if rev != 0x8000 or ptype != 1:
            sys.exit(f"{path}: revision {rev:#x} type {ptype}: only finalized PS3 packages are handled")
        self.item_count, = struct.unpack_from(">I", h, 0x14)
        self.data_off, self.data_size = struct.unpack_from(">QQ", h, 0x20)
        self.content_id = h[0x30:0x60].rstrip(b"\0").decode()
        self.iv = int.from_bytes(h[0x70:0x80], "big")

    def read(self, off, size):
        """Decrypt `size` bytes at body offset `off` (16-byte aligned)."""
        assert off % 16 == 0
        ctr = ((self.iv + off // 16) % (1 << 128)).to_bytes(16, "big")
        dec = Cipher(algorithms.AES(self.key), modes.CTR(ctr)).decryptor()
        self.f.seek(self.data_off + off)
        return dec.update(self.f.read(size))

    def entries(self):
        table = self.read(0, self.item_count * 0x20)
        for i in range(self.item_count):
            name_off, name_size, off, size, flags = struct.unpack_from(">IIQQI", table, i * 0x20)
            start = name_off & ~15
            name = self.read(start, (name_off - start + name_size + 15) & ~15)
            name = name[name_off - start:name_off - start + name_size].decode("utf-8", "replace")
            yield name, off, size, flags & 0xFF


def main():
    args = sys.argv[1:]
    listing = "--list" in args
    if "--keys" not in args or args.index("--keys") + 1 >= len(args):
        sys.exit(__doc__)
    i = args.index("--keys")
    keys = args[i + 1]
    del args[i:i + 2]
    args = [a for a in args if a != "--list"]
    if len(args) < 2:
        sys.exit(__doc__)
    pkg, out = Pkg(args[0], load_pkg_key(keys)), args[1]
    print(f"{pkg.content_id}: {pkg.item_count} items")
    for name, off, size, kind in pkg.entries():
        dest = os.path.join(out, name.lstrip("/"))
        if os.path.relpath(dest, out).startswith(".."):
            sys.exit(f"unsafe path in package: {name}")
        if kind == 4:  # directory
            if not listing:
                os.makedirs(dest, exist_ok=True)
            continue
        print(f"{size:12d}  {name}")
        if listing:
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as o:
            done = 0
            while done < size:
                n = min(CHUNK, size - done)
                o.write(pkg.read(off + done, (n + 15) & ~15)[:n])
                done += n


if __name__ == "__main__":
    main()
