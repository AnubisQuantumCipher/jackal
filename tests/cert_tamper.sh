#!/bin/sh
# A→B→A semantic tamper experiment for the proof-carrying ieval→Runs bridge
# (mission §118-130). Demonstrates the checker "turns red" for the intended
# SEMANTIC reason when the ACTUAL engine emitter is mutated to produce a
# non-enclosing interval — i.e. an error in the real evaluator prevents
# certified release (mission §71), never an unsupported acceptance.
#
# Why the engine emitter (not the checker): the Lean soundness theorem
# `cert_check_sound` makes ANY soundness-weakening tamper of the checker FAIL TO
# COMPILE (the proof would become false), which the mission classes as an
# INVALID tamper. The engine emitter is outside the proof, compiles and runs
# after mutation, so it is the valid semantic-tamper surface.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ENGINE="$ROOT/jackal_calc.anb"
CHECKER="$ROOT/proofs/lean/.lake/build/bin/jackal_cert_check"
export ANUBIS_BIN="${ANUBIS_BIN:-$HOME/anubis-lang/vm/pins/anubis-a733565f237d}"
export JACKAL_FORCE_SOURCE=1
export JACKAL_OUT=/tmp/jcert-tamper-build

gate() {  # emit a cert for x^2+1 over [1,2] and report ACCEPT/REJECT
    if "$ROOT/jackal" range-bound-cert "x^2+1" 1 2 > /tmp/tamper_cert.txt 2>/tmp/tamper.err; then
        if "$CHECKER" /tmp/tamper_cert.txt >/dev/null 2>&1; then echo ACCEPT; else echo REJECT; fi
    else
        echo ENGINE_REFUSE
    fi
}

CANON_HASH=$(shasum -a 256 "$ENGINE" | awk '{print $1}')
cp "$ENGINE" /tmp/jackal_calc.canonical.anb
echo "canonical engine sha256: $CANON_HASH"

echo "--- A (baseline): valid engine ---"
rm -rf "$JACKAL_OUT"
A=$(gate); echo "  gate: $A"
[ "$A" = "ACCEPT" ] || { echo "FAIL: baseline did not ACCEPT"; exit 1; }

echo "--- B (semantic tamper): add-node emits its raw sum as out, WITHOUT the outward pad (non-enclosing) ---"
# cert_pad_lo/cert_pad_hi widen outward; replacing them with identity in the add
# lane makes the emitted interval too tight to enclose — a real evaluator error.
# Still compiles and runs (pure Anubis edit, no proof involved).
perl -0pi -e 's/(let out_lo = )cert_pad_lo(\(flo\));\n(\s*let out_hi = )cert_pad_hi(\(fhi\));\n(\s*let line = "node " \+ str\(id\) \+ " add)/${1}flo;\n${3}fhi;\n${5}/' "$ENGINE"
if ! grep -q 'let out_lo = flo;' "$ENGINE"; then echo "FAIL: tamper pattern did not apply"; cp /tmp/jackal_calc.canonical.anb "$ENGINE"; exit 1; fi
rm -rf "$JACKAL_OUT"
B=$(gate); echo "  gate: $B"
if [ "$B" != "REJECT" ]; then
    echo "FAIL: tampered (non-enclosing) engine was not REJECTED (soundness gate inert!)"
    cp /tmp/jackal_calc.canonical.anb "$ENGINE"; exit 1
fi
echo "  -> checker turned RED for the intended reason: emitted out != recomputed padQ(fl)"

echo "--- A (restore by hash + purge stale build) ---"
cp /tmp/jackal_calc.canonical.anb "$ENGINE"
RESTORED_HASH=$(shasum -a 256 "$ENGINE" | awk '{print $1}')
[ "$RESTORED_HASH" = "$CANON_HASH" ] || { echo "FAIL: restored hash $RESTORED_HASH != canonical $CANON_HASH"; exit 1; }
echo "  restored engine sha256: $RESTORED_HASH  (matches canonical)"
rm -rf "$JACKAL_OUT"    # purge the stale native build so no cached binary masks the result
A2=$(gate); echo "  gate: $A2"
[ "$A2" = "ACCEPT" ] || { echo "FAIL: restored engine did not ACCEPT (stale build?)"; exit 1; }

echo ""
echo "A->B->A TAMPER: PASS  (green -> red-for-intended-reason -> green, restore hash-verified, stale build purged)"
