#!/bin/sh
# Build the deterministic JACKAL v1.0.4 macOS arm64 release package (mission §424).
# Assembles a self-contained, fresh-extractable package: evaluator, proved
# checker, release wrapper + shared validator, evidence, manifest, SHA256SUMS,
# and honest non-claims. All artifact paths inside the package are relative to
# the package root — no repository fallback.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VER="v1.0.4"
PKG="$ROOT/release/dist/jackal-$VER-macos-arm64"
CHECKER="$ROOT/proofs/lean/.lake/build/bin/jackal_cert_check"

rm -rf "$PKG"
mkdir -p "$PKG/evidence"

# --- binaries + trust-boundary scripts ---
cp "$ROOT/jackal-native" "$PKG/jackal-native"
cp "$CHECKER" "$PKG/jackal_cert_check"
cp "$ROOT/tests/release_validate.py" "$PKG/release_validate.py"
chmod +x "$PKG/jackal-native" "$PKG/jackal_cert_check"

# --- package-local release wrapper: all paths relative to the package root ---
cat > "$PKG/jackal-cert-release" <<'WRAP'
#!/bin/sh
# JACKAL v1.0.4 packaged certified-release gate (self-contained).
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ "$#" -eq 3 ] || { echo "usage: jackal-cert-release \"<expr in x>\" <lo> <hi>" >&2; exit 2; }
EE=$(awk '/^evaluator /{print $3}' "$HERE/MANIFEST.sha256")
EC=$(awk '/^checker /{print $3}' "$HERE/MANIFEST.sha256")
[ -n "$EE" ] && [ -n "$EC" ] || { echo "status=unavailable reason=manifest-incomplete" >&2; exit 3; }
exec python3 "$HERE/release_validate.py" --expr "$1" --lo "$2" --hi "$3" \
  --evaluator "$HERE/jackal-native" --checker "$HERE/jackal_cert_check" \
  --expected-evaluator "$EE" --expected-checker "$EC"
WRAP
chmod +x "$PKG/jackal-cert-release"

# --- evidence (durable, committed copies) ---
cp "$ROOT/release/evidence/positive_corpus.jsonl" "$PKG/evidence/"
cp "$ROOT/release/evidence/negative_controls.jsonl" "$PKG/evidence/"
cp "$ROOT/release/evidence/aba_mutations.json" "$PKG/evidence/"

EVAL_ID=$(shasum -a 256 "$PKG/jackal-native" | awk '{print $1}')
CHK_ID=$(shasum -a 256 "$PKG/jackal_cert_check" | awk '{print $1}')
SRC_ID=$(shasum -a 256 "$ROOT/jackal_calc.anb" | awk '{print $1}')

cat > "$PKG/MANIFEST.sha256" <<EOF
# JACKAL $VER package manifest — macOS arm64, schema v2, model jackal-iv-model-v1
version $VER
schema jackal-eval-cert-v2
model jackal-iv-model-v1
evaluator jackal-native $EVAL_ID
checker jackal_cert_check $CHK_ID
source jackal_calc.anb $SRC_ID
compiler_pin anubis-a733565f237d a733565f237df171e7cf93b9b37700a42d8713576818fd92f8cd23a8ad7a69e2
EOF

cat > "$PKG/NON-CLAIMS.txt" <<'EOF'
JACKAL v1.0.4 — explicit non-claims (mission §629)
- NOT universal correctness. The certified fragment is exactly:
  num, var, neg, add, sub, mul, div, integer pow (n>=0), sin, cos, abs,
  floor, ceil, round, trunc, min, max, and named constants (pi, e, tau).
- Transcendental operators (sqrt, exp, ln, tan, cbrt, atan, asin, acos,
  log10, log2, hypot, atan2), non-integer / general powers, negative integer
  powers, and '%' are FAIL-CLOSED (refused), NOT covered.
- The Lean theorem proves: an accepted certificate implies a Runs derivation
  and hence a true enclosure UNDER the named ModelTCB. It does NOT prove
  source parsing, the Anubis emitter's faithfulness, native refinement,
  executable identity, or release-wrapper correctness. Emitter faithfulness
  is TESTED (positive corpus + executed controls + A->B->A), not proved.
- bound_step (adaptive integration) composition and Anubis source->native
  refinement remain OPEN.
- Platform: macOS arm64, private unsigned/ad-hoc developer artifact. NO Apple
  Developer ID signing and NO notarization is claimed.
- This is a PRIVATE, authenticated release. No public download is claimed.
EOF

cat > "$PKG/README.txt" <<'EOF'
JACKAL v1.0.4 — proof-carrying certified-range release (macOS arm64, PRIVATE)

Verify, then release a certified enclosure:
  shasum -a 256 -c SHA256SUMS         # every shipped file
  ./jackal-cert-release "x^2+1" 1 2   # -> status=bounded + identities

status=bounded is emitted ONLY when the shared validator confirms the exact
request commitment, the exact evaluator + checker executable identities
(pinned in MANIFEST.sha256), the proved checker's ACCEPT, TOCTOU stability,
and no status escalation. Any break refuses with a stable class, never a
bounded fallback. See NON-CLAIMS.txt for the exact scope.
EOF

cat > "$PKG/PROVENANCE-RECEIPT.txt" <<EOF
JACKAL $VER build/provenance receipt
built-from-source jackal_calc.anb $SRC_ID
compiler-pin anubis-a733565f237d a733565f237df171e7cf93b9b37700a42d8713576818fd92f8cd23a8ad7a69e2
evaluator jackal-native $EVAL_ID
checker jackal_cert_check $CHK_ID
lean-theorems cert_check_sound cert_encloses certified_release
lean-axioms propext Classical.choice Quot.sound
platform macos-arm64 private-unsigned-adhoc
EOF

# --- SHA256SUMS over every shipped file (the manifest root) ---
( cd "$PKG" && find . -type f ! -name SHA256SUMS | LC_ALL=C sort \
    | while read -r f; do shasum -a 256 "$f"; done > SHA256SUMS )

echo "package=$PKG"
echo "files=$(cd "$PKG" && find . -type f | wc -l | tr -d ' ')"
echo "sha256sums_root=$(shasum -a 256 "$PKG/SHA256SUMS" | awk '{print $1}')"
