// Frozen corpus fixture: a declaration that exists only inside a raw string.
//
// Owned by tests/corpus/generate_pack_corpus.py; the programming pack corpus
// pins this file sha256.
//
// The raw literal below holds text shaped exactly like a Rust declaration of
// corpus_raw_string_phantom, and nothing in this file declares that symbol.
// tools/test_exists_verify.py blanks string-literal content before scanning for
// declaration shapes, so the phantom must be refused while the genuine anchor
// in this same file is still found. Without the blanking pass a test-exists
// certificate could be minted at assurance ceiling exact for a symbol that
// never existed.

pub fn corpus_rust_raw_anchor(value: u64) -> u64 {
    let template = r"
pub fn corpus_raw_string_phantom(value: u64) -> u64 {
    value
}
";
    value + (template.len() as u64)
}
