#!/usr/bin/env python3
"""Bind a packaged formal_receipt.py's current-epoch compat pins to the flat
Linux proof-identity bytes the package ships (range + int-cert)."""
import sys, pathlib

fr = pathlib.Path(sys.argv[1]); range_sha, int_sha = sys.argv[2], sys.argv[3]
s = fr.read_text()
range_call = (
    '        "file_sha256": _host_current_identity_sha(\n'
    '            "range_proof_identity_v172.json",\n'
    '            "84963be9b0a8851a03a38ae71da558b3e9d2c37d9d55ad7da31afbd23188499c",\n'
    '        ),'
)
int_call = (
    '        "file_sha256": _host_current_identity_sha(\n'
    '            "int_cert_proof_identity_v172.json",\n'
    '            "a8aefff85666d35cfd5412b10ae3d404260e91a98de53d5f0d2bb9f88f4ffbdf",\n'
    '        ),'
)
if range_call not in s or int_call not in s:
    sys.exit("BAKE_REFUSED detail=host-aware compat pin calls not found in packaged formal_receipt.py")
s = s.replace(range_call, f'        "file_sha256": "{range_sha}",', 1)
s = s.replace(int_call, f'        "file_sha256": "{int_sha}",', 1)
fr.write_text(s)
print(f"BAKED range={range_sha[:12]} int={int_sha[:12]}")
