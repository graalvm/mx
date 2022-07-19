local common = import "common.json";
local jdks = common.jdks;
local versions = {
    python3: "3.8.10",
    pylint: "2.4.4",
    gcc: "4.9.2",
    ruby: "2.7.2",
    git: "1.8.3",
    devtoolset: "7",
    make: "3.83",
    binutils: "2.34",
    capstone: "4.0.2",
};

# this uses <os>_<arch> or <os> depending on what field is available in 'common.json'
# if 'common.json' is migrated to jsonnet, we could simplify this by providing reasonable defaults there
local deps(project, os, arch) = if std.objectHasAll(common[project].deps, os) then common.sulong.deps[os] else common.sulong.deps[os + "_" + arch];

# Common configuration for all gates. Specific gates are defined
# by the functions at the bottom of this object.
#
# This structure allows for easily changing the
# platform details of a gate builder.
local with(os, arch, java_release, timelimit="15:00") = deps("sulong", os, arch) + {
    local path(unixpath) = if os == "windows" then std.strReplace(unixpath, "/", "\\") else unixpath,
    local exe(unixpath) = if os == "windows" then path(unixpath) + ".exe" else unixpath,
    local copydir(src, dst) = if os == "windows" then ["xcopy", path(src), path(dst), "/e", "/i", "/q"] else ["cp", "-r", src, dst],
    local mx_copy_dir = path("${PWD}/../path with a space"),
    local mx = path("./mx"),
    local openssl102_for_ruby = if os == "linux" && arch == "amd64" then {
      docker: {
        image: "phx.ocir.io/oraclelabs2/c_graal/buildslave:buildslave_ol7",
        mount_modules: true,
      },
    } else {},

    # Creates a builder name in "top down" order: first "what it is" (e.g. gate) then Java version followed by OS and arch
    with_name(prefix):: self + {
        name: "%s-jdk%s-%s-%s" % [prefix, java_release, os, arch],
    },

    python_version: "3",
    targets: ["gate"],
    capabilities: [os, arch],
    packages+: {
        "pip:pylint": "==" + versions.pylint,
        "gcc": "==" + versions.gcc,
        "python3": "==" + versions.python3,
    },
    downloads+: common.downloads.eclipse.downloads + {
        JAVA_HOME: jdks["labsjdk-ee-%s" % java_release]
    },
    environment: {
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

    java_home_in_env(suite_dir, suite_name):: [
        # Set JAVA_HOME *only* in <suite_dir>/mx.<suite>/env
        ["python3", "-c", "import os; open(r'" + path(suite_dir + "/mx.%s/env" % suite_name) + "', 'w').write('JAVA_HOME=' + os.environ['JAVA_HOME'])"],
        ["unset", "JAVA_HOME"],
    ],

    # Specific gate builders are defined by the following functions

    gate:: self.with_name("gate") + {
        environment+: {
            JDT: "builtin",
        },
        run: self.java_home_in_env(".", "mx") + [
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

    build_truffleruby:: self.with_name("gate-build-truffleruby") + deps("sulong", os, arch) + openssl102_for_ruby + {
        packages+: {
            ruby: ">=" + versions.ruby,
            python3: "==" + versions.python3,
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

    build_graalvm_ce:: self.with_name("gate-build-graalvm-ce") + deps("sulong", os, arch) + {
        packages+: {
            git: ">=" + versions.git,
            devtoolset: "==" + versions.devtoolset,
            make: ">=" + versions.make,
            binutils: "==" + versions.binutils,
            python3: "==" + versions.python3,
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
    specVersion: "3",

    # Overlay
    overlay: "35accb484712f25209a2bafd6cf699162a302c78",

    # For use by overlay
    versions:: versions,

    builds: [
        with("linux",   "amd64", 17).gate,
        with("linux",   "amd64", 17).fetchjdk_test,
        with("linux",   "amd64", 17).bisect_test,
        with("windows", "amd64", 17).gate,
        with("darwin",  "amd64", 17, timelimit="25:00").gate,
        with("linux",   "amd64", 17).bench_test,
        with("linux",   "amd64", 17).jmh_test,
        with("linux",   "amd64", 17, timelimit="20:00").proftool_test,
        with("linux",   "amd64", 11, timelimit="20:00").build_truffleruby,
        with("linux",   "amd64", 11, timelimit="20:00").build_graalvm_ce,
        with("linux",   "amd64", 17).mx_unit_test,
        with("linux",   "amd64", 17).version_update_check,
        with("linux",   "amd64", 17).post_merge_tag_version,
    ]
}
