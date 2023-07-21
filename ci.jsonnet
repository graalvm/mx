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
        name: "%s-jdk%s-%s-%s" % [self.prefix, java_release, os, arch],
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

    gate:: self.with_name("gate") + {
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
            [mx, "sclone", "--kind", "git", "--source", "https://github.com/oracle/graal.git", "--dest", "../graal"],
            [mx, "-p", "../graal/compiler", "build"],
            [mx, "-p", "../graal/compiler", "profrecord", "-E", "gate-xcomp", "$JAVA_HOME/bin/java", "-Xcomp", "foo", "||", "true"],
            [mx, "-p", "../graal/compiler", "profpackage", "gate-xcomp"],
            [mx, "-p", "../graal/compiler", "profhot", "gate-xcomp.zip"],
            [mx, "-p", "../graal/compiler", "profhot", "gate-xcomp"],
            [mx, "-p", "../graal/compiler", "profjson", "gate-xcomp", "-o", "prof_gate_xcomp.json"],
            [mx, "-p", "../graal/compiler", "benchmark", "dacapo:fop", "--tracker", "none", "--", "--profiler", "proftool"],
            [mx, "-p", "../graal/compiler", "profpackage", "-n", "proftool_fop_*"],
            [mx, "-p", "../graal/compiler", "profhot", "proftool_fop_*"],
            [mx, "-p", "../graal/compiler", "benchmark", "scala-dacapo:tmt", "--tracker", "none", "--", "--profiler", "proftool"],
            [mx, "-p", "../graal/compiler", "profpackage", "-D", "proftool_tmt_*"],
            [mx, "-p", "../graal/compiler", "profhot", "-c", "1", "-s", "proftool_tmt_*"],
            [mx, "-p", "../graal/vm", "--env", "ni-ce", "build"],
            [mx, "-p", "../graal/vm", "--env", "ni-ce", "benchmark", "renaissance-native-image:scrabble", "--tracker", "none", "--", "--jvm=native-image", "--jvm-config=default-ce", "--profiler", "proftool"],
            [mx, "profjson", "proftool_scrabble_*", "-o", "prof_scrabble.json"],
            [mx, "profhot", "proftool_scrabble_*"],
            [mx, "profrecord", "-E", "profrecord_scrabble", "../graal/vm/mxbuild/native-image-benchmarks/renaissance-*-scrabble-default-ce/renaissance-*-scrabble-default-ce", "scrabble"],
            [mx, "profhot", "profrecord_scrabble"]
        ]
    },

    fetchjdk_test:: self.with_name("fetch-jdk-test") + {
        local base_dir = "./fetch-jdk-test-folder",

        run: [
            [mx, "fetch-jdk", "--jdk-id", "labsjdk-ce-%s" % java_release, "--to", base_dir, "--alias", "jdk-%s" % java_release],
            [exe(base_dir + "/jdk-%s/bin/java" % java_release), "-version"],
        ],
        teardown: [
            ["rm", "-rf", "$base_dir"],
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

    build_truffleruby:: self.with_name("gate-build-truffleruby") + common.deps.sulong + common.deps.truffleruby + {
        environment+: {
            PATH: "$BUILD_DIR/main:$PATH", # add ./mx on PATH
        },
        run: [
            [mx, "sclone", "--kind", "git", "--source", "https://github.com/graalvm/truffleruby.git", "--dest", "../truffleruby"],
            ["cd", "../truffleruby"],
            ["bin/jt", "build", "--env", "native", "--native-images=truffleruby"],
            ["bin/jt", "-u", "native", "ruby", "-v", "-e", 'puts "Hello Ruby!"'],
        ],
    },

    build_graalvm_ce:: self.with_name("gate-build-graalvm-ce") + common.deps.sulong + {
        packages+: {
            make: ">=" + versions.make,
        },
        run: [
            [mx, "sclone", "--kind", "git", "--source", "https://github.com/oracle/graal.git", "--dest", "../graal"],
        ] + self.java_home_in_env("../graal/vm", "vm") + [
            [mx, "-p", "../graal/vm", "--env", "ce", "build"],
        ],
    },

    mx_unit_test:: self.with_name("unit-tests") + {
        environment+: {
            __MX_MODULE__: path("tests/benchmark_tests.py")
        },
        run: [
            [mx]
        ],
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
      targets: ["post-merge"],
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
    overlay: "d280a58c1a1ad015c7873c19818aae0910a64996",

    # For use by overlay
    versions:: versions,
    extra_catch_files:: extra_catch_files,
    primary_jdk_version:: 21,
    secondary_jdk_version:: 20,

    local builds = [
        with(common.linux_amd64, self.primary_jdk_version).gate,
        with(common.linux_amd64, self.primary_jdk_version).fetchjdk_test,
        with(common.linux_amd64, self.primary_jdk_version).bisect_test,
        with(common.windows_amd64, self.primary_jdk_version).gate,
        with(common.darwin_amd64, self.primary_jdk_version, timelimit="25:00").gate,
        with(common.darwin_aarch64, self.primary_jdk_version).gate,
        with(common.linux_amd64, self.primary_jdk_version).bench_test,
        with(common.linux_amd64, self.primary_jdk_version).jmh_test,
        with(common.linux_amd64, self.primary_jdk_version, timelimit="30:00").proftool_test,
        with(common.linux_amd64, self.primary_jdk_version, timelimit="20:00").build_truffleruby,
        with(common.linux_amd64, self.primary_jdk_version, timelimit="20:00").build_graalvm_ce,
        with(common.linux_amd64, self.primary_jdk_version).mx_unit_test,
        with(common.linux_amd64, self.primary_jdk_version).version_update_check,
        with(common.linux_amd64, self.primary_jdk_version).post_merge_tag_version,
    ],
    builds: [remove_mx_from_packages(b) for b in builds],
}
