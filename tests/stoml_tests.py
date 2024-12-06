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
        "full-line comments are ignored",
        {
            "rule": [
                {
                    "files": "*.sh",
                    "any": "shell@example.com",
                },
            ],
        },
        """
        # This is a top-level comment
        [[rule]]
        files = "*.sh"
        # This user really cares about proper shell scripts :-)
        any = "shell@example.com"
        """,
    )

    yield (
        "comment at line end is ignored",
        {
            "rule": [
                {
                    "files": "*.scala",
                    "any": "sc@example.com",
                },
            ],
        },
        """
        [[rule]]
        files = "*.scala" # Match all Scala sources
        any = "sc@example.com"
        """,
    )

    yield (
        "string with comment is accepted",
        {
            "rule": [
                {
                    "files": "*#",
                    "any": "cleaner@example.com",
                },
            ],
        },
        """
        [[rule]]
        files = "*#" # Hopefully no such files
        any = "cleaner@example.com"
        """,
    )

    yield (
        "windows line endings",
        {
            "rule": [
                {
                    "files": "*.win",
                    "any": "win@example.com",
                },
            ],
        },
        """[[rule]]\r\nfiles = "*.win"\r\nany = "win@example.com"\r\n""",
    )

    yield (
        "mac line endings",
        {
            "rule": [
                {
                    "files": "*.win",
                    "any": "win@example.com",
                },
            ],
        },
        """[[rule]]\rfiles = "*.win"\rany = "win@example.com"\r""",
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

    yield (
        "arrays",
        {
            "rule": [
                {
                    "files": ["A.java", "B.java"],
                }
            ]
        },
        """
        [[rule]]
        files = [
            "A.java",
            "B.java",
        ]
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
