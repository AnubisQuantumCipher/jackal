// Frozen corpus fixture: a declaration that exists only inside a line comment.
//
// Owned by tests/corpus/generate_pack_corpus.py; the programming pack corpus
// pins this file sha256.
//
// The commented-out block below names corpus_line_comment_phantom in
// declaration shape, and nothing in this file declares it:
//
// pub fn corpus_line_comment_phantom(value: u64) -> u64 {
//     value
// }
//
// corpus_rust_comment_anchor is a genuine declaration in the same file, so a
// refusal for the phantom cannot be explained by a checker that refuses every
// symbol in this file.

pub fn corpus_rust_comment_anchor(value: u64) -> u64 {
    value + 1
}
