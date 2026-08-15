#!/bin/sh
# Build the deterministic JACKAL v1.2.0 macOS arm64 release package.
# Assembles a self-contained, fresh-extractable package: evaluator, proved
# checker, release wrapper + shared validator, evidence, manifest, SHA256SUMS,
# and honest non-claims. All artifact paths inside the package are relative to
# the package root — no repository fallback.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VER="v1.2.0"
PKG="$ROOT/release/dist/jackal-$VER-macos-arm64"
CHECKER="$ROOT/proofs/lean/.lake/build/bin/jackal_cert_check"

rm -rf "$PKG"
mkdir -p "$PKG/evidence" "$PKG/plugin/hermes"

# --- binaries + trust-boundary scripts ---
cp "$ROOT/jackal-native" "$PKG/jackal-native"
cp "$CHECKER" "$PKG/jackal_cert_check"
cp "$ROOT/tests/release_validate.py" "$PKG/release_validate.py"
cp "$ROOT/tools/formal_receipt.py" "$PKG/formal_receipt.py"
cp "$ROOT/tools/receipt_verify.py" "$PKG/receipt_verify.py"
cp "$ROOT/tools/formal_status_gate.py" "$PKG/formal_status_gate.py"
cp "$ROOT/tools/coverage_inventory.py" "$PKG/coverage_inventory.py"
cp "$ROOT/release/coverage/formal_coverage_inventory.json" "$PKG/formal_coverage_inventory.json"
cp "$ROOT/plugin/hermes/server.py" "$PKG/plugin/hermes/server.py"
cp "$ROOT/plugin/hermes/bundle_hash.py" "$PKG/plugin/hermes/bundle_hash.py"
cp "$ROOT/plugin/hermes/jackal_hermes" "$PKG/plugin/hermes/jackal_hermes"
cp "$ROOT/plugin/hermes/tools.json" "$PKG/plugin/hermes/tools.json"
chmod +x "$PKG/jackal-native" "$PKG/jackal_cert_check"
chmod +x "$PKG/plugin/hermes/jackal_hermes"

# --- package-local release wrapper: all paths relative to the package root ---
cat > "$PKG/jackal-cert-release" <<'WRAP'
#!/bin/sh
# JACKAL v1.2.0 packaged certified-release gate (self-contained).
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ "$#" -eq 3 ] || [ "$#" -eq 4 ] || { echo "usage: jackal-cert-release \"<expr in x>\" <lo> <hi> [formal-receipt.json]" >&2; exit 2; }
EE=$(awk '/^evaluator /{print $3}' "$HERE/MANIFEST.sha256")
EC=$(awk '/^checker /{print $3}' "$HERE/MANIFEST.sha256")
[ -n "$EE" ] && [ -n "$EC" ] || { echo "status=unavailable reason=manifest-incomplete" >&2; exit 3; }
if [ "$#" -eq 4 ]; then
  exec python3 "$HERE/release_validate.py" --expr "$1" --lo "$2" --hi "$3" \
    --evaluator "$HERE/jackal-native" --checker "$HERE/jackal_cert_check" \
    --expected-evaluator "$EE" --expected-checker "$EC" --release-epoch v1.2.0 \
    --formal-receipt "$4"
fi
exec python3 "$HERE/release_validate.py" --expr "$1" --lo "$2" --hi "$3" \
  --evaluator "$HERE/jackal-native" --checker "$HERE/jackal_cert_check" \
  --expected-evaluator "$EE" --expected-checker "$EC" --release-epoch v1.2.0
WRAP
chmod +x "$PKG/jackal-cert-release"

# --- evidence (durable, committed copies) ---
cp "$ROOT/release/evidence/positive_corpus.jsonl" "$PKG/evidence/"
cp "$ROOT/release/evidence/negative_controls.jsonl" "$PKG/evidence/"
cp "$ROOT/release/evidence/aba_mutations.json" "$PKG/evidence/"
cp "$ROOT/release/evidence/plugin_smoke.jsonl" "$PKG/evidence/"
cp "$ROOT/release/evidence/mutations_11.json" "$PKG/evidence/"
cp "$ROOT/release/evidence/fail_closed_sweep.jsonl" "$PKG/evidence/"

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
plugin_hermes daf4e5aa37ab40f16dcd2891aecbd4a81839e351a889323d72eb038098ed93bf
EOF

cat > "$PKG/NON-CLAIMS.txt" <<'EOF'
JACKAL v1.2.0 — explicit non-claims
- NOT universal correctness. The certified fragment is exactly:
  num, var, neg, add, sub, mul, div, integer pow (n>=0), sin, cos, abs,
  floor, ceil, round, trunc, min, max, and named constants (pi, e, tau).
- Transcendental operators (sqrt, exp, ln, tan, cbrt, atan, asin, acos,
  log10, log2, hypot, atan2), non-integer / general powers, negative integer
  powers, and '%' are FAIL-CLOSED (refused), NOT covered.
