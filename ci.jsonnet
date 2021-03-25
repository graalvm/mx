local common = import "common.json";
local jdks = common.jdks;
local
java = {
  downloads+: {
    JAVA_HOME: jdks.oraclejdk8
  }
},
oraclejdk_jvmci = jdks.oraclejdk8,

# Copy mx to a directory with a space in its name to ensure
# mx can work in that context.
setup_mx = {
    path(unixpath):: unixpath,
    exe(unixpath):: unixpath,
    copydir(src, dst):: ["cp", "-r", src, dst],
    environment+: {
        MX_COPY: $.path("${PWD}/../path with a space")
    },
    setup+: [
        self.copydir("$PWD", "${MX_COPY}"),
        ["cd", "${MX_COPY}"],
    ]
},

gate = setup_mx + java + {
  targets: ['gate'],
  packages+: {
    "pip:pylint": "==1.9.3",
  },
  downloads+: {
    JDT: {name: 'ecj', version: "4.14.0", platformspecific: false},
    ECLIPSE: {name: 'eclipse', version: "4.14.0", platformspecific: true},
  },
  environment+: {
    # Required to keep pylint happy on Darwin
    # https://coderwall.com/p/-k_93g/mac-os-x-valueerror-unknown-locale-utf-8-in-python
    LC_ALL: "en_US.UTF-8",
  },
  run: [
    ["./mx", "--strict-compliance", "gate", "--strict-mode"],
  ],
  timelimit: "10:00",
},
gate_unix = common.sulong.deps.linux + gate + {
  environment+: {
    ECLIPSE_EXE: "$ECLIPSE/eclipse",
  }
},
gate_darwin = common.sulong.deps.darwin + gate + {
  environment+: {
    ECLIPSE_EXE: "$ECLIPSE/Contents/MacOS/eclipse",
  }
},
gate_windows = gate + {
  path(unixpath):: std.strReplace(unixpath, "/", "\\"),
  exe(unixpath):: self.path(unixpath) + ".exe",
  copydir(src, dst):: ["xcopy", self.path(src), self.path(dst), "/e", "/i", "/q"],
  environment+: {
    ECLIPSE_EXE: "$ECLIPSE\\eclipse.exe",
  },
  run: [
    ["./mx", "--strict-compliance", "gate", "--strict-mode", "--tags", "fullbuild"],
  ],
},
bench_test = setup_mx + java + {
  targets: ['gate'],
  run: [
    ["./mx", "benchmark", "--results-file", "bench-results.json", "--ignore-suite-commit-info=mx", "test"],
  ],
  teardown: [
    ["bench-uploader.py", "bench-results.json"],
  ],
},
jmh_test = setup_mx + java + {
  targets: ['gate'],
  setup:  [
    ["./mx", "build"],
  ],
  run: [
    ["./mx", "benchmark", "--ignore-suite-commit-info=mx", "jmh-dist:*"],
  ]
},
downstream_truffleruby = common.sulong.deps.linux + {
  targets: ['gate'],
  downloads+: {
    JAVA_HOME: oraclejdk_jvmci,
  },
  packages+: {
    ruby: ">=2.0.0",
  },
  environment+: {
    PATH: "$BUILD_DIR/main:$LLVM/bin:$PATH",
  },
  run: [
    ["./mx", 'testdownstream', '--repo', "https://github.com/graalvm/truffleruby.git", '--mx-command', "ruby_testdownstream_hello"],
  ],
  timelimit: "10:00",
},
nocache = {
  environment+: {
    MX_CACHE_DIR: "/tmp/.gate_fresh_mx_cache",
  },
  setup: [
    ['rm', '-rf', "/tmp/.gate_fresh_mx_cache"],
  ],
  teardown: [
    ['rm', '-rf', "/tmp/.gate_fresh_mx_cache"],
  ],
},
build_graalvm_ce_linux = setup_mx + common.sulong.deps.linux + {
  packages+: {
    git: '>=1.8.3',
    gcc: '==4.9.2',
    make: '>=3.83',
    binutils: '==2.23.2',
  },
  downloads+: {
    JAVA_HOME: jdks.openjdk8,
  },
  run: [
    ['git', 'clone', '--depth=1', '-b', 'cpu/graal-vm/20.3', 'https://github.com/oracle/graal.git', '../graal'],
    ['./mx', '-p', '../graal/vm', '--env', 'ce', 'build'],
  ],
  targets: ['gate'],
  timelimit: '20:00',
},
python2 = {
  environment+: {
    MX_PYTHON_VERSION: "2",
  },
},
python3 = {
  environment+: {
    MX_PYTHON_VERSION: "3",
  },
},
mx_fetchjdk_test = {
  environment+: {
    FETCH_JDK_TEST_FOLDER: "fetch-jdk-test-folder/",
  },
  run: [
    ['./mx', 'fetch-jdk', '--java-distribution', 'labsjdk-ce-11', '--to', '$FETCH_JDK_TEST_FOLDER', '--alias', 'jdk-11'],
    ['./$FETCH_JDK_TEST_FOLDER/jdk-11/bin/java', '-version'],
    ['./mx', 'fetch-jdk', '--java-distribution', 'openjdk8', '--to', '$FETCH_JDK_TEST_FOLDER', '--alias', 'jdk-8'],
    ['./$FETCH_JDK_TEST_FOLDER/jdk-8/bin/java', '-version'],
  ],
  teardown: [
    ['rm', '-rf', '$FETCH_JDK_TEST_FOLDER'],
  ],
},
mx_bisect_test = {
  setup: [
    ['git', 'config', 'user.email', "andrii.rodionov@oracle.com"],
    ['git', 'config', 'user.name', "Andrii Rodionov"],
  ],
  run: [
    ['./mx', 'bisect', '--strategy', 'bayesian', 'selfcheck'],
    ['./mx', 'bisect', '--strategy', 'bisect', 'selfcheck'],
  ],
  teardown: [
    ['rm', '-f', 'mxbuild/bisect_*.log'],
  ],
}
;

