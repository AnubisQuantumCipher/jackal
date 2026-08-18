#!/usr/bin/env python3
"""Generate/check the closed-premise v1.7.2 range and int-cert identities.

The stable proof-identity engine remains in ``gaussian_proof_identity.py`` so
archival v1 identity bytes and their generator remain untouched.  This
lane-specific entrypoint supplies only the new v2 lane contracts and records
itself as the generator.
"""

from __future__ import annotations

import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import gaussian_proof_identity as engine  # noqa: E402


RANGE_V172 = engine.LaneConfig(
    schema="jackal-range-proof-identity-v2",
    identity_name="range_proof_identity_v172.json",
    checker_path="proofs/lean/.lake/build/bin/jackal_cert_check",
    checker_target="jackal_cert_check",
    root_modules=("JackalIv.CertCheckMain",),
    fragment={
        "assurance": "formal-bounded",
        "certificate_magic": "jackal-eval-cert v2",
        "checker_boolean_definition": "JackalIv.Cert.checkCert",
        "checker_entrypoint_definition": "runRequestBound",
        "checker_executable": "jackal_cert_check",
        "family": "range-request-bound-v1",
        "lane": "range",
        "parser_definition": "JackalIv.Cert.parseCert",
        "premise_closure": (
            "interval order and ModelTCB are derived from requestMatches and "
            "the exact release allowlist"
        ),
        "premises_not_discharged_by_checker": [],
        "request_matcher_definition": "JackalIv.Cert.requestMatches",
        "runtime_alternate_implementation_boundary": (
            "request acceptance uses no implemented_by definition; two exact "
            "dump-only implemented_by attributes elsewhere in the imported "
            "closure are pinned"
        ),
        "soundness_theorem": "JackalIv.Cert.request_bound_certified_release",
        "theorem_premises": [
            "requestMatches command rawExpr rawLo rawHi hdr nodes = true (runtime checked)",
            "checkCert hdr nodes = true (runtime checked)",
        ],
    },
    theorems=(
        "JackalIv.Cert.request_bound_certified_release",
        "JackalIv.Cert.requestMatches_true",
        "JackalIv.Cert.requestMatches_interval_order",
        "JackalIv.Cert.releaseNodesOk_modelTCB",
        "JackalIv.Cert.lowerRaw_toExpr",
        "JackalIv.Cert.rawExprOf_toExpr",
        "JackalIv.Cert.cert_check_sound",
        "JackalIv.parse_lower_encloses",
    ),
    allowed_local_constructs={
        "proofs/lean/JackalIv/Correspondence.lean": {
            "implemented_by": (
                "@[implemented_by Dump.parseSexpImpl]",
                "@[implemented_by Dump.lowerSexpImpl]",
            )
        }
    },
)


INT_CERT_V172 = engine.LaneConfig(
    schema="jackal-int-cert-proof-identity-v2",
    identity_name="int_cert_proof_identity_v172.json",
    checker_path="proofs/lean/.lake/build/bin/jackal_int_cert_check",
    checker_target="jackal_int_cert_check",
    root_modules=("JackalIv.IntCertMain",),
    fragment={
        "assurance": "formal-bounded",
        "certificate_magic": "jackal-int-cert v1",
        "checker_boolean_definition": "JackalIv.IntCert.checkIntCertRequest",
        "checker_entrypoint_definition": "main (IntCertMain)",
        "checker_executable": "jackal_int_cert_check",
        "family": "integrate-bound-composed-request-bound-v1",
        "lane": "int-cert",
        "parser_definition": "JackalIv.IntCert.parseIntCert",
        "premise_closure": (
            "every embedded certificate is releaseNodesOk; ModelTCB and the "
            "former TreeTCB are derived inside int_cert_core_sound; the raw "
            "caller expression, bounds, and tolerance are matched inside "
            "checkIntCertRequest and exposed by int_cert_sound"
        ),
        "premises_not_discharged_by_checker": [],
        "runtime_alternate_implementation_boundary": (
            "checker acceptance uses no implemented_by definition; two exact "
            "dump-only implemented_by attributes elsewhere in the imported "
            "closure are pinned"
        ),
        "soundness_theorem": "JackalIv.IntCert.int_cert_sound",
        "theorem_premises": [
            "checkIntCertRequest rawExpr rawLo rawHi rawTol hdr tree = .ok () (runtime checked)",
        ],
    },
    theorems=(
        "JackalIv.IntCert.int_cert_sound",
        "JackalIv.IntCert.int_cert_core_sound",
        "JackalIv.IntCert.intRequestMatches_true",
        "JackalIv.IntCert.checkIntCertRequest_ok",
        "JackalIv.IntCert.checkIntCert_rootQExpr_exists",
        "JackalIv.IntCert.rootRawExpr_rootQExpr_embed",
        "JackalIv.IntCert.range_leaf_sound",
        "JackalIv.IntCert.taylor2_leaf_sound",
        "JackalIv.IntCert.taylor4_leaf_sound",
        "JackalIv.IntCert.split_sound",
        "JackalIv.IntCert.sem_measurable",
        "JackalIv.IntCert.embedQ_DQ",
        "JackalIv.IntCert.qexprOf_embed",
        "JackalIv.Cert.releaseNodesOk_modelTCB",
        "JackalIv.Cert.cert_check_sound",
    ),
    allowed_local_constructs={
        "proofs/lean/JackalIv/Correspondence.lean": {
            "implemented_by": (
                "@[implemented_by Dump.parseSexpImpl]",
                "@[implemented_by Dump.lowerSexpImpl]",
            )
        }
    },
)


def _normalized_argv(argv: list[str]) -> list[str]:
    """Make the range lane the explicit default for this range-owned CLI."""

    if not argv or argv[0] not in {"generate", "check"}:
        return list(argv)
    if any(arg == "--lane" or arg.startswith("--lane=") for arg in argv[1:]):
        return list(argv)
    return [argv[0], "--lane", "range", *argv[1:]]


def main() -> int:
    engine.LANES = {"int-cert": INT_CERT_V172, "range": RANGE_V172}
    # The shared engine reads its module-global __file__ when binding generator
    # bytes.  Point that name at this lane-specific entrypoint in this process.
    engine.__file__ = __file__
    engine.__doc__ = __doc__
    original_argv = sys.argv
    sys.argv = [original_argv[0], *_normalized_argv(original_argv[1:])]
    try:
        return engine.main()
    finally:
        sys.argv = original_argv


if __name__ == "__main__":
    raise SystemExit(main())
