# Build-determinism receipt — `jackal_calc.anb` → `anubis_run`

Recorded 2026-08-19 by agent `DetRecord2` on branch `feat/domain-pack-protocol`.

This file records a measurement: repeated builds of the committed engine source,
through the pinned Anubis compiler, produced one and only one binary. It also
records what that measurement does **not** license, and one design consequence
that is easy to get backwards.

## Why this file lives in `docs/`

Checked before writing, because misfiling it would break a tree's contract:

- **Not `release/evidence/`.** That tree is generated, manifest-sealed evidence.
  `grep -c "release/evidence" release/MANIFEST.sha256` → `8`, and
  `tests/evidence_determinism_test.py` requires its producers to regenerate
  byte-identical output. A hand-written prose file there would have no producer
  to re-run, and registering it would mean hand-editing a `MANIFEST.sha256` row
  — which is forbidden.
- **Not `evals/v2/receipts/`.** That tree's own charter (`README.md`, line 3)
  says "A receipt in this directory is a JSON file written by
  `evals/v2/runner.py` (schema `jackal-eval-v2-results-v1`)", verified by
  `metrics.py --verify-receipts`. A build measurement is not an eval arm and has
  none of the four required binding fields.
  `grep -c "evals/v2/receipts" release/MANIFEST.sha256` → `0`.
- **`docs/` fits.** It already holds hand-written human-authored records
  (`docs/W3_W4_W6_W10_COMPLETION_RECORD.md`), is not manifest-sealed, and no
  gate enumerates it.

## The instrument finding — read this before the numbers

**There are TWO independent caches between source and binary. A build that
looks like a fresh compile can be a cache hit in either. Quarantine both, or
you are measuring a cache and reporting a compiler.**

1. `$TMPDIR/anubis-run-cache/` — content-addressed binaries keyed by the
   compiler. On this host it already held an entry whose content digest equals
   the digest reported below, timestamped **before** this measurement began
   (`Aug 19 15:15`, measurement began `23:19`). Any run that consulted it would
   have measured cache lookup, not compilation.
2. `$TMPDIR/anubis-run-cargo-target-audited-crypto-v3/` — the **shared cargo
   target dir**. This is the layer that actually matters for the path the
   launcher uses, and it is the one an operator is most likely to miss.

Two firsthand observations pin down which layer was live:

- With the matching `anubis-run-cache` entry **present** and an explicit
  `--out`, the build still recompiled (`real 9.60`, and the cargo leaf artifact
  was rewritten). So the launcher's `--out` path did not shortcut through that
  cache. In builds 1–3 the entry was quarantined and was **not** recreated
  afterwards, which is consistent. `[INFERENCE]` — one configuration tested,
  not a proof that `--out` always bypasses it.
- The cargo target dir was **warm**: 40 `.rlib` dependency artifacts, of which
  `find … -name "*.rlib" -mmin -15 | wc -l` → `0` were touched during this
  measurement. So dependency compilation was reused, and what was re-measured
  each build was **leaf-crate codegen plus link**.

That second point is a scope limit on everything below, stated here rather than
in a footnote: **this receipt measures leaf-crate codegen and link determinism
against warm dependency rlibs.** Cold-dependency determinism is carried forward
from `DeterminismProbe`, not reproduced here.

The builds were real compilations, not artifact copies. The cargo leaf artifact
mtime advanced on every single build:

```
leaf mtime BEFORE : 2026-08-19 23:20:44.096855922
leaf mtime AFTER b4: 2026-08-19 23:23:32.021154264
leaf mtime AFTER b5: 2026-08-19 23:23:41.768093549
```

with ~9.5 s user CPU each. A copy costs milliseconds.

## Toolchain identity — what the digest is bound to

| Component | Value |
|---|---|
| Anubis compiler pin | `$HOME/anubis-lang/vm/pins/anubis-a733565f237d` |
| Pin SHA-256 | `a733565f237df171e7cf93b9b37700a42d8713576818fd92f8cd23a8ad7a69e2` |
| `rustc --version` | `rustc 1.97.0-nightly (82bee9650 2026-05-09)` |
| `cargo --version` | `cargo 1.97.0-nightly (a343accce 2026-05-08)` |
| Target triple (`rustc -vV` host) | `aarch64-apple-darwin` |
| Host | `Darwin arm64`, kernel 25.6.0, Apple M4 Max |

The pin digest matches `toolchain.anubis_compiler_pin` in
`release/evidence/build_environment_v170.json` — an independent cross-check that
this is the same compiler the sealed release records. That file does **not**
record a `rustc` version (it describes the clang/Lean-built checker binaries),
so the `rustc` identity above is recorded here for the first time.

## Measured firsthand (this session, 2026-08-19 23:19–23:24 EDT)

Five builds. **One** distinct binary digest.

