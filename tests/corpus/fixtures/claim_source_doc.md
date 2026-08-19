# Frozen corpus fixture: a document that cites tests

Owned by `tests/corpus/generate_pack_corpus.py`; the programming pack corpus
pins this file's sha256. The prose below is fixture data, not a claim about the
JACKAL engine.

## A citation that resolves

The fixture module declares a Python helper named corpus_python_target.

## A citation that does not resolve

The fixture module declares a Python helper named corpus_absent_from_fixture.

That second sentence is deliberately false: no such declaration exists in
`tests/corpus/fixtures/genuine_python_decls.py`. It is the dangling-citation
case, and the point of the fixture is that resolving a citation and validating
one are different operations. `claim-cites-test` performs only the first, and
`tools/test_exists_verify.py` refuses when even that fails.
