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
    local eclipse_dep = if arch == "amd64" then common.deps.eclipse + {
        environment+: {
            ECLIPSE_EXE: if os == "darwin" then "$ECLIPSE/Contents/MacOS/eclipse" else exe("$ECLIPSE/eclipse")
        }
    } else {
        # No CI Eclipse packages available on AArch64
    },

    local base = platform + jdk + eclipse_dep + common.deps.pylint + common.deps.sulong + common.deps.svm + {
        # Creates a builder name in "top down" order: first "what it is" (e.g. gate) then Java version followed by OS and arch
        name: "%s-jdk-%s-%s-%s" % [self.prefix, java_release, os, arch],
        targets: ["gate"],
        catch_files+: extra_catch_files,
        timelimit: timelimit,
        setup: [
            # Copy mx to a directory with a space in its name to ensure
            # mx can work in that context.
            copydir("$PWD", mx_copy_dir),
            ["cd", mx_copy_dir],
        ] + if os == "darwin" && eclipse_dep != {} then [
            # Need to remove the com.apple.quarantine attribute from Eclipse otherwise
            # it will fail to start on later macOS versions.
            ["xattr", "-d", "-r", "com.apple.quarantine", "${ECLIPSE}"],
        ] else [],

        java_home_in_env(suite_dir, suite_name):: [
            # Set JAVA_HOME *only* in <suite_dir>/mx.<suite>/env
            ["python3", "-c", "import os; open(r'" + path(suite_dir + "/mx.%s/env" % suite_name) + "', 'w').write('JAVA_HOME=' + os.environ['JAVA_HOME'])"],
            ["unset", "JAVA_HOME"],
        ],
    },

    with_name(prefix):: base + {
        prefix:: prefix,
    } + if prefix != "version-update-check" && prefix != "verify-graal-common-sync" then {
        requireArtifacts: [
            {name: "version-update-check"},
            {name: "verify-graal-common-sync"}
        ],
    } else {},

    # Specific gate builders are defined by the following functions

    gate:: self.with_name("gate") + common.deps.black + common.deps.spotbugs +{
        environment+: {
            MX_ALT_OUTPUT_ROOT: path("$BUILD_DIR/alt_output_root"),
            JDT: "builtin",
        },
        run: self.java_home_in_env(".", "mx") + [
            [mx, "--strict-compliance", "gate"]
            + (if eclipse_dep != {} then ["--strict-mode"] else [])
            + (if os == "windows" then ["--tags", "fullbuild"] else []),
        ],
    },

    bench_test:: self.with_name("bench-test") + {
        run: [
            [mx, "benchmark", "--results-file", "bench-results.json", "--ignore-suite-commit-info=mx", "test"],
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
            [mx, "benchmark", "--ignore-suite-commit-info=mx", "jmh-dist:*"],
            ['set-export', 'PYTHONPATH', '${PWD}/src:${PYTHONPATH}'],
            ["python3", path("tests/jmh_filtering_tests.py")],
        ]
    },

    proftool_test:: self.with_name("proftool-test") + {
        packages+: {
            "pip:capstone": ">=" + versions.capstone,
        },
        setup:  [
            [mx, "build"],
        ],
        run: [
            [mx, "sclone", "--kind", "git", "--source", "https://github.com/oracle/graal.git", "--branch", "cpu/graal-vm/24.1", "--dest", "../graal"],
            [mx, "-p", "../graal/compiler", "build"],
            [mx, "-p", "../graal/compiler", "profrecord", "-E", "gate-xcomp", "$JAVA_HOME/bin/java", "-Xcomp", "foo", "||", "true"],
            [mx, "-p", "../graal/compiler", "profpackage", "gate-xcomp"],
            [mx, "-p", "../graal/compiler", "profhot", "gate-xcomp.zip"],
            [mx, "-p", "../graal/compiler", "profhot", "gate-xcomp"],
            [mx, "-p", "../graal/compiler", "profjson", "gate-xcomp", "-o", "prof_gate_xcomp.json"],
            [mx, "-p", "../graal/compiler", "benchmark", "dacapo:fop", "--tracker", "none", "--", "--profiler", "proftool"],
            ["set-export", "PROFTOOL_FOP_LAST", ["printf", "%s\n", "proftool_fop_*", "|", "sort", "|", "tail", "-n", "1"]],
            [mx, "-p", "../graal/compiler", "profpackage", "-n", "$PROFTOOL_FOP_LAST"],
            [mx, "-p", "../graal/compiler", "profhot", "$PROFTOOL_FOP_LAST"],
            [mx, "-p", "../graal/compiler", "benchmark", "scala-dacapo:tmt", "--tracker", "none", "--", "--profiler", "proftool"],
            ["set-export", "PROFTOOL_TMT_LAST", ["printf", "%s\n", "proftool_tmt_*", "|", "sort", "|", "tail", "-n", "1"]],
            [mx, "-p", "../graal/compiler", "profpackage", "-D", "$PROFTOOL_TMT_LAST"],
            [mx, "-p", "../graal/compiler", "profhot", "-c", "1", "-s", "${PROFTOOL_TMT_LAST}.zip"],
            [mx, "-p", "../graal/vm", "--env", "ni-ce", "build"],
            [mx, "-p", "../graal/vm", "--env", "ni-ce", "benchmark", "renaissance-native-image:scrabble", "--tracker", "none", "--", "--jvm=native-image", "--jvm-config=default-ce", "--profiler", "proftool"],
            ["set-export", "PROFTOOL_SCRABBLE_LAST", ["printf", "%s\n", "proftool_scrabble_*", "|", "sort", "|", "tail", "-n", "1"]],
            [mx, "profjson", "$PROFTOOL_SCRABBLE_LAST", "-o", "prof_scrabble.json"],
            [mx, "profhot", "$PROFTOOL_SCRABBLE_LAST"],
            [mx, "profrecord", "-E", "profrecord_scrabble", "../graal/vm/mxbuild/native-image-benchmarks/renaissance-*-scrabble-default-ce/renaissance-*-scrabble-default-ce", "scrabble"],
            [mx, "profhot", "profrecord_scrabble"]
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

    build_graalvm_ce:: self.with_name("gate-build-graalvm-ce") + common.deps.sulong + common.deps.truffleruby + {
        packages+: {
            make: ">=" + versions.make,
        },
        run: [
            [mx, "sclone", "--kind", "git", "--source", "https://github.com/oracle/graal.git", "--branch", "cpu/graal-vm/24.1", "--dest", "../graal"],
        ] + self.java_home_in_env("../graal/vm", "vm") + [
            # Test the ce env file
            [mx, "-p", "../graal/vm", "--env", "ce", "build"],
            # Also test building Truffle languages
            [mx, "-p", "../graal/vm", "--dy", "truffleruby", "sforceimports"],
            [mx, "-p", "../graal/vm", "--dy", "truffleruby", "--env", "../../../truffleruby/mx.truffleruby/native", "graalvm-show"],
            [mx, "-p", "../graal/vm", "--dy", "truffleruby", "--env", "../../../truffleruby/mx.truffleruby/native", "build"],
        ],
    },

    mx_unit_test:: self.with_name("unit-tests") + {
        run: [
            ['set-export', 'PYTHONPATH', '${PWD}/src:${PYTHONPATH}'],
            ['python3', path('tests/benchmark_tests.py')]
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
          ["git", "-C", repo, "merge", "--no-ff", "--no-commit", remote_rev, "||", "git", "-C", repo, "mergetool", "--tool", "mx-suite-import"],
          ["test", "-z", ["git", "-C", repo, "diff", reference_rev]],
        ],
      local test_repo = "test_repo",
      environment+: {
        MERGETOOL_TEST_REPO: "<mergetool-test-repo>",
      },
      setup: [
        ["set-export", "MX_HOME", ["pwd"]],
        ["git", "clone", "--branch", "cpu/graal-vm/24.1", "${MERGETOOL_TEST_REPO}", test_repo],
      ],
      run:
        test_mergetool(test_repo, "caffcf0fe72", "172acf1141f", "ebf58d86069f5450adfe4a617aa3b52a9887a257")+ # GR-54826
        test_mergetool(test_repo, "195c215f9cf", "a6862ad4f37", "8f54cbb8faed3a765069d81b4f075b923bf39533 "), # GR-54649
    },

    version_update_check:: self.with_name("version-update-check") + {
        publishArtifacts: [
          {
            name: "version-update-check",
            patterns: ["version-update-check.ok"]
          }
        ],
        run: [
            [ path("./ci/check_version.py") ],
            [ "touch", "$PWD/version-update-check.ok" ]
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

    # Overlay
    overlay: "7a409577b7cc99b8e4f6192d988dc0519ffea0fe",

    # For use by overlay
    versions:: versions,
    extra_catch_files:: extra_catch_files,
    primary_jdk_version:: "latest",
    secondary_jdk_version:: 21,

    local builds = [
        with(common.linux_amd64, self.primary_jdk_version).gate,
        with(common.linux_amd64, self.primary_jdk_version).fetchjdk_test,
        with(common.windows_amd64, self.primary_jdk_version).fetchjdk_test,
        with(common.linux_amd64, self.primary_jdk_version).bisect_test,
        with(common.windows_amd64, self.primary_jdk_version).gate,
        with(common.darwin_amd64, self.primary_jdk_version, timelimit="25:00").gate,
        with(common.darwin_aarch64, self.primary_jdk_version).gate,
        with(common.linux_amd64, self.primary_jdk_version).bench_test,
        with(common.linux_amd64, self.primary_jdk_version).jmh_test,
        with(common.linux_amd64, self.primary_jdk_version, timelimit="30:00").proftool_test,
        with(common.linux_amd64, self.primary_jdk_version, timelimit="30:00").build_graalvm_ce,
        with(common.linux_amd64, self.primary_jdk_version).mx_unit_test,
        with(common.linux_amd64, self.primary_jdk_version).mx_mergetool_gate,
        with(common.linux_amd64, self.primary_jdk_version).version_update_check,
        with(common.linux_amd64, self.primary_jdk_version).post_merge_tag_version,

        with(common.linux_amd64, self.secondary_jdk_version).gate,
        with(common.windows_amd64, self.secondary_jdk_version).gate,
        with(common.darwin_amd64, self.secondary_jdk_version, timelimit="25:00").gate,
        with(common.darwin_aarch64, self.secondary_jdk_version).gate,
    ],
    builds: [remove_mx_from_packages(b) for b in builds],
}
