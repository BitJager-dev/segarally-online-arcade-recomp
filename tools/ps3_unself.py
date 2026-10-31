#!/usr/bin/env python3
"""Decrypt a retail NPDRM SELF (EBOOT.BIN) to an ELF with the game's .RAP license.

Follows RPCS3's rpcs3/Crypto/unself.cpp. No keys live in this repository: they are read at run time
from RPCS3's own key_vault.cpp / key_vault.h (pass the folder holding them with --keys).

    ps3_unself.py EBOOT.BIN EBOOT.elf --rap <content>.RAP --keys <dir with key_vault.cpp/.h>
"""
import argparse
import re
import struct
import sys
import zlib
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

KEY_NPDRM = 8


def aes(key, mode, data, encrypt=False):
    c = Cipher(algorithms.AES(key), mode)
    op = c.encryptor() if encrypt else c.decryptor()
    return op.update(data) + op.finalize()


def load_keys(folder):
    h = (folder / "key_vault.h").read_text()
    cpp = (folder / "key_vault.cpp").read_text()

    def const(name):
        m = re.search(rf"\b{name}\s*\[0x10\]\s*=\s*\{{([^}}]*)\}}", h)
        if not m:
            sys.exit(f"{name} not found in key_vault.h")
        return bytes(int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{2})", m.group(1)))

    body = re.search(r"void KeyVault::LoadSelfNPDRMKeys\(\)\s*\{(.*?)\n\}", cpp, re.S)
    if not body:
        sys.exit("LoadSelfNPDRMKeys not found in key_vault.cpp")
    npdrm = {}
    for m in re.finditer(r'emplace_back\(\s*0x[0-9A-Fa-f]+,\s*0x[0-9A-Fa-f]+,\s*(0x[0-9A-Fa-f]+),\s*KEY_NPDRM,\s*'
                         r'"([0-9A-Fa-f]{64})",\s*"([0-9A-Fa-f]{32})"', body.group(1)):
        npdrm[int(m.group(1), 16)] = (bytes.fromhex(m.group(2)), bytes.fromhex(m.group(3)))
    return {"npdrm": npdrm, "NP_KLIC_KEY": const("NP_KLIC_KEY"), "RAP_KEY": const("RAP_KEY"),
            "RAP_PBOX": const("RAP_PBOX"), "RAP_E1": const("RAP_E1"), "RAP_E2": const("RAP_E2")}


def rap_to_rif(rap, k):
    key = bytearray(aes(k["RAP_KEY"], modes.CBC(bytes(16)), rap))
    pbox, e1, e2 = k["RAP_PBOX"], k["RAP_E1"], k["RAP_E2"]
    for _ in range(5):
        for i in range(16):
            key[pbox[i]] ^= e1[pbox[i]]
        for i in range(15, 0, -1):
            key[pbox[i]] ^= key[pbox[i - 1]]
        o = 0
        for i in range(16):
            p = pbox[i]
            kc = (key[p] - o) & 0xFF
            ec2 = e2[p]
            if o != 1 or kc != 0xFF:
                o = 1 if kc < ec2 else 0
                key[p] = (kc - ec2) & 0xFF
            else:
                key[p] = (kc - ec2) & 0xFF
    return bytes(key)


def u(fmt, d, off):
    return struct.unpack_from(">" + fmt, d, off)


