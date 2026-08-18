#!/usr/bin/env python3
"""RED-then-GREEN contract for Blocker A: receipt-context-unsupported is a
stable REASON_CLASS with two-Python parity.

Before the fix, calling ``Refusal("receipt-context-unsupported", …)`` in
``tools/claim_bundle_verify.py`` hits the ``assert cls in REASON_CLASSES``
inside :class:`Refusal`.  Under normal Python that raises
``AssertionError`` and the outer ``except Exception`` in ``main`` silently
downgrades the reason to ``verifier-internal``.  Under ``python -O`` the
assert is stripped so the same call succeeds with the raw class name and
the CLI prints ``reason=receipt-context-unsupported``.

That divergence is exactly the producer/consumer label desynchronisation
the JACKAL kernel forbids: two "Python contexts" disagree on the stable
refusal taxonomy for the same input.  This test locks the invariant that
every code path emitting the class also declares it in ``REASON_CLASSES``,
and pins CLI parity on the four claim-context rejection paths documented
in the Gate-0 handoff:

  * v1.7.0 ``int_cert`` (revoked archival integral variant)
  * arbitrary ``int_cert`` epoch (e.g. v1.5.0)
  * arbitrary range-family epoch (e.g. v1.3.0)
  * unknown variant string (e.g. ``noop``)
  * non-string variant (e.g. integer)

plus one cross-context substitution control (current-inventory pin swapped
in on an archival receipt still refuses; the ``receipt-context-unsupported``
class is reserved for pre-dispatch variant/epoch selection failures and
must not shadow the downstream evidence-verify path).

The tests invoke the real CLI (``tools/claim_bundle_verify.py``) under
both ``python3 -I -S -B`` and ``python3 -I -S -B -O`` so the fix cannot
regress the parity later.  Bundle assembly reuses the independent
canonicaliser and node builders in ``tests/claim_hostile_test.py`` so this
file adds no third bundle formatter.
"""
from __future__ import annotations

import os
import sys

# tools/claim_bundle_verify.py refuses to import outside python3 -I -S -B;
# self-exec into that mode so the test file works under a plain `python3
# -B path.py` invocation as well as the intended isolated one.
if not (sys.flags.isolated and sys.flags.no_site):
    os.execv(sys.executable,
             [sys.executable, "-I", "-S", "-B", __file__, *sys.argv[1:]])

import base64
import copy
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
VERIFIER = ROOT / "tools/claim_bundle_verify.py"

sys.path.insert(0, str(ROOT / "tools"))
import claim_bundle_verify as cbv  # noqa: E402


