#!/bin/sh
set -eu

if [ "$#" -lt 2 ]; then
    echo "refused: a GNATprove report and SPARK source roots are required" >&2
    exit 1
fi

PROOF_REPORT=$1
shift

[ -f "$PROOF_REPORT" ] || {
    echo "refused: the GNATprove report is not a regular file" >&2
    exit 1
}

if grep -Eq '\([1-9][0-9]* pragma Assume statements?\)' "$PROOF_REPORT"; then
    echo "refused: GNATprove reports one or more proof assumptions" >&2
    exit 1
fi

command -v rg >/dev/null 2>&1 || {
    echo "refused: rg is unavailable for the SPARK assumption scan" >&2
    exit 1
}

# Ada identifiers are case-insensitive and whitespace can span lines.  Keep
# this scan multiline and case-insensitive so spelling or formatting cannot
# bypass the no-assumption/no-justification policy.
if rg -n -i -U --glob '*.ad?' \
    'pragma[[:space:]]+(Assume|Annotate)\b' "$@"; then
    echo "refused: proof assumptions or justifications are forbidden" >&2
    exit 1
fi
