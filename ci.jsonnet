local common = import "ci/common.jsonnet";
local versions = {
    gcc: "4.9.2",
    make: "3.83",
    capstone: "4.0.2",
};
local extra_catch_files = [
  "Cannot decode '(?P<filename>[^']+)'"
];
local remove_mx_from_packages(obj) = obj + {
    # Exclude mx from packages
    packages: {
        [key]: obj.packages[key]
        for key in std.objectFields(obj.packages) if key != "mx"
    },
};

# Common configuration for all gates. Specific gates are defined
# by the functions at the bottom of this object.
#
# This structure allows for easily changing the
# platform details of a gate builder.
local with(platform, java_release, timelimit="15:00") = {
    local os = platform.os,
    local arch = platform.arch,
    local path(unixpath) = if os == "windows" then std.strReplace(unixpath, "/", "\\") else unixpath,
    local exe(unixpath) = if os == "windows" then path(unixpath) + ".exe" else unixpath,
    local copydir(src, dst) = if os == "windows" then ["xcopy", path(src), path(dst), "/e", "/i", "/q"] else ["cp", "-r", src, dst],
    local mx_copy_dir = path("${PWD}/../path with a space"),
    local mx = path("./mx"),
    local jdk = common.jdks["labsjdk-ee-%s" % java_release],

    local base = platform + jdk + common.deps.pylint + common.deps.sulong + common.deps.svm + {
        # Creates a builder name in "top down" order: first "what it is" (e.g. gate) then Java version followed by OS and arch
        name: "%s-jdk-%s-%s-%s" % [self.prefix, java_release, os, arch],
        catch_files+: extra_catch_files,
        timelimit: timelimit,
        setup: [
            # Copy mx to a directory with a space in its name to ensure
            # mx can work in that context.
            copydir("$PWD", mx_copy_dir),
            ["cd", mx_copy_dir],
        ],

        java_home_in_env(suite_dir, suite_name):: [
            # Set JAVA_HOME *only* in <suite_dir>/mx.<suite>/env
            ["python3", "-c", "import os; open(r'" + path(suite_dir + "/mx.%s/env" % suite_name) + "', 'w').write('JAVA_HOME=' + os.environ['JAVA_HOME'])"],
            ["unset", "JAVA_HOME"],
        ],
    },

    with_name(prefix):: base + {
        prefix:: prefix,
    },

    # Specific gate builders are defined by the following functions

    gate:: self.with_name("gate") + common.deps.black + common.deps.spotbugs + common.deps.maven + {
        environment+: {
            MX_ALT_OUTPUT_ROOT: path("$BUILD_DIR/alt_output_root"),
            JDT: "builtin",
        },
        run: self.java_home_in_env(".", "mx") + [
            [mx, "--strict-compliance", "gate", "--strict-mode"]
            + (if os == "windows" then ["--tags", "fullbuild"] else []),
        ],
    },

    bench_test:: self.with_name("bench-test") + {
        run: [
            [mx, "benchmark", "--results-file", "bench-results.json", "test"],
        ],
        teardown: [
            ["bench-uploader.py", "bench-results.json"],
        ],
    },

    jmh_test:: self.with_name("jmh-test") + {
        setup:  [
            [mx, "build"],
        ],
        run: [
            [mx, "benchmark", "jmh-dist:*"],
            ['set-export', 'PYTHONPATH', '${PWD}/src:${PYTHONPATH}'],
            ["python3", path("tests/jmh_filtering_tests.py")],
        ]
    },

    fetchjdk_test:: self.with_name("fetch-jdk-test") + {
        local base_dir = path("./fetch-jdk-%s-test-folder" % java_release),

        run: [
            [mx, "fetch-jdk", "--jdk-id", "labsjdk-ce-%s" % java_release, "--to", base_dir, "--alias", "jdk-%s" % java_release],
            [exe(base_dir + "/jdk-%s/bin/java" % java_release), "-version"],
        ],
    },

    bisect_test:: self.with_name("bisect-test") + {
        setup: [
            ["git", "config", "user.email", "andrii.rodionov@oracle.com"],
            ["git", "config", "user.name", "Andrii Rodionov"],
        ],
        run: [
            [mx, "bisect", "--strategy", "bayesian", "selfcheck"],
            [mx, "bisect", "--strategy", "bisect", "selfcheck"],
        ],
        teardown: [
            ["rm", "-f", "mxbuild/bisect_*.log"],
        ],
    },

    mx_unit_test:: self.with_name("unit-tests") + common.deps.maven + {
        run: [
            ['set-export', 'PYTHONPATH', '${PWD}/src:${PYTHONPATH}'],
            ['python3', path('tests/benchmark_tests.py')],
            ['python3', path('tests/eclipseformat_tests.py')],
            ['python3', '-m', 'unittest', '--verbose']
        ],
    },

    mx_mergetool_gate:: self.with_name("gate-mergetool-tests") + {
        local test_mergetool(repo, local_rev, remote_rev, reference_rev) = [
          # git setup
          ["git", "-C", repo, "config", "user.name", "ol-automation_ww"],
          ["git", "-C", repo, "config", "user.email", "ol-automation_ww@oracle.com"],
          ["git", "-C", repo, "config", "mergetool.mx-suite-import.cmd",
            # use printf subcommand to work around environment variable substitution of $LOCAL, $BASE, etc. [GR-52812]
            ["printf", '${MX_HOME}/' + mx + ' -p ${MX_HOME} mergetool-suite-import "\\x24LOCAL" "\\x24BASE" "\\x24REMOTE" "\\x24MERGED"']
          ],
          ["git", "-C", repo, "config", "mergetool.mx-suite-import.trustExitCode", "true"],
          # merging
          ["git", "-C", repo, "checkout", local_rev],
          ["git", "-C", repo, "merge", "--no-ff", "--no-commit", remote_rev, "||", "git", "-C", repo, "mergetool", "--no-prompt", "--tool", "mx-suite-import"],
          ["test", "-z", ["git", "-C", repo, "diff", reference_rev]],
        ],
      local simple_test_repo = "test_repo_simple",
      local complex_test_repo = "test_repo_complex",
      setup: [
        ["set-export", "MX_HOME", ["pwd"]],
        ["python3", path("tests/create_mergetool_test_repos.py"), simple_test_repo, complex_test_repo],
      ],
      run:
        test_mergetool(simple_test_repo, "local", "remote", "expected") +
        test_mergetool(complex_test_repo, "local", "remote", "expected"),
    },

    version_update_check:: self.with_name("version-update-check") + {
        run: [
            [ path("./ci/check_version.py") ],
        ],
    },

    # Applies and pushes a tag equal to `mx version` if no such
    # tag already exists.
    post_merge_tag_version:: self.with_name("post-merge-tag-version") + {
      targets: ["post-merge", "deploy"],
      run: [
          ["set-export", "MX_NEW_TAG", [mx, "version"]],
          ["git", "show", "$MX_NEW_TAG", "||", "git", "tag", "$MX_NEW_TAG", "HEAD"],
          ["git", "push", "origin", "$MX_NEW_TAG"],
      ],
      notify_groups:: ["mx_git_tag"]
    }
};