def _load_hostile_module():
    """Import ``tests/claim_hostile_test.py`` as a module without executing
    its ``main()``; we only want its independent canonicaliser and node
    builders."""
    spec = importlib.util.spec_from_file_location(
        "_hostile_helpers", TESTS / "claim_hostile_test.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HOST = _load_hostile_module()


def _receipt_or_skip(case: unittest.TestCase):
    receipt = HOST.fresh_receipt()
    if receipt is None:
        case.skipTest("ln_rat producer/checker unavailable for fixture")
    return receipt


def _receipt_node_with_overrides(receipt: dict, *,
                                 variant_override,
                                 epoch_override: str) -> dict:
    """Build a formal-receipt evidence node whose declared variant and
    ``expected_release_epoch`` differ from the underlying v1.5.0 ln_rat
    receipt so that ``dispatch_receipt`` reaches the variant/epoch selector
    with the tuple we want to exercise."""
    payload = copy.deepcopy(receipt)
    payload["variant"] = variant_override
    raw = json.dumps(payload, indent=2, sort_keys=True).encode()
    req = payload["request"]
    prop = {
        "t": "in",
        "arg": {"t": "app", "fn": "formal.range",
                "args": [{"t": "str", "v": req["expression"]},
                         HOST.interval(req["canonical_lo"],
                                       req["canonical_hi"])]},
        "set": HOST.interval(payload["result"]["enclosure_lo"],
                             payload["result"]["enclosure_hi"]),
    }
    node = HOST.base_node(
        proposition=prop,
        evidence={"kind": "formal-receipt",
                  "payload_b64": base64.b64encode(raw).decode(),
                  "sha256": HOST.sha_hex(raw)},
        rule={"id": "evidence_admit",
              "params": {
                  "evidence_kind": "formal-receipt",
                  "expected_request": {
                      "command": req["command"],
                      "expression": req["expression"],
                      "input_lo": req["input_lo"],
                      "input_hi": req["input_hi"],
                  },
                  "expected_release_epoch": epoch_override,
                  "expected_identities": {
                      "evaluator_sha256":
                          payload["identities"]["evaluator_sha256"],
                      "checker_sha256":
                          payload["identities"]["checker_sha256"],
                  },
              }},
        producer={"name": "ln_rat_producer.py",
                  "sha256": payload["identities"]["evaluator_sha256"]},
        checker={"name": "jackal_cert_check_v170",
                 "sha256": HOST.ARCHIVAL_RANGE_CHECKER_SHA},
        assumptions=[f"receipt:{a}" for a in payload["assumptions"]],
    )
    node["assurance"] = {
        "input_provenance": "supplied",
        "model_validity": "assumed",
        "mathematical": "formal-bounded",
        "implementation": "checker-derived",
        "artifact": dict(HOST.ARTIFACT_CA),
    }
    return HOST.rehash(node)


def _run_cli(bundle: dict, *, optimize: bool) -> tuple[str, str, str, int]:
    """Invoke the real claim-bundle verifier CLI, optionally under
    ``python -O``, with the full legacy tuple pinned exactly as the
    v1.7.2 aggregate driver does.  Returns (verdict, reason, out, rc)."""
    with tempfile.TemporaryDirectory(prefix="jackal-blocker-a-") as td:
        bpath = Path(td) / "bundle.json"
        bpath.write_text(json.dumps(bundle, sort_keys=True))
        rpath = Path(td) / "root_prop.json"
        by_id = {n["id"]: n for n in bundle["nodes"]}
        rpath.write_text(json.dumps(by_id[bundle["root"]]["proposition"],
                                    sort_keys=True))
        pol = bundle["policy"]
        argv = [sys.executable, "-I", "-S", "-B"]
        if optimize:
            argv.append("-O")
        argv += [
            str(VERIFIER),
            "--bundle", str(bpath),
            "--expected-release-epoch", bundle["release_epoch"],
            "--expected-policy-sha256", HOST.sha_hex(HOST.canon(pol)),
            "--expected-root-proposition", str(rpath),
            "--expected-inference-registry", str(HOST.INF_REG),
            "--expected-inference-registry-sha256", HOST.INF_SHA,
            "--expected-unit-registry", str(HOST.UNIT_REG),
            "--expected-unit-registry-sha256", HOST.UNIT_SHA,
            "--expected-environment-epoch", HOST.ENV_EPOCH,
            "--verification-time-unix", str(HOST.VTIME),
            "--receipt-verifier", str(HOST.RECEIPT_VERIFIER),
            "--exact-verifier", str(HOST.EXACT_VERIFIER),
            "--checker", str(HOST.CHECKER),
            "--expected-checker", HOST.CHECKER_SHA,
            "--expected-evaluator", HOST.ENV_EPOCH,
            "--inventory", str(HOST.INVENTORY),
            "--expected-inventory", HOST.INVENTORY_SHA,
            "--proof-identity", str(HOST.PROOF_ID),
            "--expected-proof-identity-file", HOST.PROOF_ID_SHA,
            "--expected-proof-identity-digest", HOST.PROOF_ID_DIGEST,
            "--archival-range-checker", str(HOST.ARCHIVAL_RANGE_CHECKER),
            "--expected-archival-range-checker",
            HOST.ARCHIVAL_RANGE_CHECKER_SHA,
            "--archival-range-proof-identity",
            str(HOST.ARCHIVAL_RANGE_PROOF_ID),
            "--expected-archival-range-proof-identity-file",
            HOST.ARCHIVAL_RANGE_PROOF_ID_SHA,
            "--expected-archival-range-proof-identity-digest",
            HOST.ARCHIVAL_RANGE_PROOF_ID_DIGEST,
            "--archival-range-inventory",
            str(HOST.ARCHIVAL_RANGE_INVENTORY),
            "--expected-archival-range-inventory",
            HOST.ARCHIVAL_RANGE_INVENTORY_SHA,
        ]
        for psha in HOST._trusted_producers():
            argv += ["--trusted-producer", psha]
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=600, cwd=ROOT)
    out = (proc.stdout or "") + (proc.stderr or "")
    verdict = reason = ""
    for line in out.splitlines():
        if line.startswith("claim-verify="):
            verdict = line.split("=", 2)[1].split()[0]
            if "reason=" in line:
                reason = line.split("reason=", 1)[1].split()[0]
            break
    return verdict, reason, out, proc.returncode


