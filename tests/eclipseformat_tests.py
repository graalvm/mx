import importlib
import os
import pathlib
import sys

from contextlib import contextmanager
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

orig_mx = importlib.import_module("mx._impl.mx")
orig_mx_ide_eclipse = importlib.import_module("mx._impl.mx_ide_eclipse")


@contextmanager
def patch_attr(module, name, value):
    previous = getattr(module, name)
    setattr(module, name, value)
    try:
        yield value
    finally:
        setattr(module, name, previous)


def test_eclipseinit_and_format_files_uses_temporary_workspace():
    observed = {}
    calls = []

    def fake_eclipseinit(*args, **kwargs):
        calls.append((args, kwargs))
        return "/tmp/reused-workspace"

    class FakeLaunch:
        def __init__(self, eclipse_exe):
            assert eclipse_exe == "/path/to/eclipse"
            self.eclipse_ini = "/tmp/eclipse.ini"
            self.configuration_dir = "/tmp/eclipse-configuration"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_format_files(eclipse_exe, wsroot, eclipse_ini, eclipse_configuration, config, files):
        observed["eclipse_exe"] = eclipse_exe
        observed["wsroot"] = wsroot
        observed["eclipse_ini"] = eclipse_ini
        observed["eclipse_configuration"] = eclipse_configuration
        observed["config"] = config
        observed["files"] = files
        assert os.path.isdir(wsroot)
        assert wsroot != "/tmp/reused-workspace"
        assert os.path.basename(wsroot).startswith("mx-eclipse-workspace-")

    with patch_attr(orig_mx_ide_eclipse, "eclipseinit", fake_eclipseinit), patch_attr(
        orig_mx_ide_eclipse, "_TempEclipseLaunch", FakeLaunch
    ), patch_attr(orig_mx_ide_eclipse, "_format_files", fake_format_files):
        orig_mx_ide_eclipse.eclipseinit_and_format_files("/path/to/eclipse", "/tmp/formatter.cfg", ["A.java"])

    assert calls == [(([],), {"buildProcessorJars": False, "doFsckProjects": False})]
    assert observed["eclipse_exe"] == "/path/to/eclipse"
    assert observed["eclipse_ini"] == "/tmp/eclipse.ini"
    assert observed["eclipse_configuration"] == "/tmp/eclipse-configuration"
    assert observed["config"] == "/tmp/formatter.cfg"
    assert observed["files"] == ["A.java"]
    assert not os.path.exists(observed["wsroot"])


def test_format_files_suppresses_launcher_errors():
    observed = {}

    def fake_run(cmd, *args, **kwargs):
        observed["cmd"] = cmd
        return 0

    with patch_attr(orig_mx, "run", fake_run), patch_attr(
        orig_mx, "get_tools_jdk", lambda purpose=None: SimpleNamespace(java="/path/to/java")
    ):
        orig_mx_ide_eclipse._format_files(
            "/path/to/eclipse",
            "/tmp/workspace",
            "/tmp/eclipse.ini",
            "/tmp/eclipse-configuration",
            "/tmp/formatter.cfg",
            ["A.java"],
        )

    cmd = observed["cmd"]
    assert cmd[0] == "/path/to/eclipse"
    assert "--launcher.suppressErrors" in cmd
    assert cmd[cmd.index("--launcher.ini") + 1] == "/tmp/eclipse.ini"
    assert cmd[cmd.index("-configuration") + 1] == "/tmp/eclipse-configuration"
    assert cmd[cmd.index("-data") + 1] == "/tmp/workspace"
    assert cmd[cmd.index("-vm") + 1] == "/path/to/java"


def tests():
    test_eclipseinit_and_format_files_uses_temporary_workspace()
    test_format_files_suppresses_launcher_errors()


if __name__ == "__main__":
    tests()
