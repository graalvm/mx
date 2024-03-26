import contextlib
import json
import tempfile
from pathlib import Path

import mx_benchmark


class JsonTestRule(mx_benchmark.JsonBaseRule):
    file: Path

    def __init__(self, file: Path, replacement, keys):
        super().__init__(replacement, keys)
        self.file = file

    def getJsonFiles(self, text):
        return [self.file]


@contextlib.contextmanager
def get_temp_file(contents: str, name: str = None) -> Path:
    """
    Context manager to create a temporary file with the given contents.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        filepath = Path(tmp_dir) / (name or "tmp_file")
        filepath.write_text(contents)
        yield filepath


TEST_JSON1 = json.dumps(
    {
        "test": {
            "abc": "Text",
            "float": 1.23,
        },
        "key": 100,
    }
)


def tests():
    with get_temp_file(TEST_JSON1, "test1.json") as tmp:
        rule = JsonTestRule(
            tmp,
            {
                # Tests nested access
                "foo": ("<test.abc>", str),
                "bar": ("<key>", int),
                # Tests multiple lookups
                "baz": ("<test.float>, <key>", str),
            },
            ["test.abc", "key", "test.float"],
        )
        parsed = rule.parseResults("")
        assert len(parsed) == 1
        assert parsed[0] == {
            "test.abc": "Text",
            "test.float": "1.23",
            "key": "100",
        }

        datapoints = rule.parse("")
        assert len(datapoints) == 1
        assert datapoints[0] == {
            "foo": "Text",
            "bar": 100,
            "baz": "1.23, 100",
        }