class ReasonClassInvariantTests(unittest.TestCase):
    def test_receipt_context_unsupported_is_registered(self) -> None:
        self.assertIn("receipt-context-unsupported", cbv.REASON_CLASSES,
                      "receipt-context-unsupported must be a stable "
                      "reason class; every raise site expects it to "
                      "survive under normal Python without triggering "
                      "the assert inside Refusal.__init__")

    def test_refusal_accepts_the_class_without_assertion(self) -> None:
        # No AssertionError under normal Python.
        r = cbv.Refusal("receipt-context-unsupported", "revoked")
        self.assertEqual(r.cls, "receipt-context-unsupported")
        self.assertEqual(r.detail, "revoked")

    def test_every_raise_site_uses_a_registered_class(self) -> None:
        """Guard against future drift: read the verifier source and
        confirm every string literal passed to Refusal(...) resolves in
        REASON_CLASSES.  Blocker A's failure mode was exactly this drift
        going undetected because the assert only fires at runtime."""
        import re
        source = (ROOT / "tools/claim_bundle_verify.py").read_text()
        classes = set(re.findall(
            r'raise Refusal\(\s*"([a-z][a-z0-9-]+)"', source))
        missing = classes - set(cbv.REASON_CLASSES)
        self.assertFalse(
            missing,
            f"Refusal reason classes raised but not declared: {sorted(missing)}")


