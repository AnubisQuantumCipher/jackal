#!/bin/sh
# Build the deterministic JACKAL v1.6.0 macOS arm64 release package
# (v1.5.0 computation floor + additive claim-bundle evidence kernel).
# Generated from build_package.sh for the v1.6.0 epoch; the v1.5.0
# builder and its dist output remain byte-frozen.
# Assembles a self-contained, fresh-extractable package: evaluator, proved
# checker, release wrapper + shared validator, evidence, manifest, SHA256SUMS,
# and honest non-claims. All artifact paths inside the package are relative to
# the package root — no repository fallback.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VER="v1.6.0"
PKG="$ROOT/release/dist/jackal-$VER-macos-arm64"
CHECKER="$ROOT/proofs/lean/.lake/build/bin/jackal_cert_check"
GAUSSIAN_CHECKER="$ROOT/proofs/lean/.lake/build/bin/jackal_gaussian_check"

rm -rf "$PKG"
mkdir -p "$PKG/evidence" "$PKG/plugin/hermes"

# --- binaries + trust-boundary scripts ---
cp "$ROOT/jackal-native" "$PKG/jackal-native"
cp "$ROOT/jackal_calc.anb" "$PKG/jackal_calc.anb"
cp "$CHECKER" "$PKG/jackal_cert_check"
cp "$GAUSSIAN_CHECKER" "$PKG/jackal_gaussian_check"
cp "$ROOT/tests/release_validate.py" "$PKG/release_validate.py"
cp "$ROOT/tools/gaussian_certificate.py" "$PKG/gaussian_certificate.py"
cp "$ROOT/tools/gaussian_release.py" "$PKG/gaussian_release.py"
cp "$ROOT/tools/formal_receipt.py" "$PKG/formal_receipt.py"
cp "$ROOT/tools/receipt_verify.py" "$PKG/receipt_verify.py"
cp "$ROOT/tools/formal_status_gate.py" "$PKG/formal_status_gate.py"
cp "$ROOT/tools/coverage_inventory.py" "$PKG/coverage_inventory.py"
cp "$ROOT/tools/isolated_entry.py" "$PKG/isolated_entry.py"
cp "$ROOT/release/coverage/formal_coverage_inventory.json" "$PKG/formal_coverage_inventory.json"
cp "$ROOT/release/evidence/range_proof_identity.json" "$PKG/range_proof_identity.json"
cp "$ROOT/release/evidence/gaussian_proof_identity.json" "$PKG/gaussian_proof_identity.json"
cp "$ROOT/plugin/hermes/server.py" "$PKG/plugin/hermes/server.py"
cp "$ROOT/plugin/hermes/bundle_hash.py" "$PKG/plugin/hermes/bundle_hash.py"
cp "$ROOT/plugin/hermes/jackal_hermes" "$PKG/plugin/hermes/jackal_hermes"
cp "$ROOT/plugin/hermes/tools.json" "$PKG/plugin/hermes/tools.json"
chmod +x "$PKG/jackal-native" "$PKG/jackal_cert_check" "$PKG/jackal_gaussian_check"
chmod +x "$PKG/gaussian_certificate.py" "$PKG/gaussian_release.py" "$PKG/isolated_entry.py"
chmod +x "$PKG/plugin/hermes/jackal_hermes"

# --- package-local release wrapper: all paths relative to the package root ---
cat > "$PKG/jackal-cert-release" <<'WRAP'
#!/bin/sh
# JACKAL v1.5.0 packaged certified-release gate (self-contained).
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ "$#" -eq 4 ] || { echo "usage: jackal-cert-release \"<expr in x>\" <lo> <hi> <formal-receipt.json>" >&2; exit 2; }
EE=$(awk '/^evaluator /{print $3}' "$HERE/MANIFEST.sha256")
EC=$(awk '/^checker /{print $3}' "$HERE/MANIFEST.sha256")
ES=$(awk '/^source /{print $3}' "$HERE/MANIFEST.sha256")
EI=$(awk '/^coverage_inventory /{print $3}' "$HERE/MANIFEST.sha256")
EPF=$(awk '/^range_proof_identity /{print $3}' "$HERE/MANIFEST.sha256")
EPD=$(awk '/^range_proof_digest /{print $2}' "$HERE/MANIFEST.sha256")
[ -n "$EE" ] && [ -n "$EC" ] && [ -n "$ES" ] && [ -n "$EI" ] && \
  [ -n "$EPF" ] && [ -n "$EPD" ] || { echo "status=unavailable reason=manifest-incomplete" >&2; exit 3; }
exec python3 -I -S -B "$HERE/isolated_entry.py" range \
  --expr "$1" --lo "$2" --hi "$3" \
  --evaluator "$HERE/jackal-native" --checker "$HERE/jackal_cert_check" \
  --expected-evaluator "$EE" --expected-checker "$EC" --expected-source "$ES" \
  --inventory "$HERE/formal_coverage_inventory.json" --expected-inventory "$EI" \
  --proof-identity "$HERE/range_proof_identity.json" \
  --expected-proof-identity-file "$EPF" --expected-proof-identity-digest "$EPD" \
  --release-epoch v1.5.0 --formal-receipt "$4"
