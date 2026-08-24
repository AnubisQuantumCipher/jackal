# Spacecraft finite-burn interval certificate

> **Legacy v1 audit import:** the supplied v1 evidence is preserved byte-for-byte
> under `evidence/legacy-v1/`. It is historical rigorous interval evidence, not
> a current formal-bounded release. The v2 checker-backed lane described in the
> repository design is not complete until its Lean proof and release gates pass.

This directory contains a full-box, validated interval analysis of the
finite-duration periapsis burn challenge.  The decisive computation uses exact
integer dyadic intervals and a checked Picard self-map at every ODE step.  It
does not use a nominal trajectory or sampling as proof.

Run the evidence chain from the repository root:

```sh
/opt/homebrew/bin/python3 -B spacecraft_burn_cert/certify.py \
  --output spacecraft_burn_cert/evidence/baseline_receipt.json

/opt/homebrew/bin/python3 -B spacecraft_burn_cert/verify_receipt.py \
  spacecraft_burn_cert/evidence/baseline_receipt.json \
  --source spacecraft_burn_cert/certify.py

/opt/homebrew/bin/python3 -B spacecraft_burn_cert/validate.py \
  --output spacecraft_burn_cert/evidence/instrument_validation.json

/opt/homebrew/bin/python3 -B spacecraft_burn_cert/mutation_aba.py \
  --output spacecraft_burn_cert/evidence/mutation_aba.json

/opt/homebrew/bin/python3 -B -m unittest discover \
  -s spacecraft_burn_cert/tests -v
```

The result and its assurance boundary are in [REPORT.md](REPORT.md).  The
independent verifier deliberately imports no certifier code.  The JACKAL
receipt is complementary evidence for one pure-rational square-root step; it
does not certify the nonlinear ODE or promote the overall result to
`formal-bounded`.
