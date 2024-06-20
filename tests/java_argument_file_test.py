from mx._impl.support import java_argument_file


def test_no_escape():
    # TODO GR-49766 use @pytest.parameterize
    for arg in [
        "foo",
        "bar",
        "üöä",
        "[",
        "]",
        "(",
        "*",
        "-",
        "@Test",
        "\\",
    ]:
        assert java_argument_file.escape_argument(arg) == arg


def test_escape():
    # TODO GR-49766 use @pytest.parameterize
    for arg, escaped_without_quotes in [
        ("", ""),
        (" ", " "),
        ("text with space", "text with space"),
        ("text 'with' quote", "text \\'with\\' quote"),
        ('text "with" quote', 'text \\"with\\" quote'),
        ("text with \\ backslash and space", "text with \\\\ backslash and space"),
        ("'", "\\'"),
        ('"', '\\"'),
        ("\t", "\\t"),
        ("\n", "\\n"),
        ("\r", "\\r"),
        ("\f", "\\f"),
    ]:
        assert java_argument_file.escape_argument(arg) == f'"{escaped_without_quotes}"', arg


def tests():
    # TODO GR-49766 Remove function and let pytest discover tests
    test_no_escape()
    test_escape()
