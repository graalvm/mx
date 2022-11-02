suite = {
  "name" : "mx",
  "libraries" : {

    # ------------- Libraries -------------

    "APACHE_JMETER_5.3": {
      "urls": ["https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/apache-jmeter-5.3.zip"],
      "digest": "sha1:17480a0905d9d485bc8ce8e7be9daec2de98c251",
      "packedResource": True,
      "license": "Apache-2.0",
    },

    "JACOCOCORE_0.8.8": {
      "digest": "sha1:fb1257ce77ec2fe326aad639b2253e76f481ea2e",
      "sourceDigest": "sha1:7b92d3427263db8b991a5203b4b57488750c0505",
      "maven": {
        "groupId": "org.jacoco",
        "artifactId": "org.jacoco.core",
        "version": "0.8.8",
      },
      "dependencies" : ["ASM_9.3", "ASM_COMMONS_9.3", "ASM_TREE_9.3"],
      "license": "EPL-2.0",
    },

    "JACOCOAGENT_0.8.8": {
      "digest": "sha1:819fa4951ab75fba23be23f9f2793ced7fc423d7",
      "maven": {
        "groupId": "org.jacoco",
        "artifactId": "org.jacoco.agent",
        "version": "0.8.8",
        "classifier": "runtime",
      },
      "license": "EPL-2.0",
    },

    "JACOCOREPORT_0.8.8": {
      "digest": "sha1:366581c3bc90e2900320c528c294949bad7232c8",
      "sourceDigest": "sha1:2a140b5324d6d4fa6ad8d1da43a06d57a458c073",
      "maven": {
        "groupId": "org.jacoco",
        "artifactId": "org.jacoco.report",
        "version": "0.8.8",
      },
      "dependencies" : ["JACOCOCORE_0.8.8"],
      "license": "EPL-2.0",
    },

    "ASM_9.3": {
      "digest": "sha512:04362f50a2b66934c2635196bf8e6bd2adbe4435f312d1d97f4733c911e070f5693941a70f586928437043d01d58994325e63744e71886ae53a62c824927a4d4",
      "sourceDigest": "sha512:dde4b731263ce7f755a1ce202987cddf34490eb591d666ae665817fa59996ded3f89e86daef97c536d1fbc0041fef7eb7edf289badd2a87286116df17e6daa99",
      "maven": {
        "groupId": "org.ow2.asm",
        "artifactId": "asm",
        "version": "9.3",
      },
      "license": "BSD-new",
    },

    "ASM_ANALYSIS_9.3": {
      "digest": "sha1:4b071f211b37c38e0e9f5998550197c8593f6ad8",
      "sourceDigest": "sha1:fbcbbfcd8c350fea66dd36e63b1e118d4ab3370c",
      "maven": {
        "groupId": "org.ow2.asm",
        "artifactId": "asm-analysis",
        "version": "9.3",
      },
      "dependencies" : ["ASM_TREE_9.3"],
      "license": "BSD-new",
    },

    "ASM_COMMONS_9.3": {
      "digest": "sha1:1f2a432d1212f5c352ae607d7b61dcae20c20af5",
      "sourceDigest": "sha1:1692e21847cf3db0b24e1938553cab84f50bf03d",
      "maven": {
        "groupId": "org.ow2.asm",
        "artifactId": "asm-commons",
        "version": "9.3",
      },
      "dependencies" : ["ASM_9.3", "ASM_TREE_9.3", "ASM_ANALYSIS_9.3"],
      "license": "BSD-new",
    },

    "ASM_TREE_9.3": {
      "digest": "sha1:78d2ecd61318b5a58cd04fb237636c0e86b77d97",
      "sourceDigest": "sha1:0cc1987e5e291659c366c4b9be35d105d40a518a",
      "maven": {
        "groupId": "org.ow2.asm",
        "artifactId": "asm-tree",
        "version": "9.3",
      },
      "dependencies" : ["ASM_9.3"],
      "license": "BSD-new",
    },

    "SPOTBUGS_3.0.0" : {
      # original: https://sourceforge.net/projects/findbugs/files/findbugs/3.0.0/findbugs-3.0.0.zip/download
      "urls" : ["https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/findbugs-3.0.0.zip"],
      "digest": "sha1:6e56d67f238dbcd60acb88a81655749aa6419c5b",
    },

    "SPOTBUGS_3.1.11" : {
      # original: https://repo.maven.apache.org/maven2/com/github/spotbugs/spotbugs/3.1.11/spotbugs-3.1.11.zip
      "urls" : ["https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/spotbugs-3.1.11.zip"],
      "digest": "sha1:8f961e0ddd445cc4e89b18563ac5730766d220f1",
    },

    "SPOTBUGS_4.4.2" : {
      "urls" : ["https://github.com/spotbugs/spotbugs/releases/download/4.4.2/spotbugs-4.4.2.zip"],
      "digest": "sha1:9dfbd99283078a9820c3797310a1d21e0a23e8f6",
    },

    "SPOTBUGS_4.7.1" : {
      "urls" : ["https://github.com/spotbugs/spotbugs/releases/download/4.7.1/spotbugs-4.7.1.zip"],
      "digest": "sha1:6a2086b56b1d66cf8718a1d156847773766e37a7",
    },

    "SIGTEST_1_2" : {
      "maven": {
        "groupId": "org.netbeans.tools",
        "artifactId": "sigtest-maven-plugin",
        "version": "1.2",
      },
      "digest": "sha1:d5cc2cd2a20963b86cf95397784bc7e74101c7a9",
    },

    "SIGTEST_1_3" : {
      "maven": {
        "groupId": "org.netbeans.tools",
        "artifactId": "sigtest-maven-plugin",
        "version": "1.3",
      },
      "digest": "sha1:358cbf284ed0e2e593c1bebff5678da3acc90178",
    },

    "CODESNIPPET-DOCLET_0.81" : {
      "maven" : {
        "groupId" : "org.apidesign.javadoc",
        "artifactId" : "codesnippet-doclet",
        "version" : "0.81",
      },
      "digest": "sha1:0850057cf1dab84ee1462ba568563918b8e72cff",
    },

    "JUNIT" : {
      "digest": "sha1:2973d150c0dc1fefe998f834810d68f278ea58ec",
      "sourceDigest": "sha1:a6c32b40bf3d76eca54e3c601e5d1470c86fcdfa",
      "dependencies" : ["HAMCREST"],
      "licence" : "CPL",
      "maven" : {
        "groupId" : "junit",
        "artifactId" : "junit",
        "version" : "4.12",
      }
    },

    "JUNIT-JUPITER": {
      "digest": "sha1:b5c481685b6a8ca91c0d46f28f886a444354daa5",
      "sourceDigest": "sha1:ae586ef6525ed85ec75557768ff63a5a68755102",
      "license": "EPL-2.0",
      "dependencies": ["JUNIT-JUPITER-API", "JUNIT-JUPITER-PARAMS"],
      "maven": {
        "groupId": "org.junit.jupiter",
        "artifactId": "junit-jupiter",
        "version": "5.6.2",
      }
    },

    "JUNIT-JUPITER-API": {
        "digest": "sha1:c9ba885abfe975cda123bf6f8f0a69a1b46956d0",
        "sourceDigest": "sha1:ce1129e07053701f7458120b12229aedb05bcd4a",
        "license": "EPL-2.0",
        "dependencies": ["APIGUARDIAN-API", "OPENTEST4J"],
        "maven": {
            "groupId": "org.junit.jupiter",
            "artifactId": "junit-jupiter-api",
            "version": "5.6.2",
        }
    },

    "APIGUARDIAN-API": {
        "digest": "sha1:fc9dff4bb36d627bdc553de77e1f17efd790876c",
        "sourceDigest": "sha1:f3c15fe970af864390c8d0634c9f16aca1b064a8",
        "license": "EPL-2.0",
        "maven": {
            "groupId": "org.apiguardian",
            "artifactId": "apiguardian-api",
            "version": "1.1.0",
        }
    },

    "OPENTEST4J": {
        "digest": "sha1:28c11eb91f9b6d8e200631d46e20a7f407f2a046",
        "sourceDigest": "sha1:41d55b3c2254de9837b4ec8923cbd371b8a7eab5",
        "license": "EPL-2.0",
        "dependencies": ["JUNIT-PLATFORM-COMMONS"],
        "maven": {
            "groupId": "org.opentest4j",
            "artifactId": "opentest4j",
            "version": "1.2.0",
        }
    },

    "JUNIT-PLATFORM-COMMONS": {
        "digest": "sha1:7644a14b329e76b5fe487628b50fb5eab6ba7d26",
        "sourceDigest": "sha1:bada08402ff53506b1446bc8b3caf5a2aec6c7d1",
        "license": "EPL-2.0",
        "dependencies": ["APIGUARDIAN-API"],
        "maven": {
            "groupId": "org.junit.platform",
            "artifactId": "junit-platform-commons",
            "version": "1.6.2",
        }
    },

    "JUNIT-JUPITER-PARAMS": {
      "digest": "sha1:f2a64a42cf73077062c2386db0598062b7480d91",
      "sourceDigest": "sha1:f09c69685e20753eaf05577f5da1f9a220783def",
      "license": "EPL-2.0",
      "dependencies": ["APIGUARDIAN-API"],
      "maven": {
        "groupId": "org.junit.jupiter",
        "artifactId": "junit-jupiter-params",
        "version": "5.6.2",
      }
    },

    "JUNIT-PLATFORM-ENGINE": {
      "digest": "sha1:1752cad2579e20c2b224602fe846fc660fb35805",
      "sourceDigest": "sha1:9240cb4f3ee7693f8f18f4140acc7f8c83336e30",
      "license": "EPL-2.0",
      "dependencies": ["APIGUARDIAN-API", "OPENTEST4J"],
      "maven": {
        "groupId": "org.junit.platform",
        "artifactId": "junit-platform-engine",
        "version": "1.6.2",
      }
    },

    "JUNIT-JUPITER-ENGINE": {
      "digest": "sha1:c0833bd6de29dd77f8d071025b97b8b434308cd3",
      "sourceDigest": "sha1:2116c399709549a3094a8f2bd96bb3f94b98a341",
      "license": "EPL-2.0",
      "dependencies": ["JUNIT-JUPITER-API", "APIGUARDIAN-API", "JUNIT-PLATFORM-ENGINE"],
      "maven": {
        "groupId": "org.junit.jupiter",
        "artifactId": "junit-jupiter-engine",
        "version": "5.6.2",
      }
    },

    "JUNIT-PLATFORM-LAUNCHER": {
      "digest": "sha1:d866de2950859ca1c7996351d7b3d97428083cd0",
      "sourceDigest": "sha1:d9efa09350f724e7e7defa0e74c4f4573e276fe1",
      "license": "EPL-2.0",
      "dependencies": ["APIGUARDIAN-API", "JUNIT-PLATFORM-ENGINE"],
      "maven": {
        "groupId": "org.junit.platform",
        "artifactId": "junit-platform-launcher",
        "version": "1.6.2",
      }
    },

    "JUNIT-PLATFORM-REPORTING": {
      "digest": "sha1:517d3b96b4ed89700a5086ec504fc02d8b526e79",
      "sourceDigest": "sha1:e0c1e87c6a973aef33f9c8eb73b47f369a6d2b3f",
      "license": "EPL-2.0",
      "dependencies": ["APIGUARDIAN-API", "JUNIT-PLATFORM-LAUNCHER"],
      "maven": {
        "groupId": "org.junit.platform",
        "artifactId": "junit-platform-reporting",
        "version": "1.6.2",
      }
    },

    "JUNIT-PLATFORM-CONSOLE": {
      "digest": "sha1:dfdeb2688341f7566c5943be7607a413d753ab70",
      "sourceDigest": "sha1:10efd3f7acdc66e185d9fd60e7c5a475c2ee9474",
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
      "digest": "sha1:2bedc7feded58b5fd65595323bfaf7b9bb6a3c7a",
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
      "digest": "sha1:db9ade7f4ef4ecb48e3f522873946f9b48f949ee",
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
      "digest": "sha1:9712a8124c40298015f04a74f61b3d81a51513af",
      "licence" : "LGPLv21",
      "maven" : {
        "groupId" : "com.puppycrawl.tools",
        "artifactId" : "checkstyle",
        "version" : "8.8",
      }
    },

    "CHECKSTYLE_8.36.1" : {
      "urls" : [
        "https://github.com/checkstyle/checkstyle/releases/download/checkstyle-8.36.1/checkstyle-8.36.1-all.jar"
      ],
      "digest": "sha1:461851c7a35926559ecabe183e00f310932bd265",
      "licence" : "LGPLv21",
      "maven" : {
        "groupId" : "com.puppycrawl.tools",
        "artifactId" : "checkstyle",
        "version" : "8.36.1",
      }
    },

    "HAMCREST" : {
      "digest": "sha1:42a25dc3219429f0e5d060061f71acb49bf010a0",
      "sourceDigest": "sha1:1dc37250fbc78e23a65a67fbbaf71d2e9cbc3c0b",
      "licence" : "BSD-new",
      "maven" : {
        "groupId" : "org.hamcrest",
        "artifactId" : "hamcrest-core",
        "version" : "1.3",
      }
    },

    "COMMONS_MATH3_3_2" : {
      "digest": "sha1:ec2544ab27e110d2d431bdad7d538ed509b21e62",
      "sourceDigest": "sha1:cd098e055bf192a60c81d81893893e6e31a6482f",
      "licence" : "Apache-2.0",
      "maven" : {
        "groupId" : "org.apache.commons",
        "artifactId" : "commons-math3",
        "version" : "3.2"
      }
    },

    "JOPTSIMPLE_4_6" : {
      "digest": "sha1:306816fb57cf94f108a43c95731b08934dcae15c",
      "sourceDigest": "sha1:9cd14a61d7aa7d554f251ef285a6f2c65caf7b65",
      "licence": "MIT",
      "maven" : {
        "groupId" : "net.sf.jopt-simple",
        "artifactId" : "jopt-simple",
        "version" : "4.6"
      }
    },

    "JMH_GENERATOR_ANNPROCESS_1_18" : {
      "digest": "sha1:b852fb028de645ad2852bbe998e084d253f450a5",
      "sourceDigest": "sha1:d455b0dc6108b5e6f1fb4f6cf1c7b4cbedbecc97",
      "licence": "GPLv2-CPE",
      "maven" : {
        "groupId" : "org.openjdk.jmh",
        "artifactId" : "jmh-generator-annprocess",
        "version" : "1.18",
      }
    },

    "JMH_GENERATOR_ANNPROCESS_1_21" : {
      "digest": "sha1:7aac374614a8a76cad16b91f1a4419d31a7dcda3",
      "sourceDigest": "sha1:fb48e2a97df95f8b9dced54a1a37749d2a64d2ae",
      "licence": "GPLv2-CPE",
      "maven" : {
        "groupId" : "org.openjdk.jmh",
        "artifactId" : "jmh-generator-annprocess",
        "version" : "1.21",
      }
    },

    "JMH_1_18" : {
      "digest": "sha1:0174aa0077e9db596e53d7f9ec37556d9392d5a6",
      "sourceDigest": "sha1:7ff1e1aafea436b6aa8b29a8b8f1c2d66be26f5b",
      "licence": "GPLv2-CPE",
      "dependencies" : ["JOPTSIMPLE_4_6", "JMH_GENERATOR_ANNPROCESS_1_18", "COMMONS_MATH3_3_2"],
      "maven" : {
        "groupId" : "org.openjdk.jmh",
        "artifactId" : "jmh-core",
        "version" : "1.18",
      }
    },

    "JMH_1_21" : {
      "digest": "sha1:442447101f63074c61063858033fbfde8a076873",
      "sourceDigest": "sha1:a6fe84788bf8cf762b0e561bf48774c2ea74e370",
      "licence": "GPLv2-CPE",
      "dependencies" : ["JOPTSIMPLE_4_6", "JMH_GENERATOR_ANNPROCESS_1_21", "COMMONS_MATH3_3_2"],
      "maven" : {
        "groupId" : "org.openjdk.jmh",
        "artifactId" : "jmh-core",
        "version" : "1.21",
      }
    },

    "JACKPOT" : {
      "digest": "sha1:c90da86c534257d09defae5eead0b94d3086e749",
      "sourceDigest": "sha1:7e844d6306e2d154b39ffbacbecc44cb335c68f9",
      "licence": "Apache-2.0",
      "maven" : {
        "groupId" : "org.apache.netbeans.modules.jackpot30",
        "artifactId" : "tool",
        "version" : "12.5",
      }
    },

    "PROGUARD_BASE_7_1_0" : {
      "digest": "sha1:e295aed38344b46315e0e76a4e3c5f6f28c6891c",
      "maven" : {
        "groupId" : "com.guardsquare",
        "artifactId" : "proguard-base",
        "version" : "7.1.0",
      }
    },

    "PROGUARD_CORE_7_1_0" : {
      "digest": "sha1:31f0a0122b30aa6c2d18cb62d6770731a957b28d",
      "maven" : {
        "groupId" : "com.guardsquare",
        "artifactId" : "proguard-core",
        "version" : "7.1.0",
      }
    },

    "PROGUARD_RETRACE_7_1_0" : {
      "digest": "sha1:77b606e91563c178d0ab821804d828988cd869d8",
      "maven" : {
        "groupId" : "com.guardsquare",
        "artifactId" : "proguard-retrace",
        "version" : "7.1.0",
      }
    },

    "LOG4J_API_2_15_0" : {
      "digest": "sha1:4a5aa7e55a29391c6f66e0b259d5189aa11e45d0",
      "maven" : {
        "groupId" : "org.apache.logging.log4j",
        "artifactId" : "log4j-api",
        "version" : "2.15.0",
      }
    },

    "LOG4J_CORE_2_15_0" : {
      "digest": "sha1:ba55c13d7ac2fd44df9cc8074455719a33f375b9",
      "maven" : {
        "groupId" : "org.apache.logging.log4j",
        "artifactId" : "log4j-core",
        "version" : "2.15.0",
      }
    },

    "LOG4J_API_2_17_1" : {
      "digest": "sha1:d771af8e336e372fb5399c99edabe0919aeaf5b2",
      "maven" : {
        "groupId" : "org.apache.logging.log4j",
        "artifactId" : "log4j-api",
        "version" : "2.17.1",
      }
    },

    "LOG4J_CORE_2_17_1" : {
      "digest": "sha1:779f60f3844dadc3ef597976fcb1e5127b1f343d",
      "maven" : {
        "groupId" : "org.apache.logging.log4j",
        "artifactId" : "log4j-core",
        "version" : "2.17.1",
      }
    },

    "ORG_JSON_20211205" : {
      "digest": "sha1:47032dcf2f69880f07dab3dc60b4b0ad97318308",
      "maven" : {
        "groupId" : "org.json",
        "artifactId" : "json",
        "version" : "20211205",
      }
    },

    # As of 8.0.0, the versioning of ProGuardCORE is unlinked from ProguardBASE and ProguardRETRACE
    # since ProGuardCORE is a general library used by other projects.
    # https://github.com/Guardsquare/proguard/issues/132#issuecomment-887610759
    "PROGUARD_CORE_8_0_0" : {
      "digest": "sha1:6205518d4c7b2908e024e3c60795800adfdd5d89",
      "maven" : {
        "groupId" : "com.guardsquare",
        "artifactId" : "proguard-core",
        "version" : "8.0.0",
      },
      "dependencies" : ["LOG4J_CORE_2_15_0", "LOG4J_API_2_15_0"],
    },

    "PROGUARD_CORE_9_0_3" : {
      "digest": "sha1:8cfcd5081ffa946d4b166874579ad4fe6f6aba79",
      "maven" : {
        "groupId" : "com.guardsquare",
        "artifactId" : "proguard-core",
        "version" : "9.0.3",
      },
      "dependencies" : ["LOG4J_CORE_2_17_1", "LOG4J_API_2_17_1"],
    },

    "PROGUARD_RETRACE_7_2_0_beta1" : {
      "digest": "sha1:b49442f6e2eb905b1b812316d68b4fd811046f32",
      "maven" : {
        "groupId" : "com.guardsquare",
        "artifactId" : "proguard-retrace",
        "version" : "7.2.0-beta1",
      },
      "dependencies" : ["PROGUARD_CORE_8_0_0"],
    },

    "PROGUARD_BASE_7_2_0_beta1" : {
      "digest": "sha1:7a037414c1be2a1d98845a7fc2f352973f791f76",
      "maven" : {
        "groupId" : "com.guardsquare",
        "artifactId" : "proguard-base",
        "version" : "7.2.0-beta1",
      },
      "dependencies" : ["PROGUARD_CORE_8_0_0"],
    },

    "PROGUARD_RETRACE_7_3_0_beta1" : {
      "digest": "sha1:fee932ba149e8193ae0de7537535b17467027336",
      "maven" : {
        "groupId" : "com.guardsquare",
        "artifactId" : "proguard-retrace",
        "version" : "7.3.0-beta1",
      },
      "dependencies" : ["PROGUARD_BASE_7_3_0_beta1"],
    },

    "PROGUARD_BASE_7_3_0_beta1" : {
      "digest": "sha1:18c2e2bdb58f348d402066ed99e4f6be9f2ae3b4",
      "maven" : {
        "groupId" : "com.guardsquare",
        "artifactId" : "proguard-base",
        "version" : "7.3.0-beta1",
      },
      "dependencies" : [
        "PROGUARD_CORE_9_0_3",
        "LOG4J_CORE_2_17_1",
        "LOG4J_API_2_17_1",
        "ORG_JSON_20211205"
      ],
    },

    "NINJA" : {
      "packedResource" : True,
      "version" : "1.10.2",
      "os_arch" : {
        "linux" : {
          "amd64" : {
            # Built from the same source as https://github.com/ninja-build/ninja/releases/download/v{version}/ninja-linux.zip,
            # but on a system with older glibc for maximum compatibility with older Linux distributions.
            "urls" : ["https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/ninja-{version}-linux-amd64.zip"],
            "digest": "sha1:47213091e83ddf41f3e859af0b280fa7c8159854"
          },
          "aarch64" : {
            "urls" : ["https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/ninja-{version}-linux-aarch64.zip"],
            "digest": "sha1:ffaa7656e18b7c9cc3f1fa447902cf5e324bd35b"
          },
          "<others>" : {
            "optional" : True
          }
        },
        "linux-musl" : {
          # Steps to build:
          # (Built in an Alpine docker container, Alpine version 3.13.0)
          # apk add python2 g++ re2c git
          # mkdir build && cd build
          # git clone https://github.com/ninja-build/ninja && cd ninja
          # git checkout <github release commit of the particular Ninja version>
          # ./configure.py --bootstrap
          "amd64" : {
            "urls" : ["https://lafo.ssw.jku.at/pub/graal-external-deps/ninja-{version}-linux-amd64-musl.zip"],
            "digest": "sha1:0cc6d5cff72e63444b7abb3fc0562f6e70089147"
          }
        },
        "darwin" : {
          "amd64" : {
            "urls" : ["https://github.com/ninja-build/ninja/releases/download/v{version}/ninja-mac.zip"],
            "digest": "sha1:95d0ca5e7c67ab7181c87e6a6ec59d11b1ff2d30"
          },
          "aarch64" : {
            "urls" : ["https://github.com/ninja-build/ninja/releases/download/v{version}/ninja-mac.zip"],
            "digest": "sha1:95d0ca5e7c67ab7181c87e6a6ec59d11b1ff2d30"
          }
        },
        "windows" : {
          "amd64" : {
            "urls" : ["https://github.com/ninja-build/ninja/releases/download/v{version}/ninja-win.zip"],
            "digest": "sha1:ccacdf88912e061e0b527f2e3c69ee10544d6f8a"
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
      "urls" : ["https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/ninja_syntax-1.7.2.tar.gz"],
      "digest": "sha1:702ca2d0ae93841c5ab75e4d119b29780ec0b7d9"
    },

    "SONARSCANNER_CLI_4_2_0_1873": {
      "digest": "sha1:fda01e04cd3c7fab6661aaadad2821c44577f80a",
      "maven": {
        "groupId": "org.sonarsource.scanner.cli",
        "artifactId": "sonar-scanner-cli",
        "version": "4.2.0.1873",
      },
      "licence": "LGPLv30",
    },

    "ASYNC_PROFILER_1.8.3": {
      "packedResource": True,
      "urlbase": "https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/async-profiler",
      "os_arch": {
        "linux": {
          "amd64": {
            "digest": "sha1:66f3b460b264f50a11533e317737fe606299efd8",
            "urls": ["{urlbase}/async-profiler-1.8.3-linux-x64.tar.gz"],
          },
          "aarch64": {
            "digest": "sha1:cc9dc177d8ab9368af332eb4d39ee3be434683c3",
            "urls": ["{urlbase}/async-profiler-1.8.3-linux-aarch64.tar.gz"],
          },
          "<others>": {
            "optional": True,
          }
        },
        "darwin": {
          "amd64": {
            "digest": "sha1:81017bf1232e143c60f5f93212f617617e678cfe",
            "urls": ["{urlbase}/async-profiler-1.8.3-macos-x64.tar.gz"],
          },
          "aarch64": {
            # GR-34811
            "optional": True,
          },
        },
        "<others>": {
          "<others>": {
            "optional": True,
          },
        }
      },
      "license": "Apache-2.0",
    },

    # last compatible version for JDK 8 - do not upgrade or remove
    "ECJ_3.26": {
      "digest": "sha1:4837be609a3368a0f7e7cf0dc1bdbc7fe94993de",
      "maven": {
        "groupId": "org.eclipse.jdt",
        "artifactId": "ecj",
        "version": "3.26.0",
      },
      "licence": "EPL-2.0",
    },

    # compatible version for JDK 11 (no longer compatible with < 11)
    "ECJ_3.27": {
      "digest": "sha1:b9f4002cc13e414f303d6c3b9736b0efb505c9b8",
      "maven": {
        "groupId": "org.eclipse.jdt",
        "artifactId": "ecj",
        "version": "3.27.0",
      },
      "licence": "EPL-2.0",
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
      "checkstyleVersion" : "8.36.1",
    },

    "com.oracle.mxtool.junit.jdk9" : {
      "subDir" : "java",
      "sourceDirs" : ["src"],
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
      "javaCompliance" : "1.8+",
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
        "JACOCOREPORT_0.8.8",
        "JOPTSIMPLE_4_6",
      ],
    },

    "com.oracle.mxtool.webserver" : {
      "subDir" : "java",
      "sourceDirs" : ["src"],
      "javaCompliance" : "1.8+",
      "checkstyle" : "com.oracle.mxtool.junit",
    },

    # Native library for HotSpot assembly capture
    "com.oracle.jvmtiasmagent": {
      "subDir": "java",
      "native": "shared_lib",
      "use_jdk_headers": True,
      "os_arch": {
        "linux": {
          "amd64": {
            "cflags" : ["-fPIC", "-Wall", "-Werror", "-O", "-g", "-DJVMTI_ASM_ARCH=amd64", "-std=gnu99"],
            "ldflags" : ["-lrt"],
          },
          "aarch64": {
            "cflags" : ["-fPIC", "-Wall", "-Werror", "-O", "-g", "-DJVMTI_ASM_ARCH=aarch64", "-std=gnu99"],
          },
          "riscv64" : {
            "cflags" : ["-fPIC", "-Wall", "-Werror", "-O", "-g", "-DJVMTI_ASM_ARCH=riscv64", "-std=gnu99"],
          }
        },
        "darwin": {
            "<others>": {
                "ignore": "mac is currently not supported",
            },
        },
        "windows": {
            "<others>": {
                "ignore": "windows is not supported",
            },
        },
      },
    },
   },

  "distributions" : {
    "JUNIT_TOOL" : {
      "subDir" : "java",
      "dependencies" : [
        "com.oracle.mxtool.junit",
      ],
      "exclude" : [
        "JUNIT",
        "HAMCREST",
      ],
      "moduleInfo" : {
        "name" : "com.oracle.mxtool.junit",
      },
    },

    "MX_JACOCO_REPORT" : {
      "subDir" : "java",
      "mainClass" : "com.oracle.mxtool.jacoco.JacocoReport",
      "dependencies" : ["com.oracle.mxtool.jacoco"],
    },

    "MX_MICRO_BENCHMARKS" : {
      "subDir" : "java",
      "dependencies" : ["com.oracle.mxtool.jmh_1_21"],
    },

    "GCC_NINJA_TOOLCHAIN": {
      "native": True,
      "platformDependent": False,
      "description": "ninja rules for a GCC toolchain found on the PATH",
      "layout": {
        "toolchain.ninja": "file:ninja-toolchains/gcc.ninja",
      },
      "maven": False,
    },

    "DEFAULT_NINJA_TOOLCHAIN": {
      "native": True,
      "platformDependent": True,
      "description": "Default ninja rules for an OS-dependent toolchain found on the PATH",
      "os_arch": {
        "<others>": {
          "<others>": {
            "layout": {
              "./": "extracted-dependency:GCC_NINJA_TOOLCHAIN",
            },
            "asm_requires_cpp": False,
          },
        },
        "windows": {
          "<others>": {
            "layout": {
              "toolchain.ninja": "file:ninja-toolchains/msvc.ninja",
            },
            "asm_requires_cpp": True,
          },
        },
      },
      "maven": False,
    },
  },
}
