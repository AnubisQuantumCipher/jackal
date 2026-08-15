#!/usr/bin/env python3
"""Focused tests for the Hermes plugin's layout-independent runtime identity."""
from __future__ import annotations

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
    "runtime/formal_receipt.py",
    "runtime/formal_status_gate.py",
    "runtime/gaussian_certificate.py",
    "runtime/gaussian_release.py",
    "runtime/isolated_entry.py",
    "runtime/receipt_verify.py",
    "runtime/release_validate.py",
    "runtime/sqrt_rat_producer.py",
    "runtime/exp_rat_producer.py",
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
    "runtime/formal_receipt.py": "formal_receipt.py",
    "runtime/formal_status_gate.py": "formal_status_gate.py",
    "runtime/gaussian_certificate.py": "gaussian_certificate.py",
    "runtime/gaussian_release.py": "gaussian_release.py",
    "runtime/isolated_entry.py": "isolated_entry.py",
    "runtime/receipt_verify.py": "receipt_verify.py",
    "runtime/release_validate.py": "release_validate.py",
    "runtime/sqrt_rat_producer.py": "sqrt_rat_producer.py",
    "runtime/exp_rat_producer.py": "exp_rat_producer.py",
}


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise RuntimeError(detail)


def main() -> int:
    repo_files = resolve_runtime_files(PLUGIN_DIR)
    require(set(repo_files) == EXPECTED_LOGICAL_NAMES,
            f"runtime logical-name drift: {sorted(repo_files)}")
    repo_hash = compute_bundle_hash(PLUGIN_DIR)

    with tempfile.TemporaryDirectory(prefix="jackal-plugin-identity-") as td:
        package_root = Path(td) / "jackal-v1.3.0-macos-arm64"
        package_plugin = package_root / "plugin" / "hermes"
        for logical_name, source in repo_files.items():
            destination = package_root / PACKAGE_DESTINATIONS[logical_name]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

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
        }
        for source, destination in package_artifacts.items():
            shutil.copy2(source, destination)

        process = subprocess.Popen(
            [str(package_plugin / "jackal_hermes"), "stdio"],
            cwd=package_root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        def rpc(request: dict) -> dict:
            require(process.stdin is not None and process.stdout is not None,
                    "persistent plugin pipes missing")
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
            ready, _, _ = select.select([process.stdout], [], [], 20)
            require(bool(ready), "persistent plugin response timed out")
            line = process.stdout.readline()
            require(bool(line), "persistent plugin exited before response")
            return json.loads(line)

        package_manifest = package_root / "MANIFEST.sha256"
        runtime_victim = package_files["runtime/formal_receipt.py"]
        manifest_original = package_manifest.read_bytes()
        runtime_original = runtime_victim.read_bytes()
        try:
            baseline = rpc({"jsonrpc": "2.0", "id": 1, "method": "list_tools"})
            require("result" in baseline, f"persistent startup failed: {baseline}")

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
        require(
            isolated.returncode == 0 and "identity_match=true" in isolated.stdout,
            f"isolated launcher admitted module shadowing: {isolated.stdout}{isolated.stderr}",
        )
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
        "bundle_sha256": repo_hash,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