WRAP
chmod +x "$PKG/jackal-cert-release"

cat > "$PKG/jackal-gaussian-release" <<'WRAP'
#!/bin/sh
# JACKAL v1.5.0 theorem-backed Gaussian integration gate (self-contained).
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ "$#" -eq 5 ] || { echo "usage: jackal-gaussian-release <expression> <lo> <hi> <tolerance> <receipt.json>" >&2; exit 2; }
EP=$(awk '/^gaussian_producer /{print $3}' "$HERE/MANIFEST.sha256")
EC=$(awk '/^gaussian_checker /{print $3}' "$HERE/MANIFEST.sha256")
EI=$(awk '/^coverage_inventory /{print $3}' "$HERE/MANIFEST.sha256")
EPF=$(awk '/^gaussian_proof_identity /{print $3}' "$HERE/MANIFEST.sha256")
EPD=$(awk '/^gaussian_proof_digest /{print $2}' "$HERE/MANIFEST.sha256")
[ -n "$EP" ] && [ -n "$EC" ] && [ -n "$EI" ] && [ -n "$EPF" ] && \
  [ -n "$EPD" ] || { echo "status=refused reason=manifest-incomplete" >&2; exit 3; }
exec python3 -I -S -B "$HERE/isolated_entry.py" gaussian \
  --expression "$1" --lower "$2" --upper "$3" --tolerance "$4" \
  --producer "$HERE/gaussian_certificate.py" --checker "$HERE/jackal_gaussian_check" \
  --expected-producer "$EP" --expected-checker "$EC" --release-epoch v1.5.0 \
  --inventory "$HERE/formal_coverage_inventory.json" --expected-inventory "$EI" \
  --proof-identity "$HERE/gaussian_proof_identity.json" \
  --expected-proof-identity-file "$EPF" --expected-proof-identity-digest "$EPD" \
  --receipt "$5"
WRAP
chmod +x "$PKG/jackal-gaussian-release"

cat > "$PKG/jackal-receipt-verify" <<'WRAP'
#!/bin/sh
# JACKAL v1.5.0 isolated formal-receipt verifier (self-contained).
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 -I -S -B "$HERE/isolated_entry.py" verify "$@"
WRAP
chmod +x "$PKG/jackal-receipt-verify"

cp "$ROOT/tools/sqrt_rat_producer.py" "$PKG/sqrt_rat_producer.py"
chmod +x "$PKG/sqrt_rat_producer.py"
cat > "$PKG/jackal-sqrt-rat-release" <<'WRAP'
#!/bin/sh
# JACKAL v1.5.0 sqrt_rat pure-ℚ release gate (self-contained; NO libm TCB).
# Producer + checker identities pinned to MANIFEST.sha256; TOCTOU stable.
# When a 4th argument is supplied, writes a canonical jackal-formal-receipt-v1
# JSON receipt (variant=sqrt_rat) that jackal-receipt-verify accepts.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "$#" -lt 3 ] || [ "$#" -gt 4 ]; then
  echo "usage: jackal-sqrt-rat-release \"sqrt(x)\" <lo> <hi> [formal-receipt.json]" >&2
  exit 2
fi
EXPR="$1"; LO="$2"; HI="$3"; RECEIPT_OUT="${4:-}"
EP=$(awk '$1=="sqrt_rat_producer" {print $NF}' "$HERE/MANIFEST.sha256")
EC=$(awk '$1=="checker" {print $NF}' "$HERE/MANIFEST.sha256")
[ -n "$EP" ] && [ -n "$EC" ] || { echo "status=unavailable reason=manifest-incomplete" >&2; exit 3; }
PP=$(shasum -a 256 "$HERE/sqrt_rat_producer.py" | awk '{print $1}')
CP=$(shasum -a 256 "$HERE/jackal_cert_check" | awk '{print $1}')
[ "$PP" = "$EP" ] || { echo "status=refused reason=producer-identity detail=\"$PP != pinned $EP\"" >&2; exit 1; }
[ "$CP" = "$EC" ] || { echo "status=refused reason=checker-identity detail=\"$CP != pinned $EC\"" >&2; exit 1; }
CERT=$(mktemp)
trap 'rm -f "$CERT"' EXIT
python3 -I -S -B "$HERE/sqrt_rat_producer.py" emit \
  --expression "$EXPR" --lower "$LO" --upper "$HI" > "$CERT" 2>&1 || {
  err=$(head -1 "$CERT"); echo "status=refused reason=producer-refused detail=\"${err#REFUSE }\"" >&2; exit 1; }
PP2=$(shasum -a 256 "$HERE/sqrt_rat_producer.py" | awk '{print $1}')
[ "$PP2" = "$PP" ] || { echo "status=refused reason=producer-toctou" >&2; exit 1; }
OUT=$("$HERE/jackal_cert_check" "$CERT" range-bound-cert "$EXPR" "$LO" "$HI" 2>&1) || {
  echo "status=refused reason=checker-rejected detail=\"$OUT\"" >&2; exit 1; }
