# Shadow record → public promotion (v1.7.0)

Every other file in this directory is the frozen historical record of the
non-authoritative shadow mission (terminal state `READY_FOR_TRUST_SIGNOFF`,
branch `feat/bound-step-composition-v1.7` @ `1c2702ecb13ae6d59c039f42d9e313a5ede8ab56`,
PR #3). Nothing in it was rewritten after the fact.

The architect authorized the public promotion on 2026-08-17
(`JACKAL_V170_COMPLETION_PROMOTION_MISSION.md`, sha256
`051c14298a69624c6a00e394bd3fca342a993773f4369b98ee57ce681da9fb25`), and the
proposal in `PROMOTION_PROPOSAL.md` was carried out on branch
`feat/v170-public-promotion` (base = the shadow commit) with one recorded
design divergence:

- The public emitter is the identity-pinned untrusted producer
  `tools/int_cert_producer.py` (the promoted shadow mirror), not a new
  in-engine `integrate-bound-cert` command — the same architecture as the
  gaussian and seven `*_rat` formal lanes. The trust story is unchanged in
  both shapes (the proved compiled checker `jackal_int_cert_check` carries
  the trust; emitter faithfulness stays a disclosed testing residual), and
  this shape leaves the sealed evaluator binary byte-identical.

Where the promoted surfaces live now:

| shadow object | public object |
|---|---|
| `proofs/lean/JackalIv/Shadow*.lean` | `proofs/lean/JackalIv/IntCert*.lean` (namespace `JackalIv.IntCert`) |
| `jackal-int-cert shadow-v1` / `jackal-iv-bound-step-shadow-v1` / `research-shadow` | `jackal-int-cert v1` / `jackal-iv-bound-step-v1` / `bounded` |
| `lake env lean --run` driver | compiled `[[lean_exe]] jackal_int_cert_check` |
| `tools/bound_step_shadow_producer.py` | `tools/int_cert_producer.py` |
| `tests/bound_step_shadow_{test,aba,differential}.py` | `tests/int_cert_{matrix_test,aba_test,differential}.py` |
| `evidence/shadow_matrix.json` etc. (frozen here) | `release/evidence/int_cert_{matrix,aba,differential}.json` |
| six "bound_step … remains OPEN" surfaces | closed for the certificate lane; source→native refinement remains OPEN |

The public lane's gates, receipts, and release wave are recorded in the
v1.7.0 release notes and `release/evidence/release_review_v170.json`.