| Quantity | Value |
|---|---|
| Source `jackal_calc.anb` | `f579b6f59bc024d24914487b0cd0f18ea43dea1be52708a05a66dc885d80bb4e` |
| Binary `anubis_run` (5/5 builds) | `f11f3a429aa64dc0f09eb930e82bc3250e19eeb5a8a74b26b86683fafd72a655` |
| Generated `anubis_run.rs` (3/3 checked) | `bd10bb341104d18852aa7cf692ca4d1e6c457bed2a6937f704f66a1af532b409` |
| Linker `LC_UUID` (3/3 checked) | `88B5F95B-0B6A-34B8-A07B-CA809213EDA4` |

The source digest was read twice, before the first build and after the last, and
was unchanged both times — so the digest above describes this tree and not a
tree a sibling edited mid-measurement.

Build conditions covered:

| # | Out-dir | `anubis-run-cache` entry | `real` | Binary digest |
|---|---|---|---|---|
| 1 | `$TMPDIR/detrecord2-b1` | quarantined | 10.04 | `f11f3a42…` |
| 2 | `$TMPDIR/detrecord2-b2-other` | quarantined | 9.54 | `f11f3a42…` |
| 3 | `$TMPDIR/detrecord2 b3 with spaces` (**spaces**) | quarantined | 9.70 | `f11f3a42…` |
| 4 | `$TMPDIR/detrecord2-b4` | **present** | 9.60 | `f11f3a42…` |
| 5 | `$TMPDIR/detrecord2-b5` | quarantined | 9.60 | `f11f3a42…` |

No build-path text leaked into the binary. For both `b1` and the
space-containing `b3`, `strings -a … | grep -c` returned `0` for each of
`detrecord2`, `/var/folders`, `/tmp`, `/Users/sicarii`, and `with spaces`.

### The cache is keyed, not content-addressed

Confirmed firsthand, because conflating the two would misread every entry.
`ls -la "$TMPDIR/anubis-run-cache"` showed 4 entries; hashing each shows the
filename is a **lookup key**, never the content digest — for all four:

```
key=21bfb67137d6bbb3ad749b9b94573f3154c08b9898041804ae43d4d55ba2b5e0
  content=71d21d2b30d8c21863331ced990cd1508870994258de8911903f1ea7d72aa99a
key=6616752304ff042f439ed7d0f8de371e981b3e88419396092a57a1d44addd3c2
  content=5afc7dd24b86dcb4cc7fde83972cf1b687d69fa16fe627cf10db434e33a7a163
key=88fce265886185b819979d68510c33b6c1eb2c2ee149fe3b7301460851ff1023
  content=2cb8c916179275569e4af79f8ad4ac6d7d11fb62653873bc79151794d7e73fb1
key=9c050f3b3cc164eb4cef9bcf343600a0abbd219f589b162047ea8ecb50848731
  content=f11f3a429aa64dc0f09eb930e82bc3250e19eeb5a8a74b26b86683fafd72a655
```

The last entry (`file` → `Mach-O 64-bit executable arm64`) *contains* the binary
this receipt is about. Its name `9c050f3b…` is not that binary's digest and must
never be quoted as one.

### Why the bytes are path-independent

`PROVENANCE.md` "Build-determinism history" states the fix: a content-derived
cargo package name, so identical source implies an identical package name and
therefore identical crate-metadata hash, symbol mangling and codegen-unit
layout. Tested against this pin — predicted from the generated-Rust digest, then
looked up in the cargo target dir:

```
$ ls -d "$TMPDIR"/anubis-run-cargo-target-audited-crypto-v3/release/anubis_run_*
…/release/anubis_run_bd10bb341104d18852aa7cf6
```

`bd10bb341104d18852aa7cf6` is the first **24** hex characters of the generated
`anubis_run.rs` digest — content-derived, as documented. Note that
`PROVENANCE.md` describes the prefix as `[..12]` for anubis-lang commit
`b3390c7c`; the pin measured here (`anubis-a733565f237d`) is a later pin and
uses 24. That is a mechanism detail, not a change to the reproducibility claim,
and `b3390c7c` was not measured here, so `PROVENANCE.md` is left as written.

## Carried forward from `DeterminismProbe` — NOT reproduced here

Reported by the earlier probe agent and **not** independently re-measured by
this receipt. Same digests, wider conditions:

- 7 builds and 8 source-digest readings (this receipt: 5 builds, 2 readings).
- Builds with this program's **cargo artifacts** quarantined, including two with
  no matching `anubis-run-cache` entry at all.
- A **FRESH** build with a virgin `TMPDIR` in which **124 dependency artifacts**
  were compiled from scratch. This is the cold-dependency case that the present
  receipt explicitly does not cover.
- The observation that the `anubis-run-cache` already held a matching entry
  ~1.5 h before that probe's first build.