CP2=$(shasum -a 256 "$HERE/jackal_cert_check" | awk '{print $1}')
[ "$CP2" = "$CP" ] || { echo "status=refused reason=checker-toctou" >&2; exit 1; }
echo "status=formal-bounded"
echo "cert-status=bounded"
echo "assurance=proof-carrying-certificate(checker-accepted;sqrtRat-Runs-derivation;NO-libm-TCB)"
echo "checker.ACCEPT=$OUT"
echo "checker.sha256=$CP"
echo "producer.sha256=$PP"
if [ -n "$RECEIPT_OUT" ]; then
  python3 -I -S -B "$HERE/isolated_entry.py" emit-variant-receipt \
    --variant sqrt_rat --expression="$EXPR" --lower="$LO" --upper="$HI" \
    --cert "$CERT" --producer "$HERE/sqrt_rat_producer.py" \
    --checker "$HERE/jackal_cert_check" \
    --proof-identity "$HERE/range_proof_identity.json" \
    --inventory "$HERE/formal_coverage_inventory.json" \
    --release-epoch v1.5.0 --output "$RECEIPT_OUT"
  echo "receipt=$RECEIPT_OUT"
fi
WRAP
chmod +x "$PKG/jackal-sqrt-rat-release"

cp "$ROOT/tools/exp_rat_producer.py" "$PKG/exp_rat_producer.py"
chmod +x "$PKG/exp_rat_producer.py"
cat > "$PKG/jackal-exp-rat-release" <<'WRAP'
#!/bin/sh
# JACKAL v1.5.0 exp_rat pure-ℚ release gate (self-contained; NO libm TCB).
# Producer + checker identities pinned to MANIFEST.sha256; TOCTOU stable.
# First libm-free transcendental beyond sqrt in the formal fragment.
# When a 4th argument is supplied, writes a canonical jackal-formal-receipt-v1
# JSON receipt (variant=exp_rat) that jackal-receipt-verify accepts.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "$#" -lt 3 ] || [ "$#" -gt 4 ]; then
  echo "usage: jackal-exp-rat-release \"exp(x)\" <lo> <hi> [formal-receipt.json]" >&2
  exit 2
fi
EXPR="$1"; LO="$2"; HI="$3"; RECEIPT_OUT="${4:-}"
EP=$(awk '$1=="exp_rat_producer" {print $NF}' "$HERE/MANIFEST.sha256")
EC=$(awk '$1=="checker" {print $NF}' "$HERE/MANIFEST.sha256")
[ -n "$EP" ] && [ -n "$EC" ] || { echo "status=unavailable reason=manifest-incomplete" >&2; exit 3; }
PP=$(shasum -a 256 "$HERE/exp_rat_producer.py" | awk '{print $1}')
CP=$(shasum -a 256 "$HERE/jackal_cert_check" | awk '{print $1}')
[ "$PP" = "$EP" ] || { echo "status=refused reason=producer-identity detail=\"$PP != pinned $EP\"" >&2; exit 1; }
[ "$CP" = "$EC" ] || { echo "status=refused reason=checker-identity detail=\"$CP != pinned $EC\"" >&2; exit 1; }
CERT=$(mktemp)
trap 'rm -f "$CERT"' EXIT
python3 -I -S -B "$HERE/exp_rat_producer.py" emit \
  --expression "$EXPR" --lower "$LO" --upper "$HI" > "$CERT" 2>&1 || {
  err=$(head -1 "$CERT"); echo "status=refused reason=producer-refused detail=\"${err#REFUSE }\"" >&2; exit 1; }
PP2=$(shasum -a 256 "$HERE/exp_rat_producer.py" | awk '{print $1}')
[ "$PP2" = "$PP" ] || { echo "status=refused reason=producer-toctou" >&2; exit 1; }
OUT=$("$HERE/jackal_cert_check" "$CERT" range-bound-cert "$EXPR" "$LO" "$HI" 2>&1) || {
  echo "status=refused reason=checker-rejected detail=\"$OUT\"" >&2; exit 1; }
CP2=$(shasum -a 256 "$HERE/jackal_cert_check" | awk '{print $1}')
[ "$CP2" = "$CP" ] || { echo "status=refused reason=checker-toctou" >&2; exit 1; }
echo "status=formal-bounded"
echo "cert-status=bounded"
echo "assurance=proof-carrying-certificate(checker-accepted;expRat-Runs-derivation;NO-libm-TCB)"
echo "checker.ACCEPT=$OUT"
echo "checker.sha256=$CP"
echo "producer.sha256=$PP"
if [ -n "$RECEIPT_OUT" ]; then
  python3 -I -S -B "$HERE/isolated_entry.py" emit-variant-receipt \
    --variant exp_rat --expression="$EXPR" --lower="$LO" --upper="$HI" \
    --cert "$CERT" --producer "$HERE/exp_rat_producer.py" \
    --checker "$HERE/jackal_cert_check" \
    --proof-identity "$HERE/range_proof_identity.json" \
    --inventory "$HERE/formal_coverage_inventory.json" \
    --release-epoch v1.5.0 --output "$RECEIPT_OUT"
  echo "receipt=$RECEIPT_OUT"
