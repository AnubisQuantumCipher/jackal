# Private sealed-runtime execution development

This directory develops the private execution broker needed by the Omarchy
receipt verifier. It is **not installed, release-authorized, or connected to the
production verification path**. The existing runtime draft still cannot be
released until the integration and compatibility obligations below are closed.

## Why a guest is needed

Historical receipts bind the exact released checker bytes. Those checkers accept
request fields through command-line arguments. Adding a new argument-file
interface changes their source and binary identities; sending the new interface
to an unchanged checker makes previously accepted receipts fail. A host wrapper
that reads private input and then supplies ordinary host arguments preserves the
same exposure. A PID namespace alone does not hide those arguments from the host.

The current development route runs the entire unchanged runtime inside a
single-request guest, invoking its original isolated loader. This preserves the
plugin bundle identity and original historical selection and revocation logic.
It supersedes the checker-only prototype retained here for diagnostic evidence.
The host QEMU command contains public boot parameters and descriptor numbers.
Certificate and request fields travel through anonymous pipes after an exact
readiness frame. The guest configures a raw, non-echoing serial channel before
readiness. Only its broker owns that channel. The checker runs without privilege,
with the framed request as stdin and separate stdout/stderr capture. Its runtime
resides on a read-only disk; temporary request data exists only inside the guest.

The guest kernel, broker, loader, libraries, QEMU, and virtualization platform
are additional trusted components. They do not inherit the Lean theorem's
authority. This route targets cross-user host argument disclosure; it does not
claim protection against the operator, privileged host inspection, compromised
virtualization, swap disclosure, or hibernation.

## Development files

- `sealed_runtime_guest.c`: mounts the sealed runtime disk read-only, creates
  guest-local temporary and device filesystems, drops privilege, and invokes
  `/usr/bin/python3 -I -S -B /runtime/isolated_entry.py plugin stdio`.
- `build_sealed_runtime_guest.py`: verifies a caller-supplied archive digest,
  preserves its runtime file bytes, and records a development Python/platform
  closure. Optional Tk GUI bindings are explicitly excluded; their dependencies
  are absent on the source host. The platform is headless and needs verifier
  compatibility qualification. The companion also supplies the source-layout
  archival marker and proof record expected by the unchanged Linux code, using
  only bytes and checker identity validated against the packaged compatibility
  floor. They live outside `runtime/` and are recorded as companion inputs.
  The ext4 image is not yet reproducible.
- `sealed_runtime_runner.py`: permits only receipt and bundle verification,
  snapshots boot and disk inputs into sealed descriptors, and transports the
  original JSON values through a single-request guest.

The earlier checker-only prototype consists of:

- `guest_init.c`: standalone PID1; fixed checker selection, binary framing,
  unprivileged execution, original output/exit transport, acknowledgement and
  completion exchange, then poweroff.
- `build_development_guest.py`: creates a new output directory containing a
  statically linked broker, copied unchanged checker files and loader libraries,
  deterministic-layout initramfs, copied kernel, and observed development hashes.
- `development_runner.py`: validates the development fixture hashes, copies boot
  bytes into sealed memory descriptors, launches the explicit Linux aarch64/KVM
  profile, checks framing, and kills/reaps a failed or timed-out guest. It never
  falls back to public checker arguments.

The generated manifest explicitly sets `release_authorized` to `false`. Its
self-recorded hashes detect accidental fixture changes; they are **not** an
operator trust root. The release implementation must use separately authorized
pins and a complete dependency manifest. The fixture's fixed guest RAM and
overall deadline also need compatibility qualification.

## Building a fixture

Supply explicit paths; the output must not already exist:

```sh
mkdir -p .build
python3 -B transport/linux_aarch64/build_sealed_runtime_guest.py \
  --archive /absolute/path/to/unchanged/runtime.tar.gz \
  --expected-sha256 INDEPENDENTLY_VERIFIED_ARCHIVE_DIGEST \
  --kernel /absolute/path/to/qualified/ARM64/Image \
  --python /absolute/path/to/qualified/python \
  --stdlib /absolute/path/to/matching/python-stdlib \
  --output /absolute/path/to/new/fixture
```

The builder never changes the supplied runtime archive or kernel. Local package
provenance is not a claim that the package is a public release asset. Original
loader and verification sources must remain byte-identical; failed argument-file
changes were restored instead of broadening the inventory exception.

The installed package lacks that archival source-layout context and refuses
archival receipt construction. Historical qualification must therefore compare
the original runtime in the restored context with the guest containing the same
context; it must not claim the installed package previously accepted the case.

Original bundle refusals are preserved as well: the guest does not add support
for plugin-bound legacy bundle cases that the original runtime already refused.
 The current local
kernel and libraries are development inputs, not a portable release package.
Guest boot and checker execution must be measured before claiming compatibility.

## Development validation

`check_sealed_runtime_guest.py` compares public synthetic receipt controls against
the original loader, requiring explicit positive acceptance and byte-identical
exit/stdout/stderr. `tests/sealed_runtime_transport_test.py` checks request
refusals and descriptor cleanup during partial snapshot and launch failures.
The fixed disk profile uses modern virtio PCI with INTx (`vectors=0`); default
MSI stalled in the development host boot control. The guest supplies a fixed
local `HOME=/tmp` required by the original Python startup imports.

Whole-runtime controls matched original responses for current and historical
range receipts, request/epoch mismatches, and a current composed-integral receipt
and request mismatch. The historical comparison includes the pinned archival
layout on both sides. These are development
observations, not a complete compatibility matrix. Rebuilt fixtures must rerun
controls after broker/platform changes.

The independent source review also requires a dedicated no-dump host process,
end-to-end supervised preparation and bounded termination, and separate boot and
verifier allowances. The current development runner does not close those items.
Its development input/output/storage ceilings are not evidence that every
previously accepted boundary case is preserved. No production caller uses it.

## Completion requirements

Before integration or publication, retain evidence for:

- Every supported historical and current replay tuple: plugin identity,
  evaluator/producer, checker, proof, inventory, variant, and proof epoch.
  Keep revoked archival integral receipts revoked and retain all substitution
  refusals. Receipt and bundle front doors must use the same trusted mapping.
- Byte-identical checker output and exit behavior for original accepted and
  rejected cases, including boundary-size certificates and arguments. Existing
  input limits, request binding, and accepted cases must not be reduced.
- Raw-channel readback, no echo, exact framing, truncation/extra-frame refusal,
  timeout termination, and positive and negative completion controls.
- Immutable consumed boot/checker/dependency bytes, complete ELF dependency and
  kernel/CPU qualification, host/guest dump suppression, and a versioned QEMU
  platform profile. A readiness marker alone is not attestation.
- A separately versioned runtime manifest and inventory, complete release gates,
  actual GPT-6.1 implementation review, package reproduction, and publication
  readback. Historical manifests, proof identities, and released artifacts retain
  their bytes. The existing inventory overlay exception must not be broadened.
- Documentation and install behavior for the added virtualization dependency.
  Linux guest checkers do not replay historical macOS checker bytes; existing
  macOS interfaces and supported contexts need their own preserved path.

References: [QEMU invocation](https://www.qemu.org/docs/master/system/invocation.html),
[versioned ARM virt platform](https://www.qemu.org/docs/master/system/arm/virt.html),
and [Linux console parameters](https://cdn.kernel.org/doc/html/latest/admin-guide/kernel-parameters.html).