def unself(d, rap, k):
    magic, _, flags, _, se_meta, hsize, _ = u("IIHHIQQ", d, 0)
    if magic != 0x53434500:
        sys.exit("not a SELF")
    if flags & 0x8000:
        sys.exit("debug fSELF: use ps3recomp's tools/unfself.py")
    (_, appinfo_off, ehdr_off, phdr_off, shdr_off, _, _, supp_off, supp_size, _) = u("10Q", d, 0x20)
    _, _, prog_type, _ = u("QIIQ", d, appinfo_off)
    if prog_type != KEY_NPDRM:
        sys.exit(f"program type {prog_type} is not an NPDRM application")
    if flags not in k["npdrm"]:
        sys.exit(f"no NPDRM key for revision {flags:#x} in key_vault.cpp")
    erk, riv = k["npdrm"][flags]

    # NPDRM supplemental header: license type and content ID.
    off, end, npd = supp_off, supp_off + supp_size, None
    while off < end:
        stype, ssize, _ = u("IIQ", d, off)
        if stype == 3:
            npd = d[off + 0x10:off + 0x90]
        off += ssize or end
    if not npd or npd[:4] != b"NPD\0":
        sys.exit("no NPDRM header")
    license = u("I", npd, 8)[0]
    content_id = npd[0x10:0x40].rstrip(b"\0").decode()
    print(f"content {content_id}, license {license}, key revision {flags:#x}")
    if license not in (1, 2):
        sys.exit(f"license type {license}: not a RAP-licensed title")

    # Metadata info: NPDRM layer (klicensee from the RAP), then the SELF key.
    klic = aes(k["NP_KLIC_KEY"], modes.ECB(), rap_to_rif(rap, k))
    mi_off = 0x20 + se_meta
    info = aes(klic, modes.CBC(bytes(16)), d[mi_off:mi_off + 0x40])
    info = aes(erk, modes.CBC(riv), info)
    if info[0x10] or info[0x30]:
        sys.exit("metadata did not decrypt: wrong RAP for this EBOOT?")
    hdrs = aes(info[:0x10], modes.CTR(info[0x20:0x30]), d[mi_off + 0x40:hsize], encrypt=True)
    _, _, sec_count, key_count = u("QIII", hdrs, 0)
    secs = [u("QQIIIIIIII", hdrs, 0x20 + i * 0x30) for i in range(sec_count)]
    keys_off = 0x20 + sec_count * 0x30
    data_keys = [hdrs[keys_off + i * 16:keys_off + (i + 1) * 16] for i in range(key_count)]

    # Rebuild the ELF: header, segments, section headers, then program headers last.
    ehdr = d[ehdr_off:ehdr_off + 0x40]
    if ehdr[:4] != b"\x7fELF" or ehdr[4] != 2:
        sys.exit("only 64-bit ELF payloads are handled")
    e_phoff, e_shoff = u("QQ", ehdr, 0x20)
    e_phentsize, e_phnum, e_shentsize, e_shnum = u("HHHH", ehdr, 0x36)
    phdrs = d[phdr_off:phdr_off + e_phnum * e_phentsize]
    out = bytearray(ehdr)

    def put(pos, data):
        if len(out) < pos + len(data):
            out.extend(bytes(pos + len(data) - len(out)))
        out[pos:pos + len(data)] = data

    for data_off, data_size, stype, pidx, _, _, enc, kidx, ividx, comp in secs:
        if stype != 2:
            continue
        blob = d[data_off:data_off + data_size]
        if enc == 3:
            blob = aes(data_keys[kidx], modes.CTR(data_keys[ividx]), blob, encrypt=True)
        p_offset, = u("Q", phdrs, pidx * e_phentsize + 0x08)
        p_filesz, = u("Q", phdrs, pidx * e_phentsize + 0x20)
        if comp == 2:
            blob = zlib.decompress(blob)
            if len(blob) != p_filesz:
                print(f"warning: segment {pidx} inflated to {len(blob):#x}, expected {p_filesz:#x}")
        put(p_offset, blob)
    if shdr_off:
        put(e_shoff, d[shdr_off:shdr_off + e_shnum * e_shentsize])
    put(e_phoff, phdrs)
    return bytes(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("self")
    ap.add_argument("elf")
    ap.add_argument("--rap", required=True)
    ap.add_argument("--keys", required=True, type=Path)
    a = ap.parse_args()
    rap = Path(a.rap).read_bytes()
    if len(rap) != 16:
        sys.exit("a .RAP file is 16 bytes")
    elf = unself(Path(a.self).read_bytes(), rap, load_keys(a.keys))
    Path(a.elf).write_bytes(elf)
    print(f"wrote {a.elf} ({len(elf)} bytes)")


if __name__ == "__main__":
    main()
