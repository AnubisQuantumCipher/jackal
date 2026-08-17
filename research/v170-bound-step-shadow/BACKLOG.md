# Adjacent findings backlog — v1.7 shadow mission

**Status: research-shadow.  Findings only; no objective switching occurred.**
Pointers are against v1.6.0 = 19b763e plus this branch's shadow additions.

1. **ℚ arithmetic does not kernel-reduce under `decide` at this Mathlib
   revision.**  Even `example : (decide ((1:ℚ) + 2 ≤ 4)) = true := by decide`
   fails (Field ℚ instance tower blocks whnf).  Consequence: no existing
   in-kernel fixture computes `padLoQ`/`padHiQ` (CertCheck.lean:513-569's
   twins use var/neg nodes only), so kernel-`decide` coverage of the padded
   arithmetic arms is impossible without `Rat`-native instance work or
   `Decidable`-instance shortcuts.  The shadow fixtures use build-time
   `#guard` instead (ShadowCertFixtures.lean header note).  Candidate
   upstream fix: restate checker comparisons over `Rat.blt/beq` directly.
2. **`Cert.splitOn` is per-character non-tail-recursive**
   (CertCodec.lean:288-292): the `lean --run` interpreter overflows at
   ~10k frames, i.e. on any input beyond ~10 kB.  The compiled
   `jackal_cert_check` is unaffected (native stack + IR), but any future
   interpreter-driven tooling (or very large certificates fed to a
   constrained runner) should switch to an accumulator/`String.splitOn`
   form.  The shadow codec works around it (ShadowCertCodec.lean:parseIntCert
   uses core `String.splitOn`; embedded blocks go to `Cert.parseCertLines`
   directly).
3. **`Deriv.D`'s power rule emits `0 * b^(c-1)` sub-terms whose evaluability
   fails at `b = 0` for `c = 1`** (Deriv.lean:69: `.pow b (.num (c-1) t)`
   with c−1 = 0 is fine, but c−1 = −1 arises from D² of `x^2`'s inner
   `x^1`), so unsimplified D-chains of integer powers refuse taylor4 through
   0-crossing domains even though the engine's `simplify_bound`-interleaved
   chain evaluates.  Documented as shadow divergence D4; closing it needs
   either a mechanized `Lower.lower` interleave in the chain binding
   (`lower_preserves_defined` direction work) or a smarter mirror
   differentiator with a proved sem/DefinedOn correspondence.
4. **`tests/parser_differential.py` forces `JACKAL_FORCE_SOURCE=1`**
   (parser_differential.py:125), so it recompiles the engine from source via
   the pinned Anubis compiler; when the compile cache is cold AND another
   engine job runs concurrently, wall time explodes.  Fine serially; worth a
   `--reuse-native` escape once parse-dump lands in a resealed binary
   (comment at :122-124 anticipates this).
5. **Producer-side sharpness observation (no action needed):** the engine's
   final `iv_out` pad is magnitude-relative, so for large-magnitude
   integrals (|∫| ≈ 1e12) the released width is dominated by the pad
   (~4e-3), making tolerances below `2·ε·|∫|` structurally unmeetable —
   the R6 refusal fixture encodes this.  Engine behavior is identical
   (jackal_calc.anb:4750-4754); worth a doc note in GETTING-STARTED if
   users hit `tolerance-unmet` on large-magnitude integrals.
6. **`String.mk` is deprecated at this toolchain**; all shadow modules now
   use `String.ofList` (fixed during the mission; nothing remains).