fi
WRAP
chmod +x "$PKG/jackal-exp-rat-release"

# --- v1.5.0 pure-ℚ fragment extensions: producers, exact verifier, and
# EMITTED package-layout release wrappers (same self-contained shape as the
# sqrt_rat/exp_rat wrappers above; the repo-root wrappers resolve
# release/MANIFEST.sha256 and MUST NOT be shipped verbatim — audit finding
# 2026-08-16: a verbatim copy refuses manifest-missing inside the package) ---
for producer in ln_rat_producer sin_rat_producer atan_rat_producer tanh_rat_producer; do
  cp "$ROOT/tools/$producer.py" "$PKG/$producer.py"
  chmod +x "$PKG/$producer.py"
done
cp "$ROOT/tools/exact_verify.py" "$PKG/exact_verify.py"
chmod +x "$PKG/exact_verify.py"

# --- v1.6.0 claim-bundle evidence kernel (additive) ---
cp "$ROOT/tools/claim_kernel.py" "$PKG/claim_kernel.py"
cp "$ROOT/tools/claim_router.py" "$PKG/claim_router.py"
cp "$ROOT/tools/claim_bundle_verify.py" "$PKG/claim_bundle_verify.py"
cp "$ROOT/release/claim/inference_registry_v1.json" "$PKG/inference_registry_v1.json"
cp "$ROOT/release/claim/unit_registry_v1.json" "$PKG/unit_registry_v1.json"
chmod +x "$PKG/claim_kernel.py" "$PKG/claim_router.py" "$PKG/claim_bundle_verify.py"

cat > "$PKG/jackal-claim" <<'WRAP'
#!/bin/sh
# JACKAL v1.6.0 claim-request router (self-contained package layout).
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 -I -S -B "$HERE/claim_router.py" claim "$@"
WRAP
chmod +x "$PKG/jackal-claim"

cat > "$PKG/jackal-claim-verify" <<'WRAP'
#!/bin/sh
# JACKAL v1.6.0 independent claim-bundle verifier (self-contained).
# Fills INFRASTRUCTURE pins from the package layout + MANIFEST.sha256;
# SEMANTIC pins (epoch, root proposition, policy hash, verification time,
# nonce) must come from the caller.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
sha() { shasum -a 256 "$1" | cut -d' ' -f1; }
M="$HERE/MANIFEST.sha256"
EC=$(awk '$1=="checker"{print $NF}' "$M")
EE=$(awk '$1=="evaluator"{print $NF}' "$M")
PROOF_DIGEST=$(python3 -I -S -B -c "import json,sys; print(json.load(open(sys.argv[1]))['identity_digest_sha256'])"   "$HERE/range_proof_identity.json")
set -- "$@"   --expected-inference-registry "$HERE/inference_registry_v1.json"   --expected-inference-registry-sha256 "$(sha "$HERE/inference_registry_v1.json")"   --expected-unit-registry "$HERE/unit_registry_v1.json"   --expected-unit-registry-sha256 "$(sha "$HERE/unit_registry_v1.json")"   --expected-environment-epoch "$(sha "$HERE/jackal-native")"   --receipt-verifier "$HERE/receipt_verify.py"   --exact-verifier "$HERE/exact_verify.py"   --checker "$HERE/jackal_cert_check"   --expected-checker "$EC"   --expected-evaluator "$EE"   --inventory "$HERE/formal_coverage_inventory.json"   --expected-inventory "$(awk '$1=="coverage_inventory"{print $NF}' "$M")"   --proof-identity "$HERE/range_proof_identity.json"   --expected-proof-identity-file "$(awk '$1=="range_proof_identity"{print $NF}' "$M")"   --expected-proof-identity-digest "$PROOF_DIGEST"
for producer in sqrt_rat exp_rat ln_rat sin_rat atan_rat tanh_rat; do
  pin=$(awk -v l="${producer}_producer" '$1==l{print $NF}' "$M")
  [ -n "$pin" ] && set -- "$@" --trusted-producer "$pin"
done
exec python3 -I -S -B "$HERE/claim_bundle_verify.py" "$@"
WRAP
chmod +x "$PKG/jackal-claim-verify"

