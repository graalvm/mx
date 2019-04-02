local
java = {
  downloads+: {
    JAVA_HOME: {name: 'oraclejdk', version: "8u202", platformspecific: true}
  }
},
labsjdk8 = {name: 'labsjdk', version: "8u202-jvmci-0.58", platformspecific: true},
gate = java + {
  targets: ['gate'],
  packages+: {
    "pip:pylint": "==1.9.3",
  },
  downloads+: {
    JDT: {name: 'ecj', version: "4.5.1", platformspecific: false},
    ECLIPSE: {name: 'eclipse', version: "4.5.2", platformspecific: true},
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
gate_unix = gate + {
  environment+: {
    ECLIPSE_EXE: "$ECLIPSE/eclipse",
  }
},
gate_darwin = gate + {
  environment+: {
    ECLIPSE_EXE: "$ECLIPSE/Contents/MacOS/eclipse",
  }
},
gate_windows = gate + {
  environment+: {
    ECLIPSE_EXE: "$ECLIPSE\\eclipse.exe",
  },
  run: [
    ["./mx", "--strict-compliance", "gate", "--strict-mode", "--tags", "fullbuild"],
  ],
},
bench_test = java + {
  targets: ['gate'],
  run: [
    ["./mx", "benchmark", "--results-file", "bench-results.json", "--ignore-suite-commit-info=mx", "test"],
  ],
  teardown: [
    ["bench-uploader.py", "--url", "$BENCH_SERVER_URL", "bench-results.json"],
  ],
},
jmh_test = java + {
  targets: ['gate'],
  setup:  [
    ["./mx", "build"],
  ],
  run: [
    ["./mx", "benchmark", "--ignore-suite-commit-info=mx", "jmh-dist:*"],
  ]
},
downstream_truffleruby = {
  targets: ['gate'],
  downloads+: {
    JAVA_HOME: labsjdk8,
  },
  packages+: {
    llvm: "==3.8",
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
python2 = {
  environment+: {
    MX_PYTHON_VERSION: "2",
  },
},
python3 = {
  environment+: {
    MX_PYTHON_VERSION: "3",
  },
}
;

{
  # Overlay
  java8: labsjdk8,
  java11: {name: 'oraclejdk', version: "11+28", platformspecific: true},
  overlay: '2cf9d7ec2c131d8e999c11e4de289fa003faaebd',

  builds: [
    gate_unix +    {capabilities: ['linux', 'amd64'],   name: "gate-linux-amd64-python2"} + python2,
    gate_unix +    {capabilities: ['linux', 'amd64'],   name: "gate-linux-amd64-python3"} + python3,
    gate_darwin +  {capabilities: ['darwin_sierra', 'amd64'],  name: "gate-darwin-amd64-python3"} + python3,
    gate_windows + {capabilities: ['windows', 'amd64'], name: "gate-windows-amd64"},
    bench_test +   {capabilities: ['linux', 'amd64'],   name: "bench-linux-amd64"},
    jmh_test +     {capabilities: ['linux', 'amd64'],   name: "test-jmh-linux-amd64"},
    downstream_truffleruby +           {capabilities: ['linux', 'amd64'], name: "downstream-truffleruby-binary-truffle"},
    downstream_truffleruby + nocache + {capabilities: ['linux', 'amd64'], name: "downstream-truffleruby-binary-truffle-nocache"},

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
