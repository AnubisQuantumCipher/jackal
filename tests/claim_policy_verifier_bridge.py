#!/usr/bin/env python3
"""Isolated verifier bridge for JCK-CLAIM-001, JCK-CLAIM-002, JCK-CLAIM-003."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


if not (sys.flags.isolated and sys.flags.no_site):
    sys.stderr.write("refused: verifier bridge requires python3 -I -S -B\n")
    raise SystemExit(126)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import claim_bundle_verify as verifier  # noqa: E402


def normalized(value: str, prefix: str = "") -> str:
    result = value.strip().lower().replace("_", "-")
    if prefix and result.startswith(prefix):
        return result[len(prefix):]
    return result


def artifact_flags(mask: int) -> dict[str, bool]:
    return {
        flag: bool(mask & (1 << position))
        for position, flag in enumerate(verifier.ARTIFACT_FLAGS)
    }


def artifact_mask(flags: dict[str, bool]) -> int:
    return sum(
        1 << position
        for position, flag in enumerate(verifier.ARTIFACT_FLAGS)
        if flags[flag]
    )


def assurance_parent(
    *,
    mathematical: str = "checked",
    implementation: str = "directly-trusted",
    input_provenance: str = "unknown",
    model_validity: str = "not-applicable",
    artifact: dict[str, bool] | None = None,
) -> dict:
    return {
        "assurance": {
            "input_provenance": input_provenance,
            "model_validity": model_validity,
            "mathematical": mathematical,
            "implementation": implementation,
            "artifact": artifact or {
                flag: False for flag in verifier.ARTIFACT_FLAGS
            },
        }
    }


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    if len(sys.argv) != 2:
        raise RuntimeError("expected one SPARK vector executable")
    vectors = Path(sys.argv[1]).resolve(strict=True)
    completed = subprocess.run(
        [str(vectors)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    require(completed.returncode == 0, completed.stdout + completed.stderr)

    engine = verifier.RuleEngine(None, {})
    seen: set[str] = set()
    rule_vectors: dict[tuple[str, str, str], tuple[str, str]] = {}

    def integrated_axes(rule_id: str, parents: list[dict]) -> dict:
        return engine.computed_axes({"rule": {"id": rule_id}}, parents)

    for raw_line in completed.stdout.splitlines():
        fields = [field.strip() for field in raw_line.split("|")]
        kind = fields[0]
        seen.add(kind)

        if kind == "MATH":
            left, right, expected = (normalized(item) for item in fields[1:])
            require(
                verifier.meet_ordered(
                    [left, right], verifier.MATH_ORDER, verifier.MATH_RANKS
                ) == expected,
                f"mathematical meet mismatch: {fields}",
            )
            require(
                integrated_axes(
                    "model_condition",
                    [
                        assurance_parent(mathematical=left),
                        assurance_parent(mathematical=right),
                    ],
                )["mathematical"] == expected,
                f"integrated mathematical mismatch: {fields}",
            )
        elif kind == "PROVENANCE":
            left, right, expected = (normalized(item) for item in fields[1:])
            require(
                verifier.meet_ordered([left, right], verifier.PROV_ORDER) == expected,
                f"provenance meet mismatch: {fields}",
            )
            require(
                integrated_axes(
                    "model_condition",
                    [
                        assurance_parent(input_provenance=left),
                        assurance_parent(input_provenance=right),
                    ],
                )["input_provenance"] == expected,
                f"integrated provenance mismatch: {fields}",
            )
        elif kind == "MODEL":
            left, right, expected = (
                normalized(item, "model-") for item in fields[1:]
            )
            require(
                verifier.meet_model([left, right]) == expected,
                f"model meet mismatch: {fields}",
            )
            require(
                integrated_axes(
                    "model_condition",
                    [
                        assurance_parent(model_validity=left),
                        assurance_parent(model_validity=right),
                    ],
                )["model_validity"] == expected,
                f"integrated model mismatch: {fields}",
            )
        elif kind == "IMPLEMENTATION":
            left, right, expected = (
                normalized(item, "impl-") for item in fields[1:]
            )
            require(
                verifier.meet_ordered([left, right], verifier.IMPL_ORDER) == expected,
                f"implementation meet mismatch: {fields}",
            )
            require(
                integrated_axes(
                    "model_condition",
                    [
                        assurance_parent(implementation=left),
                        assurance_parent(implementation=right),
                    ],
                )["implementation"] == expected,
                f"integrated implementation mismatch: {fields}",
            )
        elif kind == "RULE":
            behavior = normalized(fields[1])
            mathematical = normalized(fields[2])
            implementation = normalized(fields[3], "impl-")
            rule_vectors[(behavior, mathematical, implementation)] = (
                normalized(fields[4]), normalized(fields[5], "impl-")
            )
        elif kind == "ARTIFACT":
            left, right, expected = (int(item) for item in fields[1:])
            axes = integrated_axes(
                "model_condition",
                [
                    assurance_parent(artifact=artifact_flags(left)),
                    assurance_parent(artifact=artifact_flags(right)),
                ],
            )
            require(
                artifact_mask(axes["artifact"]) == expected,
                f"artifact meet mismatch: {fields}",
            )
        else:
            raise RuntimeError(f"unknown SPARK vector kind: {kind}")

    require(
        seen == {"MATH", "PROVENANCE", "MODEL", "IMPLEMENTATION", "RULE", "ARTIFACT"},
        f"incomplete SPARK vector kinds: {sorted(seen)}",
    )

    for rule_id in verifier.RULE_IDS:
        if rule_id in verifier.PRESERVE_RULES:
            behavior = "preserve-axes"
        elif rule_id in verifier.MATH_CAPS:
            behavior = "interval-arithmetic"
        else:
            behavior = "derived-default"
        for mathematical in verifier.MATH_ORDER:
            for implementation in verifier.IMPL_ORDER:
                expected_math, expected_impl = rule_vectors[
                    (behavior, mathematical, implementation)
                ]
                axes = integrated_axes(
                    rule_id,
                    [
                        assurance_parent(
                            mathematical=mathematical,
                            implementation=implementation,
                        )
                    ],
                )
                require(
                    axes["mathematical"] == expected_math,
                    f"rule mathematical mismatch: {rule_id}",
                )
                require(
                    axes["implementation"] == expected_impl,
                    f"rule implementation mismatch: {rule_id}",
                )

    print(
        json.dumps(
            {
                "status": "pass",
                "PROV_ORDER": verifier.PROV_ORDER,
                "MODEL_ORDER": verifier.MODEL_ORDER,
                "MODEL_IDENTITY": verifier.MODEL_IDENTITY,
                "MATH_ORDER": verifier.MATH_ORDER,
                "MATH_RANKS": verifier.MATH_RANKS,
                "IMPL_ORDER": verifier.IMPL_ORDER,
                "ARTIFACT_FLAGS": verifier.ARTIFACT_FLAGS,
                "MATH_CAPS": verifier.MATH_CAPS,
                "PRESERVE_RULES": sorted(verifier.PRESERVE_RULES),
                "IMPL_CAP_DEFAULT": verifier.IMPL_CAP_DEFAULT,
                "RULE_IDS": sorted(verifier.RULE_IDS),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