emit_variant_wrapper() {
  # $1 wrapper-name  $2 producer-file  $3 manifest-label  $4 usage-expr
  # $5 assurance-tag  $6 receipt-variant  $7 extra-producer-args (may be "")
  wname="$1"; wprod="$2"; wlabel="$3"; wexpr="$4"; wassure="$5"; wvariant="$6"; wextra="$7"
  cat > "$PKG/$wname" <<WRAP
#!/bin/sh
# JACKAL v1.5.0 ${wvariant} pure-ℚ release gate (self-contained; NO libm TCB).
# Producer + checker identities pinned to MANIFEST.sha256; TOCTOU stable.
# When a 4th argument is supplied, writes a canonical jackal-formal-receipt-v1
# JSON receipt (variant=${wvariant}) that jackal-receipt-verify accepts.
set -eu
HERE=\$(CDPATH= cd -- "\$(dirname -- "\$0")" && pwd)
if [ "\$#" -lt 3 ] || [ "\$#" -gt 4 ]; then
  echo "usage: ${wname} \"${wexpr}\" <lo> <hi> [formal-receipt.json]" >&2
  exit 2
fi
EXPR="\$1"; LO="\$2"; HI="\$3"; RECEIPT_OUT="\${4:-}"
EP=\$(awk '\$1=="${wlabel}" {print \$NF}' "\$HERE/MANIFEST.sha256")
EC=\$(awk '\$1=="checker" {print \$NF}' "\$HERE/MANIFEST.sha256")
[ -n "\$EP" ] && [ -n "\$EC" ] || { echo "status=unavailable reason=manifest-incomplete" >&2; exit 3; }
PP=\$(shasum -a 256 "\$HERE/${wprod}" | awk '{print \$1}')
CP=\$(shasum -a 256 "\$HERE/jackal_cert_check" | awk '{print \$1}')
[ "\$PP" = "\$EP" ] || { echo "status=refused reason=producer-identity detail=\"\$PP != pinned \$EP\"" >&2; exit 1; }
[ "\$CP" = "\$EC" ] || { echo "status=refused reason=checker-identity detail=\"\$CP != pinned \$EC\"" >&2; exit 1; }
CERT=\$(mktemp)
trap 'rm -f "\$CERT"' EXIT
python3 -I -S -B "\$HERE/${wprod}" emit ${wextra} \\
  --expression="\$EXPR" --lower="\$LO" --upper="\$HI" > "\$CERT" 2>&1 || {
  err=\$(head -1 "\$CERT"); echo "status=refused reason=producer-refused detail=\"\${err#REFUSE }\"" >&2; exit 1; }
PP2=\$(shasum -a 256 "\$HERE/${wprod}" | awk '{print \$1}')
[ "\$PP2" = "\$PP" ] || { echo "status=refused reason=producer-toctou" >&2; exit 1; }
OUT=\$("\$HERE/jackal_cert_check" "\$CERT" range-bound-cert "\$EXPR" "\$LO" "\$HI" 2>&1) || {
  echo "status=refused reason=checker-rejected detail=\"\$OUT\"" >&2; exit 1; }
CP2=\$(shasum -a 256 "\$HERE/jackal_cert_check" | awk '{print \$1}')
[ "\$CP2" = "\$CP" ] || { echo "status=refused reason=checker-toctou" >&2; exit 1; }
echo "status=formal-bounded"
echo "cert-status=bounded"
echo "assurance=proof-carrying-certificate(checker-accepted;${wassure};NO-libm-TCB)"
echo "checker.ACCEPT=\$OUT"
echo "checker.sha256=\$CP"
echo "producer.sha256=\$PP"
if [ -n "\$RECEIPT_OUT" ]; then
  python3 -I -S -B "\$HERE/isolated_entry.py" emit-variant-receipt \\
    --variant ${wvariant} --expression="\$EXPR" --lower="\$LO" --upper="\$HI" \\
    --cert "\$CERT" --producer "\$HERE/${wprod}" \\
    --checker "\$HERE/jackal_cert_check" \\
    --proof-identity "\$HERE/range_proof_identity.json" \\
    --inventory "\$HERE/formal_coverage_inventory.json" \\
    --release-epoch v1.5.0 --output "\$RECEIPT_OUT"
  echo "receipt=\$RECEIPT_OUT"
fi
WRAP
  chmod +x "$PKG/$wname"
}

emit_variant_wrapper jackal-ln-rat-release   ln_rat_producer.py   ln_rat_producer   "ln(x)"   "lnRat-Runs-derivation"   ln_rat   ""
emit_variant_wrapper jackal-sin-rat-release  sin_rat_producer.py  sin_rat_producer  "sin(x)"  "sinRat-Runs-derivation"  sin_rat  "--op sin"
emit_variant_wrapper jackal-cos-rat-release  sin_rat_producer.py  sin_rat_producer  "cos(x)"  "cosRat-Runs-derivation"  cos_rat  "--op cos"
emit_variant_wrapper jackal-atan-rat-release atan_rat_producer.py atan_rat_producer "atan(x)" "atanRat-Runs-derivation" atan_rat ""
emit_variant_wrapper jackal-tanh-rat-release tanh_rat_producer.py tanh_rat_producer "1-2/(exp(2*x)+1)" "composite-zero-libm-DAG" tanh_rat ""

