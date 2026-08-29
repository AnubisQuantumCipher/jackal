#!/bin/sh
set -eu

# Proof obligations: JCK-CLAIM-001, JCK-CLAIM-002, JCK-CLAIM-003.

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
PROJECT="$SCRIPT_DIR/jackal_claim_policy.gpr"

if ! command -v gnatprove >/dev/null 2>&1 || ! command -v gprbuild >/dev/null 2>&1; then
    if [ -f "$HOME/opt/gnat/env.sh" ]; then
        # shellcheck disable=SC1091
        . "$HOME/opt/gnat/env.sh"
    fi
fi

command -v gprbuild >/dev/null 2>&1 || {
    echo "refused: gprbuild is unavailable" >&2
    exit 1
}
command -v gnatprove >/dev/null 2>&1 || {
    echo "refused: gnatprove is unavailable" >&2
    exit 1
}

gprbuild -p -q -P "$PROJECT"
gnatprove -P "$PROJECT" -U --level=3 --report=all --warnings=error \
    --proof-warnings=on --assumptions -j0

PROOF_REPORT="$SCRIPT_DIR/obj/gnatprove/gnatprove.out"
[ -f "$PROOF_REPORT" ] || {
    echo "refused: GNATprove summary is missing" >&2
    exit 1
}

NORMALIZED_TOTAL=$(grep '^Total' "$PROOF_REPORT" | sed 's/([0-9]*%)//g' | tr -s ' ')
set -- $NORMALIZED_TOTAL
[ "$#" -eq 6 ] && [ "$5" = "." ] && [ "$6" = "." ] || {
    echo "refused: GNATprove reports justified or unproved checks" >&2
    exit 1
}

grep -q 'unit jackal_claim_policy' "$PROOF_REPORT" || {
    echo "refused: the claim policy unit was not analyzed" >&2
    exit 1
}

"$SCRIPT_DIR/../reject_assumptions.sh" \
    "$SCRIPT_DIR/src" "$SCRIPT_DIR/tests"

echo "SPARK_PLATINUM_CLAIM_POLICY_COMPONENT_PROOF_PASS"
