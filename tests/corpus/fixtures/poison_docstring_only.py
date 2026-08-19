"""Frozen corpus fixture: a declaration that exists only inside a docstring.

This module's prose names `corpus_docstring_phantom`, and shows it in a shape
that a naive line-oriented scanner reads as a declaration:

    def corpus_docstring_phantom(value):
        return value

Nothing in this module declares it. A `test-exists` certificate minted for
`corpus_docstring_phantom` would carry assurance ceiling `exact` for a symbol
that does not exist, which is exactly the laundering the checker must refuse.

`corpus_docstring_anchor` below is a real declaration in the same file, so the
refusal above cannot be explained by a checker that refuses this file wholesale.
"""


def corpus_docstring_anchor(value):
    """Genuine declaration: the in-file control for the phantom refusal."""
    return value