# --- evidence (durable, committed copies) ---
cp "$ROOT/release/evidence/positive_corpus.jsonl" "$PKG/evidence/"
cp "$ROOT/release/evidence/negative_controls.jsonl" "$PKG/evidence/"
cp "$ROOT/release/evidence/aba_mutations.json" "$PKG/evidence/"
cp "$ROOT/release/evidence/plugin_smoke.jsonl" "$PKG/evidence/"
cp "$ROOT/release/evidence/mutations_11.json" "$PKG/evidence/"
cp "$ROOT/release/evidence/fail_closed_sweep.jsonl" "$PKG/evidence/"
cp "$ROOT/release/evidence/gaussian_formal_v130.json" "$PKG/evidence/"
cp "$ROOT/release/evidence/gaussian_formal_v150.json" "$PKG/evidence/"
cp "$ROOT/release/evidence/seal_audit_v150.json" "$PKG/evidence/"
cp "$ROOT/release/evidence/seal_audit_receipts_v150.json" "$PKG/evidence/"
cp "$ROOT/release/evidence/range_proof_identity.json" "$PKG/evidence/"
cp "$ROOT/release/evidence/gaussian_proof_identity.json" "$PKG/evidence/"
cp "$ROOT/release/evidence/receipt_semantic_mutations.json" "$PKG/evidence/"
cp "$ROOT/release/evidence/claim_hostile_matrix_v160.json" "$PKG/evidence/"
cp "$ROOT/release/evidence/claim_dogfood_v160.json" "$PKG/evidence/"
cp "$ROOT/release/evidence/claim_aba_v160.json" "$PKG/evidence/"
cp "$ROOT/release/compat/v150_floor.json" "$PKG/evidence/compat_v150_floor.json"

EVAL_ID=$(shasum -a 256 "$PKG/jackal-native" | awk '{print $1}')
CHK_ID=$(shasum -a 256 "$PKG/jackal_cert_check" | awk '{print $1}')
GPROD_ID=$(shasum -a 256 "$PKG/gaussian_certificate.py" | awk '{print $1}')
GCHK_ID=$(shasum -a 256 "$PKG/jackal_gaussian_check" | awk '{print $1}')
SRC_ID=$(shasum -a 256 "$ROOT/jackal_calc.anb" | awk '{print $1}')
PLUGIN_ID=$(python3 "$PKG/plugin/hermes/bundle_hash.py" print)
RANGE_PROOF_FILE_ID=$(shasum -a 256 "$PKG/range_proof_identity.json" | awk '{print $1}')
GAUSSIAN_PROOF_FILE_ID=$(shasum -a 256 "$PKG/gaussian_proof_identity.json" | awk '{print $1}')
RANGE_PROOF_ID=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["identity_digest_sha256"])' "$PKG/range_proof_identity.json")
GAUSSIAN_PROOF_ID=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["identity_digest_sha256"])' "$PKG/gaussian_proof_identity.json")
COVERAGE_ID=$(shasum -a 256 "$PKG/formal_coverage_inventory.json" | awk '{print $1}')
SQRT_RAT_PRODUCER_ID=$(shasum -a 256 "$PKG/sqrt_rat_producer.py" | awk '{print $1}')
EXP_RAT_PRODUCER_ID=$(shasum -a 256 "$PKG/exp_rat_producer.py" | awk '{print $1}')
LN_RAT_PRODUCER_ID=$(shasum -a 256 "$PKG/ln_rat_producer.py" | awk '{print $1}')
SIN_RAT_PRODUCER_ID=$(shasum -a 256 "$PKG/sin_rat_producer.py" | awk '{print $1}')
ATAN_RAT_PRODUCER_ID=$(shasum -a 256 "$PKG/atan_rat_producer.py" | awk '{print $1}')
TANH_RAT_PRODUCER_ID=$(shasum -a 256 "$PKG/tanh_rat_producer.py" | awk '{print $1}')
EXACT_VERIFIER_ID=$(shasum -a 256 "$PKG/exact_verify.py" | awk '{print $1}')
CLAIM_KERNEL_ID=$(shasum -a 256 "$PKG/claim_kernel.py" | awk '{print $1}')
CLAIM_ROUTER_ID=$(shasum -a 256 "$PKG/claim_router.py" | awk '{print $1}')
CLAIM_VERIFIER_ID=$(shasum -a 256 "$PKG/claim_bundle_verify.py" | awk '{print $1}')
CLAIM_INF_REG_ID=$(shasum -a 256 "$PKG/inference_registry_v1.json" | awk '{print $1}')
CLAIM_UNIT_REG_ID=$(shasum -a 256 "$PKG/unit_registry_v1.json" | awk '{print $1}')

