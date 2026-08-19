"""Frozen corpus fixture: genuine Python declarations.

Owned by `tests/corpus/generate_pack_corpus.py`. The programming pack corpus
pins this file's sha256, so any edit invalidates the frozen corpus and
`generate_pack_corpus.py --self-check` reports the mismatch by name.

Nothing here is executed by any suite. The file exists so that a `test-exists`
certificate can be checked against declarations whose line numbers are derived
by `tools/test_exists_verify.py:find_declarations`, never hand-written.
"""


def corpus_python_target(value):
    """Single genuine declaration: the positive `test-exists` case."""
    return value + 1


def corpus_python_neighbour(value):
    """A second, differently named declaration.

    Its presence keeps the positive case honest: a scanner that reported every
    `def` in the file would report a declaration_count of 4, not 1.
    """
    return value - 1


def corpus_python_twice(value):
    """First of two declarations sharing this name; declaration_count is 2."""
    return value * 2


class CorpusPythonHolder:
    """Holder whose method re-declares `corpus_python_twice`."""

    def corpus_python_twice(self, value):
        """Second declaration of the shared name."""
        return value * 3