class ReceiptContextRejectionCliTests(unittest.TestCase):
    """End-to-end: build a bundle carrying a formal-receipt evidence
    node with a variant/epoch that is not an admitted tuple, run the
    real CLI, assert exit code 1 and reason=receipt-context-unsupported
    under both normal Python and ``python -O``."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._receipt = HOST.fresh_receipt()
        if cls._receipt is None:
            raise unittest.SkipTest(
                "ln_rat producer/checker unavailable; cannot build "
                "formal-receipt fixture for Blocker A CLI tests")

    def _bundle_for(self, *, variant_override,
                    epoch_override: str) -> dict:
        node = _receipt_node_with_overrides(
            self._receipt,
            variant_override=variant_override,
            epoch_override=epoch_override)
        return HOST.bundle_of([node], node["id"])

    def _assert_receipt_context_unsupported(self, bundle: dict) -> None:
        for optimize in (False, True):
            with self.subTest(optimize=optimize):
                verdict, reason, out, rc = _run_cli(
                    bundle, optimize=optimize)
                self.assertEqual(
                    rc, 1,
                    f"expected exit 1 for receipt-context-unsupported; "
                    f"got rc={rc} out={out[:300]!r}")
                self.assertEqual(
                    verdict, "refused",
                    f"expected refused verdict; got {verdict!r}, "
                    f"out={out[:300]!r}")
                self.assertEqual(
                    reason, "receipt-context-unsupported",
                    f"expected receipt-context-unsupported; got "
                    f"{reason!r}, out={out[:300]!r}")

    def test_v170_int_cert_is_refused_with_stable_reason(self) -> None:
        bundle = self._bundle_for(variant_override="int_cert",
                                  epoch_override="v1.7.0")
        self._assert_receipt_context_unsupported(bundle)

    def test_arbitrary_int_cert_epoch_is_refused_with_stable_reason(
            self) -> None:
        bundle = self._bundle_for(variant_override="int_cert",
                                  epoch_override="v1.3.0")
        self._assert_receipt_context_unsupported(bundle)

    def test_arbitrary_range_epoch_is_refused_with_stable_reason(
            self) -> None:
        bundle = self._bundle_for(variant_override="sqrt_rat",
                                  epoch_override="v1.3.0")
        self._assert_receipt_context_unsupported(bundle)

    def test_unknown_variant_is_refused_with_stable_reason(self) -> None:
        bundle = self._bundle_for(variant_override="noop",
                                  epoch_override="v1.5.0")
        self._assert_receipt_context_unsupported(bundle)

    def test_non_string_variant_is_refused_with_stable_reason(
            self) -> None:
        bundle = self._bundle_for(variant_override=123,
                                  epoch_override="v1.5.0")
        self._assert_receipt_context_unsupported(bundle)


class CrossContextSubstitutionSanityTests(unittest.TestCase):
    """Substituting the current inventory pin into an archival receipt
    tuple must still refuse.  The stable reason for a valid tuple with a
    hostile inventory swap is downstream evidence-verify-failed (not
    receipt-context-unsupported) — the pre-dispatch selector should not
    shadow the mid-flight verification.  This locks the boundary between
    Blocker A's fix and Blocker E's independent inventory pin."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._receipt = HOST.fresh_receipt()
        if cls._receipt is None:
            raise unittest.SkipTest(
                "ln_rat producer/checker unavailable for archival fixture")

    def test_archival_tuple_with_swapped_inventory_refuses_downstream(
            self) -> None:
        node = HOST.receipt_node(self._receipt)
        bundle = HOST.bundle_of([node], node["id"])
        with tempfile.TemporaryDirectory(prefix="jackal-blocker-a-x-") as td:
            bpath = Path(td) / "bundle.json"
            bpath.write_text(json.dumps(bundle, sort_keys=True))
            rpath = Path(td) / "root_prop.json"
            by_id = {n["id"]: n for n in bundle["nodes"]}
            rpath.write_text(json.dumps(by_id[bundle["root"]]["proposition"],
                                        sort_keys=True))
            pol = bundle["policy"]
            argv = [sys.executable, "-I", "-S", "-B",
                    str(VERIFIER),
                    "--bundle", str(bpath),
                    "--expected-release-epoch", bundle["release_epoch"],
                    "--expected-policy-sha256", HOST.sha_hex(HOST.canon(pol)),
                    "--expected-root-proposition", str(rpath),
                    "--expected-inference-registry", str(HOST.INF_REG),
                    "--expected-inference-registry-sha256", HOST.INF_SHA,
                    "--expected-unit-registry", str(HOST.UNIT_REG),
                    "--expected-unit-registry-sha256", HOST.UNIT_SHA,
                    "--expected-environment-epoch", HOST.ENV_EPOCH,
                    "--verification-time-unix", str(HOST.VTIME),
                    "--receipt-verifier", str(HOST.RECEIPT_VERIFIER),
                    "--exact-verifier", str(HOST.EXACT_VERIFIER),
                    "--checker", str(HOST.CHECKER),
                    "--expected-checker", HOST.CHECKER_SHA,
                    "--expected-evaluator", HOST.ENV_EPOCH,
                    "--inventory", str(HOST.INVENTORY),
                    "--expected-inventory", HOST.INVENTORY_SHA,
                    "--proof-identity", str(HOST.PROOF_ID),
                    "--expected-proof-identity-file", HOST.PROOF_ID_SHA,
                    "--expected-proof-identity-digest", HOST.PROOF_ID_DIGEST,
                    "--archival-range-checker",
                    str(HOST.ARCHIVAL_RANGE_CHECKER),
                    "--expected-archival-range-checker",
                    HOST.ARCHIVAL_RANGE_CHECKER_SHA,
                    "--archival-range-proof-identity",
                    str(HOST.ARCHIVAL_RANGE_PROOF_ID),
                    "--expected-archival-range-proof-identity-file",
                    HOST.ARCHIVAL_RANGE_PROOF_ID_SHA,
                    "--expected-archival-range-proof-identity-digest",
                    HOST.ARCHIVAL_RANGE_PROOF_ID_DIGEST,
                    # Deliberately swap: point the archival-range-inventory
                    # arg at the CURRENT inventory bytes to prove the CLI
                    # will not silently accept.
                    "--archival-range-inventory", str(HOST.INVENTORY),
                    "--expected-archival-range-inventory",
                    HOST.INVENTORY_SHA]
            for psha in HOST._trusted_producers():
                argv += ["--trusted-producer", psha]
            proc = subprocess.run(argv, capture_output=True, text=True,
                                  timeout=600, cwd=ROOT)
        out = (proc.stdout or "") + (proc.stderr or "")
        self.assertNotEqual(proc.returncode, 0,
                            f"substitution must refuse; got rc=0 out={out[:300]!r}")
        # It MUST refuse, and MUST NOT be receipt-context-unsupported;
        # the class exists only for pre-dispatch selection failures.
        self.assertNotIn("reason=receipt-context-unsupported", out,
                         "swapped-inventory refusal must not use "
                         "receipt-context-unsupported")


if __name__ == "__main__":
    unittest.main(verbosity=2)
