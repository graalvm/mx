import io
import os
import sys
import tempfile

from contextlib import contextmanager, redirect_stderr, redirect_stdout

from mx._impl import mx as orig_mx


@contextmanager
def chdir(path):
    previous = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


@contextmanager
def mx_monkeypatch(name, value):
    previous = getattr(orig_mx, name)
    setattr(orig_mx, name, value)
    try:
        yield value
    finally:
        setattr(orig_mx, name, previous)


@contextmanager
def mx_opt_patch(**kwargs):
    sentinel = object()
    previous = {name: getattr(orig_mx._opts, name, sentinel) for name in kwargs}
    for name, value in kwargs.items():
        setattr(orig_mx._opts, name, value)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is sentinel:
                delattr(orig_mx._opts, name)
            else:
                setattr(orig_mx._opts, name, value)


@contextmanager
def argv_patch(args):
    previous_argv = sys.argv[:]
    sentinel = object()
    previous_initial = getattr(orig_mx._argParser, "initialCommandAndArgs", sentinel)
    sys.argv = args[:]
    command_index = next((i for i, arg in enumerate(args[1:], start=1) if not arg.startswith("-")), len(args))
    orig_mx._argParser.initialCommandAndArgs = args[command_index:]
    try:
        yield
    finally:
        sys.argv = previous_argv
        if previous_initial is sentinel:
            delattr(orig_mx._argParser, "initialCommandAndArgs")
        else:
            orig_mx._argParser.initialCommandAndArgs = previous_initial


def _write_suite(repo_root, suite_relpath, suite_name, imported_suites=None):
    imported_suites = imported_suites or []
    suite_dir = os.path.join(repo_root, suite_relpath)
    mx_dir = os.path.join(suite_dir, f"mx.{suite_name}")
    os.makedirs(mx_dir, exist_ok=True)
    imports = ""
    if imported_suites:
        imports = """
    "imports": {
        "suites": [
%s
        ]
    },
""" % ",\n".join([f'            {{"name": "{suite}", "subdir": True}}' for suite in imported_suites])
    with open(os.path.join(mx_dir, "suite.py"), "w") as fp:
        fp.write(
            """suite = {
    "mxversion": "7.0.0",
    "name": "%s",%s
}
"""
            % (suite_name, imports)
        )
    return suite_dir


def _create_multi_suite_repo():
    tmpdir = tempfile.TemporaryDirectory()
    repo_root = tmpdir.name
    open(os.path.join(repo_root, ".mx_vcs_root"), "w").close()
    compiler_dir = _write_suite(repo_root, "compiler", "compiler", ["sdk"])
    sdk_dir = _write_suite(repo_root, "sdk", "sdk")
    tools_dir = _write_suite(repo_root, "tools", "tools", ["sdk"])
    truffle_dir = _write_suite(repo_root, "truffle", "truffle", ["sdk"])
    return tmpdir, repo_root, {
        "compiler": compiler_dir,
        "sdk": sdk_dir,
        "tools": tools_dir,
        "truffle": truffle_dir,
    }


def _assert_abort(func, expected_message):
    stderr = io.StringIO()
    try:
        with redirect_stderr(stderr):
            func()
    except SystemExit as exc:
        assert exc.code == 1
    else:
        assert False, "expected mx.abort"
    assert expected_message in stderr.getvalue(), stderr.getvalue()


def test_discover_repo_suites():
    tmpdir, repo_root, _ = _create_multi_suite_repo()
    try:
        discovery = orig_mx._discover_repo_suites(repo_root)
        assert discovery is not None
        assert [suite.name for suite in discovery.suites] == ["compiler", "sdk", "tools", "truffle"]
        assert discovery.local_edges == [("compiler", "sdk"), ("tools", "sdk"), ("truffle", "sdk")]
        assert [suite.name for suite in discovery.root_suites] == ["compiler", "tools", "truffle"]
    finally:
        tmpdir.cleanup()


def test_show_suites_without_primary_suite():
    tmpdir, repo_root, _ = _create_multi_suite_repo()
    try:
        stdout = io.StringIO()
        with chdir(repo_root), mx_monkeypatch("_primary_suite", None), redirect_stdout(stdout):
            orig_mx.show_suites([])
        output = stdout.getvalue()
        assert "Suites:" not in output
        assert "Dependencies:" not in output
        assert "> compiler > sdk" in output
        assert "> tools > sdk" in output
        assert "  sdk" in output
        assert "sdk -> -" not in output
        assert "compiler > sdk" in output
        assert "> truffle" in output
    finally:
        tmpdir.cleanup()


