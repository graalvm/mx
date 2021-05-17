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
  },
  setup+: [
      # Need to remove the com.apple.quarantine attribute from Eclipse otherwise
      # it will fail to start on later macOS versions. 
      ["xattr", "-d", "-r", "com.apple.quarantine", "${ECLIPSE}"],
  ]
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
build_truffleruby = common.sulong.deps.linux + {
  targets: ['gate'],
  downloads+: {
    JAVA_HOME: common.jdks["labsjdk-ce-11"],
  },
  packages+: {
    ruby: ">=2.7.2",
  },
  environment+: {
    PATH: "$BUILD_DIR/main:$PATH", # add ./mx on PATH
  },
  run: [
    ['mx', 'sclone', '--kind', 'git', '--source', 'https://github.com/graalvm/truffleruby.git', '--dest', '../truffleruby'],
    ['cd', '../truffleruby'],
    ['bin/jt', 'build', '--env', 'native', '--native-images=truffleruby'],
    ['bin/jt', '-u', 'native', 'ruby', '-v', '-e', 'puts "Hello Ruby!"'],
  ],
  timelimit: "20:00",
},
build_graalvm_ce_linux = setup_mx + common.sulong.deps.linux + {
  packages+: {
    git: '>=1.8.3',
    devtoolset: '==7',
    make: '>=3.83',
    binutils: '==2.34',
  },
  downloads+: {
    JAVA_HOME: jdks.openjdk8,
  },
  run: [
    ['./mx', 'sclone', '--kind', 'git', '--source', 'https://github.com/oracle/graal.git', '--dest', '../graal'],
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
  overlay: 'd136a8a8b0820954ada5a53cf6f1413c825128fb',

  builds: [
    gate_unix +    {capabilities: ['linux', 'amd64'],   name: "gate-linux-amd64-python2"} + python2,
    gate_unix +    {capabilities: ['linux', 'amd64'],   name: "gate-linux-amd64-python3"} + python3,
    gate_unix +    {capabilities: ['linux', 'amd64'],   name: "gate-linux-amd64-python3-fetch-jdk-test"} + python3 + mx_fetchjdk_test,
    gate_unix +    {capabilities: ['linux', 'amd64'],   name: "gate-linux-amd64-python3-bisect-test"} + python3 + mx_bisect_test,
    gate_darwin +  {capabilities: ['darwin', 'amd64'],  name: "gate-darwin-amd64-python3", timelimit: "12:00"} + python3,
    gate_windows + {capabilities: ['windows', 'amd64'], name: "gate-windows-amd64"},
    bench_test +   {capabilities: ['linux', 'amd64'],   name: "bench-linux-amd64"},
    jmh_test +     {capabilities: ['linux', 'amd64'],   name: "test-jmh-linux-amd64"},
    build_truffleruby + {capabilities: ['linux', 'amd64'], name: "gate-build-truffleruby-native-linux-amd64"},
    build_graalvm_ce_linux + {capabilities: ['linux', 'amd64'], name: "gate-build-graalvm-ce-linux-amd64-python2"} + python2,
    build_graalvm_ce_linux + {capabilities: ['linux', 'amd64'], name: "gate-build-graalvm-ce-linux-amd64-python3"} + python3,

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
