local common = import "common.json";
local jdks = common.jdks;
local versions = {
    python3: "3.9.9",
    pylint: "1.9.3",
    gcc: "4.9.2",
    ruby: "2.7.2",
    git: "1.8.3",
    devtoolset: "7",
    make: "3.83",
    binutils: "2.34",
    capstone: "4.0.2",
};

# Common configuration for all gates. Specific gates are defined
# by the functions at the bottom of this object.
#
# This structure allows for easily changing the
# platform details of a gate builder.
local with(os, arch, java_release, timelimit="15:00", python=3) = common.sulong.deps[os] + {
    local path(unixpath) = if os == "windows" then std.strReplace(unixpath, "/", "\\") else unixpath,
    local exe(unixpath) = if os == "windows" then path(unixpath) + ".exe" else unixpath,
    local copydir(src, dst) = if os == "windows" then ["xcopy", path(src), path(dst), "/e", "/i", "/q"] else ["cp", "-r", src, dst],
    local mx_copy_dir = path("${PWD}/../path with a space"),
    local mx = path("./mx"),

    # Creates a builder name in "top down" order: first "what it is" (e.g. gate) then python and Java versions followed by OS and arch
    with_name(prefix):: self + {
        # Omit python version if it is 3 since that is the default
        local python_ver = if python == 3 then "" else "-python%s" % python,
        name: "%s%s-jdk%s-%s-%s" % [prefix, python_ver, java_release, os, arch],
    },

    targets: ["gate"],
    capabilities: [os, arch],
    packages+: {
        "pip:pylint": "==" + versions.pylint,
        "gcc": "==" + versions.gcc,
    },
    downloads+: common.downloads.eclipse.downloads + {
        JAVA_HOME: jdks["labsjdk-ee-%s" % java_release]
    },
    environment: {
        MX_PYTHON: "python%s" % python,
        ECLIPSE_EXE: if os == "darwin" then "$ECLIPSE/Contents/MacOS/eclipse" else exe("$ECLIPSE/eclipse"),
        # Required to keep pylint happy on Darwin
        # https://coderwall.com/p/-k_93g/mac-os-x-valueerror-unknown-locale-utf-8-in-python
        LC_ALL: "en_US.UTF-8",
    },
    timelimit: timelimit,
    setup: [
        # Copy mx to a directory with a space in its name to ensure
        # mx can work in that context.
        copydir("$PWD", mx_copy_dir),
        ["cd", mx_copy_dir],
    ] + if os == "darwin" then [
        # Need to remove the com.apple.quarantine attribute from Eclipse otherwise
        # it will fail to start on later macOS versions.
        ["xattr", "-d", "-r", "com.apple.quarantine", "${ECLIPSE}"],
    ] else [],

    # Specific gate builders are defined by the following functions

    gate:: self.with_name("gate") + {
        environment+: {
            JDT: "builtin",
        },
        run: [
            [mx, "--strict-compliance", "gate", "--strict-mode"] + if os == "windows" then ["--tags", "fullbuild"] else [],
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
        ]
    },

    proftool_test:: self.with_name("proftool-test") + {
        packages+: {
            "pip:capstone": ">=" + versions.capstone,
            "python": ">=3.4.1",
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
            [mx, "-p", "../graal/compiler", "benchmark", "dacapo:fop", "--tracker", "none", "--", "--profiler", "proftool"],
            [mx, "-p", "../graal/compiler", "profpackage", "-n", "proftool_fop_*"],
            [mx, "-p", "../graal/compiler", "profhot", "proftool_fop_*"],
            [mx, "-p", "../graal/compiler", "benchmark", "scala-dacapo:tmt", "--tracker", "none", "--", "--profiler", "proftool"],
            [mx, "-p", "../graal/compiler", "profpackage", "-D", "proftool_tmt_*"],
            [mx, "-p", "../graal/compiler", "profhot", "-c", "1", "-s", "proftool_tmt_*"]
        ]
    },

    fetchjdk_test:: self.with_name("fetch-jdk-test") + {
        local base_dir = "./fetch-jdk-test-folder",

        run: [
            [mx, "fetch-jdk", "--jdk-id", "labsjdk-ce-11", "--to", base_dir, "--alias", "jdk-11"],
            [exe(base_dir + "/jdk-11/bin/java"), "-version"],
            [mx, "fetch-jdk", "--jdk-id", "labsjdk-ce-17", "--to", base_dir, "--alias", "jdk-17"],
            [exe(base_dir + "/jdk-17/bin/java"), "-version"],
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

    build_truffleruby:: self.with_name("gate-build-truffleruby") + common.sulong.deps[os] + {
        packages+: {
            ruby: ">=" + versions.ruby
        },
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

    build_graalvm_ce:: self.with_name("gate-build-graalvm-ce") + common.sulong.deps[os] + {
        packages+: {
            git: ">=" + versions.git,
            devtoolset: "==" + versions.devtoolset,
            make: ">=" + versions.make,
            binutils: "==" + versions.binutils,
        },
        run: self.java_home_in_env("../graal/vm", "vm") + [
            [mx, "sclone", "--kind", "git", "--source", "https://github.com/oracle/graal.git", "--dest", "../graal"],
            [mx, "-p", "../graal/vm", "--env", "ce", "build"],
        ],
    },

    mx_unit_test:: self.with_name("unit-tests") + {
        run: [
            [ path("tests/run") ],
        ],
    },

    version_update_check:: self.with_name("version-update-check") + {
        run: [
            [ path("./tag_version.py"), "--check-only", "HEAD" ],
        ],
    },

    post_merge_tag_version:: self.with_name("post-merge-tag-version") + {
      targets: ["post-merge"],
      run: [
          [ path("./tag_version.py"), "HEAD" ],
      ],
      notify_groups:: ["mx_git_tag"]
    }
};

{
    # Overlay
    overlay: "fa7b89f39e034388b149591ef6fb706c72c8c29b",

    # For use by overlay
    versions:: versions,

    builds: [
        with("linux",   "amd64", 17, python=2).gate,
        with("linux",   "amd64", 17).gate,
        with("linux",   "amd64", 17).fetchjdk_test,
        with("linux",   "amd64", 17).bisect_test,
        with("windows", "amd64", 17).gate,
        with("darwin",  "amd64", 17, timelimit="25:00").gate,
        with("linux",   "amd64", 17).bench_test,
        with("linux",   "amd64", 17).jmh_test,
        with("linux",   "amd64", 17, timelimit="20:00").proftool_test,
        with("linux",   "amd64", 11, timelimit="20:00").build_truffleruby,
        with("linux",   "amd64", 11, timelimit="20:00", python=2).build_graalvm_ce,
        with("linux",   "amd64", 11, timelimit="20:00", python=3).build_graalvm_ce,
        with("linux",   "amd64", 17, python=2).mx_unit_test,
        with("linux",   "amd64", 17, python=3).mx_unit_test,
        with("linux",   "amd64", 17).version_update_check,
        with("linux",   "amd64", 17).post_merge_tag_version,
    ]
}
