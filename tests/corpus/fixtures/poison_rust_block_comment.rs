// Frozen corpus fixture: a declaration that exists only inside a block comment.
//
// Owned by tests/corpus/generate_pack_corpus.py; the programming pack corpus
// pins this file sha256.
//
// The commented-out block below is delimited by slash-star, so the phantom
// declaration line carries no comment marker of its own. The line-anchored
// declaration patterns in tools/test_exists_verify.py therefore match it on
// sight, and only the comment-blanking pass keeps it from minting a
// test-exists certificate for a symbol that does not exist. That makes this
// fixture the one case where the blanking pass, and nothing else, is what
// refuses.

/*
pub fn corpus_block_comment_phantom(value: u64) -> u64 {
    value
}
*/

pub fn corpus_rust_block_anchor(value: u64) -> u64 {
    value + 2
}
