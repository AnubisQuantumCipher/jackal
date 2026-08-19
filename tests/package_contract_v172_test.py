#!/usr/bin/env python3
"""Static plus side-effect-free dry-run contract for the v1.7.2 package."""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "release" / "build_package_v172.sh"
DIST = ROOT / "release" / "dist"
COMPILER_PATH = "/Users/sicarii/anubis-lang/vm/pins/anubis-a733565f237d"
COMPILER_SHA256 = (
    "a733565f237df171e7cf93b9b37700a42d8713576818fd92f8cd23a8ad7a69e2"
)


def snapshot_tree(root: Path) -> list[tuple[str, int, int, int]]:
    if not root.exists():
        return []
    result: list[tuple[str, int, int, int]] = []
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        result.append(
            (
                path.relative_to(root).as_posix(),
                stat.S_IFMT(info.st_mode),
                info.st_size,
                info.st_mtime_ns,
            )
        )
    return result


def run_builder(path: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["/bin/sh", os.fspath(path), "--dry-run"],
        cwd=ROOT,
        env={
            "HOME": os.fspath(Path.home()),
            "PATH": "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "LC_ALL": "C",
        },
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
    )


class PackageV172ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(BUILDER.is_file(), f"missing v1.7.2 builder: {BUILDER}")
        self.source = BUILDER.read_text(encoding="utf-8")

    def test_static_mac_arm64_and_fail_closed_contract(self) -> None:
        self.assertIn('VER="v1.7.2"', self.source)
        self.assertIn("/usr/bin/uname -s", self.source)
        self.assertIn("/usr/bin/uname -m", self.source)
        self.assertIn("unsupported-host", self.source)
        self.assertIn(COMPILER_PATH, self.source)
        self.assertIn(COMPILER_SHA256, self.source)
        self.assertNotIn("target/release", self.source)
        self.assertNotIn("rm -rf", self.source)
        self.assertIn("mktemp -d", self.source)
        self.assertIn("jackal-v1.7.2-macos-arm64", self.source)

    def test_static_self_contained_identity_and_evidence_contract(self) -> None:
        required_tokens = {
            "jackal_cert_check",
            "jackal_int_cert_check",
            "jackal_gaussian_check",
            "range_proof_identity.json",
            "int_cert_proof_identity.json",
            "gaussian_proof_identity.json",
            "compat_v172_floor.json",
            "range_ordering_aba_v172.json",
            "int_cert_premise_aba_v172.json",
            "formal_coverage_inventory.json",
            "MANIFEST.sha256",
            "SHA256SUMS",
        }
        for token in required_tokens:
            self.assertIn(token, self.source)
        self.assertGreaterEqual(self.source.count("--release-epoch v1.7.2"), 2)

    def test_archival_replay_runtime_is_pinned_and_packaged(self) -> None:
        self.assertIn(
            "21c7ede586f30a58772f321f7dbb36ab66213e199785489f99133710ac56096e",
            self.source,
        )
        self.assertIn("jackal_cert_check_v170", self.source)
        self.assertIn("formal_coverage_inventory_v170.json", self.source)
        self.assertIn(
            "18ff7b1d428dbc6f807fd4de27751ba415b33ef0b356088d7fa316ed74bb0ba6",
            self.source,
        )
        self.assertNotIn("package / \"jackal_int_cert_check_v170\"", self.source)
        self.assertIn(
            "05c3518b836f239712f897c483a2ddadad9f544e0887b1b7bb1424a27289de8a",
            self.source,
        )
        self.assertIn("revoked_int_cert_proof_identity_reference", self.source)

    def test_generated_range_wrapper_has_one_authority_binding(self) -> None:
        range_wrapper = self.source.split(
            'cat > "$PKG/jackal-cert-release"', 1
        )[1].split('cat > "$PKG/jackal-int-cert-release"', 1)[0]
        self.assertEqual(
            range_wrapper.count('--evaluator "$HERE/jackal-native"'), 1
        )
        self.assertEqual(
            range_wrapper.count('--checker "$HERE/jackal_cert_check"'), 1
        )

    def test_generated_rational_wrappers_use_current_v2_epoch(self) -> None:
        variant_wrapper = self.source.split("emit_variant_wrapper() {", 1)[1].split(
            "\nemit_variant_wrapper jackal-sqrt-rat-release", 1
        )[0]
        self.assertIn("--release-epoch v1.7.2", variant_wrapper)
        self.assertNotIn("--release-epoch v1.5.0", variant_wrapper)

    def test_generated_rational_wrappers_recheck_runtime_identity(self) -> None:
        variant_wrapper = self.source.split("emit_variant_wrapper() {", 1)[1].split(
            "\nemit_variant_wrapper jackal-sqrt-rat-release", 1
        )[0]
        self.assertIn("verify_variant_runtime_identity()", variant_wrapper)
        self.assertGreaterEqual(
            variant_wrapper.count("verify_variant_runtime_identity"), 5
        )
        producer = variant_wrapper.index('python3 -I -S -B "\\$HERE/$producer_file"')
        checker = variant_wrapper.index('OUT=\\$("\\$HERE/jackal_cert_check"')
        receipt = variant_wrapper.index('emit-variant-receipt')
        checks = [
            offset
            for offset in range(len(variant_wrapper))
            if variant_wrapper.startswith("verify_variant_runtime_identity", offset)
        ]
        self.assertTrue(any(producer < offset < checker for offset in checks))
        self.assertTrue(any(checker < offset < receipt for offset in checks))
        self.assertTrue(any(receipt < offset for offset in checks))
        for token in (
            'EM=\\$(shasum -a 256 "\\$HERE/MANIFEST.sha256"',
            'range_proof_identity',
            'range_proof_digest',
            'coverage_inventory',
            '[ "\\$MP" = "\\$EM" ]',
            '[ "\\$PF" = "\\$EPF" ]',
            '[ "\\$IF" = "\\$EI" ]',
            '[ "\\$DID" = "\\$EPD" ]',
        ):
            self.assertIn(token, variant_wrapper)

    def test_generated_rational_wrapper_reports_success_after_receipt(self) -> None:
        variant_wrapper = self.source.split("emit_variant_wrapper() {", 1)[1].split(
            "\nemit_variant_wrapper jackal-sqrt-rat-release", 1
        )[0]
        receipt = variant_wrapper.index("emit-variant-receipt")
        success = variant_wrapper.index('echo "status=formal-bounded"')
        final_check = variant_wrapper.rindex("verify_variant_runtime_identity")
        self.assertLess(receipt, final_check)
        self.assertLess(final_check, success)

    def test_dry_run_validates_plan_without_touching_dist(self) -> None:
        before = snapshot_tree(DIST)
        completed = run_builder(BUILDER)
        after = snapshot_tree(DIST)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        self.assertIn(b"PACKAGE_V172_DRY_RUN_PASS", completed.stdout)
        self.assertIn(b"platform=macos-arm64", completed.stdout)
        self.assertIn(COMPILER_SHA256.encode(), completed.stdout)
        self.assertIn(b"range_identity=range_proof_identity.json", completed.stdout)
        self.assertIn(b"int_identity=int_cert_proof_identity.json", completed.stdout)
        self.assertEqual(after, before)

    def test_build_freezes_each_input_and_validates_staged_tuple(self) -> None:
        self.assertIn('SOURCE_PLAN="$STAGE/source-plan.sha256"', self.source)
        self.assertIn('copy-source-prehash-drift', self.source)
        self.assertIn('copy-source-or-destination-drift', self.source)
        self.assertIn('/usr/bin/shasum -a 256 -c SHA256SUMS', self.source)
        self.assertIn('STAGED_SEMANTIC_VALIDATION_PASS', self.source)
        self.assertIn('plugin_hermes.identity_match=true', self.source)
        self.assertIn('staged-range-receipt.json', self.source)
        self.assertIn('staged-int-receipt.json', self.source)
        validation = self.source.index('STAGED_SEMANTIC_VALIDATION_PASS')
        archive = self.source.index('STAGED_TARBALL="$STAGE/$TARBALL_NAME"')
        self.assertLess(validation, archive)

    def test_nonclaims_distinguish_range_replay_from_revoked_int(self) -> None:
        boundary = self.source.split(
            'cat > "$PKG/NON-CLAIMS.txt"', 1
        )[1].split('cat > "$PKG/README.txt"', 1)[0]
        self.assertIn('archived v1 range identity', boundary)
        self.assertIn('replay-only', boundary)
        self.assertIn('archived v1 composed-integral identity', boundary)
        self.assertIn('historical revocation', boundary)
        self.assertIn('request-unbound checker is not shipped', boundary)

    def test_nonclaims_requires_historical_inventory_for_archival_replay(
            self) -> None:
        """Blocker D+E: NON-CLAIMS.txt must state archival range replay
        requires both the historical checker AND the historical coverage
        inventory bytes.  Documenting only the checker leaves the inventory
        pin invisible to reviewers."""
        boundary = self.source.split(
            'cat > "$PKG/NON-CLAIMS.txt" <<\'EOF\'', 1
        )[1].split("EOF", 1)[0]
        # Wrap-tolerant substring: the human sentence may straddle lines,
        # but every load-bearing token must still be present.
        normalized = " ".join(boundary.split())
        self.assertIn("historical range checker AND the exact "
                      "historical coverage inventory", normalized)
        self.assertIn("formal_coverage_inventory_v170.json", boundary)
        self.assertIn("jackal_cert_check_v170", boundary)

    def test_nonclaims_bound_the_domain_pack_surface(self) -> None:
        """The packaged boundary must state what the domain packs do NOT
        establish.  A pack routes structural and decision facts whose
        assurance ceiling is `exact`; without these sentences a reader can
        reasonably read `exact` as `the code is correct`, which is the exact
        laundering the consequence ceiling exists to prevent.  Each
        assertion pins one bullet by a phrase that appears nowhere else in
        the builder."""
        boundary = self.source.split(
            'cat > "$PKG/NON-CLAIMS.txt" <<\'EOF\'', 1
        )[1].split("EOF", 1)[0]
        normalized = " ".join(boundary.split())
        # structure-not-correctness
        self.assertIn(
            "programming-status pack establishes STRUCTURE, never "
            "correctness", normalized)
        self.assertIn(
            "whether that test executes, passes, asserts anything, or "
            "covers what a surrounding document claims it covers",
            normalized)
        # a citation is resolved, not validated
        self.assertIn(
            "claim-cites-test RESOLVES a citation; it does not validate "
            "one", normalized)
        # the criterion is the caller's, and value judgments refuse
        self.assertIn(
            "never a claim that it is the right one to optimise",
            normalized)
        self.assertIn("Value judgments are refused, not ranked", normalized)
        # the verifier's own admission
        self.assertIn("anubis_execution_status=NOT_EXECUTED", boundary)
        self.assertIn("assurance_status=NOT_MINTED", boundary)

    def test_nonclaims_admit_the_value_judgment_blocklist_gap(self) -> None:
        """The value-judgment screen is a substring blocklist, so it is
        defeated by synonyms and by leetspeak.  This is the one bullet a
        future reader is most likely to find embarrassing and quietly drop,
        so it gets its own test.  The measured words are named literally:
        a bullet that admitted incompleteness in the abstract, without
        naming a spelling that actually passes, would be unfalsifiable
        hedging rather than a disclosure."""
        boundary = self.source.split(
            'cat > "$PKG/NON-CLAIMS.txt" <<\'EOF\'', 1
        )[1].split("EOF", 1)[0]
        normalized = " ".join(boundary.split())
        self.assertIn(
            "value-judgment screen is a substring blocklist and is "
            "INCOMPLETE", normalized)
        self.assertIn(
            "criteria spelled optimal, ideal, and leetspeak such as b3st "
            "are ACCEPTED", normalized)
        # The gap must be paired with what would actually close it, so the
        # disclosure cannot be read as an unfixable fact of life.
        self.assertIn(
            "declared unit or measurement provenance on the criterion",
            normalized)

    def test_provenance_receipt_records_archival_inventory(self) -> None:
        """Blocker D+E: the PROVENANCE-RECEIPT.txt must carry a row that
        binds the packaged archival inventory bytes, not only the archival
        checker.  The archival tuple is a checker/proof/inventory triple."""
        provenance = self.source.split(
            'cat > "$PKG/PROVENANCE-RECEIPT.txt" <<EOF', 1
        )[1].split("EOF", 1)[0]
        self.assertIn("archival-range-coverage-inventory", provenance)
        self.assertIn(
            "evidence/formal_coverage_inventory_v170.json", provenance)
        self.assertIn("$ARCHIVAL_RANGE_INVENTORY_ID", provenance)

    def test_manifest_row_binds_archival_inventory_bytes(self) -> None:
        """The manifest must carry the archival inventory digest so the
        v1.7.0 replay tuple cannot be silently swapped in a shipped
        package."""
        self.assertIn(
            'ARCHIVAL_RANGE_INVENTORY_ID=$(sha256 "$PKG/evidence/'
            'formal_coverage_inventory_v170.json")',
            self.source,
        )
        self.assertIn(
            "archival_range_coverage_inventory "
            "evidence/formal_coverage_inventory_v170.json "
            "$V170_COVERAGE_INVENTORY_SHA256",
            self.source,
        )

    def test_current_and_archival_inventory_files_are_distinct(self) -> None:
        """Current v1.7.2 coverage inventory ships as
        formal_coverage_inventory.json and the archival v1.7.0 inventory
        ships under a distinct v170-suffixed name.  Rename collisions here
        collapse the two authorities into one file at package time."""
        current = "$PKG/formal_coverage_inventory.json"
        archival = "$PKG/evidence/formal_coverage_inventory_v170.json"
        self.assertIn(current, self.source)
        self.assertIn(archival, self.source)
        self.assertNotEqual(current, archival)

    def test_final_publication_refuses_dangling_symlink(self) -> None:
        """Blocker F: the final publication check must refuse a symlink
        (dangling or live) at $FINAL_PKG or $FINAL_TARBALL, not just an
        existing regular file/directory.  A dangling symlink races
        ``test -e`` (which follows the link) and would let ``mv``
        overwrite/follow it.  We assert both `-e` and `-L` are present in
        the final block."""
        idx = self.source.find('/bin/mkdir -p "$DIST"')
        self.assertGreater(idx, 0,
                           'expected final publication mkdir in builder')
        final = self.source[idx:]
        pre_mv = final.split('/bin/mv "$PKG"', 1)[0]
        self.assertIn('! -L "$FINAL_PKG"', pre_mv,
                      'final publication must reject a symlink at $FINAL_PKG')
        self.assertIn('! -L "$FINAL_TARBALL"', pre_mv,
                      'final publication must reject a symlink at $FINAL_TARBALL')
        self.assertIn('! -e "$FINAL_PKG"', pre_mv)
        self.assertIn('! -e "$FINAL_TARBALL"', pre_mv)
        head = self.source[:idx]
        self.assertIn(
            '[ ! -e "$FINAL_PKG" ] && [ ! -L "$FINAL_PKG" ]', head)
        self.assertIn(
            '[ ! -e "$FINAL_TARBALL" ] && [ ! -L "$FINAL_TARBALL" ]',
            head)

    def test_final_publication_dangling_symlink_regression(self) -> None:
        """Deterministic race regression: plant a dangling symlink at
        each final publication path and confirm the same ``[ ! -e ... ]
        && [ ! -L ... ]`` shape the builder uses correctly refuses each
        one.  This proves the guard shape survives a dangling target;
        the builder is Darwin/arm64-only so we do not spawn the full
        build here — the guard itself is the load-bearing piece."""
        with tempfile.TemporaryDirectory(prefix="jackal-blocker-f-") as td:
            for name in ("jackal-v1.7.2-macos-arm64",
                         "jackal-v1.7.2-macos-arm64.tar.gz"):
                link = Path(td) / name
                link.symlink_to(Path(td) / "does-not-exist")
                self.assertTrue(link.is_symlink(),
                                f"planted symlink missing: {link}")
                completed = subprocess.run(
                    ["/bin/sh", "-c",
                     f'[ ! -e "{link}" ] && [ ! -L "{link}" ] '
                     f'&& echo OK || echo REFUSED'],
                    capture_output=True,
                )
                self.assertEqual(completed.returncode, 0)
                self.assertIn(b"REFUSED", completed.stdout,
                              f"guard missed dangling symlink at {link}")

    def test_host_guard_is_load_bearing(self) -> None:
        mutated = self.source.replace(
            "SYSTEM=$(/usr/bin/uname -s)", "SYSTEM=Linux", 1
        ).replace("MACHINE=$(/usr/bin/uname -m)", "MACHINE=x86_64", 1)
        self.assertNotEqual(mutated, self.source)
        with tempfile.TemporaryDirectory(prefix="jackal-v172-host-") as temporary:
            candidate = Path(temporary) / "build_package_v172.sh"
            candidate.write_text(mutated, encoding="utf-8")
            candidate.chmod(0o755)
            completed = run_builder(candidate)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(b"unsupported-host", completed.stdout + completed.stderr)

    def test_shell_syntax_is_valid(self) -> None:
        completed = subprocess.run(
            ["/bin/sh", "-n", os.fspath(BUILDER)],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())


if __name__ == "__main__":
    unittest.main(verbosity=2)
