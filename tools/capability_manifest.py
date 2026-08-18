#!/usr/bin/env python3
"""W2 — machine-owned capability manifest generator + parity gate.

The capability manifest (release/capabilities/jackal_capabilities_v1.json) is
a DETERMINISTIC function of the repository's real truth surfaces:

  * tools                 <- plugin/hermes/tools.json
  * refusal vocabulary    <- REASON_CLASSES in tools/claim_bundle_verify.py
                             and tools/exact_verify.py (AST-extracted)
  * assurance ceilings    <- axis orders in tools/claim_bundle_verify.py
  * coverage inventory    <- release/coverage/formal_coverage_inventory.json
  * epochs / schemas      <- tools/claim_kernel.py
  * platform              <- .github/workflows/jackal-codex-plugin.yml host gate
  * bundle admissibility  <- declared context ids + DERIVED revoked-lane absence
  * skills / packs / profiles / docs <- on-disk presence

`--emit`  regenerates and writes the manifest (canonical, sorted, no volatile
          fields).
`--check` regenerates in memory and asserts byte-parity with the committed
          manifest; fail-closed on any drift (exit 1).  This is the W2 gate.

No timestamps or environment-specific fields: the manifest is reproducible.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "release/capabilities/jackal_capabilities_v1.json"
SCHEMA_ID = "jackal-capabilities-v1"

# Declared protocol facts owned by this generator (SPEC section 10 / MIGRATION).
ADMITTED_CONTEXTS = (
    "current-v1.7.2-range-rational",
    "archival-v1.5.0-range-rational",
    "gaussian-v1.5.0",
    "current-v1.7.2-int-cert-request-bound",
)
REVOKED_LANES = ("int-cert-v1.7.0-request-unbound",)
# The revoked request-unbound v1.7.0 int-cert checker: must NEVER be present.
REVOKED_CHECKER_SHA256 = (
    "c858e3bfc0ff2809a808170caabbf090077cb54996e76f065dbcd26ffb067d49"
)
REQUIRED_DOCS = (
    "README.md",
    "release/claim/SPEC.md",
    "plugin/hermes/tools.json",
)


def _module_const(pyfile: Path, name: str):
    """AST-extract a module-level literal constant (no code execution)."""
    tree = ast.parse(pyfile.read_text(encoding="utf-8"), filename=str(pyfile))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    return ast.literal_eval(node.value)
    raise KeyError(f"{name} not found in {pyfile}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sorted_list(seq) -> list:
    return sorted(seq)


def derive_tools() -> dict:
    doc = json.loads((ROOT / "plugin/hermes/tools.json").read_text("utf-8"))
    names = _sorted_list(t["name"] for t in doc["tools"])
    return {"count": len(names), "names": names}


def derive_refusal_vocabulary() -> dict:
    cbv = _module_const(ROOT / "tools/claim_bundle_verify.py", "REASON_CLASSES")
    exv = _module_const(ROOT / "tools/exact_verify.py", "REASON_CLASSES")
    return {
        "claim_bundle_verify": _sorted_list(cbv),
        "exact_verify": _sorted_list(exv),
    }


def derive_assurance_ceilings() -> dict:
    cbv = ROOT / "tools/claim_bundle_verify.py"
    impl_order = list(_module_const(cbv, "IMPL_ORDER"))
    return {
        "input_provenance_order": list(_module_const(cbv, "PROV_ORDER")),
        "model_validity_order": list(_module_const(cbv, "MODEL_ORDER")),
        "model_identity": _module_const(cbv, "MODEL_IDENTITY"),
        "mathematical_order": list(_module_const(cbv, "MATH_ORDER")),
        "mathematical_ranks": _module_const(cbv, "MATH_RANKS"),
        "implementation_order": impl_order,
        "artifact_flags": list(_module_const(cbv, "ARTIFACT_FLAGS")),
        "producer_emittable_provenance": _sorted_list(
            _module_const(cbv, "PRODUCER_EMITTABLE_PROV")),
        "never_granted_implementation": ["source-native-refined"],
    }


def derive_coverage_inventory() -> dict:
    p = ROOT / "release/coverage/formal_coverage_inventory.json"
    doc = json.loads(p.read_text("utf-8"))
    return {
        "sha256": _sha256(p),
        "formal_fragment": _sorted_list(doc["formal_fragment"]),
        "refused_from_formal": _sorted_list(doc["refused_from_formal"]),
        "rows": len(doc["rows"]),
    }


def derive_epochs() -> dict:
    ck = ROOT / "tools/claim_kernel.py"
    return {
        "claim_release_epoch": _module_const(ck, "RELEASE_EPOCH"),
        "schemas": {
            "node": _module_const(ck, "SCHEMA_NODE"),
            "bundle": _module_const(ck, "SCHEMA_BUNDLE"),
            "policy": _module_const(ck, "SCHEMA_POLICY"),
            "machine": _module_const(ck, "SCHEMA_MACHINE"),
        },
    }


def derive_platform() -> dict:
    wf = (ROOT / ".github/workflows/jackal-codex-plugin.yml").read_text("utf-8")
    os_ = "Darwin" if 'uname -s)" = Darwin' in wf else "unknown"
    arch = "arm64" if 'uname -m)" = arm64' in wf else "unknown"
    return {"os": os_, "arch": arch}


def _revoked_present() -> bool:
    """True iff the revoked checker sha appears in any pinned truth surface."""
    surfaces = [
        ROOT / "release/MANIFEST.sha256",
        ROOT / "release/coverage/formal_coverage_inventory.json",
    ]
    for s in surfaces:
        if s.exists() and REVOKED_CHECKER_SHA256 in s.read_text("utf-8"):
            return True
    return False


def derive_admissibility() -> dict:
    return {
        "admitted_contexts": list(ADMITTED_CONTEXTS),
        "revoked_lanes": list(REVOKED_LANES),
        "revoked_checker_sha256": REVOKED_CHECKER_SHA256,
        "revoked_checker_present_in_repo": _revoked_present(),
    }


def _glob_rel(pattern: str) -> list:
    return _sorted_list(str(p.relative_to(ROOT)) for p in ROOT.glob(pattern))


def derive_skills() -> list:
    return _glob_rel("plugins/jackel/skills/**/*.md") + _glob_rel(
        "plugin/hermes/skills/**/*.md")


def derive_packs() -> list:
    return _sorted_list(
        str(p.relative_to(ROOT)) for p in ROOT.glob("domain_packs/*")
        if p.is_dir())


def derive_profiles() -> list:
    return _glob_rel("plugin/hermes/profiles/*.json")


def derive_docs() -> dict:
    return {d: (ROOT / d).exists() for d in REQUIRED_DOCS}


def build_manifest() -> dict:
    return {
        "schema": SCHEMA_ID,
        "assurance_ceilings": derive_assurance_ceilings(),
        "bundle_admissibility": derive_admissibility(),
        "coverage_inventory": derive_coverage_inventory(),
        "docs": derive_docs(),
        "epochs": derive_epochs(),
        "packs": derive_packs(),
        "platform": derive_platform(),
        "profiles": derive_profiles(),
        "refusal_vocabulary": derive_refusal_vocabulary(),
        "skills": derive_skills(),
        "tools": derive_tools(),
    }


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="capability_manifest.py")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--emit", action="store_true", help="write the manifest")
    g.add_argument("--check", action="store_true", help="parity gate")
    args = ap.parse_args(argv[1:])

    manifest = build_manifest()
    text = canonical(manifest)

    if args.emit:
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text(text, encoding="utf-8")
        print(f"CAPABILITY_MANIFEST_EMIT=OK path={MANIFEST_PATH.relative_to(ROOT)} "
              f"tools={manifest['tools']['count']} sha256={hashlib.sha256(text.encode()).hexdigest()}")
        return 0

    # --check
    if not MANIFEST_PATH.exists():
        print("CAPABILITY_MANIFEST_PARITY=FAIL reason=manifest-missing")
        return 1
    committed = MANIFEST_PATH.read_text(encoding="utf-8")
    if committed != text:
        print("CAPABILITY_MANIFEST_PARITY=FAIL reason=drift")
        cj = json.loads(committed)
        for k in sorted(set(manifest) | set(cj)):
            if manifest.get(k) != cj.get(k):
                print(f"  - section drift: {k}")
        return 1
    if manifest["bundle_admissibility"]["revoked_checker_present_in_repo"]:
        print("CAPABILITY_MANIFEST_PARITY=FAIL reason=revoked-lane-present")
        return 1
    print(f"CAPABILITY_MANIFEST_PARITY=PASS tools={manifest['tools']['count']} "
          f"reason_classes={len(manifest['refusal_vocabulary']['claim_bundle_verify'])}"
          f"+{len(manifest['refusal_vocabulary']['exact_verify'])} "
          f"inventory_sha={manifest['coverage_inventory']['sha256'][:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
