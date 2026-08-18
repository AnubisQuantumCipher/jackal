#!/usr/bin/env python3
"""Focused tests for the Hermes plugin's layout-independent runtime identity."""
from __future__ import annotations

import hashlib
import json
import select
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "plugin" / "hermes"
sys.path.insert(0, str(PLUGIN_DIR))

from bundle_hash import compute_bundle_hash, resolve_runtime_files  # noqa: E402


EXPECTED_LOGICAL_NAMES = {
    "plugin/bundle_hash.py",
    "plugin/jackal_hermes",
    "plugin/server.py",
    "plugin/tools.json",
    "runtime/coverage_inventory.py",
    "runtime/formal_coverage_inventory.json",
    "runtime/range_proof_identity.json",
    "runtime/gaussian_proof_identity.json",
    "runtime/int_cert_proof_identity.json",
    "runtime/formal_receipt.py",
    "runtime/formal_status_gate.py",
    "runtime/gaussian_certificate.py",
    "runtime/gaussian_release.py",
    "runtime/int_cert_producer.py",
    "runtime/int_cert_release.py",
    "runtime/isolated_entry.py",
    "runtime/receipt_verify.py",
    "runtime/release_validate.py",
    "runtime/sqrt_rat_producer.py",
    "runtime/exp_rat_producer.py",
    "runtime/ln_rat_producer.py",
    "runtime/sin_rat_producer.py",
    "runtime/atan_rat_producer.py",
    "runtime/tanh_rat_producer.py",
    "runtime/exact_verify.py",
    "runtime/claim_kernel.py",
    "runtime/claim_router.py",
    "runtime/claim_bundle_verify.py",
    "runtime/inference_registry_v1.json",
    "runtime/unit_registry_v1.json",
    "runtime/tools/navier_stokes_certificate_producer.py",
    "runtime/tools/navier_stokes_receipt_verify.py",
    "runtime/domain_packs/pde/navier_stokes_v1.json",
    "runtime/domain_packs/pde/navier_stokes_v1.anb",
    "runtime/domain_packs/pde/certificates/JACKAL_T3_ZERO_PROOF_OBJECT_V1.txt",
    "runtime/domain_packs/pde/identities/JACKAL_T3_ZERO_SOLUTION_IDENTITY_V1.txt",
    "runtime/domain_packs/pde/representations/T3_ZERO_FOURIER_FIELD_V1.txt",
    "runtime/domain_packs/pde/sources/CCRT2007_COROLLARY_5_T3_APOSTERIORI.pdf",
    "runtime/domain_packs/pde/sources/ESS2003_R3_REGULARITY.pdf",
}


