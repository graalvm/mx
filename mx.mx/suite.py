suite = {
  "name" : "mx",
  "libraries" : {

    # ------------- Libraries -------------

    "JACOCOCORE_0.8.2" : {
      "sha1" : "977b33afe2344a9ee801fd3317c54d8e1f9d7a79",
      "sourceSha1" : "46f38efb779fb08216379e1a196396f4e22bbe41",
      "maven" : {
        "groupId" : "org.jacoco",
        "artifactId" : "org.jacoco.core",
        "version" : "0.8.2",
      },
      "dependencies" : ["ASM_6.2.1", "ASM_COMMONS_6.2.1", "ASM_TREE_6.2.1"],
      "licence": "EPL-1.0",
    },

    "JACOCOAGENT_0.8.2" : {
      "sha1" : "4806883004063feb978b8811f00d5ea2138750bb",
      # Cannot download sources for "maven" library with "classifier" attribute
      "maven" : {
        "groupId" : "org.jacoco",
        "artifactId" : "org.jacoco.agent",
        "version" : "0.8.2",
        "classifier" : "runtime",
      },
      "licence": "EPL-1.0",
    },

    "JACOCOREPORT_0.8.2" : {
      "sha1" : "50e133cdfd2d31ca5702b73615be70f801d3ae26",
      "sourceSha1" : "7488cd6e42cc4fa85b51200b7f451465692e033b",
      "maven" : {
        "groupId" : "org.jacoco",
        "artifactId" : "org.jacoco.report",
        "version" : "0.8.2",
      },
      "defaultBuild" : False,
      "dependencies" : ["JACOCOCORE_0.8.2"],
      "licence": "EPL-1.0",
    },

    "ASM_6.2.1": {
      "sha1": "c01b6798f81b0fc2c5faa70cbe468c275d4b50c7",
      "sourceSha1" : "cee28077ac7a63d3de0b205ec314d83944ff6267",
      "maven": {
        "groupId": "org.ow2.asm",
        "artifactId": "asm",
        "version": "6.2.1",
      },
      "license": "BSD-new",
    },

    "ASM_ANALYSIS_6.2.1": {
      "sha1": "e8b876c5ccf226cae2f44ed2c436ad3407d0ec1d",
      "sourceSha1" : "b0b249bd185677648692e7c57b488b6d7c2a6653",
      "maven": {
        "groupId": "org.ow2.asm",
        "artifactId": "asm-analysis",
        "version": "6.2.1",
      },
      "dependencies" : ["ASM_TREE_6.2.1"],
      "license": "BSD-new",
    },

    "ASM_COMMONS_6.2.1": {
      "sha1": "eaf31376d741a3e2017248a4c759209fe25c77d3",
      "sourceSha1" : "667fa0f9d370e7848b0e3d173942855a91fd1daf",
      "maven": {
        "groupId": "org.ow2.asm",
        "artifactId": "asm-commons",
        "version": "6.2.1",
      },
      "dependencies" : ["ASM_6.2.1", "ASM_TREE_6.2.1", "ASM_ANALYSIS_6.2.1"],
      "license": "BSD-new",
    },

    "ASM_TREE_6.2.1": {
      "sha1": "332b022092ecec53cdb6272dc436884b2d940615",
      "sourceSha1" : "072bd64989090e4ed58e4657e3d4481d96f643af",
      "maven": {
        "groupId": "org.ow2.asm",
        "artifactId": "asm-tree",
        "version": "6.2.1",
      },
      "dependencies" : ["ASM_6.2.1"],
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
      "urls" : [
        "https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/findbugs-3.0.0.zip",
        "http://sourceforge.net/projects/findbugs/files/findbugs/3.0.0/findbugs-3.0.0.zip/download",
      ],
      "sha1" : "6e56d67f238dbcd60acb88a81655749aa6419c5b",
    },

    "SPOTBUGS_3.1.11" : {
      "urls" : [
        "https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/spotbugs-3.1.11.zip",
        "https://repo.maven.apache.org/maven2/com/github/spotbugs/spotbugs/3.1.11/spotbugs-3.1.11.zip",
      ],
      "sha1" : "8f961e0ddd445cc4e89b18563ac5730766d220f1",
    },

    "SIGTEST" : {
      "maven": {
        "groupId": "org.netbeans.tools",
        "artifactId": "sigtest-maven-plugin",
        "version": "1.1",
      },
      "sha1": "3837cc19378e6e20202c99cdf47b1c7dc189388f",
    },

    "CODESNIPPET-DOCLET" : {
      "maven" : {
        "groupId" : "org.apidesign.javadoc",
        "artifactId" : "codesnippet-doclet",
        "version" : "0.31",
      },
      "sha1" : "ccfb545b52e23240d1ecfe591164efad33c2cecf",
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

    "CHECKSTYLE_6.0" : {
      "urls" : [
        "https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/checkstyle-6.0-all.jar",
        "jar:http://sourceforge.net/projects/checkstyle/files/checkstyle/6.0/checkstyle-6.0-bin.zip/download!/checkstyle-6.0/checkstyle-6.0-all.jar",
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
        "http://sourceforge.net/projects/checkstyle/files/checkstyle/6.15/checkstyle-6.15-all.jar",
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
        "http://sourceforge.net/projects/checkstyle/files/checkstyle/8.8/checkstyle-8.8-all.jar",
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
      "urls" : [
        "https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/jackpot-8.1-20151011.220626.jar",
      ],
      "sha1" : "b5f91770afd3b8ce645e7b967a1f266ab472053b",
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

    "SONARSCANNER_CLI_3_3_0_1492": {
      "sha1": "9116a2763e257dbc0251c18cd7dd975c588f0169",
      "maven": {
        "groupId": "org.sonarsource.scanner.cli",
        "artifactId": "sonar-scanner-cli",
        "version": "3.3.0.1492",
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
        "JACOCOREPORT_0.8.2",
        "JOPTSIMPLE_4_6",
      ],
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
