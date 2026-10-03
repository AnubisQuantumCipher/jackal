# Private checker execution development

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

The development route runs the unchanged checker inside a single-request guest.
The host QEMU command contains public boot parameters and descriptor numbers.
Certificate and request fields travel through anonymous pipes after an exact
readiness frame. The guest configures a raw, non-echoing serial channel before
readiness. Only its broker owns that channel. The checker runs without privilege,
with disconnected stdin and separate stdout/stderr capture.

The guest kernel, broker, loader, libraries, QEMU, and virtualization platform
are additional trusted components. They do not inherit the Lean theorem's
authority. This route targets cross-user host argument disclosure; it does not
claim protection against the operator, privileged host inspection, compromised
virtualization, swap disclosure, or hibernation.

## Development files

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
python3 -B transport/linux_aarch64/build_development_guest.py \
  --runtime /absolute/path/to/unchanged/runtime \
  --kernel /absolute/path/to/qualified/ARM64/Image \
  --output /absolute/path/to/new/fixture
```

The builder never changes the supplied runtime or kernel. The current local
kernel and libraries are development inputs, not a portable release package.
Guest boot and checker execution must be measured before claiming compatibility.

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
