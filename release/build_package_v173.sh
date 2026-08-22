#!/bin/sh
# Build the additive JACKAL v1.7.3 Apple Silicon macOS package.
#
# This builder never rebuilds the evaluator.  The sole Anubis compiler
# authority is the immutable, digest-checked pin below.  --dry-run validates
# every input and prints the package plan without creating a staging directory
# or touching release/dist.  --build is explicit, refuses existing outputs,
# stages on the release filesystem, and publishes only the staged result.
set -eu

SYSTEM=$(/usr/bin/uname -s)
MACHINE=$(/usr/bin/uname -m)
if [ "$SYSTEM" != "Darwin" ] || [ "$MACHINE" != "arm64" ]; then
  echo "PACKAGE_V173_REFUSED reason=unsupported-host system=$SYSTEM machine=$MACHINE expected=Darwin/arm64" >&2
  exit 3
fi

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VER="v1.7.3"
PLATFORM="macos-arm64"
PKG_NAME="jackal-v1.7.3-macos-arm64"
TARBALL_NAME="$PKG_NAME.tar.gz"
DIST=${JACKAL_DIST:-"$ROOT/release/dist"}
FINAL_PKG="$DIST/$PKG_NAME"
FINAL_TARBALL="$DIST/$TARBALL_NAME"
case "$DIST" in
  /*) ;;
  *)
    echo "PACKAGE_V173_REFUSED reason=dist-not-absolute path=$DIST" >&2
    exit 5
    ;;
esac
case "/$DIST/" in
  */../*|*/./*)
    echo "PACKAGE_V173_REFUSED reason=dist-not-canonical path=$DIST" >&2
    exit 5
    ;;
esac
COMPILER="/Users/sicarii/anubis-lang/vm/pins/anubis-a733565f237d"
COMPILER_SHA256="a733565f237df171e7cf93b9b37700a42d8713576818fd92f8cd23a8ad7a69e2"
RANGE_CHECKER="$ROOT/proofs/lean/.lake/build/bin/jackal_cert_check"
GAUSSIAN_CHECKER="$ROOT/proofs/lean/.lake/build/bin/jackal_gaussian_check"
INT_CHECKER="$ROOT/proofs/lean/.lake/build/bin/jackal_int_cert_check"
V170_ARCHIVE_URL="https://github.com/AnubisQuantumCipher/jackal/releases/download/v1.7.0/jackal-v1.7.0-macos-arm64.tar.gz"
V170_ARCHIVE_SHA256="21c7ede586f30a58772f321f7dbb36ab66213e199785489f99133710ac56096e"
V170_RANGE_CHECKER_SHA256="05c3518b836f239712f897c483a2ddadad9f544e0887b1b7bb1424a27289de8a"
V170_COVERAGE_INVENTORY_SHA256="18ff7b1d428dbc6f807fd4de27751ba415b33ef0b356088d7fa316ed74bb0ba6"
V170_PLUGIN_HERMES_SHA256="d141c909e8f5f03e268a2112f291e6bd79fafff906522eb7ca9accc247a3274b"

sha256() {
  /usr/bin/shasum -a 256 "$1" | /usr/bin/awk '{print $1}'
}

require_regular() {
  [ -f "$1" ] && [ ! -L "$1" ] || {
    echo "PACKAGE_V173_REFUSED reason=required-regular-file path=$1" >&2
    exit 4
  }
}

require_regular "$COMPILER"
OBSERVED_COMPILER_SHA256=$(sha256 "$COMPILER")
[ "$OBSERVED_COMPILER_SHA256" = "$COMPILER_SHA256" ] || {
  echo "PACKAGE_V173_REFUSED reason=compiler-authority-drift observed=$OBSERVED_COMPILER_SHA256 expected=$COMPILER_SHA256" >&2
  exit 4
}

REQUIRED_INPUTS="
jackal-native
jackal_calc.anb
proofs/lean/.lake/build/bin/jackal_cert_check
proofs/lean/.lake/build/bin/jackal_gaussian_check
proofs/lean/.lake/build/bin/jackal_int_cert_check
release/evidence/range_proof_identity_v172.json
release/evidence/int_cert_proof_identity_v172.json
release/evidence/range_proof_identity.json
release/evidence/int_cert_proof_identity.json
release/evidence/gaussian_proof_identity.json
release/evidence/lean_admission_audit_v173.json
release/compat/v172_floor.json
release/compat/v173_floor.json
release/compat/v170_floor.json
release/compat/v150_floor.json
release/evidence/range_ordering_aba_v172.json
release/evidence/int_cert_premise_aba_v172.json
release/coverage/formal_coverage_inventory.json
release/tools/repin_v173.py
tools/lean_admission_audit.py
tests/release_validate.py
tools/gaussian_certificate.py
tools/gaussian_release.py
tools/int_cert_producer.py
tools/int_cert_release.py
tools/formal_receipt.py
tools/receipt_verify.py
tools/formal_status_gate.py
tools/coverage_inventory.py
tools/isolated_entry.py
tools/exact_verify.py
tools/claim_kernel.py
tools/claim_router.py
tools/claim_bundle_verify.py
tools/anubis_program_verify.py
release/program/inventory_safe_v1.json
release/program/SPEC.md
tools/domain_pack_verify.py
tools/test_exists_verify.py
tools/decision_verify.py
domain_packs/PACK_SCHEMA.json
domain_packs/PACK_SPEC.md
domain_packs/registry_v1.json
domain_packs/core/manifest.json
domain_packs/core/core_pack.anb
domain_packs/programming/manifest.json
domain_packs/programming/programming_pack.anb
domain_packs/decision/manifest.json
domain_packs/decision/decision_pack.anb
tools/sqrt_rat_producer.py
tools/exp_rat_producer.py
tools/ln_rat_producer.py
tools/sin_rat_producer.py
tools/atan_rat_producer.py
tools/tanh_rat_producer.py
release/claim/inference_registry_v1.json
release/claim/unit_registry_v1.json
plugin/hermes/server.py
plugin/hermes/bundle_hash.py
plugin/hermes/jackal_hermes
plugin/hermes/tools.json
plugin/hermes/profiles/core.json
plugin/hermes/profiles/formal.json
plugin/hermes/profiles/full.json
plugin/hermes/schemas/jackal_agent_profile.schema.json
"

OPTIONAL_EVIDENCE_NAMES="
positive_corpus.jsonl
negative_controls.jsonl
aba_mutations.json
plugin_smoke.jsonl
mutations_11.json
fail_closed_sweep.jsonl
gaussian_formal_v130.json
gaussian_formal_v150.json
seal_audit_v150.json
seal_audit_receipts_v150.json
receipt_semantic_mutations.json
claim_hostile_matrix_v160.json
claim_dogfood_v160.json
claim_aba_v160.json
anubis_program_hostile_v1.json
build_environment_v170.json
"

for relative in $REQUIRED_INPUTS; do
  require_regular "$ROOT/$relative"
done

# Checking the plan validates every live identity, including the two
# current checker binaries, both proof-identity-v2 records, compatibility
# policy, ABA evidence, and all preserved v1.7.0 lanes.  It does not write.
python3 "$ROOT/release/tools/repin_v173.py" --check >/dev/null

MODE=${1:-}
if [ "$MODE" = "--dry-run" ]; then
  echo "PACKAGE_V173_DRY_RUN_PASS version=$VER platform=$PLATFORM"
  echo "compiler=$COMPILER compiler_sha256=$COMPILER_SHA256"
  echo "package=$FINAL_PKG"
  echo "tarball=$FINAL_TARBALL"
  echo "range_identity=range_proof_identity.json source=release/evidence/range_proof_identity_v172.json"
  echo "int_identity=int_cert_proof_identity.json source=release/evidence/int_cert_proof_identity_v172.json"
  echo "lean_admission_audit=evidence/lean_admission_audit_v173.json"
  echo "compat=evidence/compat_v172_floor.json"
  echo "program_compat=evidence/compat_v173_floor.json"
  echo "program_profile=inventory-safe-v1"
  echo "archival_runtime=v1.7.0 archive_sha256=$V170_ARCHIVE_SHA256"
  exit 0
fi

if [ "$MODE" != "--build" ] || [ "$#" -ne 1 ]; then
  echo "usage: release/build_package_v173.sh --dry-run|--build" >&2
  exit 2
fi

[ ! -e "$FINAL_PKG" ] && [ ! -L "$FINAL_PKG" ] || {
  echo "PACKAGE_V173_REFUSED reason=output-exists path=$FINAL_PKG" >&2
  exit 5
}
[ ! -e "$FINAL_TARBALL" ] && [ ! -L "$FINAL_TARBALL" ] || {
  echo "PACKAGE_V173_REFUSED reason=output-exists path=$FINAL_TARBALL" >&2
  exit 5
}

STAGE=$(mktemp -d "$ROOT/release/.v173-stage.XXXXXX")
cleanup() {
  if [ -n "${STAGE:-}" ] && [ -d "$STAGE" ]; then
    /bin/rm -r "$STAGE"
  fi
}
trap cleanup EXIT HUP INT TERM
PKG="$STAGE/$PKG_NAME"
/bin/mkdir -p \
  "$PKG/evidence" "$PKG/tools" "$PKG/program" "$PKG/release/claim" \
  "$PKG/domain_packs/core" "$PKG/domain_packs/programming" \
  "$PKG/domain_packs/decision" "$PKG/plugin/hermes/profiles" \
  "$PKG/plugin/hermes/schemas"

# Freeze every repository input before the first copy. Each copy below must
# match this plan both at the source after copying and in the staged package.
SOURCE_PLAN="$STAGE/source-plan.sha256"
: > "$SOURCE_PLAN"
for relative in $REQUIRED_INPUTS; do
  /usr/bin/printf '%s %s\n' "$(sha256 "$ROOT/$relative")" "$relative" >> "$SOURCE_PLAN"
done
SELECTED_OPTIONAL_EVIDENCE=""
for name in $OPTIONAL_EVIDENCE_NAMES; do
  optional="$ROOT/release/evidence/$name"
  if [ -e "$optional" ] || [ -L "$optional" ]; then
    require_regular "$optional"
    relative="release/evidence/$name"
    /usr/bin/printf '%s %s\n' "$(sha256 "$optional")" "$relative" >> "$SOURCE_PLAN"
    SELECTED_OPTIONAL_EVIDENCE="$SELECTED_OPTIONAL_EVIDENCE $name"
  fi
done

copy_file() {
  source_path="$1"
  destination_path="$2"
  require_regular "$source_path"
  case "$source_path" in
    "$ROOT"/*) relative_path=${source_path#"$ROOT"/} ;;
    *)
      echo "PACKAGE_V173_REFUSED reason=copy-source-outside-plan path=$source_path" >&2
      exit 4
      ;;
  esac
  expected=$(/usr/bin/awk -v target="$relative_path" '$2==target{print $1}' "$SOURCE_PLAN")
  [ -n "$expected" ] || {
    echo "PACKAGE_V173_REFUSED reason=copy-source-unplanned path=$relative_path" >&2
    exit 4
  }
  before=$(sha256 "$source_path")
  [ "$before" = "$expected" ] || {
    echo "PACKAGE_V173_REFUSED reason=copy-source-prehash-drift path=$relative_path" >&2
    exit 4
  }
  [ ! -e "$destination_path" ] && [ ! -L "$destination_path" ] || {
    echo "PACKAGE_V173_REFUSED reason=copy-destination-exists path=$destination_path" >&2
    exit 4
  }
  /bin/cp "$source_path" "$destination_path"
  after=$(sha256 "$source_path")
  copied=$(sha256 "$destination_path")
  [ "$after" = "$expected" ] && [ "$copied" = "$expected" ] || {
    echo "PACKAGE_V173_REFUSED reason=copy-source-or-destination-drift path=$relative_path" >&2
    exit 4
  }
}

# Stable package names expose the current v2 identities without leaking the
# repository's epoch-suffixed filenames into wrapper contracts.
copy_file "$ROOT/jackal-native" "$PKG/jackal-native"
copy_file "$ROOT/jackal_calc.anb" "$PKG/jackal_calc.anb"
copy_file "$RANGE_CHECKER" "$PKG/jackal_cert_check"
copy_file "$GAUSSIAN_CHECKER" "$PKG/jackal_gaussian_check"
copy_file "$INT_CHECKER" "$PKG/jackal_int_cert_check"
copy_file "$ROOT/release/evidence/range_proof_identity_v172.json" "$PKG/range_proof_identity.json"
copy_file "$ROOT/release/evidence/int_cert_proof_identity_v172.json" "$PKG/int_cert_proof_identity.json"
copy_file "$ROOT/release/evidence/gaussian_proof_identity.json" "$PKG/gaussian_proof_identity.json"
copy_file "$ROOT/release/evidence/lean_admission_audit_v173.json" "$PKG/evidence/lean_admission_audit_v173.json"
copy_file "$ROOT/release/coverage/formal_coverage_inventory.json" "$PKG/formal_coverage_inventory.json"

# Replay-only v1.7.0 receipts require the exact historical checker bytes.
# Accept an operator-supplied local copy of the published archive, otherwise
# fetch the public release asset, then verify the whole archive before reading
# only the two named regular-file members. No archive path is extracted.
V170_ARCHIVE="$STAGE/jackal-v1.7.0-macos-arm64.tar.gz"
if [ -n "${JACKAL_V170_ARCHIVE:-}" ]; then
  require_regular "$JACKAL_V170_ARCHIVE"
  /bin/cp "$JACKAL_V170_ARCHIVE" "$V170_ARCHIVE"
else
  /usr/bin/curl --fail --location --silent --show-error \
    --proto '=https' --tlsv1.2 \
    "$V170_ARCHIVE_URL" --output "$V170_ARCHIVE"
fi
[ "$(sha256 "$V170_ARCHIVE")" = "$V170_ARCHIVE_SHA256" ] || {
  echo "PACKAGE_V173_REFUSED reason=archival-archive-identity" >&2
  exit 4
}
python3 - "$V170_ARCHIVE" "$PKG" \
  "$V170_RANGE_CHECKER_SHA256" "$V170_COVERAGE_INVENTORY_SHA256" <<'PY'
import hashlib
import os
import pathlib
import sys
import tarfile

archive = pathlib.Path(sys.argv[1])
package = pathlib.Path(sys.argv[2])
expected = {
    "jackal-v1.7.0-macos-arm64/jackal_cert_check": (
        package / "jackal_cert_check_v170", sys.argv[3], 0o755
    ),
    "jackal-v1.7.0-macos-arm64/formal_coverage_inventory.json": (
        package / "evidence/formal_coverage_inventory_v170.json", sys.argv[4],
        0o644
    ),
}
with tarfile.open(archive, "r:gz") as bundle:
    members = {member.name: member for member in bundle.getmembers()}
    for name, (destination, digest, mode) in expected.items():
        member = members.get(name)
        if member is None or not member.isfile() or member.size > 256 * 1024 * 1024:
            raise SystemExit(f"archival-checker-member-refused:{name}")
        source = bundle.extractfile(member)
        if source is None:
            raise SystemExit(f"archival-checker-read-refused:{name}")
        data = source.read(256 * 1024 * 1024 + 1)
        if len(data) != member.size or hashlib.sha256(data).hexdigest() != digest:
            raise SystemExit(f"archival-checker-identity-refused:{name}")
        with destination.open("xb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        destination.chmod(mode)
PY

for relative in \
  tests/release_validate.py \
  tools/gaussian_certificate.py tools/gaussian_release.py \
  tools/int_cert_producer.py tools/int_cert_release.py \
  tools/formal_receipt.py tools/receipt_verify.py \
  tools/formal_status_gate.py tools/coverage_inventory.py \
  tools/isolated_entry.py tools/exact_verify.py \
  tools/claim_kernel.py tools/claim_router.py tools/claim_bundle_verify.py \
  tools/sqrt_rat_producer.py tools/exp_rat_producer.py \
  tools/ln_rat_producer.py tools/sin_rat_producer.py \
  tools/atan_rat_producer.py tools/tanh_rat_producer.py; do
  copy_file "$ROOT/$relative" "$PKG/$(basename "$relative")"
done

copy_file "$ROOT/tools/anubis_program_verify.py" "$PKG/tools/anubis_program_verify.py"
copy_file "$ROOT/tools/domain_pack_verify.py" "$PKG/tools/domain_pack_verify.py"
copy_file "$ROOT/tools/test_exists_verify.py" "$PKG/tools/test_exists_verify.py"
copy_file "$ROOT/tools/decision_verify.py" "$PKG/tools/decision_verify.py"
copy_file "$ROOT/tools/exact_verify.py" "$PKG/tools/exact_verify.py"
copy_file "$ROOT/release/program/inventory_safe_v1.json" "$PKG/program/inventory_safe_v1.json"
copy_file "$ROOT/domain_packs/PACK_SCHEMA.json" "$PKG/domain_packs/PACK_SCHEMA.json"
copy_file "$ROOT/release/program/SPEC.md" "$PKG/program/SPEC.md"
copy_file "$ROOT/domain_packs/PACK_SPEC.md" "$PKG/domain_packs/PACK_SPEC.md"
copy_file "$ROOT/domain_packs/registry_v1.json" "$PKG/domain_packs/registry_v1.json"
copy_file "$ROOT/domain_packs/core/manifest.json" "$PKG/domain_packs/core/manifest.json"
copy_file "$ROOT/domain_packs/core/core_pack.anb" "$PKG/domain_packs/core/core_pack.anb"
copy_file "$ROOT/domain_packs/programming/manifest.json" "$PKG/domain_packs/programming/manifest.json"
copy_file "$ROOT/domain_packs/programming/programming_pack.anb" "$PKG/domain_packs/programming/programming_pack.anb"
copy_file "$ROOT/domain_packs/decision/manifest.json" "$PKG/domain_packs/decision/manifest.json"
copy_file "$ROOT/domain_packs/decision/decision_pack.anb" "$PKG/domain_packs/decision/decision_pack.anb"
copy_file "$ROOT/plugin/hermes/profiles/core.json" "$PKG/plugin/hermes/profiles/core.json"
copy_file "$ROOT/plugin/hermes/profiles/formal.json" "$PKG/plugin/hermes/profiles/formal.json"
copy_file "$ROOT/plugin/hermes/profiles/full.json" "$PKG/plugin/hermes/profiles/full.json"
copy_file "$ROOT/plugin/hermes/schemas/jackal_agent_profile.schema.json" "$PKG/plugin/hermes/schemas/jackal_agent_profile.schema.json"

copy_file "$ROOT/release/claim/inference_registry_v1.json" "$PKG/inference_registry_v1.json"
copy_file "$ROOT/release/claim/unit_registry_v1.json" "$PKG/unit_registry_v1.json"
copy_file "$ROOT/release/claim/inference_registry_v1.json" "$PKG/release/claim/inference_registry_v1.json"
copy_file "$ROOT/release/claim/unit_registry_v1.json" "$PKG/release/claim/unit_registry_v1.json"
copy_file "$ROOT/plugin/hermes/server.py" "$PKG/plugin/hermes/server.py"
copy_file "$ROOT/plugin/hermes/bundle_hash.py" "$PKG/plugin/hermes/bundle_hash.py"
copy_file "$ROOT/plugin/hermes/jackal_hermes" "$PKG/plugin/hermes/jackal_hermes"
copy_file "$ROOT/plugin/hermes/tools.json" "$PKG/plugin/hermes/tools.json"

# Current compatibility policy plus the evidence it names.  The archival range
# v1 identity remains replay-only.  The int-cert v1 identity is historical
# revocation evidence only and its vulnerable checker is deliberately absent.
copy_file "$ROOT/release/compat/v172_floor.json" "$PKG/evidence/compat_v172_floor.json"
copy_file "$ROOT/release/compat/v173_floor.json" "$PKG/evidence/compat_v173_floor.json"
copy_file "$ROOT/release/compat/v170_floor.json" "$PKG/evidence/compat_v170_floor.json"
copy_file "$ROOT/release/compat/v150_floor.json" "$PKG/evidence/compat_v150_floor.json"
copy_file "$ROOT/release/evidence/range_ordering_aba_v172.json" "$PKG/evidence/range_ordering_aba_v172.json"
copy_file "$ROOT/release/evidence/int_cert_premise_aba_v172.json" "$PKG/evidence/int_cert_premise_aba_v172.json"
copy_file "$ROOT/release/evidence/range_proof_identity.json" "$PKG/evidence/range_proof_identity_v1.json"
copy_file "$ROOT/release/evidence/int_cert_proof_identity.json" "$PKG/evidence/int_cert_proof_identity_v1.json"
copy_file "$ROOT/release/evidence/range_proof_identity_v172.json" "$PKG/evidence/range_proof_identity_v172.json"
copy_file "$ROOT/release/evidence/int_cert_proof_identity_v172.json" "$PKG/evidence/int_cert_proof_identity_v172.json"

for name in $SELECTED_OPTIONAL_EVIDENCE; do
  copy_file "$ROOT/release/evidence/$name" "$PKG/evidence/$name"
done

/bin/chmod +x \
  "$PKG/jackal-native" "$PKG/jackal_cert_check" "$PKG/jackal_cert_check_v170" \
  "$PKG/jackal_gaussian_check" "$PKG/jackal_int_cert_check" \
  "$PKG/gaussian_certificate.py" "$PKG/gaussian_release.py" \
  "$PKG/int_cert_producer.py" "$PKG/int_cert_release.py" \
  "$PKG/isolated_entry.py" "$PKG/exact_verify.py" \
  "$PKG/claim_kernel.py" "$PKG/claim_router.py" \
  "$PKG/claim_bundle_verify.py" "$PKG/tools/anubis_program_verify.py" \
  "$PKG/tools/domain_pack_verify.py" "$PKG/tools/test_exists_verify.py" \
  "$PKG/tools/decision_verify.py" "$PKG/tools/exact_verify.py" \
  "$PKG/plugin/hermes/jackal_hermes"

cat > "$PKG/jackal-cert-release" <<'WRAP'
#!/bin/sh
# JACKAL v1.7.2 packaged range release gate (self-contained).
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ "$#" -eq 4 ] || { echo "usage: jackal-cert-release \"<expr in x>\" <lo> <hi> <receipt.json>" >&2; exit 2; }
EE=$(awk '$1=="evaluator"{print $NF}' "$HERE/MANIFEST.sha256")
EC=$(awk '$1=="checker"{print $NF}' "$HERE/MANIFEST.sha256")
ES=$(awk '$1=="source"{print $NF}' "$HERE/MANIFEST.sha256")
EI=$(awk '$1=="coverage_inventory"{print $NF}' "$HERE/MANIFEST.sha256")
EPF=$(awk '$1=="range_proof_identity"{print $NF}' "$HERE/MANIFEST.sha256")
EPD=$(awk '$1=="range_proof_digest"{print $NF}' "$HERE/MANIFEST.sha256")
[ -n "$EE" ] && [ -n "$EC" ] && [ -n "$ES" ] && [ -n "$EI" ] && [ -n "$EPF" ] && [ -n "$EPD" ] || { echo "status=unavailable reason=manifest-incomplete" >&2; exit 3; }
exec python3 -I -S -B "$HERE/isolated_entry.py" range \
  --expr "$1" --lo "$2" --hi "$3" \
  --evaluator "$HERE/jackal-native" --checker "$HERE/jackal_cert_check" \
  --expected-evaluator "$EE" --expected-checker "$EC" --expected-source "$ES" \
  --inventory "$HERE/formal_coverage_inventory.json" --expected-inventory "$EI" \
  --proof-identity "$HERE/range_proof_identity.json" \
  --expected-proof-identity-file "$EPF" --expected-proof-identity-digest "$EPD" \
  --release-epoch v1.7.2 --formal-receipt "$4"
WRAP

cat > "$PKG/jackal-int-cert-release" <<'WRAP'
#!/bin/sh
# JACKAL v1.7.2 packaged composed-integral release gate (self-contained).
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ "$#" -eq 5 ] || { echo "usage: jackal-int-cert-release \"<expr in x>\" <lo> <hi> <tol> <receipt.json>" >&2; exit 2; }
EP=$(awk '$1=="int_cert_producer"{print $NF}' "$HERE/MANIFEST.sha256")
EC=$(awk '$1=="int_cert_checker"{print $NF}' "$HERE/MANIFEST.sha256")
EI=$(awk '$1=="coverage_inventory"{print $NF}' "$HERE/MANIFEST.sha256")
EPF=$(awk '$1=="int_cert_proof_identity"{print $NF}' "$HERE/MANIFEST.sha256")
EPD=$(awk '$1=="int_cert_proof_digest"{print $NF}' "$HERE/MANIFEST.sha256")
[ -n "$EP" ] && [ -n "$EC" ] && [ -n "$EI" ] && [ -n "$EPF" ] && [ -n "$EPD" ] || { echo "status=refused reason=manifest-incomplete" >&2; exit 3; }
exec python3 -I -S -B "$HERE/isolated_entry.py" int-cert \
  --expression "$1" --lower "$2" --upper "$3" --tolerance "$4" \
  --producer "$HERE/int_cert_producer.py" --checker "$HERE/jackal_int_cert_check" \
  --expected-producer "$EP" --expected-checker "$EC" --receipt "$5" \
  --inventory "$HERE/formal_coverage_inventory.json" --expected-inventory "$EI" \
  --proof-identity "$HERE/int_cert_proof_identity.json" \
  --expected-proof-identity-file "$EPF" --expected-proof-identity-digest "$EPD" \
  --release-epoch v1.7.2
WRAP

cat > "$PKG/jackal-gaussian-release" <<'WRAP'
#!/bin/sh
# Preserved theorem-backed Gaussian lane; package-local and self-contained.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ "$#" -eq 5 ] || { echo "usage: jackal-gaussian-release <expression> <lo> <hi> <tolerance> <receipt.json>" >&2; exit 2; }
EP=$(awk '$1=="gaussian_producer"{print $NF}' "$HERE/MANIFEST.sha256")
EC=$(awk '$1=="gaussian_checker"{print $NF}' "$HERE/MANIFEST.sha256")
EI=$(awk '$1=="coverage_inventory"{print $NF}' "$HERE/MANIFEST.sha256")
EPF=$(awk '$1=="gaussian_proof_identity"{print $NF}' "$HERE/MANIFEST.sha256")
EPD=$(awk '$1=="gaussian_proof_digest"{print $NF}' "$HERE/MANIFEST.sha256")
[ -n "$EP" ] && [ -n "$EC" ] && [ -n "$EI" ] && [ -n "$EPF" ] && [ -n "$EPD" ] || { echo "status=refused reason=manifest-incomplete" >&2; exit 3; }
exec python3 -I -S -B "$HERE/isolated_entry.py" gaussian \
  --expression "$1" --lower "$2" --upper "$3" --tolerance "$4" \
  --producer "$HERE/gaussian_certificate.py" --checker "$HERE/jackal_gaussian_check" \
  --expected-producer "$EP" --expected-checker "$EC" \
  --inventory "$HERE/formal_coverage_inventory.json" --expected-inventory "$EI" \
  --proof-identity "$HERE/gaussian_proof_identity.json" \
  --expected-proof-identity-file "$EPF" --expected-proof-identity-digest "$EPD" \
  --release-epoch v1.5.0 --receipt "$5"
WRAP

cat > "$PKG/jackal-receipt-verify" <<'WRAP'
#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 -I -S -B "$HERE/isolated_entry.py" verify "$@"
WRAP

cat > "$PKG/jackal-claim" <<'WRAP'
#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 -I -S -B "$HERE/claim_router.py" claim "$@"
WRAP

cat > "$PKG/jackal-anubis-program" <<'WRAP'
#!/bin/sh
# check invokes only Anubis build --evidence; no subcommand executes artifact.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 -I -S -B "$HERE/tools/anubis_program_verify.py" "$@"
WRAP

cat > "$PKG/jackal-claim-verify" <<'WRAP'
#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
M="$HERE/MANIFEST.sha256"
sha() { shasum -a 256 "$1" | awk '{print $1}'; }
set -- "$@" \
  --expected-inference-registry "$HERE/inference_registry_v1.json" \
  --expected-inference-registry-sha256 "$(sha "$HERE/inference_registry_v1.json")" \
  --expected-unit-registry "$HERE/unit_registry_v1.json" \
  --expected-unit-registry-sha256 "$(sha "$HERE/unit_registry_v1.json")" \
  --expected-environment-epoch "$(sha "$HERE/jackal-native")" \
  --receipt-verifier "$HERE/receipt_verify.py" --exact-verifier "$HERE/exact_verify.py" \
  --checker "$HERE/jackal_cert_check" --expected-checker "$(awk '$1=="checker"{print $NF}' "$M")" \
  --expected-evaluator "$(awk '$1=="evaluator"{print $NF}' "$M")" \
  --inventory "$HERE/formal_coverage_inventory.json" \
  --expected-inventory "$(awk '$1=="coverage_inventory"{print $NF}' "$M")" \
  --proof-identity "$HERE/range_proof_identity.json" \
  --expected-proof-identity-file "$(awk '$1=="range_proof_identity"{print $NF}' "$M")" \
  --expected-proof-identity-digest "$(awk '$1=="range_proof_digest"{print $NF}' "$M")" \
  --gaussian-checker "$HERE/jackal_gaussian_check" \
  --expected-gaussian-checker "$(awk '$1=="gaussian_checker"{print $NF}' "$M")" \
  --gaussian-proof-identity "$HERE/gaussian_proof_identity.json" \
  --expected-gaussian-proof-identity-file "$(awk '$1=="gaussian_proof_identity"{print $NF}' "$M")" \
  --expected-gaussian-proof-identity-digest "$(awk '$1=="gaussian_proof_digest"{print $NF}' "$M")" \
  --int-cert-checker "$HERE/jackal_int_cert_check" \
  --expected-int-cert-checker "$(awk '$1=="int_cert_checker"{print $NF}' "$M")" \
  --int-cert-proof-identity "$HERE/int_cert_proof_identity.json" \
  --expected-int-cert-proof-identity-file "$(awk '$1=="int_cert_proof_identity"{print $NF}' "$M")" \
  --expected-int-cert-proof-identity-digest "$(awk '$1=="int_cert_proof_digest"{print $NF}' "$M")" \
  --archival-range-checker "$HERE/jackal_cert_check_v170" \
  --expected-archival-range-checker "$(awk '$1=="archival_range_checker"{print $NF}' "$M")" \
  --archival-range-proof-identity "$HERE/evidence/range_proof_identity_v1.json" \
  --expected-archival-range-proof-identity-file "$(awk '$1=="archival_range_proof_identity"{print $NF}' "$M")" \
  --expected-archival-range-proof-identity-digest "$(awk '$1=="archival_range_proof_digest"{print $NF}' "$M")" \
  --archival-range-inventory "$HERE/evidence/formal_coverage_inventory_v170.json" \
  --expected-archival-range-inventory "$(awk '$1=="archival_range_coverage_inventory"{print $NF}' "$M")"
for producer in sqrt_rat exp_rat ln_rat sin_rat atan_rat tanh_rat; do
  pin=$(awk -v label="${producer}_producer" '$1==label{print $NF}' "$M")
  [ -n "$pin" ] && set -- "$@" --trusted-producer "$pin"
done
pin=$(awk '$1=="gaussian_producer"{print $NF}' "$M")
[ -n "$pin" ] && set -- "$@" --trusted-producer "$pin"
pin=$(awk '$1=="int_cert_producer"{print $NF}' "$M")
[ -n "$pin" ] && set -- "$@" --trusted-producer "$pin"
exec python3 -I -S -B "$HERE/claim_bundle_verify.py" "$@"
WRAP

emit_variant_wrapper() {
  wrapper_name="$1"
  producer_file="$2"
  manifest_label="$3"
  variant="$4"
  producer_extra="$5"
  cat > "$PKG/$wrapper_name" <<WRAP
#!/bin/sh
# Pure-rational lane reissued under the current v2 proof-identity epoch;
# package-local and self-contained.
set -eu
HERE=\$(CDPATH= cd -- "\$(dirname -- "\$0")" && pwd)
[ "\$#" -ge 3 ] && [ "\$#" -le 4 ] || { echo "usage: $wrapper_name <expression> <lo> <hi> [receipt.json]" >&2; exit 2; }
EXPR="\$1"; LO="\$2"; HI="\$3"; RECEIPT="\${4:-}"
[ -f "\$HERE/MANIFEST.sha256" ] && [ ! -L "\$HERE/MANIFEST.sha256" ] || { echo "status=refused reason=manifest-identity" >&2; exit 1; }
EM=\$(shasum -a 256 "\$HERE/MANIFEST.sha256" | awk '{print \$1}')
EP=\$(awk '\$1=="$manifest_label"{print \$NF}' "\$HERE/MANIFEST.sha256")
EC=\$(awk '\$1=="checker"{print \$NF}' "\$HERE/MANIFEST.sha256")
EPF=\$(awk '\$1=="range_proof_identity"{print \$NF}' "\$HERE/MANIFEST.sha256")
EPD=\$(awk '\$1=="range_proof_digest"{print \$NF}' "\$HERE/MANIFEST.sha256")
EI=\$(awk '\$1=="coverage_inventory"{print \$NF}' "\$HERE/MANIFEST.sha256")
[ -n "\$EP" ] && [ -n "\$EC" ] && [ -n "\$EPF" ] && [ -n "\$EPD" ] && [ -n "\$EI" ] || { echo "status=refused reason=manifest-incomplete" >&2; exit 1; }
verify_variant_runtime_identity() {
  MP=\$(shasum -a 256 "\$HERE/MANIFEST.sha256" | awk '{print \$1}')
  PP=\$(shasum -a 256 "\$HERE/$producer_file" | awk '{print \$1}')
  CP=\$(shasum -a 256 "\$HERE/jackal_cert_check" | awk '{print \$1}')
  PF=\$(shasum -a 256 "\$HERE/range_proof_identity.json" | awk '{print \$1}')
  IF=\$(shasum -a 256 "\$HERE/formal_coverage_inventory.json" | awk '{print \$1}')
  DID=\$(python3 -I -S -B -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["identity_digest_sha256"])' "\$HERE/range_proof_identity.json")
  [ "\$MP" = "\$EM" ] && [ "\$PP" = "\$EP" ] && [ "\$CP" = "\$EC" ] && \
    [ "\$PF" = "\$EPF" ] && [ "\$IF" = "\$EI" ] && [ "\$DID" = "\$EPD" ] || {
    echo "status=refused reason=identity" >&2
    exit 1
  }
}
verify_variant_runtime_identity
CERT=\$(mktemp)
trap 'rm -f "\$CERT"' EXIT
python3 -I -S -B "\$HERE/$producer_file" emit $producer_extra --expression="\$EXPR" --lower="\$LO" --upper="\$HI" >"\$CERT" 2>&1 || { echo "status=refused reason=producer-refused" >&2; exit 1; }
verify_variant_runtime_identity
OUT=\$("\$HERE/jackal_cert_check" "\$CERT" range-bound-cert "\$EXPR" "\$LO" "\$HI" 2>&1) || { echo "status=refused reason=checker-rejected detail=\"\$OUT\"" >&2; exit 1; }
verify_variant_runtime_identity
if [ -n "\$RECEIPT" ]; then
  python3 -I -S -B "\$HERE/isolated_entry.py" emit-variant-receipt \
    --variant "$variant" --expression="\$EXPR" --lower="\$LO" --upper="\$HI" \
    --cert "\$CERT" --producer "\$HERE/$producer_file" \
    --checker "\$HERE/jackal_cert_check" \
    --proof-identity "\$HERE/range_proof_identity.json" \
    --inventory "\$HERE/formal_coverage_inventory.json" \
    --release-epoch v1.7.2 --output "\$RECEIPT"
fi
verify_variant_runtime_identity
[ -z "\$RECEIPT" ] || echo "receipt=\$RECEIPT"
echo "status=formal-bounded"
echo "checker.ACCEPT=\$OUT"
WRAP
  /bin/chmod +x "$PKG/$wrapper_name"
}

emit_variant_wrapper jackal-sqrt-rat-release sqrt_rat_producer.py sqrt_rat_producer sqrt_rat ""
emit_variant_wrapper jackal-exp-rat-release exp_rat_producer.py exp_rat_producer exp_rat ""
emit_variant_wrapper jackal-ln-rat-release ln_rat_producer.py ln_rat_producer ln_rat ""
emit_variant_wrapper jackal-sin-rat-release sin_rat_producer.py sin_rat_producer sin_rat "--op sin"
emit_variant_wrapper jackal-cos-rat-release sin_rat_producer.py sin_rat_producer cos_rat "--op cos"
emit_variant_wrapper jackal-atan-rat-release atan_rat_producer.py atan_rat_producer atan_rat ""
emit_variant_wrapper jackal-tanh-rat-release tanh_rat_producer.py tanh_rat_producer tanh_rat ""

/bin/chmod +x "$PKG/jackal-cert-release" "$PKG/jackal-int-cert-release" \
  "$PKG/jackal-gaussian-release" "$PKG/jackal-receipt-verify" \
  "$PKG/jackal-claim" "$PKG/jackal-claim-verify" \
  "$PKG/jackal-anubis-program"

EVALUATOR_ID=$(sha256 "$PKG/jackal-native")
RANGE_CHECKER_ID=$(sha256 "$PKG/jackal_cert_check")
GAUSSIAN_CHECKER_ID=$(sha256 "$PKG/jackal_gaussian_check")
INT_CHECKER_ID=$(sha256 "$PKG/jackal_int_cert_check")
ARCHIVAL_RANGE_CHECKER_ID=$(sha256 "$PKG/jackal_cert_check_v170")
ARCHIVAL_RANGE_INVENTORY_ID=$(sha256 "$PKG/evidence/formal_coverage_inventory_v170.json")
INT_PRODUCER_ID=$(sha256 "$PKG/int_cert_producer.py")
SOURCE_ID=$(sha256 "$PKG/jackal_calc.anb")
RANGE_IDENTITY_FILE_ID=$(sha256 "$PKG/range_proof_identity.json")
INT_IDENTITY_FILE_ID=$(sha256 "$PKG/int_cert_proof_identity.json")
GAUSSIAN_IDENTITY_FILE_ID=$(sha256 "$PKG/gaussian_proof_identity.json")
RANGE_IDENTITY_DIGEST=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["identity_digest_sha256"])' "$PKG/range_proof_identity.json")
INT_IDENTITY_DIGEST=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["identity_digest_sha256"])' "$PKG/int_cert_proof_identity.json")
GAUSSIAN_IDENTITY_DIGEST=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["identity_digest_sha256"])' "$PKG/gaussian_proof_identity.json")
LEAN_ADMISSION_AUDIT_ID=$(sha256 "$PKG/evidence/lean_admission_audit_v173.json")
LEAN_ADMISSION_AUDIT_DIGEST=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["audit_digest_sha256"])' "$PKG/evidence/lean_admission_audit_v173.json")
COVERAGE_ID=$(sha256 "$PKG/formal_coverage_inventory.json")
COMPAT_ID=$(sha256 "$PKG/evidence/compat_v172_floor.json")
PROGRAM_COMPAT_ID=$(sha256 "$PKG/evidence/compat_v173_floor.json")
RANGE_ABA_ID=$(sha256 "$PKG/evidence/range_ordering_aba_v172.json")
INT_ABA_ID=$(sha256 "$PKG/evidence/int_cert_premise_aba_v172.json")
PLUGIN_ID=$(python3 "$PKG/plugin/hermes/bundle_hash.py" print)

cat > "$PKG/MANIFEST.sha256" <<EOF
# JACKAL $VER package manifest — Apple Silicon macOS only; current proof identities schema v2
version $VER
platform $PLATFORM
schema jackal-eval-cert-v2
model jackal-iv-model-v1
evaluator jackal-native $EVALUATOR_ID
checker jackal_cert_check $RANGE_CHECKER_ID
archival_v170_archive_source github-release-v1.7.0 $V170_ARCHIVE_SHA256
archival_range_checker jackal_cert_check_v170 $ARCHIVAL_RANGE_CHECKER_ID
archival_range_coverage_inventory evidence/formal_coverage_inventory_v170.json $V170_COVERAGE_INVENTORY_SHA256
archival_plugin_hermes v1.7.0-plugin $V170_PLUGIN_HERMES_SHA256
gaussian_producer gaussian_certificate.py $(sha256 "$PKG/gaussian_certificate.py")
gaussian_checker jackal_gaussian_check $GAUSSIAN_CHECKER_ID
source jackal_calc.anb $SOURCE_ID
compiler_pin anubis-a733565f237d $COMPILER_SHA256
plugin_hermes $PLUGIN_ID
range_proof_identity range_proof_identity.json $RANGE_IDENTITY_FILE_ID
range_proof_digest $RANGE_IDENTITY_DIGEST
archival_range_proof_identity evidence/range_proof_identity_v1.json $(sha256 "$PKG/evidence/range_proof_identity_v1.json")
archival_range_proof_digest $(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["identity_digest_sha256"])' "$PKG/evidence/range_proof_identity_v1.json")
gaussian_proof_identity gaussian_proof_identity.json $GAUSSIAN_IDENTITY_FILE_ID
gaussian_proof_digest $GAUSSIAN_IDENTITY_DIGEST
lean_admission_audit evidence/lean_admission_audit_v173.json $LEAN_ADMISSION_AUDIT_ID
lean_admission_audit_digest $LEAN_ADMISSION_AUDIT_DIGEST
int_cert_producer int_cert_producer.py $INT_PRODUCER_ID
int_cert_checker jackal_int_cert_check $INT_CHECKER_ID
int_cert_proof_identity int_cert_proof_identity.json $INT_IDENTITY_FILE_ID
int_cert_proof_digest $INT_IDENTITY_DIGEST
revoked_int_cert_proof_identity_reference evidence/int_cert_proof_identity_v1.json $(sha256 "$PKG/evidence/int_cert_proof_identity_v1.json")
compatibility_floor evidence/compat_v172_floor.json $COMPAT_ID
program_compatibility_floor evidence/compat_v173_floor.json $PROGRAM_COMPAT_ID
range_ordering_aba evidence/range_ordering_aba_v172.json $RANGE_ABA_ID
int_cert_premise_aba evidence/int_cert_premise_aba_v172.json $INT_ABA_ID
coverage_inventory formal_coverage_inventory.json $COVERAGE_ID
sqrt_rat_producer sqrt_rat_producer.py $(sha256 "$PKG/sqrt_rat_producer.py")
exp_rat_producer exp_rat_producer.py $(sha256 "$PKG/exp_rat_producer.py")
ln_rat_producer ln_rat_producer.py $(sha256 "$PKG/ln_rat_producer.py")
sin_rat_producer sin_rat_producer.py $(sha256 "$PKG/sin_rat_producer.py")
atan_rat_producer atan_rat_producer.py $(sha256 "$PKG/atan_rat_producer.py")
tanh_rat_producer tanh_rat_producer.py $(sha256 "$PKG/tanh_rat_producer.py")
exact_verifier exact_verify.py $(sha256 "$PKG/exact_verify.py")
claim_kernel claim_kernel.py $(sha256 "$PKG/claim_kernel.py")
claim_router claim_router.py $(sha256 "$PKG/claim_router.py")
claim_verifier claim_bundle_verify.py $(sha256 "$PKG/claim_bundle_verify.py")
claim_inference_registry inference_registry_v1.json $(sha256 "$PKG/inference_registry_v1.json")
claim_unit_registry unit_registry_v1.json $(sha256 "$PKG/unit_registry_v1.json")
domain_pack_registry domain_packs/registry_v1.json $(sha256 "$PKG/domain_packs/registry_v1.json")
domain_pack_verifier tools/domain_pack_verify.py $(sha256 "$PKG/tools/domain_pack_verify.py")
domain_pack_test_exists_checker tools/test_exists_verify.py $(sha256 "$PKG/tools/test_exists_verify.py")
domain_pack_decision_checker tools/decision_verify.py $(sha256 "$PKG/tools/decision_verify.py")
anubis_program_verifier tools/anubis_program_verify.py $(sha256 "$PKG/tools/anubis_program_verify.py")
anubis_program_policy program/inventory_safe_v1.json $(sha256 "$PKG/program/inventory_safe_v1.json")
EOF

cat > "$PKG/NON-CLAIMS.txt" <<'EOF'
JACKAL v1.7.3 — explicit boundary
- Apple Silicon macOS only; unsigned and not notarized.
- Range and composed-integral formal language applies only to the declared
  checker-accepted fragments and the v2 identities shipped here.
- The archived v1 range identity is replay-only.  Archival replay
  requires the exact historical range checker AND the exact historical
  coverage inventory that shipped with it (jackal_cert_check_v170 plus
  formal_coverage_inventory_v170.json); no other checker/inventory tuple
  is admitted for archival replay, and reversed range intervals remain
  revoked and refuse.
- The archived v1 composed-integral identity is historical revocation
  evidence only. Its request-unbound checker is not shipped or admitted;
  every v1.7.0 int-certificate receipt refuses formal replay.
- Unsupported proof epochs and fragments refuse.
- Gaussian, pure-rational, exact-CAS, and claim-kernel lanes preserve their
  prior assurance classes. No lane is silently upgraded.
- A programming-status pack establishes STRUCTURE, never correctness.
  test-exists says only that a declaration-shaped occurrence of a named
  symbol exists in bytes at a claimed content hash.  It says nothing
  about whether that test executes, passes, asserts anything, or covers
  what a surrounding document claims it covers.
- claim-cites-test RESOLVES a citation; it does not validate one.  A
  document may cite a real test that checks something entirely
  different, and this checker cannot see that.
- The decision pack orders options by a caller-declared numeric
  criterion.  Accepting that criterion is never a claim that it is the
  right one to optimise.  Value judgments are refused, not ranked.
- The value-judgment screen is a substring blocklist and is INCOMPLETE.
  Measured on the shipped engine: criteria spelled optimal, ideal, and
  leetspeak such as b3st are ACCEPTED, while best and preference_score
  refuse.  Closing that gap requires a declared unit or measurement
  provenance on the criterion, which is a protocol change and was not
  made.
- The domain-pack verifier checks metadata, identity, and policy only.
  It records anubis_execution_status=NOT_EXECUTED and
  assurance_status=NOT_MINTED in its own output: a declared manifest
  ceiling is an upper bound on what a consumer may claim, never a grant.
- verified-program-evidence and verified-program-receipt mean exact byte/pin,
  roster, producer-summary, approved-Z3 UNSAT, and independent-RUP checks
  under inventory-safe-v1.  They do not establish policy-construct totality,
  source-to-VC proof, SMT-to-CNF proof, source-native refinement, runtime
  behavior, or universal language soundness.
- Program verification never executes the compiled artifact.  The check front
  door invokes only the exact approved compiler's build --evidence path.
- No universal correctness, source-to-native refinement, input-truth proof,
  operating-system proof, or authenticated builder claim is made.
- The repository-wide Lean admission audit binds tracked source, theorem
  axioms, and observed checker bytes. It does not prove the compiler, kernel,
  native code, operating system, hardware, or supply chain.
EOF

cat > "$PKG/README.txt" <<'EOF'
JACKAL v1.7.3 — unified domain-pack and Anubis program evidence for Apple Silicon macOS.

First run: shasum -a 256 -c SHA256SUMS
Current stable identities:
  range_proof_identity.json      schema jackal-range-proof-identity-v2
  int_cert_proof_identity.json   schema jackal-int-cert-proof-identity-v2
Compatibility and A->B->A evidence live under evidence/.
The repository-wide Lean admission record is
evidence/lean_admission_audit_v173.json.
The complete 41-tool catalog and core/formal/full profiles live under
plugin/hermes/. Domain packs and their checkers retain repository-relative
paths under domain_packs/ and tools/. Program verification uses
jackal-anubis-program with program/inventory_safe_v1.json.
Current range and composed-integral wrappers emit release epoch v1.7.2.
See NON-CLAIMS.txt before interpreting any result.
EOF

cat > "$PKG/PROVENANCE-RECEIPT.txt" <<EOF
JACKAL $VER package wiring receipt
platform $PLATFORM
compiler-authority $COMPILER $COMPILER_SHA256
evaluator jackal-native $EVALUATOR_ID
range-checker jackal_cert_check $RANGE_CHECKER_ID
archival-range-checker jackal_cert_check_v170 $ARCHIVAL_RANGE_CHECKER_ID
archival-range-coverage-inventory evidence/formal_coverage_inventory_v170.json $ARCHIVAL_RANGE_INVENTORY_ID
int-cert-checker jackal_int_cert_check $INT_CHECKER_ID
archival-plugin-hermes v1.7.0-plugin $V170_PLUGIN_HERMES_SHA256
gaussian-checker jackal_gaussian_check $GAUSSIAN_CHECKER_ID
range-proof-identity range_proof_identity.json $RANGE_IDENTITY_FILE_ID $RANGE_IDENTITY_DIGEST
int-cert-proof-identity int_cert_proof_identity.json $INT_IDENTITY_FILE_ID $INT_IDENTITY_DIGEST
lean-admission-audit evidence/lean_admission_audit_v173.json $LEAN_ADMISSION_AUDIT_ID $LEAN_ADMISSION_AUDIT_DIGEST
compatibility-floor evidence/compat_v172_floor.json $COMPAT_ID
program-compatibility-floor evidence/compat_v173_floor.json $PROGRAM_COMPAT_ID
domain-pack-registry domain_packs/registry_v1.json $(sha256 "$PKG/domain_packs/registry_v1.json")
domain-pack-verifier tools/domain_pack_verify.py $(sha256 "$PKG/tools/domain_pack_verify.py")
anubis-program-verifier tools/anubis_program_verify.py $(sha256 "$PKG/tools/anubis_program_verify.py")
anubis-program-policy program/inventory_safe_v1.json $(sha256 "$PKG/program/inventory_safe_v1.json")
range-ordering-aba evidence/range_ordering_aba_v172.json $RANGE_ABA_ID
int-cert-premise-aba evidence/int_cert_premise_aba_v172.json $INT_ABA_ID
EOF

(cd "$PKG" && /usr/bin/find . -type f ! -name SHA256SUMS | LC_ALL=C /usr/bin/sort |
  while IFS= read -r file; do /usr/bin/shasum -a 256 "$file"; done > SHA256SUMS)

# Validate the staged package itself before it can become a tarball or enter
# release/dist. This rejects a self-consistent manifest built from a
# semantically mismatched checker/proof/policy tuple.
(cd "$PKG" && /usr/bin/shasum -a 256 -c SHA256SUMS >/dev/null)
python3 -I -S -B - "$PKG" "$V170_RANGE_CHECKER_SHA256" \
  "$V170_COVERAGE_INVENTORY_SHA256" <<'PY'
import hashlib
import json
import pathlib
import sys

package = pathlib.Path(sys.argv[1]).resolve()
expected_archival_range_checker = sys.argv[2]
expected_archival_range_inventory = sys.argv[3]


def refuse(reason: str) -> None:
    raise SystemExit(f"PACKAGE_V173_REFUSED reason=staged-semantic-{reason}")


def require(condition: bool, reason: str) -> None:
    if not condition:
        refuse(reason)


def sha(path: pathlib.Path) -> str:
    require(path.is_file() and not path.is_symlink(), f"regular-file:{path.name}")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            refuse(f"duplicate-json-key:{key}")
        result[key] = value
    return result


def load_json(relative: str):
    path = package / relative
    require(path.is_file() and not path.is_symlink(), f"json-regular:{relative}")
    data = path.read_bytes()
    require(len(data) <= 4 * 1024 * 1024, f"json-size:{relative}")
    try:
        return json.loads(data, object_pairs_hook=reject_duplicates)
    except (UnicodeError, json.JSONDecodeError) as exc:
        refuse(f"json-parse:{relative}:{exc}")


manifest_path = package / "MANIFEST.sha256"
require(manifest_path.is_file() and not manifest_path.is_symlink(), "manifest-regular")
manifest_bytes = manifest_path.read_bytes()
require(len(manifest_bytes) <= 1024 * 1024, "manifest-size")
rows = {}
for raw in manifest_bytes.decode("utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    fields = line.split()
    require(len(fields) >= 2, "manifest-row")
    label = fields[0]
    require(label not in rows, f"manifest-duplicate:{label}")
    rows[label] = fields[1:]


def row_hash(label: str) -> str:
    require(label in rows and len(rows[label]) >= 1, f"manifest-missing:{label}")
    value = rows[label][-1]
    require(len(value) == 64 and all(c in "0123456789abcdef" for c in value),
            f"manifest-digest:{label}")
    return value


range_current = load_json("range_proof_identity.json")
gaussian_current = load_json("gaussian_proof_identity.json")
int_current = load_json("int_cert_proof_identity.json")
lean_audit = load_json("evidence/lean_admission_audit_v173.json")
range_archival = load_json("evidence/range_proof_identity_v1.json")
int_revoked = load_json("evidence/int_cert_proof_identity_v1.json")
compat = load_json("evidence/compat_v172_floor.json")

range_checker = sha(package / "jackal_cert_check")
gaussian_checker = sha(package / "jackal_gaussian_check")
int_checker = sha(package / "jackal_int_cert_check")
archival_range_checker = sha(package / "jackal_cert_check_v170")
require(range_checker == row_hash("checker"), "range-checker-manifest")
require(gaussian_checker == row_hash("gaussian_checker"),
        "gaussian-checker-manifest")
require(int_checker == row_hash("int_cert_checker"), "int-checker-manifest")
require(archival_range_checker == expected_archival_range_checker,
        "archival-range-checker-pin")
require(archival_range_checker == row_hash("archival_range_checker"),
        "archival-range-checker-manifest")
require(sha(package / "evidence/formal_coverage_inventory_v170.json") ==
        expected_archival_range_inventory,
        "archival-range-inventory-pin")
require(row_hash("archival_range_coverage_inventory") ==
        expected_archival_range_inventory,
        "archival-range-inventory-manifest")
revoked_int_checker_path = package.joinpath("jackal_int_cert_check_v170")
require(not revoked_int_checker_path.exists(), "revoked-int-checker-present")
require("archival_int_cert_checker" not in rows, "revoked-int-checker-row")

proofs = (
    (range_current, "jackal-range-proof-identity-v2", range_checker,
     "range_proof_identity", "range_proof_digest"),
    (gaussian_current, "jackal-gaussian-proof-identity-v1", gaussian_checker,
     "gaussian_proof_identity", "gaussian_proof_digest"),
    (int_current, "jackal-int-cert-proof-identity-v2", int_checker,
     "int_cert_proof_identity", "int_cert_proof_digest"),
    (range_archival, "jackal-range-proof-identity-v1", archival_range_checker,
     "archival_range_proof_identity", "archival_range_proof_digest"),
)
for proof, schema, checker, file_label, digest_label in proofs:
    require(proof.get("schema") == schema, f"proof-schema:{file_label}")
    require(proof.get("checker", {}).get("sha256") == checker,
            f"proof-checker:{file_label}")
    proof_path = rows[file_label][0]
    require(sha(package / proof_path) == row_hash(file_label),
            f"proof-file:{file_label}")
    require(proof.get("identity_digest_sha256") == row_hash(digest_label),
            f"proof-digest:{file_label}")

require(lean_audit.get("schema") == "jackal-lean-admission-audit-v1",
        "lean-audit-schema")
require(sha(package / "evidence/lean_admission_audit_v173.json") ==
        row_hash("lean_admission_audit"), "lean-audit-file")
lean_audit_digest = lean_audit.pop("audit_digest_sha256", None)
computed_lean_audit_digest = hashlib.sha256(
    json.dumps(lean_audit, sort_keys=True, separators=(",", ":"),
               ensure_ascii=False).encode("utf-8")
).hexdigest()
require(lean_audit_digest == computed_lean_audit_digest,
        "lean-audit-self-digest")
require(lean_audit_digest == row_hash("lean_admission_audit_digest"),
        "lean-audit-manifest-digest")
audit_result = lean_audit.get("audit_result", {})
require(audit_result.get("status") == "pass", "lean-audit-status")
require(audit_result.get("logical_admission_count") == 0,
        "lean-audit-admission-count")
source_inventory = lean_audit.get("source_inventory", {})
source_files = source_inventory.get("files", [])
require(source_inventory.get("file_count") == 42 and len(source_files) == 42,
        "lean-audit-source-count")
source_paths = [item.get("path") for item in source_files
                if isinstance(item, dict)]
require(len(source_paths) == 42 and len(set(source_paths)) == 42,
        "lean-audit-source-uniqueness")
construct_policy = source_inventory.get("construct_policy", {})
require(construct_policy.get("forbidden_findings") == [],
        "lean-audit-forbidden-findings")
allowed_findings = construct_policy.get("allowed_findings", [])
require(len(allowed_findings) == 2 and
        {item.get("construct") for item in allowed_findings} ==
        {"implemented_by"}, "lean-audit-allowed-findings")
theorem_audit = lean_audit.get("theorem_axiom_audit", {})
theorem_rows = theorem_audit.get("theorems", [])
require(theorem_audit.get("theorem_count") == 27 and len(theorem_rows) == 27,
        "lean-audit-theorem-count")
theorem_names = [item.get("theorem") for item in theorem_rows
                 if isinstance(item, dict)]
require(len(theorem_names) == 27 and len(set(theorem_names)) == 27,
        "lean-audit-theorem-uniqueness")
for item in theorem_rows:
    require(item.get("axioms") ==
            ["propext", "Classical.choice", "Quot.sound"],
            f"lean-audit-axioms:{item.get('theorem')}")
trust_surface = lean_audit.get("trust_surface", {})
require(trust_surface.get("logical_admissions") == [],
        "lean-audit-logical-admissions")
require(trust_surface.get("repository_axiom_declarations") == [],
        "lean-audit-repository-axioms")
audit_bindings = lean_audit.get("release_bindings", {}).get(
    "current_proof_identities", [])
require(len(audit_bindings) == 3, "lean-audit-binding-count")
expected_audit_bindings = {
    "range": (range_checker, sha(package / "range_proof_identity.json")),
    "gaussian": (gaussian_checker, sha(package / "gaussian_proof_identity.json")),
    "int-cert": (int_checker, sha(package / "int_cert_proof_identity.json")),
}
for binding in audit_bindings:
    lane = binding.get("lane")
    require(lane in expected_audit_bindings, f"lean-audit-binding-lane:{lane}")
    expected_checker, expected_identity = expected_audit_bindings.pop(lane)
    require(binding.get("checker_sha256") == expected_checker,
            f"lean-audit-binding-checker:{lane}")
    require(binding.get("identity_checker_sha256") == expected_checker,
            f"lean-audit-identity-checker:{lane}")
    require(binding.get("identity_sha256") == expected_identity,
            f"lean-audit-binding-identity:{lane}")
require(expected_audit_bindings == {}, "lean-audit-binding-coverage")

require(int_revoked.get("schema") == "jackal-int-cert-proof-identity-v1",
        "revoked-int-proof-schema")
revoked_reference = rows.get("revoked_int_cert_proof_identity_reference", [])
require(len(revoked_reference) == 2, "revoked-int-proof-reference")
require(sha(package / revoked_reference[0]) == revoked_reference[1],
        "revoked-int-proof-file")

lanes = compat.get("lanes", {})
for lane in ("range", "rational_variants"):
    current = lanes.get(lane, {}).get("current", {})
    archival = lanes.get(lane, {}).get("archival_v1", {})
    require(current.get("schema") == "jackal-range-proof-identity-v2",
            f"compat-current-schema:{lane}")
    require(current.get("allowed_release_epochs") == ["v1.7.2"],
            f"compat-current-epoch:{lane}")
    require(current.get("identity_file_sha256") == row_hash("range_proof_identity"),
            f"compat-current-proof:{lane}")
    require(archival.get("mode") == "replay-only", f"compat-archive-mode:{lane}")
    require(archival.get("allowed_release_epochs") == ["v1.5.0"],
            f"compat-archive-epoch:{lane}")
    require(archival.get("checker_sha256") == archival_range_checker,
            f"compat-archive-checker:{lane}")
    require(archival.get("identity_file_sha256") ==
            row_hash("archival_range_proof_identity"),
            f"compat-archive-proof:{lane}")

int_policy = lanes.get("int_cert", {})
int_current_policy = int_policy.get("current", {})
int_archival_policy = int_policy.get("archival_v1", {})
require(int_current_policy.get("schema") == "jackal-int-cert-proof-identity-v2",
        "compat-int-current-schema")
require(int_current_policy.get("allowed_release_epochs") == ["v1.7.2"],
        "compat-int-current-epoch")
require(int_current_policy.get("identity_file_sha256") ==
        row_hash("int_cert_proof_identity"), "compat-int-current-proof")
require(int_archival_policy.get("mode") == "revoked-refuse",
        "compat-int-revocation-mode")
require(int_archival_policy.get("allowed_release_epochs") == [],
        "compat-int-revocation-epochs")
require(int_archival_policy.get("identity_file_sha256") == revoked_reference[1],
        "compat-int-revocation-proof")

program_compat = load_json("evidence/compat_v173_floor.json")
policy = load_json("program/inventory_safe_v1.json")
catalog = load_json("plugin/hermes/tools.json")
full_profile = load_json("plugin/hermes/profiles/full.json")
tool_names = [tool.get("name") for tool in catalog.get("tools", [])
              if isinstance(tool, dict)]
require(catalog.get("version") == "v1.7.3", "catalog-version")
require(len(tool_names) == 41 and len(set(tool_names)) == 41,
        "catalog-tool-count")
require(full_profile.get("tools") == tool_names, "full-profile-catalog-parity")
for profile_name in ("core", "formal", "full"):
    profile = load_json(f"plugin/hermes/profiles/{profile_name}.json")
    profile_digest = profile.pop("profile_digest_sha256", None)
    computed_profile_digest = hashlib.sha256(
        json.dumps(profile, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    require(profile_digest == computed_profile_digest,
            f"profile-digest:{profile_name}")
require(program_compat.get("release_epoch") == "v1.7.3",
        "program-compat-epoch")
require(program_compat.get("tool_count") == 41, "program-compat-tool-count")
require(program_compat.get("program_profile") == "inventory-safe-v1",
        "program-compat-profile")
require(program_compat.get("independent_policy_construct_totality") is False,
        "program-compat-construct-totality")
policy_digest = policy.pop("policy_digest_sha256", None)
computed_policy_digest = hashlib.sha256(
    json.dumps(policy, sort_keys=True, separators=(",", ":"),
               ensure_ascii=False).encode("utf-8")
).hexdigest()
require(policy_digest == computed_policy_digest, "program-policy-digest")
require(program_compat.get("program_policy_sha256") == policy_digest,
        "program-compat-policy")

manifest_bound_files = {
    "domain_pack_registry": "domain_packs/registry_v1.json",
    "domain_pack_verifier": "tools/domain_pack_verify.py",
    "domain_pack_test_exists_checker": "tools/test_exists_verify.py",
    "domain_pack_decision_checker": "tools/decision_verify.py",
    "anubis_program_verifier": "tools/anubis_program_verify.py",
    "anubis_program_policy": "program/inventory_safe_v1.json",
}
for label, relative in manifest_bound_files.items():
    require(len(rows.get(label, [])) == 2, f"manifest-shape:{label}")
    require(rows[label][0] == relative, f"manifest-path:{label}")
    require(row_hash(label) == sha(package / relative),
            f"manifest-file:{label}")
print("STAGED_IDENTITY_VALIDATION_PASS")
PY

PACK_VALIDATION=$(python3 -I -S -B "$PKG/tools/domain_pack_verify.py" \
  --root "$PKG" 2>&1) || {
  echo "PACKAGE_V173_REFUSED reason=staged-domain-pack detail=$PACK_VALIDATION" >&2
  exit 4
}
case "$PACK_VALIDATION" in
  *'"status":"accepted"'*) ;;
  *)
    echo "PACKAGE_V173_REFUSED reason=staged-domain-pack-status detail=$PACK_VALIDATION" >&2
    exit 4
    ;;
esac

PLUGIN_SELFTEST=$("$PKG/plugin/hermes/jackal_hermes" selftest 2>&1) || {
  echo "PACKAGE_V173_REFUSED reason=staged-plugin-selftest detail=$PLUGIN_SELFTEST" >&2
  exit 4
}
case "$PLUGIN_SELFTEST" in
  *"plugin_hermes.identity_match=true"*) ;;
  *)
    echo "PACKAGE_V173_REFUSED reason=staged-plugin-identity detail=$PLUGIN_SELFTEST" >&2
    exit 4
    ;;
esac

SMOKE_DIR="$STAGE/staged-semantic-smoke"
/bin/mkdir "$SMOKE_DIR"
RANGE_SMOKE_RECEIPT="$SMOKE_DIR/staged-range-receipt.json"
INT_SMOKE_RECEIPT="$SMOKE_DIR/staged-int-receipt.json"
RANGE_SMOKE=$("$PKG/jackal-cert-release" x 0 1 "$RANGE_SMOKE_RECEIPT" 2>&1) || {
  echo "PACKAGE_V173_REFUSED reason=staged-range-smoke detail=$RANGE_SMOKE" >&2
  exit 4
}
case "$RANGE_SMOKE" in *"status=formal-bounded"*) ;; *)
  echo "PACKAGE_V173_REFUSED reason=staged-range-status detail=$RANGE_SMOKE" >&2
  exit 4
esac
INT_SMOKE=$("$PKG/jackal-int-cert-release" 0 0 1 2 "$INT_SMOKE_RECEIPT" 2>&1) || {
  echo "PACKAGE_V173_REFUSED reason=staged-int-smoke detail=$INT_SMOKE" >&2
  exit 4
}
case "$INT_SMOKE" in *"status=formal-bounded"*) ;; *)
  echo "PACKAGE_V173_REFUSED reason=staged-int-status detail=$INT_SMOKE" >&2
  exit 4
esac

RANGE_VERIFY=$("$PKG/jackal-receipt-verify" \
  --receipt "$RANGE_SMOKE_RECEIPT" --checker "$PKG/jackal_cert_check" \
  --expected-evaluator "$EVALUATOR_ID" --expected-checker "$RANGE_CHECKER_ID" \
  --expected-source "$SOURCE_ID" --expected-release-epoch v1.7.2 \
  --expected-command range-bound-cert --expected-expression x \
  --expected-input-lo 0 --expected-input-hi 1 \
  --inventory "$PKG/formal_coverage_inventory.json" --expected-inventory "$COVERAGE_ID" \
  --proof-identity "$PKG/range_proof_identity.json" \
  --expected-proof-identity-file "$RANGE_IDENTITY_FILE_ID" \
  --expected-proof-identity-digest "$RANGE_IDENTITY_DIGEST" 2>&1) || {
  echo "PACKAGE_V173_REFUSED reason=staged-range-replay detail=$RANGE_VERIFY" >&2
  exit 4
}
INT_VERIFY=$("$PKG/jackal-receipt-verify" \
  --receipt "$INT_SMOKE_RECEIPT" --checker "$PKG/jackal_int_cert_check" \
  --expected-evaluator "$INT_PRODUCER_ID" --expected-checker "$INT_CHECKER_ID" \
  --expected-release-epoch v1.7.2 --expected-command integrate-bound-cert \
  --expected-expression 0 --expected-input-lo 0 --expected-input-hi 1 \
  --expected-tolerance 2 --inventory "$PKG/formal_coverage_inventory.json" \
  --expected-inventory "$COVERAGE_ID" \
  --proof-identity "$PKG/int_cert_proof_identity.json" \
  --expected-proof-identity-file "$INT_IDENTITY_FILE_ID" \
  --expected-proof-identity-digest "$INT_IDENTITY_DIGEST" 2>&1) || {
  echo "PACKAGE_V173_REFUSED reason=staged-int-replay detail=$INT_VERIFY" >&2
  exit 4
}
for replay in "$RANGE_VERIFY" "$INT_VERIFY"; do
  /usr/bin/printf '%s\n' "$replay" | /usr/bin/grep -F "status=verified verdict=ACCEPT" >/dev/null &&
  /usr/bin/printf '%s\n' "$replay" | /usr/bin/grep -F "receipt_valid=true" >/dev/null &&
  /usr/bin/printf '%s\n' "$replay" | /usr/bin/grep -F "checker_verdict=ACCEPT" >/dev/null || {
    echo "PACKAGE_V173_REFUSED reason=staged-replay-markers detail=$replay" >&2
    exit 4
  }
done

# The semantic smokes must not mutate any packaged authority byte.
(cd "$PKG" && /usr/bin/shasum -a 256 -c SHA256SUMS >/dev/null)
echo "STAGED_SEMANTIC_VALIDATION_PASS"

STAGED_TARBALL="$STAGE/$TARBALL_NAME"
python3 - "$PKG" "$STAGED_TARBALL" <<'PY'
import gzip
import pathlib
import sys
import tarfile

package = pathlib.Path(sys.argv[1]).resolve()
output = pathlib.Path(sys.argv[2]).resolve()
paths = [package, *sorted(package.rglob("*"), key=lambda p: p.relative_to(package).as_posix())]
with output.open("wb") as raw:
    with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for path in paths:
                relative = path.relative_to(package).as_posix() if path != package else ""
                arcname = package.name if not relative else f"{package.name}/{relative}"
                info = archive.gettarinfo(str(path), arcname=arcname)
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                info.mtime = 1786924800
                info.pax_headers = {}
                if path.is_file():
                    with path.open("rb") as source:
                        archive.addfile(info, source)
                else:
                    archive.addfile(info)
PY

/bin/mkdir -p "$DIST"
# Blocker F: reject any existing regular file, directory, OR (dangling
# or live) symlink at the final publication paths. Bare `-e` misses a
# symlink whose target no longer exists, so `mv` would then overwrite
# the link or follow it. Guarding both `-e` and `-L` closes both
# race variants: appearance-during-build and pre-race symlink poison.
[ ! -e "$FINAL_PKG" ] && [ ! -L "$FINAL_PKG" ] \
  && [ ! -e "$FINAL_TARBALL" ] && [ ! -L "$FINAL_TARBALL" ] || {
  echo "PACKAGE_V173_REFUSED reason=output-appeared-during-build" >&2
  exit 5
}
/bin/mv "$PKG" "$FINAL_PKG"
/bin/mv "$STAGED_TARBALL" "$FINAL_TARBALL"

echo "PACKAGE_V173_BUILD_PASS version=$VER platform=$PLATFORM"
echo "package=$FINAL_PKG"
echo "files=$(cd "$FINAL_PKG" && /usr/bin/find . -type f | /usr/bin/wc -l | /usr/bin/tr -d ' ')"
echo "sha256sums_root=$(sha256 "$FINAL_PKG/SHA256SUMS")"
echo "tarball=$FINAL_TARBALL"
echo "tarball_sha256=$(sha256 "$FINAL_TARBALL")"
echo "tarball_bytes=$(/usr/bin/wc -c < "$FINAL_TARBALL" | /usr/bin/tr -d ' ')"
