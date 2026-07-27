from app.grading.evidence import verify_quote


def test_exact_match():
    assert verify_quote("The quick fox jumps.", "Prefix. The quick fox jumps. Suffix.")


def test_quote_not_present_is_rejected():
    assert not verify_quote("This never appears.", "Prefix. The quick fox jumps. Suffix.")


def test_curly_quotes_in_quote_match_straight_quotes_in_source():
    assert verify_quote("She said, ‘hello’ to him.", "She said, 'hello' to him.")


def test_curly_double_quotes_in_source_match_straight_quotes_in_quote():
    assert verify_quote('The essay called it "a turning point".', "The essay called it “a turning point”.")


def test_extra_whitespace_in_quote_is_collapsed():
    assert verify_quote("The   quick  fox\tjumps.\n", "Prefix. The quick fox jumps. Suffix.")


def test_case_insensitive_match():
    assert verify_quote("THE QUICK FOX JUMPS.", "Prefix. the quick fox jumps. Suffix.")


def test_empty_quote_is_rejected():
    assert not verify_quote("", "Any source text at all.")


def test_whitespace_only_quote_is_rejected():
    assert not verify_quote("   \n\t", "Any source text at all.")


def test_partial_word_substring_matches_without_boundaries():
    # This is a plain substring check, not tokenized on word boundaries.
    assert verify_quote("cat", "The concatenation of ideas.")


def test_quote_longer_than_any_matching_span_is_rejected():
    assert not verify_quote(
        "The quick fox jumps over the fence.",
        "The quick fox jumps. That is all.",
    )


def test_nfkc_ligature_in_source_matches_plain_letters_in_quote():
    # U+FB01 LATIN SMALL LIGATURE FI normalizes (NFKC) to "fi".
    assert verify_quote("a fi pattern", "a ﬁ pattern")