cat > "$PKG/MANIFEST.sha256" <<EOF
# JACKAL $VER package manifest — macOS arm64, schema v2, model jackal-iv-model-v1
version $VER
schema jackal-eval-cert-v2
model jackal-iv-model-v1
evaluator jackal-native $EVAL_ID
checker jackal_cert_check $CHK_ID
gaussian_producer gaussian_certificate.py $GPROD_ID
gaussian_checker jackal_gaussian_check $GCHK_ID
source jackal_calc.anb $SRC_ID
compiler_pin anubis-a733565f237d a733565f237df171e7cf93b9b37700a42d8713576818fd92f8cd23a8ad7a69e2
plugin_hermes $PLUGIN_ID
range_proof_identity range_proof_identity.json $RANGE_PROOF_FILE_ID
range_proof_digest $RANGE_PROOF_ID
gaussian_proof_identity gaussian_proof_identity.json $GAUSSIAN_PROOF_FILE_ID
gaussian_proof_digest $GAUSSIAN_PROOF_ID
coverage_inventory formal_coverage_inventory.json $COVERAGE_ID
sqrt_rat_producer sqrt_rat_producer.py $SQRT_RAT_PRODUCER_ID
exp_rat_producer exp_rat_producer.py $EXP_RAT_PRODUCER_ID
ln_rat_producer ln_rat_producer.py $LN_RAT_PRODUCER_ID
sin_rat_producer sin_rat_producer.py $SIN_RAT_PRODUCER_ID
atan_rat_producer atan_rat_producer.py $ATAN_RAT_PRODUCER_ID
tanh_rat_producer tanh_rat_producer.py $TANH_RAT_PRODUCER_ID
exact_verifier exact_verify.py $EXACT_VERIFIER_ID
claim_kernel claim_kernel.py $CLAIM_KERNEL_ID
claim_router claim_router.py $CLAIM_ROUTER_ID
claim_verifier claim_bundle_verify.py $CLAIM_VERIFIER_ID
claim_inference_registry inference_registry_v1.json $CLAIM_INF_REG_ID
claim_unit_registry unit_registry_v1.json $CLAIM_UNIT_REG_ID
EOF
cat > "$PKG/NON-CLAIMS.txt" <<'EOF'
JACKAL v1.6.0 — explicit non-claims
- The v1.6.0 claim-bundle evidence kernel is ADDITIVE: it composes the
  lanes below into content-addressed claim graphs and never upgrades
  any lane's epistemic class.  It is NOT a universal theorem prover,
  NOT universally sound, NOT source-to-native refined, NOT an
  end-to-end formally verified executable, NOT a general replacement
  for Mathematica/Sage/SymPy, and it NEVER validates real-world input
  truth: perfect mathematics over supplied inputs stays visibly
  conditional (input_provenance=supplied).
- Claim-kernel residual non-claims ride verbatim in every bundle:
  no source-native refinement; no one-time replay prevention without
  an external nonce store; no probability distributions inferred from
  intervals; no real-world input truth; bounded fragments only;
  transparency metadata is never mathematical evidence.
- Interval-composed enclosures cap at mathematical=bounded: the hull
  arithmetic is recomputed by the independent Python verifier, not by
  the Lean checker.  Formal parents keep formal-bounded in their own
  nodes; the graph never flattens them.
- NOT universal correctness. The certified range fragment is exactly:
  num, var, neg, add, sub, mul, div, integer pow (n>=0), sin, cos, abs,
  floor, ceil, round, trunc, min, max, sqrt (via `sqrt_rat`, v1.4.0:
  pure-ℚ Newton square bracket — NO libm TCB), exp (via `exp_rat`,
  general-sign since v1.5.0: pure-ℚ Taylor partial + certified remainder,
  negative arguments via the exact reciprocal identity — NO libm TCB),
  ln (via `ln_rat`, v1.5.0: inverse exponential bracket, 0 < lo — NO libm
  TCB), point-form sin and cos (via `sin_rat`/`cos_rat`, v1.5.0: midpoint
  Taylor + Lipschitz-1, |midpoint| <= 1; 2πk argument reduction is NOT in
  the fragment), atan (via `atan_rat`, v1.5.0: cap/tan-bracket/reciprocal
  strategies over rational π bounds — NO libm TCB), AND the tanh composite
  `1-2/(exp(2*x)+1)` (via `tanh_rat`, v1.5.0, |x| <= 20: the receipt binds
  the composite expression string; the tanh reading is a documented
  identity, never a checker claim).  Every other transcendental range
  operator (tan, cbrt, asin, acos, log10, log2, hypot, atan2, generic and
  negative powers, `%`) AND named constants (pi, e, tau) are
  FAIL-CLOSED (refused) on the formal path.  Named constants were
  excluded 2026-08-15 (§487-const audit): a `const_rounded` node's
  value/fl_lo fields are bound only by the undischarged `ConstTCB`
  premise (not ℚ-decidable), so admitting them would let a crafted
  `pi value=0` node earn a release ACCEPT while π lies outside the
  certified box.  Constants remain available in weaker lanes (rat, eval)
  at their honest epistemic class.
- The exact CAS lanes (canon, poly-canon, poly-eq, poly-gcd, ratfunc-canon,
  roots-isolate, alg-sign, alg-cmp, xgcd, mod-pow, mod-inv, crt, divides,
  prime-cert) are `status=exact`, NOT formal: exact integer/rational
  computation whose `jackal-exact-cert-v1` certificates are re-checked by
  full independent recomputation (`exact_verify.py`); no Lean checker
  involvement, and formal-* language is structurally refused on them.
- The separate zero-libm `gaussian-exp-square-integral-v1` family formally
  covers only canonical `exp(-A*(x-mu)^2)` when A is an exact rational square
  and the transformed finite domain contains the proved core.  Other formal
  integration requests refuse without falling back to the conditional lane.
