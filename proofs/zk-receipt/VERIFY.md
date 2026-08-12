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
