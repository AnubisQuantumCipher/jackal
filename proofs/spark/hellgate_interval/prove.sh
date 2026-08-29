#!/bin/sh
set -eu

# Proof obligations: JCK-INT-001, JCK-INT-002, JCK-INT-003, JCK-INT-004.

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
PROJECT="$SCRIPT_DIR/hellgate_interval.gpr"

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
"$SCRIPT_DIR/bin/hellgate_interval_demo"
gnatprove -P "$PROJECT" -U --level=3 --report=all --warnings=error \
    --proof-warnings=on --assumptions -j0

PROOF_REPORT="$SCRIPT_DIR/obj/gnatprove/gnatprove.out"
if [ ! -f "$PROOF_REPORT" ]; then
    echo "refused: GNATprove summary is missing" >&2
    exit 1
fi

NORMALIZED_TOTAL=$(grep '^Total' "$PROOF_REPORT" | sed 's/([0-9]*%)//g' | tr -s ' ')
set -- $NORMALIZED_TOTAL
if [ "$#" -ne 6 ] || [ "$5" != "." ] || [ "$6" != "." ]; then
    echo "refused: GNATprove reports justified or unproved checks" >&2
    exit 1
fi

grep -q 'unit jackal_interval_envelope' "$PROOF_REPORT" || {
    echo "refused: the interval decision unit was not analyzed" >&2
    exit 1
}

"$SCRIPT_DIR/../reject_assumptions.sh" \
    "$PROOF_REPORT" "$SCRIPT_DIR/src" "$SCRIPT_DIR/tests"

echo "SPARK_PLATINUM_INTERVAL_COMPONENT_PROOF_PASS"