- The Lean theorem proves: an accepted certificate implies a Runs derivation
  and hence a true enclosure UNDER the named ModelTCB. It does NOT prove
  source parsing, the Anubis emitter's faithfulness, native refinement,
  executable identity, or release-wrapper correctness. Runtime provenance is
  enforced by the shared validator and independently rechecked from the
  embedded certificate. Emitter faithfulness is TESTED (positive corpus +
  executed controls + A->B->A), not proved.
- bound_step (adaptive integration) composition and Anubis source->native
  refinement remain OPEN.
- Platform: macOS arm64, unsigned/ad-hoc developer artifact. NO Apple
  Developer ID signing and NO notarization is claimed.
- This is a PUBLIC release of the jackal-calc project. The artifact is
  unsigned; verify SHA256SUMS and the pinned evaluator/checker identities in
  MANIFEST.sha256 before use.
EOF

cat > "$PKG/README.txt" <<'EOF'
JACKAL v1.2.0 — proof-carrying formal-receipt release (macOS arm64, public, unsigned)

Verify, then release a certified enclosure:
  shasum -a 256 -c SHA256SUMS         # every shipped file
  ./jackal-cert-release "x^2+1" 1 2 receipt.json
  python3 receipt_verify.py --receipt receipt.json \
    --checker ./jackal_cert_check \
    --expected-evaluator 820c0722e46a0800115c404ea1c9251c6f72fe8c6897bdabe437f342f9310b6c \
    --expected-checker 2186b43f8e45b7b3e55e189d64e92f15999664f5194caed929d14b29b006f59b \
    --inventory ./formal_coverage_inventory.json

status=formal-bounded is emitted ONLY when the shared validator confirms the exact
request commitment, the exact evaluator + checker executable identities
(pinned in MANIFEST.sha256), the proved checker's ACCEPT, TOCTOU stability,
and no status escalation. The formal receipt embeds the accepted certificate;
receipt_verify.py re-runs the pinned checker and re-derives the semantic
bindings. Any break refuses with a stable class, never a bounded fallback.
The bundled plugin/hermes adapter exposes the same release and verification
path. See NON-CLAIMS.txt for the exact scope.
EOF

cat > "$PKG/PROVENANCE-RECEIPT.txt" <<EOF
JACKAL $VER build/provenance receipt
built-from-source jackal_calc.anb $SRC_ID
compiler-pin anubis-a733565f237d a733565f237df171e7cf93b9b37700a42d8713576818fd92f8cd23a8ad7a69e2
evaluator jackal-native $EVAL_ID
checker jackal_cert_check $CHK_ID
lean-theorems cert_check_sound cert_encloses certified_release
lean-axioms propext Classical.choice Quot.sound
platform macos-arm64 public-unsigned-adhoc
EOF

# --- SHA256SUMS over every shipped file (the manifest root) ---
( cd "$PKG" && find . -type f ! -name SHA256SUMS | LC_ALL=C sort \
    | while read -r f; do shasum -a 256 "$f"; done > SHA256SUMS )

# --- byte-reproducible archive.  Do not delegate archive metadata to the host
# tar implementation: serialize a sorted ustar stream with fixed ownership,
# names, modes, and timestamps, then gzip it with mtime=0 and no filename. ---
TARBALL="$ROOT/release/dist/jackal-$VER-macos-arm64.tar.gz"
python3 - "$PKG" "$TARBALL" <<'PY'
import gzip
import pathlib
import sys
import tarfile

pkg = pathlib.Path(sys.argv[1]).resolve()
out = pathlib.Path(sys.argv[2]).resolve()
paths = [pkg, *sorted(pkg.rglob("*"), key=lambda p: p.relative_to(pkg).as_posix())]
with out.open("wb") as raw:
    with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w", format=tarfile.USTAR_FORMAT) as tf:
            for path in paths:
                arcname = pkg.name if path == pkg else f"{pkg.name}/{path.relative_to(pkg).as_posix()}"
                info = tf.gettarinfo(str(path), arcname=arcname)
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                info.mtime = 1786752000  # 2026-08-15T00:00:00Z
                info.pax_headers = {}
                if path.is_file():
                    with path.open("rb") as src:
                        tf.addfile(info, src)
                else:
                    tf.addfile(info)
PY

echo "package=$PKG"
echo "files=$(cd "$PKG" && find . -type f | wc -l | tr -d ' ')"
echo "sha256sums_root=$(shasum -a 256 "$PKG/SHA256SUMS" | awk '{print $1}')"
echo "tarball=$TARBALL"
echo "tarball_sha256=$(shasum -a 256 "$TARBALL" | awk '{print $1}')"
echo "tarball_bytes=$(command wc -c < "$TARBALL" | tr -d ' ')"
