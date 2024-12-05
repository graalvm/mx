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
TEST_JSON2 = json.dumps(
    {
        "benchmark": {
            "name": "hello-world",
            "label.with.periods": "Foo",
        },
        "latency": [
            {"percentile": 90, "value": 1.0},
            {"percentile": 99, "value": 2.0},
        ],
    }
)


def test_json_base_rule():
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


def test_json_array_rule():
    with get_temp_file(TEST_JSON2, "test2.json") as tmp:
        rule = mx_benchmark.JsonArrayFixedFileRule(
            tmp,
            {
                # Test nested access with custom ``indexer_str`` set to "__"
                "benchmark": ("<benchmark__name>", str),
                "dummy": ("<benchmark__label.with.periods>", str),
                # Test array access
                "latency": ("<latency__value>", float),
                "percentile": ("<latency__percentile>", int),
            },
            ["benchmark__name", "benchmark__label.with.periods", "latency__value", "latency__percentile"],
            indexer_str="__",
        )

        # Test ``resolve_key`` method
        with open(tmp) as f:
            json_content = json.load(f)
            benchmark_values = rule.resolve_key(json_content, "benchmark__name")
            assert benchmark_values == ["hello-world"]
            dummy_values = rule.resolve_key(json_content, "benchmark__label.with.periods")
            assert dummy_values == ["Foo"]
            latency_values = rule.resolve_key(json_content, "latency__value")
            assert latency_values == ["1.0", "2.0"]
            percentile_values = rule.resolve_key(json_content, "latency__percentile")
            assert percentile_values == ["90", "99"]

        # Test ``parseResults`` method
        parsed = rule.parseResults("")
        assert parsed == [
            {
                "benchmark__name": "hello-world",
                "benchmark__label.with.periods": "Foo",
                "latency__value": "1.0",
                "latency__percentile": "90",
            },
            {
                "benchmark__name": "hello-world",
                "benchmark__label.with.periods": "Foo",
                "latency__value": "2.0",
                "latency__percentile": "99",
            },
        ]

        # Test ``parse`` method
        datapoints = rule.parse("")
        assert datapoints == [
            {
                "benchmark": "hello-world",
                "dummy": "Foo",
                "latency": 1.0,
                "percentile": 90,
            },
            {
                "benchmark": "hello-world",
                "dummy": "Foo",
                "latency": 2.0,
                "percentile": 99,
            },
        ]


def tests():
    test_json_base_rule()
    test_json_array_rule()
