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


def _create_workspace_with_subrepos():
    tmpdir = tempfile.TemporaryDirectory()
    workspace_root = tmpdir.name
    repo_a = os.path.join(workspace_root, "repo-a")
    repo_b = os.path.join(workspace_root, "repo-b")
    os.makedirs(repo_a, exist_ok=True)
    os.makedirs(repo_b, exist_ok=True)
    open(os.path.join(repo_a, ".mx_vcs_root"), "w").close()
    open(os.path.join(repo_b, ".mx_vcs_root"), "w").close()
    compiler_dir = _write_suite(repo_a, "compiler", "compiler", ["sdk"])
    sdk_dir = _write_suite(repo_a, "sdk", "sdk")
    tools_dir = _write_suite(repo_b, "tools", "tools", ["sdk"])
    truffle_dir = _write_suite(repo_b, "truffle", "truffle", ["sdk"])
    return tmpdir, workspace_root, {
        "repo-a": repo_a,
        "repo-b": repo_b,
    }, {
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


def test_discover_repo_suites_from_workspace_root():
    tmpdir, workspace_root, repo_dirs, suite_dirs = _create_workspace_with_subrepos()
    try:
        discovery = orig_mx._discover_repo_suites(workspace_root)
        assert discovery is not None
        assert discovery.repo_root == workspace_root
        assert discovery.repo_roots == [os.path.realpath(repo_dirs["repo-a"]), os.path.realpath(repo_dirs["repo-b"])]
        assert [suite.name for suite in discovery.suites] == ["compiler", "sdk", "tools", "truffle"]
        suite_repo_roots = {suite.name: os.path.realpath(suite.repo_root) for suite in discovery.suites}
        assert suite_repo_roots == {
            "compiler": os.path.realpath(repo_dirs["repo-a"]),
            "sdk": os.path.realpath(repo_dirs["repo-a"]),
            "tools": os.path.realpath(repo_dirs["repo-b"]),
            "truffle": os.path.realpath(repo_dirs["repo-b"]),
        }
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
        assert "> compiler (compiler) > sdk" in output
        assert "> tools (tools) > sdk" in output
        assert "  sdk (sdk)" in output
        assert "sdk -> -" not in output
        assert "compiler (compiler) > sdk" in output
        assert "> truffle (truffle) > sdk" in output
    finally:
        tmpdir.cleanup()


def test_show_suites_without_primary_suite_from_workspace_root():
    tmpdir, workspace_root, _, _ = _create_workspace_with_subrepos()
    try:
        stdout = io.StringIO()
        with chdir(workspace_root), mx_monkeypatch("_primary_suite", None), redirect_stdout(stdout):
            orig_mx.show_suites([])
        output = stdout.getvalue()
        assert "> compiler (repo-a/compiler) > sdk" in output
        assert "> tools (repo-b/tools) > sdk" in output
        assert "  sdk (repo-a/sdk)" in output
        assert "> truffle (repo-b/truffle) > sdk" in output
    finally:
        tmpdir.cleanup()


def test_show_suites_for_root_suites_only():
    tmpdir, repo_root, _ = _create_multi_suite_repo()
    try:
        stdout = io.StringIO()
        with chdir(repo_root), mx_monkeypatch("_primary_suite", None), mx_opt_patch(all_suites=False, root_suites=True, diff_suites=False, diff_branch_suites=False), redirect_stdout(stdout):
            orig_mx.show_suites([])
        output = stdout.getvalue()
        assert "> compiler (compiler)" in output
        assert "> tools (tools)" in output
        assert "> truffle (truffle)" in output
        assert "\n  sdk (sdk)" not in output
        assert "> compiler (compiler) > sdk" not in output
    finally:
        tmpdir.cleanup()


def test_show_suites_diff_for_all_suites():
    tmpdir, repo_root, suite_dirs = _create_multi_suite_repo()
    try:
        stdout = io.StringIO()
        changed_paths = [os.path.join(suite_dirs["sdk"], "mx.sdk", "suite.py")]

        def fake_get_repo_diff_paths(discovery):
            return "uncommitted changes", changed_paths

        with chdir(repo_root), mx_monkeypatch("_primary_suite", None), mx_monkeypatch("_get_repo_diff_paths", fake_get_repo_diff_paths), mx_opt_patch(all_suites=False, root_suites=False, diff_suites=True, diff_branch_suites=False), redirect_stdout(stdout):
            orig_mx.show_suites([])
        output = stdout.getvalue()
        assert output.strip() == "sdk (sdk)"
    finally:
        tmpdir.cleanup()


def test_show_suites_diff_branch_for_all_suites():
    tmpdir, repo_root, suite_dirs = _create_multi_suite_repo()
    try:
        stdout = io.StringIO()
        changed_paths = [os.path.join(suite_dirs["sdk"], "mx.sdk", "suite.py")]

        def fake_get_repo_diff_paths(discovery):
            return "uncommitted changes", changed_paths

        with chdir(repo_root), mx_monkeypatch("_primary_suite", None), mx_monkeypatch("_get_repo_diff_paths", fake_get_repo_diff_paths), mx_opt_patch(all_suites=False, root_suites=False, diff_suites=False, diff_branch_suites=True), redirect_stdout(stdout):
            orig_mx.show_suites([])
        output = stdout.getvalue()
        assert output.strip() == "sdk (sdk)"
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

        with chdir(repo_root), mx_monkeypatch("_primary_suite", None), mx_monkeypatch("run", fake_run), argv_patch(["mx", "--root-suites", "build", "--dry-run"]), mx_opt_patch(all_suites=False, root_suites=True, diff_suites=False, diff_branch_suites=False, primary=False, specific_suites=[], primary_suite_path=None):
            retcode = orig_mx._run_command_for_repo_suites("build", discovery)

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

        with chdir(repo_root), mx_monkeypatch("_primary_suite", None), mx_monkeypatch("run", fake_run), argv_patch(["mx", "--all-suites", "build", "--dry-run"]), mx_opt_patch(all_suites=True, root_suites=False, diff_suites=False, diff_branch_suites=False, primary=False, specific_suites=[], primary_suite_path=None):
            retcode = orig_mx._run_command_for_repo_suites("build", discovery)

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


def test_diff_path_selection_for_all_suites():
    tmpdir, repo_root, suite_dirs = _create_multi_suite_repo()
    try:
        discovery = orig_mx._discover_repo_suites(repo_root)
        changed_paths = [os.path.join(suite_dirs["sdk"], "mx.sdk", "suite.py")]
        selected = orig_mx._select_repo_suites_by_paths(discovery, changed_paths, root_suites_only=False)
        assert [suite.name for suite in selected] == ["sdk"]
    finally:
        tmpdir.cleanup()


def test_diff_path_selection_for_root_suites():
    tmpdir, repo_root, suite_dirs = _create_multi_suite_repo()
    try:
        discovery = orig_mx._discover_repo_suites(repo_root)
        changed_paths = [os.path.join(suite_dirs["sdk"], "mx.sdk", "suite.py")]
        selected = orig_mx._select_repo_suites_by_paths(discovery, changed_paths, root_suites_only=True)
        assert [suite.name for suite in selected] == ["compiler", "tools", "truffle"]
    finally:
        tmpdir.cleanup()


def test_diff_path_selection_for_repo_level_change_selects_all():
    tmpdir, repo_root, _ = _create_multi_suite_repo()
    try:
        discovery = orig_mx._discover_repo_suites(repo_root)
        changed_paths = [os.path.join(repo_root, "mx.py")]
        selected_all = orig_mx._select_repo_suites_by_paths(discovery, changed_paths, root_suites_only=False)
        assert [suite.name for suite in selected_all] == ["compiler", "sdk", "tools", "truffle"]
        selected_roots = orig_mx._select_repo_suites_by_paths(discovery, changed_paths, root_suites_only=True)
        assert [suite.name for suite in selected_roots] == ["compiler", "tools", "truffle"]
    finally:
        tmpdir.cleanup()


def test_workspace_repo_level_change_selects_only_own_repo_suites():
    tmpdir, workspace_root, repo_dirs, _ = _create_workspace_with_subrepos()
    try:
        discovery = orig_mx._discover_repo_suites(workspace_root)
        changed_paths = [os.path.join(repo_dirs["repo-a"], "README.md")]
        selected = orig_mx._select_repo_suites_by_paths(discovery, changed_paths, root_suites_only=False)
        assert [suite.name for suite in selected] == ["compiler", "sdk"]
    finally:
        tmpdir.cleanup()


def test_diff_suites_dispatches_once_per_selected_suite():
    tmpdir, repo_root, _ = _create_multi_suite_repo()
    try:
        discovery = orig_mx._discover_repo_suites(repo_root)
        commands = []

        def fake_run(cmd, **kwargs):
            commands.append((cmd, kwargs))
            return 0

        def fake_get_repo_diff_paths(discovery):
            return "uncommitted changes", [os.path.join(repo_root, "sdk", "mx.sdk", "suite.py")]

        with chdir(repo_root), mx_monkeypatch("_primary_suite", None), mx_monkeypatch("run", fake_run), mx_monkeypatch("_get_repo_diff_paths", fake_get_repo_diff_paths), argv_patch(["mx", "--diff-suites", "build", "--dry-run"]), mx_opt_patch(all_suites=False, root_suites=False, diff_suites=True, diff_branch_suites=False, primary=False, specific_suites=[], primary_suite_path=None):
            retcode = orig_mx._run_command_for_repo_suites("build", discovery)

        assert retcode == 0
        assert len(commands) == 1
        cmd, kwargs = commands[0]
        assert cmd[cmd.index("-p") + 1] == os.path.join(repo_root, "sdk")
        assert "--diff-suites" not in cmd
        assert "build" in cmd
        assert "--dry-run" in cmd
        assert kwargs["cwd"] == os.path.join(repo_root, "sdk")
    finally:
        tmpdir.cleanup()


def test_multi_suite_flags_rejected_with_active_primary_suite():
    expected = "`--all-suites`, `--root-suites`, `--diff-suites`, and `--diff-branch-suites` cannot be used when a primary suite is already active"
    with mx_monkeypatch("_primary_suite", object()), mx_opt_patch(all_suites=True, root_suites=False, diff_suites=False, diff_branch_suites=False):
        _assert_abort(lambda: orig_mx.build([]), expected)
    with mx_monkeypatch("_primary_suite", object()), mx_opt_patch(all_suites=False, root_suites=True, diff_suites=False, diff_branch_suites=False):
        _assert_abort(lambda: orig_mx.build([]), expected)
    with mx_monkeypatch("_primary_suite", object()), mx_opt_patch(all_suites=False, root_suites=False, diff_suites=True, diff_branch_suites=False):
        _assert_abort(lambda: orig_mx.build([]), expected)


def tests():
    test_discover_repo_suites()
    test_discover_repo_suites_from_workspace_root()
    test_show_suites_without_primary_suite()
    test_show_suites_without_primary_suite_from_workspace_root()
    test_show_suites_for_root_suites_only()
    test_show_suites_diff_for_all_suites()
    test_show_suites_diff_branch_for_all_suites()
    test_build_without_primary_suite_shows_all_suites_hint()
    test_root_suites_dispatches_once_per_root_suite()
    test_all_suites_dispatches_once_per_discovered_suite()
    test_diff_path_selection_for_all_suites()
    test_diff_path_selection_for_root_suites()
    test_diff_path_selection_for_repo_level_change_selects_all()
    test_workspace_repo_level_change_selects_only_own_repo_suites()
    test_diff_suites_dispatches_once_per_selected_suite()
    test_multi_suite_flags_rejected_with_active_primary_suite()
