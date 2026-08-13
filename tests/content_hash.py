#!/usr/bin/env python3
"""Reproducible content hash for a JACKAL native binary (Mach-O arm64).

Measured 2026-08-13: rebuilding identical source with the pinned Anubis
compiler produces byte-identical machine code and data on every build — the
only bytes that vary are linker metadata (LC_UUID, __LINKEDIT symbol/signature
region, 16 bytes of load-command headers). So the honest reproducibility
statement is segment-scoped: this tool hashes the parts of the binary that ARE
the program — every executable byte of __TEXT past the header page, plus all
of __DATA_CONST and __DATA — and excludes Mach-O headers, load commands and
__LINKEDIT, which carry per-link metadata by design of the Apple toolchain.

Two builds of the same source must agree on this hash; a build of different
source must not. Usage:

    python3 tests/content_hash.py jackal-native [more binaries...]
"""
from __future__ import annotations

import hashlib
import struct
import sys

LC_SEGMENT_64 = 0x19
PAGE = 16384
HASHED_SEGMENTS = ("__TEXT", "__DATA_CONST", "__DATA")


def content_hash(path: str) -> str:
    data = open(path, "rb").read()
    magic = struct.unpack_from("<I", data, 0)[0]
    if magic != 0xFEEDFACF:
        raise SystemExit(f"{path}: not a 64-bit little-endian Mach-O (magic {magic:#x})")
    ncmds = struct.unpack_from("<I", data, 16)[0]
    digest = hashlib.sha256()
    off = 32
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, off)
        if cmd == LC_SEGMENT_64:
            name = data[off + 8:off + 24].rstrip(b"\0").decode()
            fileoff, filesize = struct.unpack_from("<QQ", data, off + 40)
            if name in HASHED_SEGMENTS and filesize > 0:
                start = fileoff
                if name == "__TEXT":
                    # skip the header page: Mach-O header + load commands
                    # (LC_UUID et al.) live in __TEXT's first page
                    start = fileoff + PAGE
                digest.update(name.encode() + b"\0")
                digest.update(data[start:fileoff + filesize])
        off += cmdsize
    return digest.hexdigest()


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    for path in sys.argv[1:]:
        print(f"{content_hash(path)}  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