{
    specVersion: "3",

    tierConfig: {
        tier1: "gate",
        tier2: "gate",
    },

    # Shared configuration values
    versions:: versions,
    extra_catch_files:: extra_catch_files,
    primary_jdk_version:: "latest",
    secondary_jdk_version:: 21,

    local tier1(build) = build + common.frequencies.tier1,
    local tier2(build) = build + common.frequencies.tier2,

    local builds = [
        tier2(with(common.linux_amd64, self.primary_jdk_version).gate),
        tier2(with(common.linux_amd64, self.primary_jdk_version).fetchjdk_test),
        tier2(with(common.windows_amd64, self.primary_jdk_version).fetchjdk_test),
        tier2(with(common.linux_amd64, self.primary_jdk_version).bisect_test),
        tier2(with(common.windows_amd64, self.primary_jdk_version).gate),
        tier2(with(common.darwin_aarch64, self.primary_jdk_version).gate),
        tier2(with(common.linux_amd64, self.primary_jdk_version).bench_test),
        tier2(with(common.linux_amd64, self.primary_jdk_version).jmh_test),
        tier2(with(common.linux_amd64, self.primary_jdk_version).mx_unit_test),
        tier2(with(common.linux_amd64, self.primary_jdk_version).mx_mergetool_gate),
        tier1(with(common.linux_amd64, self.primary_jdk_version).version_update_check),
        with(common.linux_amd64, self.primary_jdk_version).post_merge_tag_version,

        tier2(with(common.linux_amd64, self.secondary_jdk_version).gate),
        tier2(with(common.windows_amd64, self.secondary_jdk_version).gate),
        tier2(with(common.darwin_aarch64, self.secondary_jdk_version).gate),
    ],
    builds: [remove_mx_from_packages(b) for b in builds],
}