Where the two overlap — source digest, binary digest, generated-Rust digest,
`LC_UUID`, path-independence including spaces, no path leakage, ~10 s CPU per
build — they agree exactly. Nothing in this receipt contradicts the probe.

## Reproduction

```bash
cd /path/to/jackal
shasum -a 256 jackal_calc.anb
#   expect f579b6f59bc024d24914487b0cd0f18ea43dea1be52708a05a66dc885d80bb4e

# Quarantine the anubis-level cache entry whose CONTENT is the target binary.
mkdir -p "$TMPDIR/q"
for f in "$TMPDIR"/anubis-run-cache/*; do
  [ "$(shasum -a 256 "$f" | cut -d' ' -f1)" = \
    f11f3a429aa64dc0f09eb930e82bc3250e19eeb5a8a74b26b86683fafd72a655 ] \
    && mv "$f" "$TMPDIR/q/"
done

# Two builds into distinct out-dirs, one path containing spaces.
for out in "$TMPDIR/det-a" "$TMPDIR/det b with spaces"; do
  rm -rf "$out"; mkdir -p "$out"
  JACKAL_FORCE_SOURCE=1 JACKAL_OUT="$out" ./jackal mod-pow 2 10 1000
  shasum -a 256 "$out/anubis_run" "$out/anubis_run.rs"
  otool -l "$out/anubis_run" | awk '/LC_UUID/{f=1} f&&/uuid/{print $2; exit}'
done

# Restore the quarantined entry.
mv "$TMPDIR"/q/* "$TMPDIR"/anubis-run-cache/ && rmdir "$TMPDIR/q"

# Instrument checks — did rustc actually run, and are the deps warm?
T="$TMPDIR/anubis-run-cargo-target-audited-crypto-v3"
find "$T/release/deps" -name "*.rlib" | wc -l          # total dependency rlibs
find "$T/release/deps" -name "*.rlib" -mmin -15 | wc -l # how many this run rebuilt
```

For a **cold-dependency** reproduction, point `TMPDIR` at an empty directory
first; expect several minutes and ~124 dependency compilations.

## NON-CLAIMS

Stated so this file cannot be cited beyond what it measured.

- **Not a cross-host claim.** One host: Apple M4 Max, Darwin arm64, kernel
  25.6.0. Nothing here says another machine produces `f11f3a42…`.
- **Not a cross-time claim.** One session, ~5 minutes wide, one clock. This is
  not evidence that a build next month reproduces these bytes.
- **Not a cross-toolchain claim.** One Anubis pin, one `rustc`, one `cargo`, one
  SDK. A toolchain bump is *expected* to move the binary digest and doing so is
  not a defect.
- **Not a cold-dependency claim.** 40 dependency rlibs were reused warm; `0`
  were rebuilt. The 124-artifact cold case is carried forward, not reproduced.
- **Not a claim about `jackal-native`.** No `jackal-native` existed in the tree
  during this measurement (`ls -l jackal-native` → no such file). The digests
  here are for `anubis_run` built into a temp out-dir. The separately sealed
  release binaries have their own byte-pinned identities in
  `release/MANIFEST.sha256`.
- **Not evidence the engine is correct.** Reproducibility says repeated builds
  agree. It says nothing about whether what they agree on computes the right
  answer. A deterministic build of a wrong program is deterministically wrong.
- **Not a supply-chain claim.** Determinism does not establish that the pin, the
  `rustc`, or the 40 dependency rlibs are themselves untampered. It establishes
  that *this* toolchain, whatever it is, maps this source to these bytes
  repeatably.
- **Five builds is not a proof.** It is five observations. A nondeterminism with
  low per-build probability would not have shown up.

## Design consequence — reproducibility does not buy a cheap guard

This is counter-intuitive and will otherwise be got wrong by whoever builds the
launcher's predicted-digest guard.

Reproducibility is **necessary but not sufficient** for a predicted-digest
guard. It makes `source -> binary` a *function*; it does not make that function
*cheaply evaluable*. There is no closed form — the only evaluator is `rustc`, at
~10 s (and minutes cold). A launcher wanting an expected digest must either
recompile at every `exec`, destroying the entire purpose of the native fast
path, or read a digest recorded earlier — which **is** a build receipt. **The
design collapses into a receipt regardless of reproducibility.**

The receipt must bind the whole tuple:

```
(source_digest, anubis_pin_digest, rustc_version, target) -> binary_digest
```

Binding `source_digest` alone makes a legitimate toolchain bump
indistinguishable from tampering. That false positive is the failure that
matters: a guard that cries wolf on routine upgrades trains people to bypass it,
and a bypassed guard is worth less than no guard, because it also carries
misplaced confidence.

What reproducibility actually buys is not cheapness. It is that the receipt
becomes **third-party verifiable**: anyone holding the same tuple can rebuild
and compare, so the receipt stops being an assertion the maintainer makes about
themselves and becomes a claim someone else can refute.
