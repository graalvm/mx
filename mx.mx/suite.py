suite = {
  "name" : "mx",
  "libraries" : {

    # ------------- Libraries -------------

    "JACOCOCORE_0.8.4" : {
      "sha1" : "53addc878614171ff0fcbc8f78aed12175c22cdb",
      "sourceSha1" : "9bd1fa334d941005bc9ab3ac92478a590f5b7d73",
      "maven" : {
        "groupId" : "org.jacoco",
        "artifactId" : "org.jacoco.core",
        "version" : "0.8.4",
      },
      "dependencies" : ["ASM_7.1", "ASM_COMMONS_7.1", "ASM_TREE_7.1"],
      "licence": "EPL-1.0",
    },

    "JACOCOAGENT_0.8.4" : {
      "sha1" : "869021a6d90cfb008b12e83fccbe42eca29e5355",
      # Cannot download sources for "maven" library with "classifier" attribute
      "maven" : {
        "groupId" : "org.jacoco",
        "artifactId" : "org.jacoco.agent",
        "version" : "0.8.4",
        "classifier" : "runtime",
      },
      "licence": "EPL-1.0",
    },

    "JACOCOREPORT_0.8.4" : {
      "sha1" : "e5ca9511493b7e3bc2cabdb8ded92e855f3aac32",
      "sourceSha1" : "eb61e479b35b467954f28a565c094c563b790e19",
      "maven" : {
        "groupId" : "org.jacoco",
        "artifactId" : "org.jacoco.report",
        "version" : "0.8.4",
      },
      "dependencies" : ["JACOCOCORE_0.8.4"],
      "licence": "EPL-1.0",
    },

    "ASM_7.1": {
      "sha1": "fa29aa438674ff19d5e1386d2c3527a0267f291e",
      "sourceSha1" : "9d170062d595240da35301362b079e5579c86f49",
      "maven": {
        "groupId": "org.ow2.asm",
        "artifactId": "asm",
        "version": "7.1",
      },
      "license": "BSD-new",
    },

    "ASM_ANALYSIS_7.1": {
      "sha1": "379e0250f7a4a42c66c5e94e14d4c4491b3c2ed3",
      "sourceSha1" : "36789198124eb075f1a5efa18a0a7812fb16f47f",
      "maven": {
        "groupId": "org.ow2.asm",
        "artifactId": "asm-analysis",
        "version": "7.1",
      },
      "dependencies" : ["ASM_TREE_7.1"],
      "license": "BSD-new",
    },

    "ASM_COMMONS_7.1": {
      "sha1": "431dc677cf5c56660c1c9004870de1ed1ea7ce6c",
      "sourceSha1" : "a62ff3ae6e37affda7c6fb7d63b89194c6d006ee",
      "maven": {
        "groupId": "org.ow2.asm",
        "artifactId": "asm-commons",
        "version": "7.1",
      },
      "dependencies" : ["ASM_7.1", "ASM_TREE_7.1", "ASM_ANALYSIS_7.1"],
      "license": "BSD-new",
    },

    "ASM_TREE_7.1": {
      "sha1": "a3662cf1c1d592893ffe08727f78db35392fa302",
      "sourceSha1" : "157238292b551de8680505fa2d19590d136e25b9",
      "maven": {
        "groupId": "org.ow2.asm",
        "artifactId": "asm-tree",
        "version": "7.1",
      },
      "dependencies" : ["ASM_7.1"],
      "license": "BSD-new",
    },

    "JACOCOCORE" : {  # deprecated, to be removed in a future version
      "sha1" : "66215826a684eb6866d4c14a5a4f9c344f1d1eef",
      "sourceSha1" : "a365ee459836b2aa18028929923923d15f0c3af9",
      "maven" : {
        "groupId" : "org.jacoco",
        "artifactId" : "org.jacoco.core",
        "version" : "0.7.9",
      },
      "licence": "EPL-1.0",
    },

    "JACOCOAGENT" : {  # deprecated, to be removed in a future version
      "sha1" : "a6ac9cca89d889222a40dab9dd5039bfd22a4cff",
      "maven" : {
        "groupId" : "org.jacoco",
        "artifactId" : "org.jacoco.agent",
        "version" : "0.7.9",
        "classifier" : "runtime",
      },
      "licence": "EPL-1.0",
    },

    "JACOCOREPORT" : {  # deprecated, to be removed in a future version
      "sha1" : "8a7f78fdf2a4e58762890d8e896a9298c2980c10",
      "sourceSha1" : "e6703ef288523a8e63fa756d8adeaa70858d41b0",
      "maven" : {
        "groupId" : "org.jacoco",
        "artifactId" : "org.jacoco.report",
        "version" : "0.7.9",
      },
      "dependencies" : ["JACOCOCORE", "ASM_DEBUG_ALL"],
      "licence": "EPL-1.0",
    },

    "ASM_DEBUG_ALL": {  # deprecated, to be removed in a future version
      "maven": {
        "groupId": "org.ow2.asm",
        "artifactId": "asm-debug-all",
        "version": "5.0.4",
      },
      "sha1": "702b8525fcf81454235e5e2fa2a35f15ffc0ec7e",
      # sources are omitted on purpose: they produce warnings due to duplicated jar entries
      # see https://gitlab.ow2.org/asm/asm/issues/317795
      "license": "BSD-new",
    },

    "SPOTBUGS_3.0.0" : {
      # original: https://sourceforge.net/projects/findbugs/files/findbugs/3.0.0/findbugs-3.0.0.zip/download
      "urls" : ["https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/findbugs-3.0.0.zip"],
      "sha1" : "6e56d67f238dbcd60acb88a81655749aa6419c5b",
    },

    "SPOTBUGS_3.1.11" : {
      # original: https://repo.maven.apache.org/maven2/com/github/spotbugs/spotbugs/3.1.11/spotbugs-3.1.11.zip
      "urls" : ["https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/spotbugs-3.1.11.zip"],
      "sha1" : "8f961e0ddd445cc4e89b18563ac5730766d220f1",
    },

    "SIGTEST" : {
      "maven": {
        "groupId": "org.netbeans.tools",
        "artifactId": "sigtest-maven-plugin",
        "version": "1.2",
      },
      "sha1": "d5cc2cd2a20963b86cf95397784bc7e74101c7a9",
    },

    "CODESNIPPET-DOCLET" : {
      "maven" : {
        "groupId" : "org.apidesign.javadoc",
        "artifactId" : "codesnippet-doclet",
        "version" : "0.51",
      },
      "sha1" : "688f42e00c8d013d59b9dc173e53ede9462fa906",
    },

    "JUNIT" : {
      "sha1" : "2973d150c0dc1fefe998f834810d68f278ea58ec",
      "sourceSha1" : "a6c32b40bf3d76eca54e3c601e5d1470c86fcdfa",
      "dependencies" : ["HAMCREST"],
      "licence" : "CPL",
      "maven" : {
        "groupId" : "junit",
        "artifactId" : "junit",
        "version" : "4.12",
      }
    },

    "JUNIT-JUPITER": {
      "sha1": "b5c481685b6a8ca91c0d46f28f886a444354daa5",
      "sourceSha1": "ae586ef6525ed85ec75557768ff63a5a68755102",
      "license": "EPL-2.0",
      "dependencies": ["JUNIT-JUPITER-API", "JUNIT-JUPITER-PARAMS"],
      "maven": {
        "groupId": "org.junit.jupiter",
        "artifactId": "junit-jupiter",
        "version": "5.6.2",
      }
    },

    "JUNIT-JUPITER-API": {
        "sha1": "c9ba885abfe975cda123bf6f8f0a69a1b46956d0",
        "sourceSha1": "ce1129e07053701f7458120b12229aedb05bcd4a",
        "license": "EPL-2.0",
        "dependencies": ["APIGUARDIAN-API", "OPENTEST4J"],
        "maven": {
            "groupId": "org.junit.jupiter",
            "artifactId": "junit-jupiter-api",
            "version": "5.6.2",
        }
    },

    "APIGUARDIAN-API": {
        "sha1": "fc9dff4bb36d627bdc553de77e1f17efd790876c",
        "sourceSha1": "f3c15fe970af864390c8d0634c9f16aca1b064a8",
        "license": "EPL-2.0",
        "maven": {
            "groupId": "org.apiguardian",
            "artifactId": "apiguardian-api",
            "version": "1.1.0",
        }
    },

    "OPENTEST4J": {
        "sha1": "28c11eb91f9b6d8e200631d46e20a7f407f2a046",
        "sourceSha1": "41d55b3c2254de9837b4ec8923cbd371b8a7eab5",
        "license": "EPL-2.0",
        "dependencies": ["JUNIT-PLATFORM-COMMONS"],
        "maven": {
            "groupId": "org.opentest4j",
            "artifactId": "opentest4j",
            "version": "1.2.0",
        }
    },

    "JUNIT-PLATFORM-COMMONS": {
        "sha1": "7644a14b329e76b5fe487628b50fb5eab6ba7d26",
        "sourceSha1": "bada08402ff53506b1446bc8b3caf5a2aec6c7d1",
        "license": "EPL-2.0",
        "dependencies": ["APIGUARDIAN-API"],
        "maven": {
            "groupId": "org.junit.platform",
            "artifactId": "junit-platform-commons",
            "version": "1.6.2",
        }
    },

    "JUNIT-JUPITER-PARAMS": {
      "sha1": "f2a64a42cf73077062c2386db0598062b7480d91",
      "sourceSha1": "f09c69685e20753eaf05577f5da1f9a220783def",
      "license": "EPL-2.0",
      "dependencies": ["APIGUARDIAN-API"],
      "maven": {
        "groupId": "org.junit.jupiter",
        "artifactId": "junit-jupiter-params",
        "version": "5.6.2",
      }
    },

    "JUNIT-PLATFORM-ENGINE": {
      "sha1": "1752cad2579e20c2b224602fe846fc660fb35805",
      "sourceSha1": "9240cb4f3ee7693f8f18f4140acc7f8c83336e30",
      "license": "EPL-2.0",
      "dependencies": ["APIGUARDIAN-API", "OPENTEST4J"],
      "maven": {
        "groupId": "org.junit.platform",
        "artifactId": "junit-platform-engine",
        "version": "1.6.2",
      }
    },

    "JUNIT-JUPITER-ENGINE": {
      "sha1": "c0833bd6de29dd77f8d071025b97b8b434308cd3",
      "sourceSha1": "2116c399709549a3094a8f2bd96bb3f94b98a341",
      "license": "EPL-2.0",
      "dependencies": ["JUNIT-JUPITER-API", "APIGUARDIAN-API", "JUNIT-PLATFORM-ENGINE"],
      "maven": {
        "groupId": "org.junit.jupiter",
        "artifactId": "junit-jupiter-engine",
        "version": "5.6.2",
      }
    },

    "JUNIT-PLATFORM-LAUNCHER": {
      "sha1": "d866de2950859ca1c7996351d7b3d97428083cd0",
      "sourceSha1": "d9efa09350f724e7e7defa0e74c4f4573e276fe1",
      "license": "EPL-2.0",
      "dependencies": ["APIGUARDIAN-API", "JUNIT-PLATFORM-ENGINE"],
      "maven": {
        "groupId": "org.junit.platform",
        "artifactId": "junit-platform-launcher",
        "version": "1.6.2",
      }
    },

    "JUNIT-PLATFORM-REPORTING": {
      "sha1": "517d3b96b4ed89700a5086ec504fc02d8b526e79",
      "sourceSha1": "e0c1e87c6a973aef33f9c8eb73b47f369a6d2b3f",
      "license": "EPL-2.0",
      "dependencies": ["APIGUARDIAN-API", "JUNIT-PLATFORM-LAUNCHER"],
      "maven": {
        "groupId": "org.junit.platform",
        "artifactId": "junit-platform-reporting",
        "version": "1.6.2",
      }
    },

    "JUNIT-PLATFORM-CONSOLE": {
      "sha1": "dfdeb2688341f7566c5943be7607a413d753ab70",
      "sourceSha1": "10efd3f7acdc66e185d9fd60e7c5a475c2ee9474",
      "license": "EPL-2.0",
      "dependencies": ["APIGUARDIAN-API", "JUNIT-PLATFORM-REPORTING"],
      "maven": {
        "groupId": "org.junit.platform",
        "artifactId": "junit-platform-console",
        "version": "1.6.2",
      }
    },

    "CHECKSTYLE_6.0" : {
      "urls" : [
        "https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/checkstyle-6.0-all.jar",
        "https://github.com/checkstyle/checkstyle/releases/download/checkstyle-6.0/checkstyle-6.0-all.jar",
      ],
      "sha1" : "2bedc7feded58b5fd65595323bfaf7b9bb6a3c7a",
      "licence" : "LGPLv21",
      "maven" : {
        "groupId" : "com.puppycrawl.tools",
        "artifactId" : "checkstyle",
        "version" : "6.0",
      }
    },

    "CHECKSTYLE_6.15" : {
      "urls" : [
        "https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/checkstyle-6.15-all.jar",
        "https://github.com/checkstyle/checkstyle/releases/download/checkstyle-6.15/checkstyle-6.15-all.jar",
      ],
      "sha1" : "db9ade7f4ef4ecb48e3f522873946f9b48f949ee",
      "licence" : "LGPLv21",
      "maven" : {
        "groupId" : "com.puppycrawl.tools",
        "artifactId" : "checkstyle",
        "version" : "6.15",
      }
    },

    "CHECKSTYLE_8.8" : {
      "urls" : [
        "https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/checkstyle-8.8-all.jar",
        "https://github.com/checkstyle/checkstyle/releases/download/checkstyle-8.8/checkstyle-8.8-all.jar",
      ],
      "sha1" : "9712a8124c40298015f04a74f61b3d81a51513af",
      "licence" : "LGPLv21",
      "maven" : {
        "groupId" : "com.puppycrawl.tools",
        "artifactId" : "checkstyle",
        "version" : "8.8",
      }
    },

    "HAMCREST" : {
      "sha1" : "42a25dc3219429f0e5d060061f71acb49bf010a0",
      "sourceSha1" : "1dc37250fbc78e23a65a67fbbaf71d2e9cbc3c0b",
      "licence" : "BSD-new",
      "maven" : {
        "groupId" : "org.hamcrest",
        "artifactId" : "hamcrest-core",
        "version" : "1.3",
      }
    },

    "COMMONS_MATH3_3_2" : {
      "sha1" : "ec2544ab27e110d2d431bdad7d538ed509b21e62",
      "sourceSha1" : "cd098e055bf192a60c81d81893893e6e31a6482f",
      "licence" : "Apache-2.0",
      "maven" : {
        "groupId" : "org.apache.commons",
        "artifactId" : "commons-math3",
        "version" : "3.2"
      }
    },

    "JOPTSIMPLE_4_6" : {
      "sha1" : "306816fb57cf94f108a43c95731b08934dcae15c",
      "sourceSha1" : "9cd14a61d7aa7d554f251ef285a6f2c65caf7b65",
      "licence": "MIT",
      "maven" : {
        "groupId" : "net.sf.jopt-simple",
        "artifactId" : "jopt-simple",
        "version" : "4.6"
      }
    },

    "JMH_GENERATOR_ANNPROCESS_1_18" : {
      "sha1": "b852fb028de645ad2852bbe998e084d253f450a5",
      "sourceSha1" : "d455b0dc6108b5e6f1fb4f6cf1c7b4cbedbecc97",
      "licence": "GPLv2-CPE",
      "maven" : {
        "groupId" : "org.openjdk.jmh",
        "artifactId" : "jmh-generator-annprocess",
        "version" : "1.18",
      }
    },

    "JMH_GENERATOR_ANNPROCESS_1_21" : {
      "sha1": "7aac374614a8a76cad16b91f1a4419d31a7dcda3",
      "sourceSha1" : "fb48e2a97df95f8b9dced54a1a37749d2a64d2ae",
      "licence": "GPLv2-CPE",
      "maven" : {
        "groupId" : "org.openjdk.jmh",
        "artifactId" : "jmh-generator-annprocess",
        "version" : "1.21",
      }
    },

    "JMH_1_18" : {
      "sha1": "0174aa0077e9db596e53d7f9ec37556d9392d5a6",
      "sourceSha1": "7ff1e1aafea436b6aa8b29a8b8f1c2d66be26f5b",
      "licence": "GPLv2-CPE",
      "dependencies" : ["JOPTSIMPLE_4_6", "JMH_GENERATOR_ANNPROCESS_1_18", "COMMONS_MATH3_3_2"],
      "maven" : {
        "groupId" : "org.openjdk.jmh",
        "artifactId" : "jmh-core",
        "version" : "1.18",
      }
    },

    "JMH_1_21" : {
      "sha1": "442447101f63074c61063858033fbfde8a076873",
      "sourceSha1": "a6fe84788bf8cf762b0e561bf48774c2ea74e370",
      "licence": "GPLv2-CPE",
      "dependencies" : ["JOPTSIMPLE_4_6", "JMH_GENERATOR_ANNPROCESS_1_21", "COMMONS_MATH3_3_2"],
      "maven" : {
        "groupId" : "org.openjdk.jmh",
        "artifactId" : "jmh-core",
        "version" : "1.21",
      }
    },

    "JACKPOT" : {
      "sha1" : "9e945acafbdfd585d9079769098f1d78bc8e9921",
      "sourceSha1": "62949e61e68bd014bad5267007fae2b2c3cf6c9a",
      "licence": "Apache-2.0",
      "maven" : {
        "groupId" : "org.apache.netbeans.modules.jackpot30",
        "artifactId" : "tool",
        "version" : "11.1",
      }
    },

    "PROGUARD" : {
      "sha1" : "996a984a7e230fdcfc269d66a6c91fd1587edd50",
      "maven" : {
        "groupId" : "net.sf.proguard",
        "artifactId" : "proguard-base",
        "version" : "5.3.1",
      }
    },

    "PROGUARD_RETRACE" : {
      "sha1" : "4a57d643d2ded6ebcf4b7bcdab8fcf3d2588aa1b",
      "maven" : {
        "groupId" : "net.sf.proguard",
        "artifactId" : "proguard-retrace",
        "version" : "5.3.1",
      }
    },

    # ProGuard introduced support for JDK 9
    "PROGUARD_6_0_3" : {
      "sha1" : "7135739d2d3834964c543ed21e2936ce34747aca",
      "maven" : {
        "groupId" : "net.sf.proguard",
        "artifactId" : "proguard-base",
        "version" : "6.0.3",
      }
    },

    "PROGUARD_RETRACE_6_0_3" : {
      "sha1" : "4f249d487b06bedd29f0b7d9277a63d12d5d0a7e",
      "maven" : {
        "groupId" : "net.sf.proguard",
        "artifactId" : "proguard-retrace",
        "version" : "6.0.3",
      }
    },

    "PROGUARD_6_1_1" : {
      "sha1" : "1d351efe6ada35a40cd1a0fdad4a255229e1c41b",
      "maven" : {
        "groupId" : "net.sf.proguard",
        "artifactId" : "proguard-base",
        "version" : "6.1.1",
      }
    },

    "PROGUARD_RETRACE_6_1_1" : {
      "sha1" : "8b86348867593bd221521b01554724411f939d3c",
      "maven" : {
        "groupId" : "net.sf.proguard",
        "artifactId" : "proguard-retrace",
        "version" : "6.1.1",
      }
    },

    "NINJA" : {
      "packedResource" : True,
      "version" : "1.8.2",
      "os_arch" : {
        "linux" : {
          "amd64" : {
            "urls" : ["https://github.com/ninja-build/ninja/releases/download/v{version}/ninja-linux.zip"],
            "sha1" : "987234c4ce45505c21302e097c24efef4873325c"
          },
          "aarch64" : {
            "urls" : ["https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/ninja-{version}-linux-aarch64.zip"],
            "sha1" : "0939b204638c8aae5e2fc2bf9c7576c805d65331"
          },
          "<others>" : {
            "optional" : True
          }
        },
        "darwin" : {
          "amd64" : {
            "urls" : ["https://github.com/ninja-build/ninja/releases/download/v{version}/ninja-mac.zip"],
            "sha1" : "8142c497f7dfbdb052a1e31960fdfe2c6f9a5ca2"
          }
        },
        "windows" : {
          "amd64" : {
            "urls" : ["https://github.com/ninja-build/ninja/releases/download/v{version}/ninja-win.zip"],
            "sha1" : "637cc6e144f5cc7c6388a30f3c32ad81b2e0442e"
          }
        },
        "solaris" : {
          "<others>" : {
            "optional" : True
          }
        }
      }
    },

    "NINJA_SYNTAX" : {
      "packedResource" : True,
      "version" : "1.7.2",
      "urls" : ["https://pypi.org/packages/source/n/ninja_syntax/ninja_syntax-{version}.tar.gz"],
      "sha1" : "702ca2d0ae93841c5ab75e4d119b29780ec0b7d9"
    },

    "SONARSCANNER_CLI_4_2_0_1873": {
      "sha1": "fda01e04cd3c7fab6661aaadad2821c44577f80a",
      "maven": {
        "groupId": "org.sonarsource.scanner.cli",
        "artifactId": "sonar-scanner-cli",
        "version": "4.2.0.1873",
      },
      "licence": "LGPLv30",
    },
  },

  "licenses" : {
    "GPLv2-CPE" : {
      "name" : "GNU General Public License, version 2, with the Classpath Exception",
      "url" : "http://openjdk.java.net/legal/gplv2+ce.html"
    },
    "BSD-new" : {
      "name" : "New BSD License (3-clause BSD license)",
      "url" : "http://opensource.org/licenses/BSD-3-Clause"
    },
    "CPL" : {
      "name" : "Common Public License Version 1.0",
      "url" : "http://opensource.org/licenses/cpl1.0.txt"
    },
    "LGPLv21" : {
      "name" : "GNU Lesser General Public License, version 2.1",
      "url" : "http://www.gnu.org/licenses/old-licenses/lgpl-2.1.en.html"
    },
    "LGPLv30": {
      "name": "GNU Lesser General Public License, version 3.0",
      "url": "http://www.gnu.org/licenses/lgpl-3.0.en.html"
    },
    "MIT" : {
      "name" : "MIT License",
      "url" : "http://opensource.org/licenses/MIT"
    },
    "Apache-2.0" : {
      "name" : "Apache License 2.0",
      "url" : "https://opensource.org/licenses/Apache-2.0"
    },
    "EPL-1.0": {
      "name": "Eclipse Public License 1.0",
      "url": "https://opensource.org/licenses/EPL-1.0",
    },
    "EPL-2.0": {
      "name": "Eclipse Public License 2.0",
      "url": "https://opensource.org/licenses/EPL-2.0",
    },
  },

  "projects" : {

    "com.oracle.mxtool.jmh_1_21" : {
      "subDir" : "java",
      "sourceDirs" : ["src"],
      "dependencies" : [
        "JMH_1_21",
      ],
      "checkstyle" : "com.oracle.mxtool.junit",
      "javaCompliance" : "1.8+",
      "annotationProcessors" : ["JMH_1_21"],
      "spotbugsIgnoresGenerated" : True,
    },

    "com.oracle.mxtool.junit" : {
      "subDir" : "java",
      "sourceDirs" : ["src"],
      "dependencies" : [
        "JUNIT",
      ],
      "javaCompliance" : "1.8+",
      "checkstyleVersion" : "8.8",
    },

    "com.oracle.mxtool.junit.jdk9" : {
      "subDir" : "java",
      "sourceDirs" : ["src"],
      "dependencies" : [
      ],
      "requiresConcealed" : {
        "java.base" : [
          "jdk.internal.module",
        ],
      },
      "multiReleaseJarVersion": "9",
      "overlayTarget" : "com.oracle.mxtool.junit",
      "checkPackagePrefix" : False,
      "javaCompliance" : "9+",
      "checkstyle" : "com.oracle.mxtool.junit",
    },

    "com.oracle.mxtool.compilerserver" : {
      "subDir" : "java",
      "sourceDirs" : ["src"],
      "javaCompliance" : "1.7+", # jdk7 or later
      "checkstyle" : "com.oracle.mxtool.junit",
    },

    "com.oracle.mxtool.checkcopy" : {
      "subDir" : "java",
      "sourceDirs" : ["src"],
      "javaCompliance" : "1.8+",
      "checkstyle" : "com.oracle.mxtool.junit",
    },

    "com.oracle.mxtool.jacoco" : {
      "subDir" : "java",
      "sourceDirs" : ["src"],
      "javaCompliance" : "1.8+",
      "checkstyle" : "com.oracle.mxtool.junit",
      "dependencies" : [
        "JACOCOREPORT_0.8.4",
        "JOPTSIMPLE_4_6",
      ],
    },

    "com.oracle.mxtool.webserver" : {
      "subDir" : "java",
      "sourceDirs" : ["src"],
      "javaCompliance" : "1.8+",
      "checkstyle" : "com.oracle.mxtool.junit",
    },
   },

  "distributions" : {
    "JUNIT_TOOL" : {
      "subDir" : "java",
      "dependencies" : [
        "com.oracle.mxtool.junit",
        "JUNIT",
        "HAMCREST",
      ],
      "exclude" : [
        "JUNIT",
        "HAMCREST",
      ],
    },

    "MX_JACOCO_REPORT" : {
      "subDir" : "java",
      "mainClass" : "com.oracle.mxtool.jacoco.JacocoReport",
      "dependencies" : ["com.oracle.mxtool.jacoco"],
    },

    "MX_MICRO_BENCHMARKS" : {
      "subDir" : "java",
      "dependencies" : ["com.oracle.mxtool.jmh_1_21"],
    }
  },
}
