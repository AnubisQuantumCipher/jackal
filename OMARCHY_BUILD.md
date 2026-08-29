# Omarchy JACKAL — full native rebuild recipe (Linux aarch64)

Every binary in the Omarchy edition is built from source on this host; none are
committed (they are large and reproducible). This is the complete recipe to
rebuild the whole stack from a fresh clone. Times are approximate on 8 cores.

Prerequisites (system): `pacman -S z3 cmake` (z3 is *supporting only*, not the
program-evidence anchor), `cargo`/`rustc` (stable), `elan` (Lean), `python3`.

## 1. Anubis compiler  (~2 min)
    cd ~/Projects/anubis-lang
    cargo build --release -p anubis --no-default-features   # skip the Apple `prove` feature
    install -m755 target/release/anubis ~/.local/bin/anubis

## 2. Lean checkers (current)  (~40 min incl. Mathlib cache)
    cd ~/Projects/jackal/proofs/lean
    export PATH="$HOME/.elan/bin:$PATH"
    lake exe cache get                                       # prebuilt Mathlib oleans — do NOT compile Mathlib
    lake build jackal_cert_check jackal_gaussian_check jackal_int_cert_check jackal_parse_dump
    # -> proofs/lean/.lake/build/bin/{jackal_cert_check,jackal_gaussian_check,jackal_int_cert_check}

## 3. jackal-native (engine)  (~1 min; needs Z3 for its contract obligations)
    cd ~/Projects/jackal
    ANUBIS_BIN=~/.local/bin/anubis anubis build jackal_calc.anb --out /tmp/jn
    cp /tmp/jn/anubis_out ./jackal-native

## 4. Archival v1.7.0 checker (native)  (~40 min in a v1.7.0 worktree)
    git worktree add /tmp/j170 v1.7.0
    cd /tmp/j170/proofs/lean && export PATH="$HOME/.elan/bin:$PATH"
    lake exe cache get && lake build jackal_cert_check
    mkdir -p ~/jackal-omarchy-archival
    cp .lake/build/bin/jackal_cert_check ~/jackal-omarchy-archival/jackal_cert_check_v170   # expect sha d515cdc2
    git -C ~/Projects/jackal show v1.7.0:release/coverage/formal_coverage_inventory.json \
        > ~/jackal-omarchy-archival/formal_coverage_inventory_v170.json                     # expect sha 18ff7b1d
    git worktree remove /tmp/j170 --force

## 5. Approved Z3 4.15.4 (double-build, byte-reproducible)  (~6 min)
    # recipe: ~/omarchy-jackal-completion/z3build/build_recipe.sh (deterministic:
    # SOURCE_DATE_EPOCH, -ffile-prefix-map, Release, static, --build-id=none)
    URL=https://github.com/Z3Prover/z3/archive/refs/tags/z3-4.15.4.tar.gz  # archive sha dae52625
    # build TWICE in isolated dirs; both MUST equal sha b6fcd93b (else STOP: not reproducible)
    install -m700 <build>/z3 ~/.local/share/JACKAL/z3/linux-aarch64/jackal_z3_v4154

## 6. Regenerate host evidence + manifest  (seconds)
    export PATH="$HOME/.elan/bin:$PATH"
    # host-suffixed proof identities, compat floor, lean audit, archival identity/marker,
    # approved_z3 marker — see the *.linux-aarch64* files under release/evidence, release/compat.
    JACKAL_ANUBIS_COMPILER_PATH=~/.local/bin/anubis python3 -B release/tools/repin_linux.py --write
    python3 -B tools/capability_inventory.py --write
    python3 -B tools/capability_drift_gate.py --write-plugin-identity

## 7. Build the package  (~1 min)
    JACKAL_ANUBIS_COMPILER_PATH=~/.local/bin/anubis JACKAL_DIST=~/jackal-dist-linux \
    JACKAL_ARCHIVAL_DIR=~/jackal-omarchy-archival \
    JACKAL_Z3_DIR=~/.local/share/JACKAL/z3/linux-aarch64 \
      sh release/build_package_linux.sh --build
    # then update the linux-aarch64 pin block in plugins/jackel/scripts/provision_runtime.py
    # with the printed tarball sha256/size + SHA256SUMS sha + extracted size.

## 8. Install
    /bin/sh plugins/jackel/scripts/launch_mcp.sh provision --tarball \
      ~/jackal-dist-linux/jackal-v1.7.3-linux-aarch64.tar.gz
    omarchy-jackal doctor            # FUNCTIONAL from live probes

## Known-good digests
    anubis compiler   c6affa8c…   jackal-native       (rebuild)   cert_check     89e4e42d…
    gaussian_check    1f21c6b2…   int_cert_check      f2e26f50…   v170 archival  d515cdc2…
    approved Z3 4.15.4 b6fcd93b…  inventory-safe-v1 policy (frozen) 1b94350a…

## Trust-surface sign-offs
    - jackal_anubis_check_program: RESOLVED 2026-08-24 — architect (khephri.labs@proton.me)
      designated the clean-source Linux/aarch64 anubis CHECK COMPILER sha256
      6c3ae920… (double-built byte-identical, from anubis-lang commit 0ad40aaf =
      6aa6fd92 + host-honest doctor; supersedes 7cdafb30 which lacked the doctor fix,
      recipe §1). Scope: Linux/aarch64 only; macOS 0d6a8f89 not reused;
      inventory-safe-v1 policy body byte-frozen (1b94350a). Verifier anchor is
      host-aware (Darwin=0d6a8f89 preserved). Independently re-verified 2026-08-24
      (verified-program-evidence, 4 proofs, receipt 46c7b357… (D2)). Records:
      release/evidence/anubis_program_dogfood_linux_aarch64_v1.json and
      ~/omarchy-jackal-completion/evidence/compiler/SIGNOFF_linux_aarch64.json;
      finding ~/omarchy-jackal-completion/evidence/I_check_compiler_finding.json
      = RESOLVED_ARCHITECT_SIGNED_OFF.
    - Note: the overall product verdict stays _V111_PENDING — gated on the FUTURE
      sealed 49-tool package (AWAITING_SEALED_V111_PACKAGE), NOT on this
      check-compiler round, which is independently resolved. Linux x86_64
      execution remains gate-declared/unobserved (separate item).
