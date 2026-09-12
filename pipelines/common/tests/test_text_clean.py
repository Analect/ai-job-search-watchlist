"""US8 regression: conditional double-encoding unescape in clean_description().

Two invariants:
1. A doubly-encoded fixture is correctly unescaped to real HTML.
2. An already-correct HTML fixture is left byte-for-byte unchanged.
"""

from pipelines.common.text_clean import clean_description


def test_doubly_encoded_is_unescaped():
    double_encoded = (
        "&lt;h1&gt;Senior Engineer&lt;/h1&gt;"
        "&lt;p&gt;Join our &lt;strong&gt;team&lt;/strong&gt;.&lt;/p&gt;"
    )
    result = clean_description(double_encoded)
    assert result == (
        "<h1>Senior Engineer</h1>"
        "<p>Join our <strong>team</strong>.</p>"
    ), f"Expected unescaped HTML, got: {result!r}"


def test_already_correct_html_unchanged():
    correct_html = (
        "<h1>Senior Engineer</h1>"
        "<p>Join our <strong>team</strong>. Salary &amp; benefits included.</p>"
    )
    result = clean_description(correct_html)
    assert result == correct_html, (
        f"Already-correct HTML must not be altered. Got: {result!r}"
    )


def test_empty_input():
    assert clean_description(None) is None
    assert clean_description("") == ""


def test_idempotent():
    double_encoded = "&lt;p&gt;Hello&lt;/p&gt;"
    first_pass = clean_description(double_encoded)
    second_pass = clean_description(first_pass)
    assert first_pass == second_pass, (
        "clean_description must be idempotent — second pass must equal first pass"
    )