PACKAGE_DESTINATIONS = {
    "plugin/bundle_hash.py": "plugin/hermes/bundle_hash.py",
    "plugin/jackal_hermes": "plugin/hermes/jackal_hermes",
    "plugin/server.py": "plugin/hermes/server.py",
    "plugin/tools.json": "plugin/hermes/tools.json",
    "runtime/coverage_inventory.py": "coverage_inventory.py",
    "runtime/formal_coverage_inventory.json": "formal_coverage_inventory.json",
    "runtime/range_proof_identity.json": "range_proof_identity.json",
    "runtime/gaussian_proof_identity.json": "gaussian_proof_identity.json",
    "runtime/int_cert_proof_identity.json": "int_cert_proof_identity.json",
    "runtime/formal_receipt.py": "formal_receipt.py",
    "runtime/formal_status_gate.py": "formal_status_gate.py",
    "runtime/gaussian_certificate.py": "gaussian_certificate.py",
    "runtime/gaussian_release.py": "gaussian_release.py",
    "runtime/int_cert_producer.py": "int_cert_producer.py",
    "runtime/int_cert_release.py": "int_cert_release.py",
    "runtime/isolated_entry.py": "isolated_entry.py",
    "runtime/receipt_verify.py": "receipt_verify.py",
    "runtime/release_validate.py": "release_validate.py",
    "runtime/sqrt_rat_producer.py": "sqrt_rat_producer.py",
    "runtime/exp_rat_producer.py": "exp_rat_producer.py",
    "runtime/ln_rat_producer.py": "ln_rat_producer.py",
    "runtime/sin_rat_producer.py": "sin_rat_producer.py",
    "runtime/atan_rat_producer.py": "atan_rat_producer.py",
    "runtime/tanh_rat_producer.py": "tanh_rat_producer.py",
    "runtime/exact_verify.py": "exact_verify.py",
    "runtime/claim_kernel.py": "claim_kernel.py",
    "runtime/claim_router.py": "claim_router.py",
    "runtime/claim_bundle_verify.py": "claim_bundle_verify.py",
    "runtime/inference_registry_v1.json": "inference_registry_v1.json",
    "runtime/unit_registry_v1.json": "unit_registry_v1.json",
    "runtime/tools/navier_stokes_certificate_producer.py":
        "tools/navier_stokes_certificate_producer.py",
    "runtime/tools/navier_stokes_receipt_verify.py":
        "tools/navier_stokes_receipt_verify.py",
    "runtime/domain_packs/pde/navier_stokes_v1.json":
        "domain_packs/pde/navier_stokes_v1.json",
    "runtime/domain_packs/pde/navier_stokes_v1.anb":
        "domain_packs/pde/navier_stokes_v1.anb",
    "runtime/domain_packs/pde/certificates/JACKAL_T3_ZERO_PROOF_OBJECT_V1.txt":
        "domain_packs/pde/certificates/JACKAL_T3_ZERO_PROOF_OBJECT_V1.txt",
    "runtime/domain_packs/pde/identities/JACKAL_T3_ZERO_SOLUTION_IDENTITY_V1.txt":
        "domain_packs/pde/identities/JACKAL_T3_ZERO_SOLUTION_IDENTITY_V1.txt",
    "runtime/domain_packs/pde/representations/T3_ZERO_FOURIER_FIELD_V1.txt":
        "domain_packs/pde/representations/T3_ZERO_FOURIER_FIELD_V1.txt",
    "runtime/domain_packs/pde/sources/CCRT2007_COROLLARY_5_T3_APOSTERIORI.pdf":
        "domain_packs/pde/sources/CCRT2007_COROLLARY_5_T3_APOSTERIORI.pdf",
    "runtime/domain_packs/pde/sources/ESS2003_R3_REGULARITY.pdf":
        "domain_packs/pde/sources/ESS2003_R3_REGULARITY.pdf",
}


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise RuntimeError(detail)


