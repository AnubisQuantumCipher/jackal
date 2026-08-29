#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)

command -v python3 >/dev/null 2>&1 || {
    echo "refused: python3 is unavailable for the SPARK assumption scan" >&2
    exit 1
}

exec python3 -I -B "$SCRIPT_DIR/reject_assumptions.py" "$@"