def test_build_without_primary_suite_shows_all_suites_hint():
    tmpdir, repo_root, _ = _create_multi_suite_repo()
    try:
        with chdir(repo_root), mx_monkeypatch("_primary_suite", None), mx_opt_patch(all_suites=False, root_suites=False):
            _assert_abort(lambda: orig_mx.build([]), "Use `mx --root-suites build` to run for root suites")
    finally:
        tmpdir.cleanup()


def test_root_suites_dispatches_once_per_root_suite():
    tmpdir, repo_root, suite_dirs = _create_multi_suite_repo()
    try:
        discovery = orig_mx._discover_repo_suites(repo_root)
        commands = []

        def fake_run(cmd, **kwargs):
            commands.append((cmd, kwargs))
            return 0

        with chdir(repo_root), mx_monkeypatch("_primary_suite", None), mx_monkeypatch("run", fake_run), argv_patch(["mx", "--root-suites", "build", "--dry-run"]), mx_opt_patch(all_suites=False, root_suites=True, primary=False, specific_suites=[], primary_suite_path=None):
            retcode = orig_mx._run_command_for_repo_suites("build", discovery, root_suites_only=True)

        assert retcode == 0
        assert len(commands) == 3
        invoked_primary_suites = [cmd[cmd.index("-p") + 1] for cmd, _ in commands]
        assert invoked_primary_suites == [suite_dirs["compiler"], suite_dirs["tools"], suite_dirs["truffle"]]
        for cmd, kwargs in commands:
            assert "--all-suites" not in cmd
            assert "--root-suites" not in cmd
            assert "build" in cmd
            assert "--dry-run" in cmd
            assert cmd.index("-p") < cmd.index("build")
            assert kwargs["cwd"] in invoked_primary_suites
    finally:
        tmpdir.cleanup()


def test_all_suites_dispatches_once_per_discovered_suite():
    tmpdir, repo_root, suite_dirs = _create_multi_suite_repo()
    try:
        discovery = orig_mx._discover_repo_suites(repo_root)
        commands = []

        def fake_run(cmd, **kwargs):
            commands.append((cmd, kwargs))
            return 0

        with chdir(repo_root), mx_monkeypatch("_primary_suite", None), mx_monkeypatch("run", fake_run), argv_patch(["mx", "--all-suites", "build", "--dry-run"]), mx_opt_patch(all_suites=True, root_suites=False, primary=False, specific_suites=[], primary_suite_path=None):
            retcode = orig_mx._run_command_for_repo_suites("build", discovery, root_suites_only=False)

        assert retcode == 0
        assert len(commands) == 4
        invoked_primary_suites = [cmd[cmd.index("-p") + 1] for cmd, _ in commands]
        assert invoked_primary_suites == [suite_dirs["compiler"], suite_dirs["sdk"], suite_dirs["tools"], suite_dirs["truffle"]]
        for cmd, kwargs in commands:
            assert "--all-suites" not in cmd
            assert "--root-suites" not in cmd
            assert "build" in cmd
            assert "--dry-run" in cmd
            assert cmd.index("-p") < cmd.index("build")
            assert kwargs["cwd"] in invoked_primary_suites
    finally:
        tmpdir.cleanup()


def test_multi_suite_flags_rejected_with_active_primary_suite():
    with mx_monkeypatch("_primary_suite", object()), mx_opt_patch(all_suites=True, root_suites=False):
        _assert_abort(lambda: orig_mx.build([]), "`--all-suites` and `--root-suites` cannot be used when a primary suite is already active")
    with mx_monkeypatch("_primary_suite", object()), mx_opt_patch(all_suites=False, root_suites=True):
        _assert_abort(lambda: orig_mx.build([]), "`--all-suites` and `--root-suites` cannot be used when a primary suite is already active")


def tests():
    test_discover_repo_suites()
    test_show_suites_without_primary_suite()
    test_build_without_primary_suite_shows_all_suites_hint()
    test_root_suites_dispatches_once_per_root_suite()
    test_all_suites_dispatches_once_per_discovered_suite()
    test_multi_suite_flags_rejected_with_active_primary_suite()