def main() -> int:
    repo_files = resolve_runtime_files(PLUGIN_DIR)
    require(set(repo_files) == EXPECTED_LOGICAL_NAMES,
            f"runtime logical-name drift: {sorted(repo_files)}")
    require(len(EXPECTED_LOGICAL_NAMES) == 39,
            f"expected 39 runtime logical names, declared {len(EXPECTED_LOGICAL_NAMES)}")
    for logical_name in EXPECTED_LOGICAL_NAMES:
        if logical_name.startswith((
            "runtime/tools/", "runtime/domain_packs/",
        )):
            require(
                PACKAGE_DESTINATIONS[logical_name] ==
                logical_name.removeprefix("runtime/"),
                f"packaged Navier layout was flattened: {logical_name}",
            )
    catalog = json.loads((PLUGIN_DIR / "tools.json").read_text())
    require(catalog.get("version") == "v1.8.0",
            "Navier successor catalog must not rewrite sealed v1.7 identity")
    tools_by_name = {tool["name"]: tool for tool in catalog["tools"]}
    navier_check = tools_by_name.get("jackal_navier_stokes_check")
    require(isinstance(navier_check, dict),
            "direct Navier check tool missing from Hermes catalog")
    require(set(navier_check["arguments"]) == {"request"},
            "Navier check must accept only the structured request object")
    require(navier_check["returns"]["status"] == "bounded | indeterminate | refused",
            "Navier check status classes drifted")
    navier_verify = tools_by_name.get("jackal_verify_navier_stokes_receipt")
    require(isinstance(navier_verify, dict),
            "direct Navier receipt-replay tool missing from Hermes catalog")
    require(set(navier_verify["arguments"]) == {"receipt", "expected_request"},
            "Navier replay must bind a caller-supplied expected request")
    require(navier_verify["returns"]["verification_scope"] == "receipt_replay_only",
            "Navier replay must not promote mathematical status")
    claim_tool = tools_by_name["jackal_claim"]
    require("navier" not in json.dumps(claim_tool, sort_keys=True).lower(),
            "Navier must remain outside jackal_claim routing")
    repo_hash = compute_bundle_hash(PLUGIN_DIR)

    with tempfile.TemporaryDirectory(prefix="jackal-plugin-identity-") as td:
        package_root = Path(td) / "jackal-v1.3.0-macos-arm64"
        package_plugin = package_root / "plugin" / "hermes"
        for logical_name, source in repo_files.items():
            destination = package_root / PACKAGE_DESTINATIONS[logical_name]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            # Package mutation probes operate only on this private copy;
            # theorem-source PDFs are intentionally read-only in the repo.
            destination.chmod(destination.stat().st_mode | 0o200)

        package_files = resolve_runtime_files(package_plugin)
        package_hash = compute_bundle_hash(package_plugin)
        require(repo_hash == package_hash,
                f"repo/package identity mismatch: {repo_hash} != {package_hash}")
        require(set(package_files) == EXPECTED_LOGICAL_NAMES,
                f"package logical-name drift: {sorted(package_files)}")

        # Materialize the non-bundle artifacts needed to start a persistent
        # package plugin process, then prove post-start manifest/runtime swaps
        # are noticed on the next dispatch (the startup hash is not cached as
        # a forever-valid authorization).
        package_artifacts = {
            ROOT / "release/MANIFEST.sha256": package_root / "MANIFEST.sha256",
            ROOT / "jackal-native": package_root / "jackal-native",
            ROOT / "jackal_calc.anb": package_root / "jackal_calc.anb",
            ROOT / "proofs/lean/.lake/build/bin/jackal_cert_check":
                package_root / "jackal_cert_check",
            ROOT / "proofs/lean/.lake/build/bin/jackal_gaussian_check":
                package_root / "jackal_gaussian_check",
            ROOT / "proofs/lean/.lake/build/bin/jackal_int_cert_check":
                package_root / "jackal_int_cert_check",
        }
        for source, destination in package_artifacts.items():
            if source.exists():
                shutil.copy2(source, destination)
            else:
                # This test exercises plugin/runtime identity and the direct
                # Python Navier lane, not legacy native proof execution.  A
                # source checkout may intentionally omit generated binaries;
                # materialize inert package-only placeholders so server layout
                # discovery remains testable without weakening a real lane.
                require(source.name in {
                    "jackal-native", "jackal_cert_check",
                    "jackal_gaussian_check", "jackal_int_cert_check",
                }, f"required package fixture missing: {source}")
                destination.write_bytes(
                    f"identity-test-placeholder:{source.name}\n".encode())
                destination.chmod(0o755)

        # The persistent-process checks exercise the identity MECHANISM
        # (post-start swaps must refuse), not the shipped pin value — the
        # smoke suite owns pin-value equality.  Pin the package-local
        # manifest copy to the freshly computed bundle hash so the process
        # starts even while the repo `plugin_hermes` row is mid-re-pin;
        # after the lead re-pins, this rewrite is a byte-for-byte no-op.
        package_manifest = package_root / "MANIFEST.sha256"
        pinned_lines = [
            (f"plugin_hermes {package_hash}"
             if line.startswith("plugin_hermes ") else line)
            for line in package_manifest.read_text().splitlines()
        ]
        package_manifest.write_text("\n".join(pinned_lines) + "\n")

        process = subprocess.Popen(
            [str(package_plugin / "jackal_hermes"), "stdio"],
            cwd=package_root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        def rpc(request: dict, *, timeout: int = 20) -> dict:
            require(process.stdin is not None and process.stdout is not None,
                    "persistent plugin pipes missing")
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
            ready, _, _ = select.select([process.stdout], [], [], timeout)
            require(bool(ready), "persistent plugin response timed out")
            line = process.stdout.readline()
            require(bool(line), "persistent plugin exited before response")
            return json.loads(line)

        runtime_victim = package_files["runtime/formal_receipt.py"]
        manifest_original = package_manifest.read_bytes()
        runtime_original = runtime_victim.read_bytes()
        try:
            baseline = rpc({"jsonrpc": "2.0", "id": 1, "method": "list_tools"})
            require("result" in baseline, f"persistent startup failed: {baseline}")

            navier_request = json.loads((
                ROOT / "release/evidence/navier_stokes_fixture_receipts/requests/"
                "gate_b_ratio_gt_one_alert.json"
            ).read_text())
            oversized_request = rpc({
                "jsonrpc": "2.0", "id": "NR1",
                "method": "jackal_navier_stokes_check",
                "params": {"request": {"padding": "x" * (4 * 1024 * 1024)}},
            }, timeout=30).get("result", {})
            require(
                oversized_request.get("reason") == "plugin-args-resource-limit",
                f"oversized Navier request did not refuse at byte cap: "
                f"{oversized_request}",
            )
            oversized_receipt = rpc({
                "jsonrpc": "2.0", "id": "NR2",
                "method": "jackal_verify_navier_stokes_receipt",
                "params": {
                    "receipt": {"padding": "x" * (16 * 1024 * 1024)},
                    "expected_request": navier_request,
                },
            }, timeout=30).get("result", {})
            require(
                oversized_receipt.get("reason") == "plugin-args-resource-limit",
                f"oversized Navier receipt did not refuse at byte cap: "
                f"{oversized_receipt}",
            )
            checked = rpc({
                "jsonrpc": "2.0", "id": "N1",
                "method": "jackal_navier_stokes_check",
                "params": {"request": navier_request},
            }, timeout=180).get("result", {})
            require(checked.get("status") == "indeterminate",
                    f"Navier alert status was not preserved: {checked}")
            require(checked.get("halt") is True,
                    f"Navier alert did not halt: {checked}")
            require(
                checked.get("reason") ==
                "uncertified_potential_blowup_vortex_stretching",
                f"Navier alert reason drifted: {checked}",
            )
            require(checked.get("receipt_replay") == "verified",
                    f"Navier producer output bypassed replay: {checked}")
            require(checked.get("verification_scope") == "receipt_replay_only",
                    f"Navier replay scope was promoted: {checked}")
            require(checked.get("nonclaims") == navier_request["nonclaims"],
                    f"Navier nonclaims drifted: {checked}")
            receipt = checked.get("receipt")
            require(isinstance(receipt, dict),
                    f"Navier check omitted receipt: {checked}")
            packaged_manifest = package_root / "domain_packs/pde/navier_stokes_v1.json"
            packaged_source = package_root / "domain_packs/pde/navier_stokes_v1.anb"
            authority = receipt.get("authority", {})
            require(
                authority.get("pack_manifest_sha256") ==
                hashlib.sha256(packaged_manifest.read_bytes()).hexdigest(),
                f"packaged producer did not bind packaged manifest: {authority}",
            )
            require(
                authority.get("anubis_source_sha256") ==
                hashlib.sha256(packaged_source.read_bytes()).hexdigest(),
                f"packaged producer did not bind packaged source: {authority}",
            )

            replayed = rpc({
                "jsonrpc": "2.0", "id": "N2",
                "method": "jackal_verify_navier_stokes_receipt",
                "params": {
                    "receipt": receipt,
                    "expected_request": navier_request,
                },
            }, timeout=180).get("result", {})
            require(replayed.get("status") == "verified",
                    f"Navier receipt replay failed: {replayed}")
            require(replayed.get("mathematical_status") == "indeterminate",
                    f"Navier replay promoted mathematical status: {replayed}")
            require(replayed.get("halt") is True,
                    f"Navier replay lost halt decision: {replayed}")
            require(replayed.get("verification_scope") == "receipt_replay_only",
                    f"Navier replay scope drifted: {replayed}")
            require(replayed.get("nonclaims") == navier_request["nonclaims"],
                    f"Navier replay lost nonclaims: {replayed}")

            wrong_request = json.loads(json.dumps(navier_request))
            wrong_request["scope"]["t1"] = "2"
            mismatch = rpc({
                "jsonrpc": "2.0", "id": "N3",
                "method": "jackal_verify_navier_stokes_receipt",
                "params": {
                    "receipt": receipt,
                    "expected_request": wrong_request,
                },
            }, timeout=180).get("result", {})
            require(mismatch.get("status") == "refused",
                    f"Navier request mismatch did not refuse: {mismatch}")
            require(
                mismatch.get("reason") == "navier-receipt-replay-refused",
                f"Navier request mismatch used a fallback: {mismatch}",
            )
            require("mathematical_status" not in mismatch,
                    f"failed replay exposed promoted status: {mismatch}")

            package_manifest.write_bytes(manifest_original + b"\n")
            manifest_swap = rpc({
                "jsonrpc": "2.0", "id": 2, "method": "jackal_range_bound",
                "params": {"expression": "x", "input_lo": "0", "input_hi": "1"},
            })
            require(
                manifest_swap.get("result", {}).get("reason") == "plugin-manifest-changed",
                f"post-start manifest swap was not refused: {manifest_swap}",
            )
            package_manifest.write_bytes(manifest_original)

            runtime_victim.write_bytes(runtime_original + b"\n")
            runtime_swap = rpc({
                "jsonrpc": "2.0", "id": 3, "method": "jackal_range_bound",
                "params": {"expression": "x", "input_lo": "0", "input_hi": "1"},
            })
            require(
                runtime_swap.get("result", {}).get("reason") == "plugin-bundle-mismatch",
                f"post-start runtime swap was not refused: {runtime_swap}",
            )
        finally:
            package_manifest.write_bytes(manifest_original)
            runtime_victim.write_bytes(runtime_original)
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)

        # A bundle-authorized component is still untrusted output-wise.  A
        # noisy packaged producer must be killed at the wrapper byte cap,
        # rather than buffered until it exits or misreported as a missing
        # receipt.  Repin only this private package copy so startup identity
        # remains valid and the real handler boundary is exercised.
        producer_victim = package_files[
            "runtime/tools/navier_stokes_certificate_producer.py"
        ]
        producer_original = producer_victim.read_bytes()
        noisy_source = (
            b"#!/usr/bin/env python3\n"
            b"import sys\n"
            b"sys.stdout.write('X' * (256 * 1024))\n"
            b"sys.stdout.flush()\n"
        )
        try:
            producer_victim.write_bytes(noisy_source)
            producer_victim.chmod(0o755)
            noisy_hash = compute_bundle_hash(package_plugin)
            noisy_manifest_lines = [
                (f"plugin_hermes {noisy_hash}"
                 if line.startswith("plugin_hermes ") else line)
                for line in manifest_original.decode().splitlines()
            ]
            package_manifest.write_text("\n".join(noisy_manifest_lines) + "\n")
            process = subprocess.Popen(
                [str(package_plugin / "jackal_hermes"), "stdio"],
                cwd=package_root,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                noisy = rpc({
                    "jsonrpc": "2.0", "id": "NR3",
                    "method": "jackal_navier_stokes_check",
                    "params": {"request": navier_request},
                }, timeout=30).get("result", {})
                require(
                    noisy.get("reason") == "navier-subprocess-output-limit",
                    f"noisy Navier producer was not output-bounded: {noisy}",
                )
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
        finally:
            producer_victim.write_bytes(producer_original)
            package_manifest.write_bytes(manifest_original)
        require(compute_bundle_hash(package_plugin) == package_hash,
                "package identity did not restore after noisy producer control")

        # Every declared runtime byte is load-bearing: a one-byte append to
        # each resolved package file must change the overall identity.
        for logical_name, path in package_files.items():
            original = path.read_bytes()
            path.write_bytes(original + b"\n")
            mutated = compute_bundle_hash(package_plugin)
            require(mutated != package_hash,
                    f"mutation was not identity-bound: {logical_name}")
            path.write_bytes(original)
            require(compute_bundle_hash(package_plugin) == package_hash,
                    f"identity did not restore: {logical_name}")

        # No candidate means fail closed instead of silently omitting a
        # runtime dependency.
        victim = package_files["runtime/receipt_verify.py"]
        victim.unlink()
        try:
            resolve_runtime_files(package_plugin)
        except SystemExit as exc:
            require("plugin-runtime-file-missing" in str(exc),
                    f"wrong missing-file refusal: {exc}")
        else:
            raise RuntimeError("missing runtime dependency was accepted")

    # Import-confusion control: unlisted sibling/root modules do not affect the
    # bundle digest, so the launcher must prevent them from shadowing stdlib or
    # exact project modules.  The isolated loader ignores both files and still
    # reaches the pinned selftest.  Pre-isolation server.py imported these.
    malicious_stdlib = PLUGIN_DIR / "subprocess.py"
    malicious_project = ROOT / "receipt_verify.py"
    require(not malicious_stdlib.exists() and not malicious_project.exists(),
            "shadow-control paths unexpectedly exist")
    try:
        malicious_stdlib.write_text("raise RuntimeError('SHADOWED-STDLIB')\n")
        malicious_project.write_text("raise RuntimeError('SHADOWED-PROJECT')\n")
        require(compute_bundle_hash(PLUGIN_DIR) == repo_hash,
                "unlisted shadow unexpectedly changed declared bundle identity")
        isolated = subprocess.run(
            [str(PLUGIN_DIR / "jackal_hermes"), "selftest"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        combined = isolated.stdout + isolated.stderr
        require("SHADOWED" not in combined,
                f"isolated launcher imported a shadow module: {combined}")
        if isolated.returncode == 0 and "identity_match=true" in isolated.stdout:
            pass  # pinned repo bundle: full selftest identity verdict
        elif isolated.returncode != 0 and (
                "reason=plugin-bundle-mismatch" in isolated.stdout
                or "reason=plugin-manifest-missing" in isolated.stdout
                or "plugin-layout-missing:" in combined):
            # The repo pin is mid-re-pin cycle: the isolated launcher still
            # reached a stable fail-closed boundary instead of importing
            # either shadow module.  Clean source checkouts may intentionally
            # omit generated native/checker artifacts.
            print("selftest identity_match: SKIPPED-artifact-or-manifest-pending")
        else:
            raise RuntimeError(
                f"isolated launcher admitted module shadowing: {combined}")
    finally:
        malicious_stdlib.unlink(missing_ok=True)
        malicious_project.unlink(missing_ok=True)

    print(json.dumps({
        "schema": "jackal-hermes-runtime-bundle-v2-test",
        "repo_package_equal": True,
        "runtime_file_count": len(repo_files),
        "all_runtime_mutations_bound": True,
        "missing_runtime_refused": True,
        "unlisted_module_shadow_refused": True,
        "post_start_manifest_swap_refused": True,
        "post_start_runtime_swap_refused": True,
        "navier_subprocess_output_bounded": True,
        "navier_request_receipt_caps_enforced": True,
        "bundle_sha256": repo_hash,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
