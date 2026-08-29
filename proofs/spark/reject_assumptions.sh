#!/bin/sh
set -eu

if [ "$#" -eq 0 ]; then
    echo "refused: no SPARK source roots were supplied" >&2
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
