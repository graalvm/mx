import atexit
import os
import shutil
import tempfile

from mx_codeowners import stoml_parse_rules


def test_parsing_generate_cases():
    yield (
        "smoke test",
        {
            "rule": [
                {
                    "files": "*.md",
                    "any": "user1@example.com",
                },
            ],
        },
        """
[[rule]]
files = "*.md"
any = "user1@example.com"
""",
    )

    yield (
        "indentation is ignored",
        {
            "rule": [
                {
                    "files": "*.java",
                    "any": "user2@example.com",
                }
            ],
        },
        """
        [[rule]]
        files = "*.java"
        any = "user2@example.com"
        """,
    )

    yield (
        "properties are recognized",
        {
            "rule": [
                {
                    "files": "*",
                    "any": "user@example.com",
                }
            ],
            "properties": {
                "overwrite_parent": True,
            },
        },
        """
        [properties]
        overwrite_parent = true
        [[rule]]
        files = "*"
        any = "user@example.com"
        """,
    )

    yield (
        "generic parsing",
        {
            "one": [
                {
                    "uno": "i",
                    "dos": "ii",
                },
                {
                    "tres": "iii",
                    "cuatro": "iv",
                },
            ],
            "two": {
                "cinco": "v",
            },
        },
        """
        [[one]]
        uno = "i"
        dos = "ii"

        [two]
        cinco = "v"

        [[one]]
        tres = "iii"
        cuatro = "iv"
        """,
    )


def test_parsing():
    for test_name, expected, toml_descriptor in test_parsing_generate_cases():
        print("test_parsing('" + test_name + "')")

        actual = stoml_parse_rules(toml_descriptor)
        # print("Actual: {}\nExpected: {}".format(actual, expected))

        assert actual == expected


def tests():
    test_parsing()


if __name__ == "__main__":
    tests()
