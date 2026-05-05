import importlib
import os
import pathlib
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

orig_mx_native = importlib.import_module("mx._impl.mx_native")


def test_source_discovery_ignores_file_names():
    with tempfile.TemporaryDirectory() as tmpdir:
        source_dir = os.path.join(tmpdir, "src")
        os.makedirs(source_dir)
        pathlib.Path(source_dir, ".DS_Store").touch()
        pathlib.Path(source_dir, ".swp").touch()
        pathlib.Path(source_dir, "library.c").touch()
        pathlib.Path(source_dir, "notes.txt").touch()

        project = SimpleNamespace(dir=tmpdir, source_dirs=lambda: [source_dir])
        source = orig_mx_native.NinjaProject._source.init(project)

        assert "" not in source["files"]
        assert source["files"][".c"] == [os.path.join("src", "library.c")]
        assert source["files"][".txt"] == [os.path.join("src", "notes.txt")]


def test_unsupported_default_native_sources_reports_paths():
    source_files = {
        ".c": ["src/library.c"],
        ".txt": ["src/notes.txt"],
        "": ["src/README"],
    }

    assert orig_mx_native._unsupported_default_native_source_files(source_files) == [
        "src/README",
        "src/notes.txt",
    ]


def test_unsupported_default_native_sources_error_message_reports_paths():
    class AbortRaised(Exception):
        pass

    def abort(message):
        raise AbortRaised(message)

    previous_abort = orig_mx_native.mx.abort
    orig_mx_native.mx.abort = abort
    try:
        project = SimpleNamespace(_source={"files": {"": ["src/README"], ".txt": ["src/notes.txt"]}})
        try:
            orig_mx_native.DefaultNativeProject.generate_manifest_for_task(project, None, None, None)
        except AbortRaised as e:
            assert str(e) == "Unsupported source files for default native project: src/README, src/notes.txt"
        else:
            assert False, "expected unsupported source files to abort"
    finally:
        orig_mx_native.mx.abort = previous_abort


def tests():
    test_source_discovery_ignores_file_names()
    test_unsupported_default_native_sources_reports_paths()
    test_unsupported_default_native_sources_error_message_reports_paths()