{
  # Overlay
  java8: oraclejdk_jvmci,
  java11: jdks['labsjdk-ee-11'],
  overlay: '44403c66cf7fdace76f4db16fd6a9e4467687235',

  builds: [
    gate_unix +    {capabilities: ['linux', 'amd64'],   name: "gate-linux-amd64-python2"} + python2,
    gate_unix +    {capabilities: ['linux', 'amd64'],   name: "gate-linux-amd64-python3"} + python3,
    gate_unix +    {capabilities: ['linux', 'amd64'],   name: "gate-linux-amd64-python3-fetch-jdk-test"} + python3 + mx_fetchjdk_test,
    gate_unix +    {capabilities: ['linux', 'amd64'],   name: "gate-linux-amd64-python3-bisect-test"} + python3 + mx_bisect_test,
    gate_darwin +  {capabilities: ['darwin_sierra', 'amd64'],  name: "gate-darwin-amd64-python3"} + python3,
    gate_windows + {capabilities: ['windows', 'amd64'], name: "gate-windows-amd64"},
    bench_test +   {capabilities: ['linux', 'amd64'],   name: "bench-linux-amd64"},
    jmh_test +     {capabilities: ['linux', 'amd64'],   name: "test-jmh-linux-amd64"},
    downstream_truffleruby +           {capabilities: ['linux', 'amd64'], name: "downstream-truffleruby-binary-truffle"},
    downstream_truffleruby + nocache + {capabilities: ['linux', 'amd64'], name: "downstream-truffleruby-binary-truffle-nocache"},
    build_graalvm_ce_linux +           {capabilities: ['linux', 'amd64'], name: "gate-build-graalvm-ce-linux-amd64-python2"} + python2,
    build_graalvm_ce_linux +           {capabilities: ['linux', 'amd64'], name: "gate-build-graalvm-ce-linux-amd64-python3"} + python3,

    {
      capabilities: ['linux', 'amd64'], targets: ['gate'], name: "gate-version-update-check",
      run: [
        [ "./tag_version.py", "--check-only", "HEAD" ],
      ],
    },
    {
      capabilities: ['linux', 'amd64'], targets: ['post-merge'], name: "post-merge-tag-version",
      run: [
        [ "./tag_version.py", "HEAD" ],
      ],
      notify_emails: [ "doug.simon@oracle.com" ],
    }
  ]
}
