import importlib
import pathlib
import sys
import tempfile
from io import StringIO
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

mx_ide_intellij = importlib.import_module("mx._impl.mx_ide_intellij")


def test_suite_import_order_handles_diamond_imports():
    suites = {name: SimpleNamespace(name=name) for name in ("a", "b", "c", "d")}
    imports = {
        "a": ["b", "c"],
        "b": ["d"],
        "c": ["d"],
        "d": [],
    }

    order = mx_ide_intellij._intellij_suite_import_order("a", suites, imports)
    positions = {suite.name: index for index, suite in enumerate(order)}

    assert positions["d"] < positions["b"] < positions["a"]
    assert positions["d"] < positions["c"] < positions["a"]


def test_formatter_override_warning_contains_values_and_provenance():
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = pathlib.Path(temp_dir)
        default_source = temp_path / "default.prefs"
        importee_source = temp_path / "importee.prefs"
        importer_source = temp_path / "importer.prefs"
        property_name = "org.eclipse.jdt.core.formatter.alignment_for_selector_in_method_invocation"
        default_source.write_text(f"{property_name}=default\n", encoding="utf-8")
        importee_source.write_text(f"{property_name}=old\n", encoding="utf-8")
        importer_source.write_text(f"{property_name}=new\n", encoding="utf-8")

        importee = SimpleNamespace(name="importee", dir=temp_dir)
        importer = SimpleNamespace(name="importer", dir=temp_dir)
        output = StringIO()
        warnings = []
        mx_ide_intellij._intellij_write_eclipse_settings(
            output,
            [(None, str(default_source)), (importee, str(importee_source)), (importer, str(importer_source))],
            ("org.eclipse.jdt.core.formatter.",),
            {"importer": ["importee"]},
            warnings.append,
        )

        assert len(warnings) == 1
        warning = warnings[0]
        assert property_name in warning
        assert "old value 'old'" in warning
        assert "new value 'new'" in warning
        assert "importee (importee.prefs)" in warning
        assert "importer (importer.prefs)" in warning
        assert f"{property_name}=new" in output.getvalue()

        importer_source.write_text(f"{property_name}=old\n", encoding="utf-8")
        warnings.clear()
        mx_ide_intellij._intellij_write_eclipse_settings(
            StringIO(),
            [(importee, str(importee_source)), (importer, str(importer_source))],
            ("org.eclipse.jdt.core.formatter.",),
            {"importer": ["importee"]},
            warnings.append,
        )
        assert not warnings


def test_formatter_override_warning_handles_diamond_imports():
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = pathlib.Path(temp_dir)
        property_name = "org.eclipse.jdt.core.formatter.test_property"
        values = {"d": "d", "b": "b", "c": "c", "a": "a"}
        suites = {}
        sources = []
        for name, value in values.items():
            source = temp_path / f"{name}.prefs"
            source.write_text(f"{property_name}={value}\n", encoding="utf-8")
            suites[name] = SimpleNamespace(name=name, dir=temp_dir)
            sources.append((suites[name], str(source)))

        warnings = []
        mx_ide_intellij._intellij_write_eclipse_settings(
            StringIO(),
            sources,
            ("org.eclipse.jdt.core.formatter.",),
            {"a": ["b", "c"], "b": ["d"], "c": ["d"]},
            warnings.append,
        )

        assert len(warnings) == 3
        assert sum("old value 'd'" in warning for warning in warnings) == 2
        assert any("old value 'c'" in warning and "new value 'a'" in warning for warning in warnings)


def tests():
    test_suite_import_order_handles_diamond_imports()
    test_formatter_override_warning_contains_values_and_provenance()
    test_formatter_override_warning_handles_diamond_imports()


if __name__ == "__main__":
    tests()