- The Lean theorem proves: an accepted certificate implies a Runs derivation
  and hence a true enclosure UNDER the named ModelTCB.  It does NOT prove
  source parsing, the Anubis emitter's faithfulness, native refinement,
  executable identity, or release-wrapper correctness.  Runtime provenance is
  enforced by the shared validator and independently rechecked from the
  embedded certificate.  Emitter faithfulness is TESTED (positive corpus +
  executed controls + A->B->A), not proved.
- bound_step (adaptive integration) composition and Anubis source->native
  refinement remain OPEN.
- Platform: macOS arm64, unsigned/ad-hoc developer artifact.  NO Apple
  Developer ID signing and NO notarization is claimed.
- This is a PUBLIC release of the jackal-calc project.  The artifact is
  unsigned; verify SHA256SUMS and the pinned evaluator/checker identities in
  MANIFEST.sha256 before use.
EOF

cat > "$PKG/README.txt" <<'EOF'
JACKAL v1.6.0 — claim-bundle evidence kernel + proof-carrying formal receipts + pure-ℚ sqrt/exp/ln/sin/cos/atan/tanh + certified exact CAS (macOS arm64, public, unsigned)

Verify, then release a certified enclosure:
  shasum -a 256 -c SHA256SUMS         # every shipped file
  ./jackal-cert-release "x^2+1" 1 2 receipt.json
  ./jackal-sqrt-rat-release "sqrt(x)" 2 3           # pure-ℚ sqrt (NO libm TCB)
  ./jackal-exp-rat-release  "exp(x)"  -1 1          # pure-ℚ exp  (NO libm TCB, general-sign)
  ./jackal-ln-rat-release   "ln(x)"   2 3           # pure-ℚ ln   (NO libm TCB, v1.5.0)
  ./jackal-sin-rat-release  "sin(x)"  0 1           # pure-ℚ sin  (NO libm TCB, v1.5.0)
  ./jackal-cos-rat-release  "cos(x)"  0 1           # pure-ℚ cos  (NO libm TCB, v1.5.0)
  ./jackal-atan-rat-release "atan(x)" 0 1           # pure-ℚ atan (NO libm TCB, v1.5.0)
  ./jackal-tanh-rat-release "1-2/(exp(2*x)+1)" 0 1  # pure-ℚ tanh composite (v1.5.0)
  ./jackal-gaussian-release 'exp(-10000000000*(x-0.5000123456789)^2)' \
    0 1 1/1000000000000 gaussian-receipt.json
  ./jackal-receipt-verify --receipt receipt.json \
    --checker ./jackal_cert_check \
    --expected-evaluator "$(awk '/^evaluator /{print $3}' MANIFEST.sha256)" \
    --expected-checker "$(awk '/^checker /{print $3}' MANIFEST.sha256)" \
    --expected-source "$(awk '/^source /{print $3}' MANIFEST.sha256)" \
    --expected-release-epoch v1.5.0 \
    --expected-command range-bound-cert \
    --expected-expression 'x^2+1' \
    --expected-input-lo 1 --expected-input-hi 2 \
    --proof-identity ./range_proof_identity.json \
    --expected-proof-identity-file "$(awk '/^range_proof_identity /{print $3}' MANIFEST.sha256)" \
    --expected-proof-identity-digest "$(awk '/^range_proof_digest /{print $2}' MANIFEST.sha256)" \
    --expected-inventory "$(awk '/^coverage_inventory /{print $3}' MANIFEST.sha256)" \
    --inventory ./formal_coverage_inventory.json

v1.6.0 claim-bundle evidence kernel (additive):
  ./jackal-claim --request request.json --emit-bundle bundle.json
  ./jackal-claim-verify --bundle bundle.json \
    --expected-release-epoch v1.6.0 \
    --expected-root-proposition root_prop.json \
    --expected-policy-sha256 <hex> \
    --verification-time-unix <unix-seconds>
The router compiles structured claim requests into content-addressed
claim graphs over the lanes above; the standalone verifier replays
every hash, rule, axis, floor, and rendering independently and returns
verified | refused | indeterminate with stable reason classes.

status=formal-bounded is emitted ONLY when the shared validator confirms the exact
request commitment, the exact evaluator + checker executable identities
(pinned in MANIFEST.sha256), the proved checker's ACCEPT, TOCTOU stability,
and no status escalation.  The formal receipt embeds the accepted certificate;
jackal-receipt-verify re-runs the pinned checker and re-derives the semantic
bindings.  Any break refuses with a stable class, never a bounded fallback.
The bundled plugin/hermes adapter exposes the same release and verification
path.  See NON-CLAIMS.txt for the exact scope.
EOF

cat > "$PKG/PROVENANCE-RECEIPT.txt" <<EOF
JACKAL $VER build/provenance receipt
built-from-source jackal_calc.anb $SRC_ID
compiler-pin anubis-a733565f237d a733565f237df171e7cf93b9b37700a42d8713576818fd92f8cd23a8ad7a69e2
evaluator jackal-native $EVAL_ID
checker jackal_cert_check $CHK_ID
gaussian-producer gaussian_certificate.py $GPROD_ID
gaussian-checker jackal_gaussian_check $GCHK_ID
lean-theorems cert_check_sound cert_encloses certified_release gaussian_integral_check_sound
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
