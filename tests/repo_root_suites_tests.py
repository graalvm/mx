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


@contextmanager
def sys_module_patch(name):
    sentinel = object()
    previous = sys.modules.get(name, sentinel)
    sys.modules.pop(name, None)
    try:
        yield
    finally:
        if previous is sentinel:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous


def _write_suite(repo_root, suite_relpath, suite_name, imported_suites=None, import_entries=None):
    imported_suites = imported_suites or []
    suite_dir = os.path.join(repo_root, suite_relpath)
    mx_dir = os.path.join(suite_dir, f"mx.{suite_name}")
    os.makedirs(mx_dir, exist_ok=True)
    imports = ""
    if import_entries is None and imported_suites:
        import_entries = [{"name": suite, "subdir": True} for suite in imported_suites]
    if import_entries:
        imports = """
    "imports": {
        "suites": [
%s
        ]
    },
""" % ",\n".join([f"            {repr(entry)}" for entry in import_entries])
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


def _create_repo_with_nested_imported_suite():
    tmpdir = tempfile.TemporaryDirectory()
    repo_root = tmpdir.name
    open(os.path.join(repo_root, ".mx_vcs_root"), "w").close()
    compiler_dir = _write_suite(repo_root, "compiler", "compiler")
    imported_sdk_dir = _write_suite(os.path.join(repo_root, "compiler", "mx.imports", "source"), "sdk", "sdk")
    tools_dir = _write_suite(repo_root, "tools", "tools")
    return tmpdir, repo_root, {
        "compiler": compiler_dir,
        "tools": tools_dir,
        "imported-sdk": imported_sdk_dir,
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


def _create_workspace_with_duplicate_suite_names():
    tmpdir = tempfile.TemporaryDirectory()
    workspace_root = tmpdir.name
    repo_a = os.path.join(workspace_root, "repo-a")
    repo_b = os.path.join(workspace_root, "repo-b")
    os.makedirs(repo_a, exist_ok=True)
    os.makedirs(repo_b, exist_ok=True)
    open(os.path.join(repo_a, ".mx_vcs_root"), "w").close()
    open(os.path.join(repo_b, ".mx_vcs_root"), "w").close()
    compiler_dir = _write_suite(repo_a, "compiler", "compiler", ["sdk"])
    sdk_a_dir = _write_suite(repo_a, "sdk", "sdk")
    tools_dir = _write_suite(repo_b, "tools", "tools", ["sdk"])
    sdk_b_dir = _write_suite(repo_b, "sdk", "sdk")
    return tmpdir, workspace_root, {
        "repo-a": repo_a,
        "repo-b": repo_b,
    }, {
        "compiler": compiler_dir,
        "repo-a-sdk": sdk_a_dir,
        "tools": tools_dir,
        "repo-b-sdk": sdk_b_dir,
    }


def _create_workspace_with_ambiguous_import():
    tmpdir = tempfile.TemporaryDirectory()
    workspace_root = tmpdir.name
    importer_repo = os.path.join(workspace_root, "importer-repo")
    repo_a = os.path.join(workspace_root, "repo-a")
    repo_b = os.path.join(workspace_root, "repo-b")
    os.makedirs(importer_repo, exist_ok=True)
    os.makedirs(repo_a, exist_ok=True)
    os.makedirs(repo_b, exist_ok=True)
    open(os.path.join(importer_repo, ".mx_vcs_root"), "w").close()
    open(os.path.join(repo_a, ".mx_vcs_root"), "w").close()
    open(os.path.join(repo_b, ".mx_vcs_root"), "w").close()
    compiler_dir = _write_suite(importer_repo, "compiler", "compiler", ["sdk"])
    sdk_a_dir = _write_suite(repo_a, "sdk", "sdk")
    sdk_b_dir = _write_suite(repo_b, "sdk", "sdk")
    return tmpdir, workspace_root, {
        "compiler": compiler_dir,
        "repo-a-sdk": sdk_a_dir,
        "repo-b-sdk": sdk_b_dir,
    }


def _create_repo_with_missing_import():
    tmpdir = tempfile.TemporaryDirectory()
    repo_root = tmpdir.name
    open(os.path.join(repo_root, ".mx_vcs_root"), "w").close()
    compiler_dir = _write_suite(
        repo_root,
        "compiler",
        "compiler",
        import_entries=[
            {
                "name": "sdk",
                "version": "deadbeef",
                "urls": [{"url": "https://example.invalid/sdk.git", "kind": "git"}],
            }
        ],
    )
    return tmpdir, repo_root, {"compiler": compiler_dir}


def _create_repo_with_partial_missing_imports():
    tmpdir = tempfile.TemporaryDirectory()
    repo_root = tmpdir.name
    open(os.path.join(repo_root, ".mx_vcs_root"), "w").close()
    compiler_dir = _write_suite(
        repo_root,
        "compiler",
        "compiler",
        import_entries=[
            {
                "name": "sdk",
                "version": "deadbeef",
                "urls": [{"url": "https://example.invalid/sdk.git", "kind": "git"}],
            }
        ],
    )
    tools_dir = _write_suite(repo_root, "tools", "tools")
    return tmpdir, repo_root, {"compiler": compiler_dir, "tools": tools_dir}


def _edge_name_pairs(discovery):
    suites_by_key = {suite.suite_key: suite for suite in discovery.suites}
    return [(suites_by_key[importer].name, suites_by_key[imported].name) for importer, imported in discovery.local_edges]


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
        assert _edge_name_pairs(discovery) == [("compiler", "sdk"), ("tools", "sdk"), ("truffle", "sdk")]
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


def test_discover_repo_suites_ignores_nested_imported_suites():
    tmpdir, repo_root, suite_dirs = _create_repo_with_nested_imported_suite()
    try:
        discovery = orig_mx._discover_repo_suites(repo_root)
        assert [suite.name for suite in discovery.suites] == ["compiler", "tools"]
        assert [suite.name for suite in discovery.root_suites] == ["compiler", "tools"]
        assert all(suite.suite_dir != suite_dirs["imported-sdk"] for suite in discovery.suites)
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
        assert "Roots:\n" in output
        assert "Others:\n" in output
        assert "  compiler (compiler): depends on: sdk" in output
        assert "  tools (tools): depends on: sdk" in output
        assert "  sdk (sdk)" in output
        assert "sdk: depends on: -" not in output
        assert "compiler (compiler): depends on: sdk" in output
        assert "  truffle (truffle): depends on: sdk" in output
        assert "> compiler" not in output
    finally:
        tmpdir.cleanup()


def test_show_suites_without_primary_suite_from_workspace_root():
    tmpdir, workspace_root, _, _ = _create_workspace_with_subrepos()
    try:
        stdout = io.StringIO()
        with chdir(workspace_root), mx_monkeypatch("_primary_suite", None), redirect_stdout(stdout):
            orig_mx.show_suites([])
        output = stdout.getvalue()
        assert "Roots:\n" in output
        assert "Others:\n" in output
        assert "  compiler (repo-a/compiler): depends on: sdk" in output
        assert "  tools (repo-b/tools): depends on: sdk" in output
        assert "  sdk (repo-a/sdk)" in output
        assert "  truffle (repo-b/truffle): depends on: sdk" in output
    finally:
        tmpdir.cleanup()


def test_show_suites_without_primary_suite_with_locations():
    tmpdir, repo_root, suite_dirs = _create_multi_suite_repo()
    try:
        stdout = io.StringIO()
        with chdir(repo_root), mx_monkeypatch("_primary_suite", None), redirect_stdout(stdout):
            orig_mx.show_suites(["--locations"])
        output = stdout.getvalue()
        assert "Roots:\n" in output
        assert "Others:\n" in output
        assert f"  compiler ({suite_dirs['compiler']}): depends on: sdk" in output
        assert f"  sdk ({suite_dirs['sdk']})" in output
        assert f"  tools ({suite_dirs['tools']}): depends on: sdk" in output
    finally:
        tmpdir.cleanup()


def test_show_suites_without_primary_suite_rejects_detailed_flags():
    tmpdir, repo_root, _ = _create_multi_suite_repo()
    try:
        with chdir(repo_root), mx_monkeypatch("_primary_suite", None):
            _assert_abort(lambda: orig_mx.show_suites(["--licenses"]), "--licenses require an active primary suite when running `mx suites`.")
    finally:
        tmpdir.cleanup()


def test_discover_repo_suites_with_duplicate_names_from_workspace_root():
    tmpdir, workspace_root, _, suite_dirs = _create_workspace_with_duplicate_suite_names()
    try:
        discovery = orig_mx._discover_repo_suites(workspace_root)
        assert [suite.name for suite in discovery.suites] == ["compiler", "sdk", "sdk", "tools"]
        assert [suite.name for suite in discovery.root_suites] == ["compiler", "tools"]
        assert discovery.local_edges == [
            (os.path.realpath(suite_dirs["compiler"]), os.path.realpath(suite_dirs["repo-a-sdk"])),
            (os.path.realpath(suite_dirs["tools"]), os.path.realpath(suite_dirs["repo-b-sdk"])),
        ]
    finally:
        tmpdir.cleanup()


def test_show_suites_with_duplicate_names_disambiguates_dependencies():
    tmpdir, workspace_root, _, _ = _create_workspace_with_duplicate_suite_names()
    try:
        stdout = io.StringIO()
        with chdir(workspace_root), mx_monkeypatch("_primary_suite", None), redirect_stdout(stdout):
            orig_mx.show_suites([])
        output = stdout.getvalue()
        assert "Roots:\n" in output
        assert "Others:\n" in output
        assert "  compiler (repo-a/compiler): depends on: sdk (repo-a/sdk)" in output
        assert "  sdk (repo-a/sdk)" in output
        assert "  sdk (repo-b/sdk)" in output
        assert "  tools (repo-b/tools): depends on: sdk (repo-b/sdk)" in output
    finally:
        tmpdir.cleanup()


def test_discover_repo_suites_reports_ambiguous_imports():
    tmpdir, workspace_root, suite_dirs = _create_workspace_with_ambiguous_import()
    try:
        discovery = orig_mx._discover_repo_suites(workspace_root)
        assert discovery.local_edges == []
        compiler_key = os.path.realpath(suite_dirs["compiler"])
        assert compiler_key in discovery.ambiguous_imports
        imports = discovery.ambiguous_imports[compiler_key]
        assert len(imports) == 1
        assert "sdk (ambiguous:" in imports[0]
        assert "repo-a/sdk" in imports[0]
        assert "repo-b/sdk" in imports[0]
    finally:
        tmpdir.cleanup()


def test_show_suites_reports_ambiguous_imports():
    tmpdir, workspace_root, _ = _create_workspace_with_ambiguous_import()
    try:
        stdout = io.StringIO()
        with chdir(workspace_root), mx_monkeypatch("_primary_suite", None), redirect_stdout(stdout):
            orig_mx.show_suites([])
        output = stdout.getvalue()
        assert "Ambiguous dependencies:\n" in output
        assert "  compiler (importer-repo/compiler): depends on: sdk (ambiguous:" in output
        assert "repo-a/sdk" in output
        assert "repo-b/sdk" in output
        assert "depends on: sdk, sdk" not in output
    finally:
        tmpdir.cleanup()


def test_show_suites_for_root_suites_only():
    tmpdir, repo_root, _ = _create_multi_suite_repo()
    try:
        stdout = io.StringIO()
        with chdir(repo_root), mx_monkeypatch("_primary_suite", None), mx_opt_patch(all_suites=False, root_suites=True, diff_suites=False, diff_branch_suites=False), redirect_stdout(stdout):
            orig_mx.show_suites([])
        output = stdout.getvalue()
        assert "Roots:\n" in output
        assert "Others:\n" not in output
        assert "  compiler (compiler)" in output
        assert "  tools (tools)" in output
        assert "  truffle (truffle)" in output
        assert "\n  sdk (sdk)" not in output
        assert "compiler (compiler): depends on: sdk" not in output
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
        assert output.strip() == "Others:\n  sdk (sdk)"
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
        assert output.strip() == "Others:\n  sdk (sdk)"
    finally:
        tmpdir.cleanup()


def test_get_repo_diff_paths_ignores_non_git_repos():
    tmpdir, repo_root, _ = _create_multi_suite_repo()
    try:
        discovery = orig_mx._discover_repo_suites(repo_root)

        def fake_get_vc(path, abortOnError=True):
            return None

        with mx_monkeypatch("VC", type("FakeVCNamespace", (), {"get_vc": staticmethod(fake_get_vc)})), mx_opt_patch(all_suites=False, root_suites=False, diff_suites=True, diff_branch_suites=False):
            diff_desc, changed_paths = orig_mx._get_repo_diff_paths(discovery)

        assert diff_desc == "uncommitted changes"
        assert changed_paths == []
    finally:
        tmpdir.cleanup()


def test_get_repo_diff_paths_uses_only_git_repos_in_mixed_workspace():
    tmpdir, workspace_root, repo_dirs, _ = _create_workspace_with_subrepos()
    try:
        discovery = orig_mx._discover_repo_suites(workspace_root)

        class FakeGit(object):
            kind = "git"

        def fake_get_vc(path, abortOnError=True):
            if os.path.realpath(path) == os.path.realpath(repo_dirs["repo-a"]):
                return FakeGit()
            return None

        def fake_git_diff_name_status_z(vc_dir, extra_args):
            assert os.path.realpath(vc_dir) == os.path.realpath(repo_dirs["repo-a"])
            assert extra_args == ["HEAD"]
            return "M\0compiler/mx.compiler/suite.py\0"

        with mx_monkeypatch("VC", type("FakeVCNamespace", (), {"get_vc": staticmethod(fake_get_vc)})), mx_monkeypatch("_git_diff_name_status_z", fake_git_diff_name_status_z), mx_opt_patch(all_suites=False, root_suites=False, diff_suites=True, diff_branch_suites=False):
            diff_desc, changed_paths = orig_mx._get_repo_diff_paths(discovery)

        assert diff_desc == "uncommitted changes"
        assert changed_paths == [os.path.realpath(os.path.join(repo_dirs["repo-a"], "compiler", "mx.compiler", "suite.py"))]
    finally:
        tmpdir.cleanup()


def test_parser_accepts_optional_diff_branch_suites_value():
    parser = orig_mx.ArgParser()
    parsed = parser.parse_args(["--diff-branch-suites"])
    assert parsed.diff_branch_suites == "master"

    parsed = parser.parse_args(["--diff-branch-suites=main"])
    assert parsed.diff_branch_suites == "main"


def test_diff_branch_suites_requires_configured_branch_with_fixup_message():
    tmpdir, repo_root, _ = _create_multi_suite_repo()
    try:
        discovery = orig_mx._discover_repo_suites(repo_root)
        stderr = io.StringIO()

        class FakeGit(object):
            kind = "git"

        def fake_get_vc(path, abortOnError=True):
            return FakeGit()

        class FakeGitConfig(object):
            def check_for_git(self):
                return self

            def _commitish_revision(self, vcdir, commitish, abortOnError=True):
                assert commitish == "main"
                return None

        with mx_monkeypatch("VC", type("FakeVCNamespace", (), {"get_vc": staticmethod(fake_get_vc)})), mx_monkeypatch("GitConfig", FakeGitConfig), mx_opt_patch(all_suites=False, root_suites=False, diff_suites=False, diff_branch_suites="main"):
            try:
                with redirect_stderr(stderr):
                    orig_mx._get_repo_diff_paths(discovery)
            except SystemExit as exc:
                assert exc.code == 1
            else:
                assert False, "expected mx.abort"

        message = stderr.getvalue()
        assert "`--diff-branch-suites` requires a local `main` branch" in message
        assert "git fetch origin main" in message
        assert "git branch -f main FETCH_HEAD" in message
    finally:
        tmpdir.cleanup()


def test_parser_rejects_primary_suite_path_with_repo_suite_flags():
    parser = orig_mx.ArgParser()
    stderr = io.StringIO()
    try:
        with redirect_stderr(stderr):
            parser.parse_args(["-p", "/tmp/suite", "--all-suites"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        assert False, "expected argparse error"
    assert "not allowed with argument -p/--primary-suite-path" in stderr.getvalue()


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
        logs = []

        def fake_run(cmd, **kwargs):
            commands.append((cmd, kwargs))
            return 0

        def fake_log(msg=""):
            logs.append(msg)

        with chdir(repo_root), mx_monkeypatch("_primary_suite", None), mx_monkeypatch("run", fake_run), mx_monkeypatch("log", fake_log), mx_monkeypatch("_check_command_available_for_suite", lambda command, suite_dir: True), argv_patch(["mx", "--root-suites", "build", "--dry-run"]), mx_opt_patch(all_suites=False, root_suites=True, diff_suites=False, diff_branch_suites=False, primary=False, specific_suites=[], primary_suite_path=None):
            retcode = orig_mx._run_command_for_repo_suites("build", discovery)

        assert retcode == 0
        assert len(commands) == 3
        assert "Selected root suites: compiler, tools, truffle" in logs
        assert "3 commands executed successfully" in logs
        assert "Summary:" not in logs
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


def test_recursive_mx_args_preserve_global_option_values_matching_command_name():
    with argv_patch(["mx", "--env", "build", "build", "--dry-run"]):
        orig_mx._argParser.initialCommandAndArgs = ["build", "--dry-run"]
        cmd = orig_mx._recursive_mx_args_for_suite("/tmp/suite")

    assert cmd == [
        sys.executable,
        "-u",
        os.path.join(orig_mx._mx_home, "mx.py"),
        "--env",
        "build",
        "-p",
        "/tmp/suite",
        "build",
        "--dry-run",
    ]


def test_recursive_mx_args_strip_diff_branch_suites_with_explicit_value():
    with argv_patch(["mx", "--diff-branch-suites=main", "build", "--dry-run"]):
        orig_mx._argParser.initialCommandAndArgs = ["build", "--dry-run"]
        cmd = orig_mx._recursive_mx_args_for_suite("/tmp/suite")

    assert cmd == [
        sys.executable,
        "-u",
        os.path.join(orig_mx._mx_home, "mx.py"),
        "-p",
        "/tmp/suite",
        "build",
        "--dry-run",
    ]


def test_all_suites_dispatches_once_per_discovered_suite():
    tmpdir, repo_root, suite_dirs = _create_multi_suite_repo()
    try:
        discovery = orig_mx._discover_repo_suites(repo_root)
        commands = []
        logs = []

        def fake_run(cmd, **kwargs):
            commands.append((cmd, kwargs))
            return 0

        def fake_log(msg=""):
            logs.append(msg)

        with chdir(repo_root), mx_monkeypatch("_primary_suite", None), mx_monkeypatch("run", fake_run), mx_monkeypatch("log", fake_log), mx_monkeypatch("_check_command_available_for_suite", lambda command, suite_dir: True), argv_patch(["mx", "--all-suites", "custom-command", "--dry-run"]), mx_opt_patch(all_suites=True, root_suites=False, diff_suites=False, diff_branch_suites=False, primary=False, specific_suites=[], primary_suite_path=None):
            retcode = orig_mx._run_command_for_repo_suites("custom-command", discovery)

        assert retcode == 0
        assert len(commands) == 4
        assert "Selected suites: compiler, sdk, tools, truffle" in logs
        assert "4 commands executed successfully" in logs
        assert "Summary:" not in logs
        invoked_primary_suites = [cmd[cmd.index("-p") + 1] for cmd, _ in commands]
        assert invoked_primary_suites == [suite_dirs["compiler"], suite_dirs["sdk"], suite_dirs["tools"], suite_dirs["truffle"]]
        for cmd, kwargs in commands:
            assert "--all-suites" not in cmd
            assert "--root-suites" not in cmd
            assert "custom-command" in cmd
            assert "--dry-run" in cmd
            assert cmd.index("-p") < cmd.index("custom-command")
            assert kwargs["cwd"] in invoked_primary_suites
    finally:
        tmpdir.cleanup()


def test_bulk_suite_run_preserves_live_command_output():
    tmpdir, repo_root, _ = _create_multi_suite_repo()
    try:
        discovery = orig_mx._discover_repo_suites(repo_root)
        commands = []

        def fake_run(cmd, **kwargs):
            commands.append((cmd, kwargs))
            return 0

        with chdir(repo_root), mx_monkeypatch("_primary_suite", None), mx_monkeypatch("run", fake_run), mx_monkeypatch("_check_command_available_for_suite", lambda command, suite_dir: True), argv_patch(["mx", "--all-suites", "custom-command", "--dry-run"]), mx_opt_patch(all_suites=True, root_suites=False, diff_suites=False, diff_branch_suites=False, primary=False, specific_suites=[], primary_suite_path=None):
            retcode = orig_mx._run_command_for_repo_suites("custom-command", discovery)

        assert retcode == 0
        assert len(commands) == 4
        for _, kwargs in commands:
            assert "out" not in kwargs
            assert "err" not in kwargs
    finally:
        tmpdir.cleanup()


def test_bulk_suite_run_aborts_on_keyboard_interrupt():
    tmpdir, repo_root, _ = _create_multi_suite_repo()
    try:
        discovery = orig_mx._discover_repo_suites(repo_root)
        logs = []

        def fake_run(cmd, **kwargs):
            assert kwargs["interruptIsFatal"] is True
            raise KeyboardInterrupt()

        def fake_log(msg=""):
            logs.append(msg)

        def fake_abort(msg):
            raise RuntimeError(msg)

        with chdir(repo_root), mx_monkeypatch("_primary_suite", None), mx_monkeypatch("run", fake_run), mx_monkeypatch("log", fake_log), mx_monkeypatch("abort", fake_abort), mx_monkeypatch("_check_command_available_for_suite", lambda command, suite_dir: True), argv_patch(["mx", "--all-suites", "custom-command", "--dry-run"]), mx_opt_patch(all_suites=True, root_suites=False, diff_suites=False, diff_branch_suites=False, primary=False, specific_suites=[], primary_suite_path=None):
            try:
                orig_mx._run_command_for_repo_suites("custom-command", discovery)
                assert False, "expected abort on keyboard interrupt"
            except RuntimeError as exc:
                assert str(exc) == "1"

        assert "Summary:" not in logs
        assert "commands executed successfully" not in " ".join(logs)
    finally:
        tmpdir.cleanup()


def test_main_dispatches_arbitrary_command_for_selected_suites():
    tmpdir, repo_root, suite_dirs = _create_multi_suite_repo()
    try:
        commands = []
        logs = []

        def fake_run(cmd, **kwargs):
            commands.append((cmd, kwargs))
            return 0

        def fake_log(msg=""):
            logs.append(msg)

        with chdir(repo_root), mx_monkeypatch("run", fake_run), mx_monkeypatch("log", fake_log), mx_monkeypatch("_check_command_available_for_suite", lambda command, suite_dir: True), argv_patch(["mx", "--all-suites", "custom-command", "--dry-run"]), sys_module_patch("mx_mx"):
            orig_mx.main()

        assert len(commands) == 4
        assert logs[0] == "Selected suites: compiler, sdk, tools, truffle"
        assert "4 commands executed successfully" in logs
        assert "Summary:" not in logs
        invoked_primary_suites = [cmd[cmd.index("-p") + 1] for cmd, _ in commands]
        assert invoked_primary_suites == [suite_dirs["compiler"], suite_dirs["sdk"], suite_dirs["tools"], suite_dirs["truffle"]]
        for cmd, kwargs in commands:
            assert "custom-command" in cmd
            assert "--dry-run" in cmd
            assert cmd.index("-p") < cmd.index("custom-command")
            assert kwargs["cwd"] in invoked_primary_suites
    finally:
        tmpdir.cleanup()


def test_main_dispatch_respects_skip_missing_imports():
    tmpdir, repo_root, suite_dirs = _create_repo_with_partial_missing_imports()
    try:
        commands = []
        logs = []

        def fake_run(cmd, **kwargs):
            commands.append((cmd, kwargs))
            return 0

        def fake_log(msg=""):
            logs.append(msg)

        with chdir(repo_root), mx_monkeypatch("run", fake_run), mx_monkeypatch("log", fake_log), mx_monkeypatch("_check_command_available_for_suite", lambda command, suite_dir: True), argv_patch(["mx", "--all-suites", "--skip-missing-imports", "custom-command", "--dry-run"]), sys_module_patch("mx_mx"):
            orig_mx.main()

        assert len(commands) == 1
        cmd, kwargs = commands[0]
        assert cmd[cmd.index("-p") + 1] == suite_dirs["tools"]
        assert "custom-command" in cmd
        assert "--skip-missing-imports" not in cmd
        assert "--all-suites" not in cmd
        assert kwargs["cwd"] == suite_dirs["tools"]
        assert "Selected suites: compiler, tools" in logs
        assert "Skipping suite `compiler` due to missing local imports: sdk" in logs
        assert "Skipped 1 suite with missing local imports" in logs
        assert "1 command executed successfully" in logs
        assert "Summary:" not in logs
    finally:
        tmpdir.cleanup()


def test_main_does_not_bulk_dispatch_suites():
    tmpdir, repo_root, _ = _create_multi_suite_repo()
    try:
        dispatched = []

        def fail_bulk_dispatch(command, discovery):
            dispatched.append((command, discovery))
            assert False, "suites should not recurse through bulk run dispatch"

        stdout = io.StringIO()
        with chdir(repo_root), mx_monkeypatch("_run_command_for_repo_suites", fail_bulk_dispatch), mx_monkeypatch("_check_stdout_encoding", lambda: None), argv_patch(["mx", "--all-suites", "suites", "--locations"]), sys_module_patch("mx_mx"), redirect_stdout(stdout):
            orig_mx.main()

        assert dispatched == []
        assert "Roots:" in stdout.getvalue()
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


def test_diff_path_selection_with_duplicate_names_selects_only_matching_suite():
    tmpdir, workspace_root, _, suite_dirs = _create_workspace_with_duplicate_suite_names()
    try:
        discovery = orig_mx._discover_repo_suites(workspace_root)
        changed_paths = [os.path.join(suite_dirs["repo-a-sdk"], "mx.sdk", "suite.py")]
        selected = orig_mx._select_repo_suites_by_paths(discovery, changed_paths, root_suites_only=False)
        assert [suite.suite_dir for suite in selected] == [suite_dirs["repo-a-sdk"]]
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

        with chdir(repo_root), mx_monkeypatch("_primary_suite", None), mx_monkeypatch("run", fake_run), mx_monkeypatch("_get_repo_diff_paths", fake_get_repo_diff_paths), mx_monkeypatch("_check_command_available_for_suite", lambda command, suite_dir: True), argv_patch(["mx", "--diff-suites", "build", "--dry-run"]), mx_opt_patch(all_suites=False, root_suites=False, diff_suites=True, diff_branch_suites=False, primary=False, specific_suites=[], primary_suite_path=None):
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


def test_skip_missing_imports_skips_all_selected_suites():
    tmpdir, repo_root, _ = _create_repo_with_missing_import()
    try:
        discovery = orig_mx._discover_repo_suites(repo_root)
        commands = []
        logs = []

        def fake_run(cmd, **kwargs):
            commands.append((cmd, kwargs))
            return 0

        def fake_log(msg=""):
            logs.append(msg)

        with chdir(repo_root), mx_monkeypatch("_primary_suite", None), mx_monkeypatch("run", fake_run), mx_monkeypatch("log", fake_log), mx_monkeypatch("_check_command_available_for_suite", lambda command, suite_dir: True), argv_patch(["mx", "--all-suites", "--skip-missing-imports", "build", "--dry-run"]), mx_opt_patch(all_suites=True, root_suites=False, diff_suites=False, diff_branch_suites=False, skip_missing_imports=True, primary=False, specific_suites=[], primary_suite_path=None):
            retcode = orig_mx._run_command_for_repo_suites("build", discovery)

        assert retcode == 0
        assert commands == []
        assert "Selected suites: compiler" in logs
        assert "Skipping suite `compiler` due to missing local imports: sdk" in logs
        assert "Skipped 1 suite with missing local imports" in logs
        assert "No commands executed; all selected suites were skipped due to missing local imports" in logs
        assert "Summary:" not in logs
    finally:
        tmpdir.cleanup()


def test_skip_missing_imports_allows_other_selected_suites_to_run():
    tmpdir, repo_root, suite_dirs = _create_repo_with_partial_missing_imports()
    try:
        discovery = orig_mx._discover_repo_suites(repo_root)
        commands = []
        logs = []

        def fake_run(cmd, **kwargs):
            commands.append((cmd, kwargs))
            return 0

        def fake_log(msg=""):
            logs.append(msg)

        with chdir(repo_root), mx_monkeypatch("_primary_suite", None), mx_monkeypatch("run", fake_run), mx_monkeypatch("log", fake_log), mx_monkeypatch("_check_command_available_for_suite", lambda command, suite_dir: True), argv_patch(["mx", "--all-suites", "--skip-missing-imports", "build", "--dry-run"]), mx_opt_patch(all_suites=True, root_suites=False, diff_suites=False, diff_branch_suites=False, skip_missing_imports=True, primary=False, specific_suites=[], primary_suite_path=None):
            retcode = orig_mx._run_command_for_repo_suites("build", discovery)

        assert retcode == 0
        assert len(commands) == 1
        cmd, kwargs = commands[0]
        assert cmd[cmd.index("-p") + 1] == suite_dirs["tools"]
        assert kwargs["cwd"] == suite_dirs["tools"]
        assert "Skipping suite `compiler` due to missing local imports: sdk" in logs
        assert "Skipped 1 suite with missing local imports" in logs
        assert "1 command executed successfully" in logs
        assert "Summary:" not in logs
    finally:
        tmpdir.cleanup()


def test_summary_uses_suite_paths_for_duplicate_names():
    tmpdir, workspace_root, _, suite_dirs = _create_workspace_with_duplicate_suite_names()
    try:
        discovery = orig_mx._discover_repo_suites(workspace_root)
        logs = []

        def fake_run(cmd, **kwargs):
            if cmd[cmd.index("-p") + 1] == suite_dirs["repo-a-sdk"]:
                return 1
            return 0

        def fake_log(msg=""):
            logs.append(msg)

        def fake_abort(msg):
            raise RuntimeError(msg)

        with chdir(workspace_root), mx_monkeypatch("_primary_suite", None), mx_monkeypatch("run", fake_run), mx_monkeypatch("log", fake_log), mx_monkeypatch("abort", fake_abort), mx_monkeypatch("_check_command_available_for_suite", lambda command, suite_dir: True), argv_patch(["mx", "--all-suites", "build", "--dry-run"]), mx_opt_patch(all_suites=True, root_suites=False, diff_suites=False, diff_branch_suites=False, primary=False, specific_suites=[], primary_suite_path=None):
            try:
                orig_mx._run_command_for_repo_suites("build", discovery)
                assert False, "expected abort for failed suite command"
            except RuntimeError as exc:
                assert str(exc) == "1 suite command failed."

        assert "  FAILED (1): sdk (repo-a/sdk)" in logs
        assert "  OK: compiler, sdk (repo-b/sdk), tools" in logs
        assert "Summary:" in logs
    finally:
        tmpdir.cleanup()


def test_summary_distinguishes_missing_command_from_failure():
    tmpdir, repo_root, suite_dirs = _create_multi_suite_repo()
    try:
        discovery = orig_mx._discover_repo_suites(repo_root)
        commands = []
        logs = []

        def fake_run(cmd, **kwargs):
            commands.append((cmd, kwargs))
            return 0

        def fake_log(msg=""):
            logs.append(msg)

        def fake_abort(msg):
            raise RuntimeError(msg)

        def fake_check_command_available_for_suite(command, suite_dir):
            return suite_dir != suite_dirs["sdk"]

        with chdir(repo_root), mx_monkeypatch("_primary_suite", None), mx_monkeypatch("run", fake_run), mx_monkeypatch("log", fake_log), mx_monkeypatch("abort", fake_abort), mx_monkeypatch("_check_command_available_for_suite", fake_check_command_available_for_suite), argv_patch(["mx", "--all-suites", "custom-command", "--dry-run"]), mx_opt_patch(all_suites=True, root_suites=False, diff_suites=False, diff_branch_suites=False, primary=False, specific_suites=[], primary_suite_path=None):
            try:
                orig_mx._run_command_for_repo_suites("custom-command", discovery)
                assert False, "expected abort for unavailable command"
            except RuntimeError as exc:
                assert str(exc) == "1 suite does not define `custom-command`."

        assert len(commands) == 3
        invoked_primary_suites = [cmd[cmd.index("-p") + 1] for cmd, _ in commands]
        assert suite_dirs["sdk"] not in invoked_primary_suites
        assert "  COMMAND UNDEFINED: sdk" in logs
        assert "  OK: compiler, tools, truffle" in logs
        assert "Summary:" in logs
    finally:
        tmpdir.cleanup()


def test_diff_summary_uses_suite_paths_for_duplicate_names():
    tmpdir, workspace_root, _, suite_dirs = _create_workspace_with_duplicate_suite_names()
    try:
        discovery = orig_mx._discover_repo_suites(workspace_root)
        logs = []

        def fake_run(cmd, **kwargs):
            return 0

        def fake_log(msg=""):
            logs.append(msg)

        def fake_get_repo_diff_paths(discovery):
            return "uncommitted changes", [os.path.join(suite_dirs["repo-a-sdk"], "mx.sdk", "suite.py")]

        with chdir(workspace_root), mx_monkeypatch("_primary_suite", None), mx_monkeypatch("run", fake_run), mx_monkeypatch("log", fake_log), mx_monkeypatch("_get_repo_diff_paths", fake_get_repo_diff_paths), mx_monkeypatch("_check_command_available_for_suite", lambda command, suite_dir: True), argv_patch(["mx", "--diff-suites", "build", "--dry-run"]), mx_opt_patch(all_suites=False, root_suites=False, diff_suites=True, diff_branch_suites=False, primary=False, specific_suites=[], primary_suite_path=None):
            retcode = orig_mx._run_command_for_repo_suites("build", discovery)

        assert retcode == 0
        assert "Diff filter (uncommitted changes) selected suites: sdk (repo-a/sdk)" in logs
        assert "Running `build` for suite `sdk (repo-a/sdk)`" in logs
        assert "1 command executed successfully" in logs
        assert "Summary:" not in logs
    finally:
        tmpdir.cleanup()


def test_multi_suite_flags_reject_primary_suite_path_from_env():
    tmpdir, repo_root, _ = _create_multi_suite_repo()
    try:
        discovery = orig_mx._discover_repo_suites(repo_root)
        expected = "`MX_PRIMARY_SUITE_PATH` cannot be used together with `--all-suites`, `--root-suites`, `--diff-suites`, or `--diff-branch-suites`."
        with chdir(repo_root), mx_monkeypatch("_primary_suite", object()), mx_monkeypatch("_primary_suite_path", "/tmp/suite"), mx_opt_patch(all_suites=True, root_suites=False, diff_suites=False, diff_branch_suites=False, primary=False, specific_suites=[], primary_suite_path=None):
            _assert_abort(lambda: orig_mx._run_command_for_repo_suites("build", discovery), expected)
    finally:
        tmpdir.cleanup()


def test_multi_suite_flags_reject_primary_and_specific_suite_filters():
    tmpdir, repo_root, _ = _create_multi_suite_repo()
    try:
        discovery = orig_mx._discover_repo_suites(repo_root)
        expected = "`--primary` and `--suite` cannot be used together with `--all-suites`, `--root-suites`, `--diff-suites`, or `--diff-branch-suites`."
        with chdir(repo_root), mx_monkeypatch("_primary_suite", object()), mx_opt_patch(all_suites=True, root_suites=False, diff_suites=False, diff_branch_suites=False, primary=True, specific_suites=[], primary_suite_path=None):
            _assert_abort(lambda: orig_mx._run_command_for_repo_suites("build", discovery), expected)
        with chdir(repo_root), mx_monkeypatch("_primary_suite", object()), mx_opt_patch(all_suites=True, root_suites=False, diff_suites=False, diff_branch_suites=False, primary=False, specific_suites=["sdk"], primary_suite_path=None):
            _assert_abort(lambda: orig_mx._run_command_for_repo_suites("build", discovery), expected)
    finally:
        tmpdir.cleanup()


def tests():
    test_discover_repo_suites()
    test_discover_repo_suites_from_workspace_root()
    test_discover_repo_suites_ignores_nested_imported_suites()
    test_show_suites_without_primary_suite()
    test_show_suites_without_primary_suite_from_workspace_root()
    test_show_suites_without_primary_suite_with_locations()
    test_show_suites_without_primary_suite_rejects_detailed_flags()
    test_discover_repo_suites_with_duplicate_names_from_workspace_root()
    test_show_suites_with_duplicate_names_disambiguates_dependencies()
    test_discover_repo_suites_reports_ambiguous_imports()
    test_show_suites_reports_ambiguous_imports()
    test_show_suites_for_root_suites_only()
    test_show_suites_diff_for_all_suites()
    test_show_suites_diff_branch_for_all_suites()
    test_get_repo_diff_paths_ignores_non_git_repos()
    test_get_repo_diff_paths_uses_only_git_repos_in_mixed_workspace()
    test_parser_accepts_optional_diff_branch_suites_value()
    test_diff_branch_suites_requires_configured_branch_with_fixup_message()
    test_parser_rejects_primary_suite_path_with_repo_suite_flags()
    test_build_without_primary_suite_shows_all_suites_hint()
    test_root_suites_dispatches_once_per_root_suite()
    test_recursive_mx_args_preserve_global_option_values_matching_command_name()
    test_recursive_mx_args_strip_diff_branch_suites_with_explicit_value()
    test_all_suites_dispatches_once_per_discovered_suite()
    test_bulk_suite_run_preserves_live_command_output()
    test_bulk_suite_run_aborts_on_keyboard_interrupt()
    test_main_does_not_bulk_dispatch_suites()
    test_diff_path_selection_for_all_suites()
    test_diff_path_selection_for_root_suites()
    test_diff_path_selection_for_repo_level_change_selects_all()
    test_workspace_repo_level_change_selects_only_own_repo_suites()
    test_diff_path_selection_with_duplicate_names_selects_only_matching_suite()
    test_diff_suites_dispatches_once_per_selected_suite()
    test_skip_missing_imports_skips_all_selected_suites()
    test_skip_missing_imports_allows_other_selected_suites_to_run()
    test_summary_uses_suite_paths_for_duplicate_names()
    test_summary_distinguishes_missing_command_from_failure()
    test_diff_summary_uses_suite_paths_for_duplicate_names()
    test_multi_suite_flags_reject_primary_suite_path_from_env()
    test_multi_suite_flags_reject_primary_and_specific_suite_filters()
