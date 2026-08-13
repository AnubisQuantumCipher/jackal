# JACKAL zero-knowledge calculation receipt

This directory contains a RISC0 zkVM receipt proving that the program
[`proofs/jackal_proof_guest.anb`](../jackal_proof_guest.anb) — JACKAL's integer core
(Euclidean gcd, the gcd-reduced exact binomial algorithm, trial-division primality, lcm) —
executed honestly and committed the value **8**: all eight of its arithmetic invariants held.

The ImageID is derived from the compiled guest ELF, so the receipt binds the *output* to the
*exact program* that produced it. A third party needs to trust neither the host that ran the
proof nor its author.

## Verify

```bash
/Users/sicarii/anubis-lang/vm/pins/anubis-51f4a964347a verify-receipt \
  --receipt proofs/zk-receipt/receipt.bin \
  --image-id proofs/zk-receipt/image_id.txt
```

Decode the committed journal (little-endian u32; expected value `8`):

```bash
python3 -c "import struct; print(struct.unpack('<I', open('proofs/zk-receipt/journal.bin','rb').read()))"
```

## Source ↔ receipt binding, reconciled (2026-08-13)

A field audit asked whether `guest_source_sha256` in `risc0_metadata.json`
(`2d11f1bf…`) matches the checked-in guest source, whose raw file hash is
`3c0c7d30…`. The two hashes have **different preimages by design**:
`guest_source_sha256` digests the deterministic transpiled Rust guest
(`guest_source.rs`), not the `.anb` bytes. On 2026-08-13 the entire chain was
re-derived from the committed `proofs/jackal_proof_guest.anb` with the pinned
compiler:

- regenerated `guest_source.rs` sha256 = `2d11f1bf7b4af2af65187fbad9ff54656c9c93e902fda8f8f1a18535a18dae83` — equal to the receipt's recorded value;
- rebuilt `guest.elf` sha256 = `d363e61d9426d7d029a60cd9e268272f57ea0195725dde1a83b8ce47508ec2b4` — byte-identical to the receipt's recorded ELF;
- derived ImageID identical (`2031595584 2502850517 … 2324132228`);
- a fresh receipt was generated and verified, committing the same journal
  (`8`, sha256 `dc765660…`).

The committed guest source therefore provably produces the exact program this
receipt binds to. (STARK receipts are randomized, so the fresh `receipt.bin`
bytes differ; the committed original continues to verify and is retained.)

## Provenance

- Proved 2026-08-12 on the CPU lane (`R0_DISABLE_METAL=1`, `lane_observed=cpu`) with the
  pinned compiler `anubis-51f4a964347a` and the vendored risc0 3.0.5 stack
  (`--metal-reference /Users/sicarii/anubis-lang`).
- ImageID: `2031595584 2502850517 1061793976 3631788647 2192956682 3896767421 1303558953 2324132228`
- receipt.bin sha256: `9542f4a91e2f1187d1f06ca8129edd6e278efb145e08b70787b73ede897f0b2b`
- journal.bin sha256: `dc765660b06ee03dd16fd7ca5b957e8c805161ac2c4af28c5a100ab2ab432ca1`
- Negative control performed at proving time: flipping one byte of the receipt makes
  `verify-receipt` fail with "verification indicates proof is invalid".

## Honest boundary

The receipt proves *this guest program* ran and produced journal `8`. It does not prove
anything about the interactive `jackal` binary, the float engine, or the physical models —
those are covered by the (non-cryptographic) black-box suite, self-test, and parity gates.
