suite = {
  "name" : "mx",
  "libraries" : {

    # ------------- Libraries -------------
    "JACOCOCORE_0.8.13": {
      "digest": "sha512:72659a6242537f09ec1f1c836d66988133924b1ddea60c74f82728106f9d1240273d4f7ee7b37f742b2acaa94c7da8062cf648811d0fa5c311ecea77607510c7",
      "sourceDigest": "sha512:0f9a8aabbe9aa07f7d4e4cab69e3bec13269f9bf060a857720c6dd9c0583f2b29ebbb6cfc6b3323b37516cb93589758cf3df2368ba3cd3969886ad93cf6cabed",
      "maven": {
        "groupId": "org.jacoco",
        "artifactId": "org.jacoco.core",
        "version": "0.8.13",
      },
      "dependencies" : ["ASM_9.8", "ASM_COMMONS_9.8", "ASM_TREE_9.8"],
      "license": "EPL-2.0",
    },

    "JACOCOAGENT_0.8.13": {
      "digest": "sha512:f0a09d84bfa5f5c07bdee0ba506911d80922e9838e824a53bf9c64e643e7300f902db4b503339cfb4bd7b4151248ba83d268bdfa40fcd0a55a9a40f8c64c3683",
      "maven": {
        "groupId": "org.jacoco",
        "artifactId": "org.jacoco.agent",
        "version": "0.8.13",
        "classifier": "runtime",
      },
      "license": "EPL-2.0",
    },

    "JACOCOREPORT_0.8.13": {
      "digest": "sha512:12fed977103bf4574af77ba614c81c6e92ea0fddd982c43ba6b57bd5b39bc212892ce6fc5d1182426b3fc152040d9da1b091798762ab6eb6c1e3da6d8a9f1962",
      "sourceDigest": "sha512:7b92aad7bfea144b860123dba148a2c16fd13ff924bf3fc40ed2367e0110aa91d5a359a371455776bd786d031953c2cb83e7f1f48ba41b4913dbf7433de47cab",
      "maven": {
        "groupId": "org.jacoco",
        "artifactId": "org.jacoco.report",
        "version": "0.8.13",
      },
      "dependencies" : ["JACOCOCORE_0.8.13"],
      "license": "EPL-2.0",
    },

    "ASM_9.8": {
      "digest": "sha512:cbd250b9c698a48a835e655f5f5262952cc6dd1a434ec0bc3429a9de41f2ce08fcd3c4f569daa7d50321ca6ad1d32e131e4199aa4fe54bce9e9691b37e45060e",
      "sourceDigest": "sha512:329663d73f165c7e006a20dd24bb6f5b4ac1079097d83c91770fd9fc537655a384c4cc40e5835f800d6453d393b6adbcd51c6eab6fe90cd8e1e8e87b9b513cc4",
      "maven": {
        "groupId": "org.ow2.asm",
        "artifactId": "asm",
        "version": "9.8",
      },
      "license": "BSD-new",
    },

    "ASM_ANALYSIS_9.8": {
      "digest": "sha512:0268e6dc2cc4965180ca1b62372e3c5fc280d6dc09cfeace2ac4e43468025e8a78813e4e93beafc0352e67498c70616cb4368313aaab532025fa98146c736117",
      "sourceDigest": "sha512:daabbc03bcfdb5227d410171a5322fa4cde907f9fe32760b293ffd761c3290fcf406bc0290f1f82774dcbd9347be55dbea65cda550084e35a6d57cbad63c8593",
      "maven": {
        "groupId": "org.ow2.asm",
        "artifactId": "asm-analysis",
        "version": "9.8",
      },
      "dependencies" : ["ASM_TREE_9.8"],
      "license": "BSD-new",
    },

    "ASM_COMMONS_9.8": {
      "digest": "sha512:d2add10e25416b701bd84651b42161e090df2f32940de5e06e0e2a41c6106734db2fe5136f661d8a8af55e80dc958bc7b385a1004f0ebe550828dfa1e9d70d41",
      "sourceDigest": "sha512:dea8a2f871024210980821dc06c6796a3fca58293f650614275a086aaf9e2f45066a128f434dadabb85162c52796e99c863a6838e851ec02d6d97c603ed5a6d9",
      "maven": {
        "groupId": "org.ow2.asm",
        "artifactId": "asm-commons",
        "version": "9.8",
      },
      "dependencies" : ["ASM_9.8", "ASM_TREE_9.8", "ASM_ANALYSIS_9.8"],
      "license": "BSD-new",
    },

    "ASM_TREE_9.8": {
      "digest": "sha512:4493f573d9f0cfc8837db9be25a8b61a825a06aafc0e02f0363875584ff184a5a14600e53793c09866300859e44f153faffd0e050de4a7fba1a63b5fb010a9a7",
      "sourceDigest": "sha512:3cea80bc7b55679dfa3d2065c6cb6951007cc7817082e9fcf4c5e3cdc073c22eddf7c7899cff60b1092049ec9038e8d3aa9a8828ef731739bda8b5afcec30e86",
      "maven": {
        "groupId": "org.ow2.asm",
        "artifactId": "asm-tree",
        "version": "9.8",
      },
      "dependencies" : ["ASM_9.8"],
      "license": "BSD-new",
    },

    "SPOTBUGS_3.0.0" : {
      # original: https://sourceforge.net/projects/findbugs/files/findbugs/3.0.0/findbugs-3.0.0.zip/download
      "urls" : ["https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/findbugs-3.0.0.zip"],
      "digest": "sha512:948200dde19ac54a9f353cdae6d584b77f5ed926a4d664b132d5fdfde4f608a8599e798a9f83c41ebba0429876c22cde79de0a00cbe357f4a56fcdb61aba43c1",
    },

    "SPOTBUGS_3.1.11" : {
      # original: https://repo.maven.apache.org/maven2/com/github/spotbugs/spotbugs/3.1.11/spotbugs-3.1.11.zip
      "urls" : ["https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/spotbugs-3.1.11.zip"],
      "digest": "sha512:98572754ab2df4ebc604d286fb8d83a7a053827d522df933cda3bc51f55f22a4123dad34a92954fdcaa3a81bd41dd466fa7ac1c7e4de980101fecef9905763a9",
    },

    "SPOTBUGS_4.4.2" : {
      "urls" : ["https://github.com/spotbugs/spotbugs/releases/download/4.4.2/spotbugs-4.4.2.zip"],
      "digest": "sha512:8ef2b502e684943d317d8f51ab4103c6b0cc716d1b53adf51a43a3cfd34bfd224924dddafa326b760acd6cf630afaf82107bf045cddb8a603f8d55cc4409aab6",
    },

    "SPOTBUGS_4.7.1" : {
      "urls" : ["https://github.com/spotbugs/spotbugs/releases/download/4.7.1/spotbugs-4.7.1.zip"],
      "digest": "sha512:2b19837ed5ef55654139a86579ea3ab8edeaf716245eb61503c0c861038bc32d84d50d7316442f32338aef3688119b9137df28d8d3cea1fb8d0653710d96259d",
    },

    "SPOTBUGS_4.7.3" : {
      "urls" : ["https://github.com/spotbugs/spotbugs/releases/download/4.7.3/spotbugs-4.7.3.zip"],
      "digest": "sha512:fcece0ecbc5301b5d101668b997beda59f4590f01010a6d195e4212ba989150a85760c25bd252966cde82844a43f4992d32bf6fc175ad01d0a578ca573e22c2e",
    },

    "SPOTBUGS_4.7.3_JDK21_BACKPORT" : {
      "urls" : ["https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/spotbugs-4.7.3-jdk21-backport.zip"],
      "digest": "sha512:c8f7ba8154ec40d33d2864b4fdd0c5763a1d6d8f64bb5e2d3204d841e28189d8ef6fe4a6866a72465df607318e3ad9c5d18db7f96cccc502957fd6e2dd6f0537",
    },

    "SIGTEST_1_2" : {
      "maven": {
        "groupId": "org.netbeans.tools",
        "artifactId": "sigtest-maven-plugin",
        "version": "1.2",
      },
      "digest": "sha512:a005b7ec0eb37a34539e5694a2620b4b5acb54104fb04b04aa8321bb63f93fbac985dc131f207b0cc4f94ea8f8b144059991a14ca0b36a46a8bd2b8226c601ef",
    },

    "SIGTEST_1_3" : {
      "maven": {
        "groupId": "org.netbeans.tools",
        "artifactId": "sigtest-maven-plugin",
        "version": "1.3",
      },
      "digest": "sha512:4365f4bbfeca6f61c4d27f89c5bb6aa2fcc88dab3eab4e26a97ddbc6cfc6c2a0a67949b9e3417e43851fb92e04e639b7eb19c8c00c91ddfca9f1a6df4ec7deef",
    },

    "CODESNIPPET-DOCLET_1.0" : {
      "maven" : {
        "groupId" : "org.apidesign.javadoc",
        "artifactId" : "codesnippet-doclet",
        "version" : "1.0",
      },
      "digest": "sha512:6d4d4cf1a59e200a05b11d03fe61656401ddf76cac8a4017d83c478381c5ac727922709c7d2c511281e89a7de636e3bf997bcb22e516232e0ba1f662d0413794",
    },

    "JUNIT" : {
      "digest": "sha512:a31b9950f929a7e5a600d89787ef40e42a8a8e2392e210d0c0f45b3572937670a18a524f1815508cd1152cd1eaa7275cb7430ba45c053be365c83c231bccd3f0",
      "sourceDigest": "sha512:b6299ee0f7b0ed187539d81115eb5a2cc0443172db2da63821cb683da3fafa765cd38227ac0cdfe74f2cf8e61fb8679224cebfd1057331dd9d85aa2325417481",
      "dependencies" : ["HAMCREST"],
      "licence" : "CPL",
      "maven" : {
        "groupId" : "junit",
        "artifactId" : "junit",
        "version" : "4.13.2",
      }
    },

    "JUNIT-JUPITER": {
      "digest": "sha512:d10edf43b62c5947b50c506e84d65829138970acd6a85c066d7c6ca192477bed197af77866f6b18ea7b8ebc8a1a16666dc7982a967533079e8927a65aa3b484d",
      "sourceDigest": "sha512:d7f1de1afb4a475b80fcd07edf98d77dc3de5378dee9b76dcd2f2dd30784015fba4d06532851333246c227208a4d49ce7bf8b174d0454fb71b331c6f5d4d49a9",
      "license": "EPL-2.0",
      "dependencies": ["JUNIT-JUPITER-API", "JUNIT-JUPITER-PARAMS"],
      "maven": {
        "groupId": "org.junit.jupiter",
        "artifactId": "junit-jupiter",
        "version": "5.10.2",
      }
    },

    "JUNIT-JUPITER-API": {
        "digest": "sha512:7dfb74405cc011bf0b9176f2093686680225ef32658ec82b55bad9857eb38999b8ac25c23f920127b426120bfc20938f2d9dc8df111a509d9858d350e5ff7685",
        "sourceDigest": "sha512:c96241f2cb6fe40a3e9b5639eb378ccbfa7d0efe0ffb232856d5248630a8e4a64220bef9aa86f5e38e91cf3e7d8b5926b707769674c20ee7ac7f044336eabda9",
        "license": "EPL-2.0",
        "dependencies": ["APIGUARDIAN-API", "OPENTEST4J"],
        "maven": {
            "groupId": "org.junit.jupiter",
            "artifactId": "junit-jupiter-api",
            "version": "5.10.2",
        }
    },

    "APIGUARDIAN-API": {
        "digest": "sha512:d7ccd0e7019f1a997de39d66dc0ad4efe150428fdd7f4c743c93884f1602a3e90135ad34baea96d5b6d925ad6c0c8487c8e78304f0a089a12383d4a62e2c9a61",
        "sourceDigest": "sha512:0035bb640f97d8c64b9fc085084a94b1c8ffa2dc3145bd59d1ff5cbb2c63ff776569a3fe27bd2e996644223c8748d022e0863ff38391e3b72e82242f123f49a5",
        "license": "EPL-2.0",
        "maven": {
            "groupId": "org.apiguardian",
            "artifactId": "apiguardian-api",
            "version": "1.1.2",
        }
    },

    "OPENTEST4J": {
        "digest": "sha512:78fc698a7871bb50305e3657893c10500595f043348d875f57bc39ca4a6a51eda3967b7c8c8a7ec3e8f85f2171bca4aa98823e912e416e87e81c6ba5b70a37c3",
        "sourceDigest": "sha512:f54436dbd733fdae98b984c2c42ef4d1fc114217155b044c21f6e44f0c9e509156423c16aa73aa2d6acae00d2677e7c072aaea36836b21a440df6abe08d44b8d",
        "license": "EPL-2.0",
        "dependencies": ["JUNIT-PLATFORM-COMMONS"],
        "maven": {
            "groupId": "org.opentest4j",
            "artifactId": "opentest4j",
            "version": "1.3.0",
        }
    },

    "JUNIT-PLATFORM-COMMONS": {
        "digest": "sha512:aa739ee21b91fd4476aa5f9ad975f83cd440b6fbac71c8cc15816e3924710c0d70838465ee22a1b7390c2bae42ef1809868fa7ae0169b75f437cd95baac539d1",
        "sourceDigest": "sha512:8963ff47fca9af4390762f40366d2ff5ab54d4992aea7947ec3055b5f16e54229aae81fa75996400f31a0cc522b177d93a342eeea3e63d48a55fe85626ac00a1",
        "license": "EPL-2.0",
        "dependencies": ["APIGUARDIAN-API"],
        "maven": {
            "groupId": "org.junit.platform",
            "artifactId": "junit-platform-commons",
            "version": "1.10.2",
        }
    },

    "JUNIT-JUPITER-PARAMS": {
      "digest": "sha512:002b2010769413f1bc86cf95a48f679eeb7a372379e8f401f892d03bd1089483937a77f08c095579f81b8f0a27896fac6bebdc4c09a2dff9f5459e09207ac0d8",
      "sourceDigest": "sha512:776e597de5a3305f5fdbe33f9d1c948829e544d8e83d32af7f52014b58472a0df1e8cc9f66084301a137bfad056c5ac693fe2e9219ec5359c81d435bd8a15941",
      "license": "EPL-2.0",
      "dependencies": ["APIGUARDIAN-API"],
      "maven": {
        "groupId": "org.junit.jupiter",
        "artifactId": "junit-jupiter-params",
        "version": "5.10.2",
      }
    },

    "JUNIT-PLATFORM-ENGINE": {
      "digest": "sha512:5ca468aff73099673266e4e1431189023b0a660292f4f6c101dc4b03b8ab3643392731aa55455bf3a5079331a563dacda0c6b3cf3df64563ca6e0201af609e27",
      "sourceDigest": "sha512:0a97eaec00892f7c9e5924279613e0e41c07ecd7cdafa8b5852de1c0468fc5e8c71becfdbe0ea864959d6913308bc50c0f08565628bd9a295aa8e5a57d2eac2f",
      "license": "EPL-2.0",
      "dependencies": ["APIGUARDIAN-API", "OPENTEST4J"],
      "maven": {
        "groupId": "org.junit.platform",
        "artifactId": "junit-platform-engine",
        "version": "1.10.2",
      }
    },

    "JUNIT-JUPITER-ENGINE": {
      "digest": "sha512:0a95745a7d7b7d1cc4974e946cb0ab2696d7739ec1cee8545a34d6f14e63f065d06ab1363e4fc1b588d5197107f9ffc42537bebcd7b10a945fae316e5fdbc103",
      "sourceDigest": "sha512:d16517d7638fe80055e262e99083cd2c84ec7203819d7f949977fd56864c9c4050ca1fe7924ebcb774a85b83bce5ed5e766423692a096607c95721426761dc2c",
      "license": "EPL-2.0",
      "dependencies": ["JUNIT-JUPITER-API", "APIGUARDIAN-API", "JUNIT-PLATFORM-ENGINE"],
      "maven": {
        "groupId": "org.junit.jupiter",
        "artifactId": "junit-jupiter-engine",
        "version": "5.10.2",
      }
    },

    "JUNIT-VINTAGE-ENGINE": {
      "digest": "sha512:1833a242d9b42c506b133d51e22b82bfe66d20c809b39d8e7baaa185409365cc75bc5c7904c04ffae52a3785bee6577bba9093f7fe985610239c58a9a7ab76d7",
      "sourceDigest": "sha512:155d73f8af171ed6fb220be1a2337adf59a2bc60398bc2754bf37c57f578c841675e9b895fc8bb3542ded5ffe9d40436d056642cabdf95220a07f55314f0cfea",
      "license": "EPL-2.0",
      "dependencies": ["JUNIT", "APIGUARDIAN-API", "JUNIT-PLATFORM-ENGINE"],
      "maven": {
        "groupId": "org.junit.vintage",
        "artifactId": "junit-vintage-engine",
        "version": "5.10.2",
      }
    },

    "JUNIT-PLATFORM-LAUNCHER": {
      "digest": "sha512:764f1e1a978d8970524a22bf37f807d0a2b94a388abd79d23287ec931266f752e6fedf6599348fd6baf5fcef2105dddb315f680352532e8f2209b56e5d74f7ba",
      "sourceDigest": "sha512:e9eccf15a8fc69e356c00eaa885e62c5e38163bc7092dd71a1b521230294ed1c6c8adbe54de5f6124c6dde81038171ef6605d49b2654a1d0f34881519de27996",
      "license": "EPL-2.0",
      "dependencies": ["APIGUARDIAN-API", "JUNIT-PLATFORM-ENGINE"],
      "maven": {
        "groupId": "org.junit.platform",
        "artifactId": "junit-platform-launcher",
        "version": "1.10.2",
      }
    },

    "JUNIT-PLATFORM-REPORTING": {
      "digest": "sha512:a0cf9741de3fe0a74527385595dde85acbfa06a8fd7bebc379ff6791d39e8ee2484d18a2cf7cc6520455a7ea3be55c1f0ef6d137e2e36a7e3e58a53113959763",
      "sourceDigest": "sha512:a19f5d55142363cc01d3379db253ada5dec79fb38823ad4087e4573f0a897d172197466c98fbcc9dd449f96c7eeb661c8419d276bbbfbd63959f190be8795e16",
      "license": "EPL-2.0",
      "dependencies": ["APIGUARDIAN-API", "JUNIT-PLATFORM-LAUNCHER"],
      "maven": {
        "groupId": "org.junit.platform",
        "artifactId": "junit-platform-reporting",
        "version": "1.10.2",
      }
    },

    "JUNIT-PLATFORM-CONSOLE": {
      "digest": "sha512:d3e7e4e31e7d0a9a7a0125e8c6f73219487c49e2bebae6196f07fe0fac9854c9b56b546b0aa51524bf87dfd7f1df7a49ba8f1de2df63f1bfab328ebccb1cdbfd",
      "sourceDigest": "sha512:b7b5b5909b2df8774eeb39b8603dcb2209713784b9aab8563933447bc5c5a124e48faab7af4a724402326b80d9205128ab33fb4edddc61b65d9501bf988588e0",
      "license": "EPL-2.0",
      "dependencies": ["APIGUARDIAN-API", "JUNIT-PLATFORM-REPORTING"],
      "maven": {
        "groupId": "org.junit.platform",
        "artifactId": "junit-platform-console",
        "version": "1.10.2",
      }
    },

    "JUNIT-PLATFORM-NATIVE": {
      "digest": "sha512:db9faa6ede8fbf346ad72688b5c446710967c252eda6642d8f900206b9b94c98b69a339b8abaaf7c56da89ae779ebd0e491dc8a999ba7b705e6b16c43c1225f9",
      "sourceDigest": "sha512:a51d02d8460128aa53c40f23620713db376836951a4c22c5eb366d0e223c7311160c7dec0e251e5ba5d2955736e1080e9ff8ab42bf6f6110484ab4675f2d2f9c",
      "license": "UPL",
      "maven": {
        "groupId": "org.graalvm.buildtools",
        "artifactId": "junit-platform-native",
        "version": "0.10.0",
      },
      "dependencies": ["mx:JUNIT-JUPITER", "mx:JUNIT-PLATFORM-CONSOLE", "mx:JUNIT-JUPITER-ENGINE", "mx:JUNIT-VINTAGE-ENGINE"]
    },

    "CHECKSTYLE_6.0" : {
      "urls" : [
        "https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/checkstyle-6.0-all.jar",
        "https://github.com/checkstyle/checkstyle/releases/download/checkstyle-6.0/checkstyle-6.0-all.jar",
      ],
      "digest": "sha512:57ba0a14302e736e8d5d1e4f720ea6b8ee5e49ed811fadb36afe740d441147567ff7e865089b8e47d27af16eafe7def337f9f38e20e8a6ff828a28f713271eb8",
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
      "digest": "sha512:7cc96c77183d7aa907a8107194843cd64b84643511e50cd1099c954ce1bc182ec16d5b327135e64b28765bd27d1980ee0ceb73d7f3f3d8dea52df0b1281abaf0",
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
      "digest": "sha512:4484fed4321fc1d96607d453faa3a1435bfffd61b21cc0b3e6e381bca47bcde17b34a55a160820b7deece3bfa67ac92dc53d0fc64576c82ffaeae1e80b033ca6",
      "licence" : "LGPLv21",
      "maven" : {
        "groupId" : "com.puppycrawl.tools",
        "artifactId" : "checkstyle",
        "version" : "8.8",
      }
    },

    "CHECKSTYLE_10.7.0" : {
      "urls" : [
        "https://github.com/checkstyle/checkstyle/releases/download/checkstyle-10.7.0/checkstyle-10.7.0-all.jar"
      ],
      "digest": "sha512:5527f5fca9870d02f691b4d34459386d203558414bdbfb2a117af698101487b4ab6387174e600745a7d1acf0a0358d78bb219d0fba47e4b7ef9365395b0b41b6",
      "licence" : "LGPLv21",
      "maven" : {
        "groupId" : "com.puppycrawl.tools",
        "artifactId" : "checkstyle",
        "version" : "10.7.0",
      }
    },

    "CHECKSTYLE_10.21.0" : {
      "urls" : [
        "https://github.com/checkstyle/checkstyle/releases/download/checkstyle-10.21.0/checkstyle-10.21.0-all.jar"
      ],
      "digest": "sha512:401940e1475a333afee636535708fa842b1a11b30f9fd43518589aaf94c2cf601b24f83176e95ffc171e2befe968267262b24a0a3931a009b39531a6fe570e60",
      "licence" : "LGPLv21",
      "maven" : {
        "groupId" : "com.puppycrawl.tools",
        "artifactId" : "checkstyle",
        "version" : "10.21.0",
      }
    },

     "CHECKSTYLE_8.36.1" : {
      "urls" : [
        "https://github.com/checkstyle/checkstyle/releases/download/checkstyle-8.36.1/checkstyle-8.36.1-all.jar"
      ],
      "digest": "sha512:faaacfd79a93586b54064c8b85587d892530fe50a7eb8904cd6e46d8f7d3f253359383f57e9c5788e403a6c9a637f6f52fcf75c006138194efcdbf1962ef5ee7",
      "licence" : "LGPLv21",
      "maven" : {
        "groupId" : "com.puppycrawl.tools",
        "artifactId" : "checkstyle",
        "version" : "8.36.1",
      }
    },

    "HAMCREST" : {
      "digest": "sha512:e237ae735aac4fa5a7253ec693191f42ef7ddce384c11d29fbf605981c0be077d086757409acad53cb5b9e53d86a07cc428d459ff0f5b00d32a8cbbca390be49",
      "sourceDigest": "sha512:38553c75f18f7b39ec86b6c0ce468c775c858f3b7fe234e6bdba1f36a089953a69ea9b645afa34eedb67e0f27e016cde084c2f194d466bc930445de6f7e3fef4",
      "licence" : "BSD-new",
      "maven" : {
        "groupId" : "org.hamcrest",
        "artifactId" : "hamcrest-core",
        "version" : "1.3",
      }
    },

    "COMMONS_MATH3_3_2" : {
      "digest": "sha512:80fb66a51688c4247b957f9787921e5acb9144d71a4ab0b03b2c30f46427e50c53e6e31ca5ddb04dab2cf5e7c0eedae168103c719f8074be464918ab2e4d6e6d",
      "sourceDigest": "sha512:bbb9223025a399ea4dd030da20484030c5ac564ff15b463f67165d2aa17aecdb15fb52fe09ce6aa1f896e749730ebe44cb794c2618200fdc8b5bc7dda6837483",
      "licence" : "Apache-2.0",
      "maven" : {
        "groupId" : "org.apache.commons",
        "artifactId" : "commons-math3",
        "version" : "3.2"
      }
    },

    "JOPTSIMPLE_4_6" : {
      "digest": "sha512:18bf59191d7a456e7675c841df8411ebe425da40532e103db95483be5d2a75510d8a38ad9755cdd4e0be27afe7cfd0b358599388a84fcec1ee27e89caa37f5af",
      "sourceDigest": "sha512:bd10f5ba984b2d75334353f2dd093c28455d49ea05a2c6776fa3834adc386545393f016f13b6608e096b4f8546f4b9d1c3c3948d249a4dbb9b89347b144eea7f",
      "licence": "MIT",
      "maven" : {
        "groupId" : "net.sf.jopt-simple",
        "artifactId" : "jopt-simple",
        "version" : "4.6"
      }
    },

    "JMH_GENERATOR_ANNPROCESS_1_18" : {
      "digest": "sha512:554d58fe550862aa07341668b37aa2bc8780630490c67e73512fc53bf8e4c570f6d8866bf0675a6d1503f680aa649303fb12aae6ede5edc73e65f41e01fb5387",
      "sourceDigest": "sha512:d45f26e49a7d0cb97c38362ee07bd98d542abacccb0d4721da6515a810fe4c01bea62cc900d324ac42162076926b24f56f8247133c402956a7522b2e957c9ff1",
      "licence": "GPLv2-CPE",
      "maven" : {
        "groupId" : "org.openjdk.jmh",
        "artifactId" : "jmh-generator-annprocess",
        "version" : "1.18",
      }
    },

    "JMH_GENERATOR_ANNPROCESS_1_21" : {
      "digest": "sha512:352deb5304ad54d8089485ce066e409c689012a0dee5af4fd8511402cd35624dd4cabd507b876115304c0c9824b837e96028500e279ba164480e1195a757b45c",
      "sourceDigest": "sha512:0c4b7187fd7f524ffe3b63708776136bdd4cddafa172e1f571488c5d0fe4a5526e1edf1e74ef7619950620df8b65003577f1ea97b1c10a935e39361e4e4822f0",
      "licence": "GPLv2-CPE",
      "maven" : {
        "groupId" : "org.openjdk.jmh",
        "artifactId" : "jmh-generator-annprocess",
        "version" : "1.21",
      }
    },

    "JMH_1_18" : {
      "digest": "sha512:2c6fecd9b0f2d114cc826849eae626351ebf94b7bdb46c0e3d73e0c6bbfe996640bed5c3eb20d9235f20cff49dd9b7a341512fa9ab30a8f6ce3c70e5263c90ff",
      "sourceDigest": "sha512:e64394608aa51408d02bce6f4c85ef152aae53046b2301eeadbbf398fb76042db169905046b79ada652f54f5188490d7a898bb4fbc5a73fd18be0cc34b644b21",
      "licence": "GPLv2-CPE",
      "dependencies" : ["JOPTSIMPLE_4_6", "JMH_GENERATOR_ANNPROCESS_1_18", "COMMONS_MATH3_3_2"],
      "maven" : {
        "groupId" : "org.openjdk.jmh",
        "artifactId" : "jmh-core",
        "version" : "1.18",
      }
    },

    "JMH_1_21" : {
      "digest": "sha512:81bca9388bdd0612fa65ca85ccaec5ba01738d7e45e76ea90f64dfb89539ad4dbfca064189dcc05a43f0f3f1bd0b6124676968a953ff7989b06232ff8d00574b",
      "sourceDigest": "sha512:899cedb156944cc1da1b291ca4a592ad57f9069e1c27c23db934eb8c0e9495c4616f51a7ca7d718cecb7edc0e60c07e2740163893e1c942bd5b026c8e5f14798",
      "licence": "GPLv2-CPE",
      "dependencies" : ["JOPTSIMPLE_4_6", "JMH_GENERATOR_ANNPROCESS_1_21", "COMMONS_MATH3_3_2"],
      "maven" : {
        "groupId" : "org.openjdk.jmh",
        "artifactId" : "jmh-core",
        "version" : "1.21",
      }
    },

    "JACKPOT" : {
      "digest": "sha512:117e22f1d509ad5eac019111f78a39da4ed0eb6f5211fbec30030fab9a1d77a9dcaca2cc8eb1c9f8351cc4a218c6aba389af637149c1f561299a4f68effccd10",
      "sourceDigest": "sha512:75fc4e3846a51ca5cfa344518a6b369e0830f1a451b320a82d0466a4f341297503fdd758fa4873fa758b06741d87dd60dd616cd66a04a35d70971622da819e67",
      "licence": "Apache-2.0",
      "maven" : {
        "groupId" : "org.apache.netbeans.modules.jackpot30",
        "artifactId" : "tool",
        "version" : "12.5",
      }
    },

    "PROGUARD_BASE_7_1_0" : {
      "digest": "sha512:4d41a822fe37d5d479e43e2416967f7ecb8530f0e4bb4cf8e6e29f7dbf5b8a979b434a255303df1f0135ba3fa63f1348452f9cc0a1603352aca8bab11facbf46",
      "maven" : {
        "groupId" : "com.guardsquare",
        "artifactId" : "proguard-base",
        "version" : "7.1.0",
      }
    },

    "PROGUARD_CORE_7_1_0" : {
      "digest": "sha512:55e47990ce6b141b6892921853e84a109166c1292b0c9003e4afd6d2c8422d944622b337e199da501ef4954dcb3d555ddb0806924f516a7752faaab0a8f26322",
      "maven" : {
        "groupId" : "com.guardsquare",
        "artifactId" : "proguard-core",
        "version" : "7.1.0",
      }
    },

    "PROGUARD_RETRACE_7_1_0" : {
      "digest": "sha512:c9b5ee54b8295c0c9b49c866d7cebde14f4bb9d0adcc1715e0e0278c401750393bc5c15921e891c97420c5b8938ff4a9c66080ae393c4a9da6d2864da1970714",
      "maven" : {
        "groupId" : "com.guardsquare",
        "artifactId" : "proguard-retrace",
        "version" : "7.1.0",
      }
    },

    "LOG4J_API_2_15_0" : {
      "digest": "sha512:39f88d089c5c7ce85e326aba1b32ace0a21e540fd4580c9c1e1b483251cb945aa568fa8ea3b0f82e3392ce13433c4c5626d0b6be909593774d71cded64483f15",
      "maven" : {
        "groupId" : "org.apache.logging.log4j",
        "artifactId" : "log4j-api",
        "version" : "2.15.0",
      }
    },

    "LOG4J_CORE_2_15_0" : {
      "digest": "sha512:7dd3c6d0e8f0bd4cd7d0e54ac515611ee2796d720a75f8b1b8b582eb1ef6bb5e736685c4e1c18fa70f3f9301acfc5b683aa72062321df6d906cd4be9b046fa85",
      "maven" : {
        "groupId" : "org.apache.logging.log4j",
        "artifactId" : "log4j-core",
        "version" : "2.15.0",
      }
    },

    "LOG4J_API_2_17_1" : {
      "digest": "sha512:48a58c2f317d451ac1622bdfbfa5d3cd9de45d40d5d5df98f39fe6d53c74da56e200f8e3d19a309d4e1ea364369379c0ef9d79b928fc20ea743857f347259c03",
      "maven" : {
        "groupId" : "org.apache.logging.log4j",
        "artifactId" : "log4j-api",
        "version" : "2.17.1",
      }
    },

    "LOG4J_CORE_2_17_1" : {
      "digest": "sha512:8d3d6a17afc41cde43b19c9a696793d009d9271bc6430762f10157018453f8a53cde6e6aa4f3f0b703eaf1f2944d047398d29b470924ecc3290d1923b0e29750",
      "maven" : {
        "groupId" : "org.apache.logging.log4j",
        "artifactId" : "log4j-core",
        "version" : "2.17.1",
      }
    },

    "LOG4J_API_2_19_0" : {
      "digest": "sha512:f7cf3647ed90de7fdef377e4321aa9b9ea2512a46d99109b359f7fc5dcfe6d3ae9f879c212707ea4fd16d358d10d21c56d5178ec4803504745de6fe48c66c3f7",
      "maven" : {
        "groupId" : "org.apache.logging.log4j",
        "artifactId" : "log4j-api",
        "version" : "2.19.0",
      }
    },

    "LOG4J_CORE_2_19_0" : {
      "digest": "sha512:1300ada6f86818ef4dcd17448a8965c1c6dd41ec414de2b2a5bafdf25d03c12100fa9e8f422d7b346f2984e5dfb3d599f8c1a971a6bcaca0cf938943d06364e7",
      "maven" : {
        "groupId" : "org.apache.logging.log4j",
        "artifactId" : "log4j-core",
        "version" : "2.19.0",
      }
    },

    "LOG4J_API_2_24_2" : {
      "digest": "sha512:9665821c14c582dddd0ed181f8d49da3e25857eec11328e0d8978757f1cd2360ae60cf103a4b26b1ad5be47cf0857863a7a3c432a0f71f9eef14f64e8754f35c",
      "maven" : {
        "groupId" : "org.apache.logging.log4j",
        "artifactId" : "log4j-api",
        "version" : "2.24.2",
      }
    },

    "LOG4J_CORE_2_24_2" : {
      "digest": "sha512:9a8ab3921a8285d500c3e6ce78254803cd785a18fb196951b2161a2a773043317e7c7a30fcf171948e861c952ff1d14a3baf66e1eba7f3393eb956f1069ac677",
      "maven" : {
        "groupId" : "org.apache.logging.log4j",
        "artifactId" : "log4j-core",
        "version" : "2.24.2",
      }
    },

    "ORG_JSON_20211205" : {
      "digest": "sha512:bcfada5d9f87bd6494e2c9b4d8da2a700b262eb2541296cf5f38a6e4c8dddf496f1db4bb8b10277dcdf8882a7942ab84b5d73e636312c2b193cf3d5d2969ef82",
      "maven" : {
        "groupId" : "org.json",
        "artifactId" : "json",
        "version" : "20211205",
      }
    },

    "ORG_JSON_20231013" : {
      "digest": "sha512:a5cdd1ed984448d6538746429f2d1a0ec8f64f93af0e84870ce898a9f07a81d11bf27d2ee081471975772efc8a0d3d5e05541197a532066e9edb09ad032d31a3",
      "maven" : {
        "groupId" : "org.json",
        "artifactId" : "json",
        "version" : "20231013",
      }
    },

    "GSON_2.9.0" : {
      "digest": "sha512:13ff22a60ee6a72ba0c4e8fe3702b8f3f6be6b67ed4279079a9843f57ad0ca125d4ecc1564ac4e736eab10fb6254d2c011b2c08c514d708be7f8091332ed2c2c",
      "maven" : {
        "groupId" : "com.google.code.gson",
        "artifactId" : "gson",
        "version" : "2.9.0",
      }
    },

    "GSON_2.11.0" : {
      "digest": "sha512:b8c91426a8275b42ea5c55b104308ffbe656ae3354bc661f62173352e53a4818a009e4dd82bc6cf518c77fda5a4d2eab0d3ad832581a8f0d87966ef04e6c025a",
      "maven" : {
        "groupId" : "com.google.code.gson",
        "artifactId" : "gson",
        "version" : "2.11.0",
      }
    },

    # As of 8.0.0, the versioning of ProGuardCORE is unlinked from ProguardBASE and ProguardRETRACE
    # since ProGuardCORE is a general library used by other projects.
    # https://github.com/Guardsquare/proguard/issues/132#issuecomment-887610759
    "PROGUARD_CORE_8_0_0" : {
      "digest": "sha512:5c6bb0de77cd99a1c18c421754965403f21f59cf8d13276b07ef41a748f1f1a8dca99fd4f16c79ba474fda3425194e7d91c1e9c342f59caafeb978b2f65289f4",
      "maven" : {
        "groupId" : "com.guardsquare",
        "artifactId" : "proguard-core",
        "version" : "8.0.0",
      },
      "dependencies" : ["LOG4J_CORE_2_15_0", "LOG4J_API_2_15_0"],
    },

    "PROGUARD_CORE_9_0_3" : {
      "digest": "sha512:a376c1ff1873a7225add0cdb3aa68cae7659854fe7a1005031c9129938ba151bafa0c775f67fc93b2e5b3c5a69d2a36f9d0690a005381b8fe3de29a7eebf0abb",
      "maven" : {
        "groupId" : "com.guardsquare",
        "artifactId" : "proguard-core",
        "version" : "9.0.3",
      },
      "dependencies" : ["LOG4J_CORE_2_17_1", "LOG4J_API_2_17_1"],
    },

    "PROGUARD_CORE_9_0_8" : {
      "digest": "sha512:d728792f5d3b1a14ff61f4ff455bf09879dba3edd2e9af66fb738a90ae36cb2d004738564db1f1809d53deba01662a50eb5b66bf1c7df38da59a851c85dd31c5",
      "maven" : {
        "groupId" : "com.guardsquare",
        "artifactId" : "proguard-core",
        "version" : "9.0.8",
      },
      "dependencies" : ["LOG4J_CORE_2_19_0", "LOG4J_API_2_19_0"],
    },

    "PROGUARD_RETRACE_7_2_0_beta1" : {
      "digest": "sha512:55157386457f22faf4ea3fe7d9e494a43a7fb4b6865e4db74e3e8f8e4f2d4c781cc8f720eaa4de0f2e92c5e30544f8f0dbe9ad4d654da6de4bb5ffb1f2878c22",
      "maven" : {
        "groupId" : "com.guardsquare",
        "artifactId" : "proguard-retrace",
        "version" : "7.2.0-beta1",
      },
      "dependencies" : ["PROGUARD_CORE_8_0_0"],
    },

    "PROGUARD_BASE_7_2_0_beta1" : {
      "digest": "sha512:45d6c9524895041872cf67217f409f855df630d67bbf1ad2ca0cdd88223072090f86f2bda07219dd0170e0c12b1f88c7e5d253e8d36eb9679d31925265ee14d7",
      "maven" : {
        "groupId" : "com.guardsquare",
        "artifactId" : "proguard-base",
        "version" : "7.2.0-beta1",
      },
      "dependencies" : ["PROGUARD_CORE_8_0_0"],
    },

    "PROGUARD_RETRACE_7_3_0_beta1" : {
      "digest": "sha512:7b156134f6749ddd3b397be89c62a36f81915d2cfd61eb1185872a8eac776f526418f6dd3e05a5da52c1ce96ff590a4279bc4ab92a522398e047cf5d4d82b7cc",
      "maven" : {
        "groupId" : "com.guardsquare",
        "artifactId" : "proguard-retrace",
        "version" : "7.3.0-beta1",
      },
      "dependencies" : ["PROGUARD_BASE_7_3_0_beta1"],
    },

    "PROGUARD_BASE_7_3_0_beta1" : {
      "digest": "sha512:aa1d9ccd1d2ea8ca7f7c7ae21fa8a5c8d0f0e927c6303a2b662890f2968c56f1f445bf378cfa67db23892fdac0468f3a183fef77380c676d3f475cd57578889b",
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

    "PROGUARD_BASE_7_3_2_alpha" : {
      "digest": "sha512:0dcdb47379b084a1d8358a837661111497db6919ce014e21e7772749967d996075e90717f49330b0b00374d65e122d0da211b48763d987c130567b676590bab1",
      "urls": ["https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/proguard-7.3.2-alpha.jar"],
    },

    "PROGUARD_RETRACE_7_3_2_alpha" : {
      "digest": "sha512:f51074ef93c54b9dec6c629f4241ab4fb0e8ebc583b9293f1f95c37bc886a94dcdb95cdfa5eb9ac5e01611c289e7d7f56779627041481dd5c491894f2119313f",
      "urls": ["https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/retrace-7.3.2-alpha.jar"],
    },

    "PROGUARD_BASE_7_3_2" : {
      "digest": "sha512:1d5c988372930ed5d4b441d9ff3102e278173b01f2552779261d6f76da6cbeebf26c7d5cf53d860112cbf645f9c59b35b122782d5d60c4386c873ff1691a624f",
      "maven" : {
        "groupId" : "com.guardsquare",
        "artifactId" : "proguard-base",
        "version" : "7.3.2",
      },
      "dependencies" : [
        "PROGUARD_CORE_9_0_8",
        "LOG4J_CORE_2_19_0",
        "LOG4J_API_2_19_0",
        "ORG_JSON_20211205"
      ],
    },

    "PROGUARD_RETRACE_7_3_2" : {
      "digest": "sha512:5ef65868a441345716a1c4ae7fd78dceb97754246787daadd3edaaae57dcd8c3e9f9c22d1d8a97dc28cf6312214acadac94c0188f22fafbb7b293ec766b83de3",
      "maven" : {
        "groupId" : "com.guardsquare",
        "artifactId" : "proguard-retrace",
        "version" : "7.3.2",
      },
      "dependencies" : ["PROGUARD_BASE_7_3_2"],
    },

    "PROGUARD_BASE_7_3_2_JDK21_BACKPORT" : {
      # Identical to PROGUARD_RETRACE_7_3_2 besides the dependency on PROGUARD_CORE_9_0_8_JDK21_BACKPORT
      "digest": "sha512:1d5c988372930ed5d4b441d9ff3102e278173b01f2552779261d6f76da6cbeebf26c7d5cf53d860112cbf645f9c59b35b122782d5d60c4386c873ff1691a624f",
      "maven" : {
        "groupId" : "com.guardsquare",
        "artifactId" : "proguard-base",
        "version" : "7.3.2",
      },
      "dependencies" : [
        "PROGUARD_CORE_9_0_8_JDK21_BACKPORT",
        "LOG4J_CORE_2_19_0",
        "LOG4J_API_2_19_0",
        "ORG_JSON_20211205"
      ],
    },

    "PROGUARD_CORE_9_0_8_JDK21_BACKPORT" : {
      # Built from https://github.com/graalvm/proguard-core/tree/da/jdk21
      "digest": "sha512:4605e7374736faebd71a4c49eb05cbd6da7894630fb037936335767d3b094201638b1ca7052db040b3dd804cf4eff5861d79c130ce8cec4ebf96c1ad42790283",
      "urls": ["https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/proguard-core-9.0.8-jdk21-backport.jar"],
    },

    "PROGUARD_BASE_7_5_0" : {
      "digest": "sha512:da7c0cc01daabbec0a6861288ae0a6f2aa5d70bb4ff01e356724cd0a9448f10789de793d1dcc5a9f246dc335041e66a4d0c9d4f5ec885a8fc56bc5dd82c9345a",
      "maven" : {
        "groupId" : "com.guardsquare",
        "artifactId" : "proguard-base",
        "version" : "7.5.0",
      },
      "dependencies" : [
        "PROGUARD_CORE_9_1_4",
        "GSON_2.9.0",
        "LOG4J_CORE_2_19_0",
        "LOG4J_API_2_19_0",
        "ORG_JSON_20231013"
      ],
    },

    "PROGUARD_RETRACE_7_5_0" : {
      "digest": "sha512:0bfeb05ebd170670684193883c660003ffd079f0d889166c220ebc3ebc12c16bffa92e8291bd4d802753a21f2cae1864ccaada781b5027458e7a694ae7ab9c63",
      "maven" : {
        "groupId" : "com.guardsquare",
        "artifactId" : "proguard-retrace",
        "version" : "7.5.0",
      },
      "dependencies" : ["PROGUARD_BASE_7_5_0"],
    },

    "PROGUARD_CORE_9_1_4" : {
      "digest": "sha512:a385b489b649377d1bc0aced28dc84e24c61460edb32d126162a48465055323aa2e5d92c9a83d29e31629378651a299a964c2576d58f4fc56e7c15ce46fd6424",
      "maven" : {
        "groupId" : "com.guardsquare",
        "artifactId" : "proguard-core",
        "version" : "9.1.4",
      },
      "dependencies" : ["LOG4J_CORE_2_19_0", "LOG4J_API_2_19_0"],
    },

    "JETBRAINS_JAVA_ANNOTATIONS_26_0_1" : {
      "digest": "sha512:c7be38957318874b837d029dc7b2a1f8b009feaa5362a56cba4f4c8a7d502993b3c900ee338eb9c9ee9494d7fd946bd280403eee28b244d213edb0b145a9ebfd",
      "maven" : {
        "groupId" : "org.jetbrains",
        "artifactId" : "annotations",
        "version" : "26.0.1",
      },
    },

    "PROGUARD_CORE_9_1_10" : {
      "digest": "sha512:45b3e9170e56b7beebb81e74160292556a2d6adb22f315287a288cccfa56868ca59d82a8eb0960c26fec369fd37971b761f3655a1b8ad38b77d6b66a776c8fc0",
      "maven" : {
        "groupId" : "com.guardsquare",
        "artifactId" : "proguard-core",
        "version" : "9.1.10",
      },
      "dependencies" : ["LOG4J_CORE_2_24_2", "LOG4J_API_2_24_2", "JETBRAINS_JAVA_ANNOTATIONS_26_0_1"],
    },

    "PROGUARD_BASE_7_7_0" : {
      "digest": "sha512:8d4dffc91c7710101e7b08becca484c10396a680918aea68a84929f77f037d58e717174f306a48421d051eb1559c2e40d77751b8efe7bc13472d32769f99c705",
      "maven" : {
        "groupId" : "com.guardsquare",
        "artifactId" : "proguard-base",
        "version" : "7.7.0",
      },
      "dependencies" : [
        "PROGUARD_CORE_9_1_10",
        "GSON_2.11.0",
        "LOG4J_CORE_2_24_2",
        "LOG4J_API_2_24_2",
        "ORG_JSON_20231013"
      ],
    },

    "PROGUARD_RETRACE_7_7_0" : {
      "digest": "sha512:14c88b9f314827d0f5f27ad29c9eeef622451004168970a5fc41e3ae9b085eb924132af62c32809a388a5edc7ce790e0d53ae833518031f120031111c9775991",
      "maven" : {
        "groupId" : "com.guardsquare",
        "artifactId" : "proguard-retrace",
        "version" : "7.7.0",
      },
      "dependencies" : ["PROGUARD_BASE_7_7_0"],
    },

    "NINJA" : {
      "packedResource" : True,
      "os_arch" : {
        "linux" : {
          "amd64" : {
            "version" : "1.10.2",
            # Built from the same source as https://github.com/ninja-build/ninja/releases/download/v{version}/ninja-linux.zip,
            # but on a system with older glibc for maximum compatibility with older Linux distributions.
            "urls" : ["https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/ninja-{version}-linux-amd64.zip"],
            "digest": "sha512:203be0ba85c899530cbf8d27f9f2a2e8247ae3cea66ea3f9f2e2f159cc4583bf424c130791f9ac6d70a4abf53e48291a696704b0670272ceb5ab63d00003acaf"
          },
          "aarch64" : {
            "version" : "1.10.2",
            "urls" : ["https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/ninja-{version}-linux-aarch64.zip"],
            "digest": "sha512:6592d1c6397a3968df5d473c11c29de040df938a06ac5351f09bdea10fe78a4d171e9dd8be68e62cba30d01b72d575f55b29376b46812e7c4c168df34dbbf76f"
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
            "version" : "1.10.2",
            "urls" : ["https://lafo.ssw.jku.at/pub/graal-external-deps/ninja-{version}-linux-amd64-musl.zip"],
            "digest": "sha512:5f23099cac6d9e852c2368930ecf0eb859afc17aeba48cbcba844ecb7a020e30aae2f637186544d780a1319162a4b4dc8b230996f19ce0b4f1aeb61be6a56653"
          }
        },
        "darwin" : {
          "amd64" : {
            "version" : "1.10.2",
            "urls" : ["https://github.com/ninja-build/ninja/releases/download/v{version}/ninja-mac.zip"],
            "digest": "sha512:bcd12f6a3337591306d1b99a7a25a6933779ba68db79f17c1d3087d7b6308d245daac08df99087ff6be8dc7dd0dcdbb3a50839a144745fa719502b3a7a07260b"
          },
          "aarch64" : {
            "version" : "1.10.2",
            "urls" : ["https://github.com/ninja-build/ninja/releases/download/v{version}/ninja-mac.zip"],
            "digest": "sha512:bcd12f6a3337591306d1b99a7a25a6933779ba68db79f17c1d3087d7b6308d245daac08df99087ff6be8dc7dd0dcdbb3a50839a144745fa719502b3a7a07260b"
          }
        },
        "windows" : {
          "amd64" : {
            # This is a hotfix version for Windows to support long paths (GR-67552). Eventually, this dependency should
            # be updated and built from source on all platforms (GR-13214).
            "version" : "1.12.1",
            "urls" : ["https://github.com/ninja-build/ninja/releases/download/v{version}/ninja-win.zip"],
            "digest": "sha512:d6715c6458d798bcb809f410c0364dabd937b5b7a3ddb4cd5aba42f9fca45139b2a8a3e7fd9fbd88fd75d298ed99123220b33c7bdc8966a9d5f2a1c9c230955f"
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
      "digest": "sha512:8c9756de31a88be913f9bb9ff440c58a5c109721348cb59542fb1eee6f95d99f686121b2ab31622b37683632b1a9391285906e31d13f79b82b9e0980681dee4d"
    },

    "SONARSCANNER_CLI_4_2_0_1873": {
      "digest": "sha512:69311bc54a898aac4631a09945dd5621f86c63f6c747b00fe7ffdf479f11ee89a112be3051196ec17c7bf883c045b0b81abfb4d2807a8be106fa6078bcfeb370",
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
            "digest": "sha512:dd991d57234c55c2b8d6c7cb91a001287a5ea15d76ccafc08c7004fc50ea1231c26a9bcfcb41e4d9a9b18b6b041f57c1ae15c0e1e1a7daab1fff7cb18b504725",
            "urls": ["{urlbase}/async-profiler-1.8.3-linux-x64.tar.gz"],
          },
          "aarch64": {
            "digest": "sha512:7445c9d2ecb0fc568ae490976bf58eebbccec04b5466cc80fc52323bcf2513847e9aef1dc89de95a32896f9953a2007493555123c4dfdfcf85cf112810f70ea5",
            "urls": ["{urlbase}/async-profiler-1.8.3-linux-aarch64.tar.gz"],
          },
          "<others>": {
            "optional": True,
          }
        },
        "darwin": {
          "amd64": {
            "digest": "sha512:3e49b1dd6b3240b6f3653914a2288bedbb5ad88e6476b704c3d055bafa4cbe7ec6f556a7dbc086f18b07ef29d89949bc4d9b8485aa62106c92475c62df2e9395",
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
      "digest": "sha512:ab441acf5551a7dc81c353eaccb3b3df9e89a48987294d19e39acdb83a5b640fcdff7414cee29f5b96eaa8826647f1d5323e185018fe33a64c402d69c73c9158",
      "maven": {
        "groupId": "org.eclipse.jdt",
        "artifactId": "ecj",
        "version": "3.26.0",
      },
      "licence": "EPL-2.0",
    },

    # compatible version for JDK 11 (no longer compatible with < 11)
    "ECJ_3.27": {
      "digest": "sha512:6ceffd50cbcdd539bc8a31d40f674e8e97995697e5c737bf66119c8921e727562586ea6e451a3e0c504337a6725845ee32bd894383afae3a898ff2b57d1962b2",
      "maven": {
        "groupId": "org.eclipse.jdt",
        "artifactId": "ecj",
        "version": "3.27.0",
      },
      "licence": "EPL-2.0",
    },

    # compatible version for JDK >= 17
    "ECJ_3.32": {
      "digest": "sha512:62b19c6701547cb30922fd336a0d40fb0610279a732a93673910954028b79d69e0e3175494d20d3dae9bf4b844677c6bc5d29f337f45b6988bcfaf93b3787602",
      "maven": {
        "groupId": "org.eclipse.jdt",
        "artifactId": "ecj",
        "version": "3.32.0",
      },
      "licence": "EPL-2.0",
    },

    # compatible version for JDK >= 21
    "ECJ_3.36": {
      "digest": "sha512:f889b0f305cdf6b548e13ef73cd8ec488be3bf43a3d48659a1fcfce01068fb47adb398bb6006a067d61cfefbee7ecc279e4fcea385f27be211817709cdebc54e",
      "maven": {
        "groupId": "org.eclipse.jdt",
        "artifactId": "ecj",
        "version": "3.36.0",
      },
      "licence": "EPL-2.0",
    },

    # compatible version for JDK >= 24
    "ECJ_3.41": {
      "digest": "sha512:f79cadd22cc0b2c9ce8d7cd168280b98835caa24dd6b8c14aab06ce67fe2048c161c6f4b38df686783e64aeb4953cbb0886fea6e3abffad99aa62f1aa80e6d40",
      "maven": {
        "groupId": "org.eclipse.jdt",
        "artifactId": "ecj",
        "version": "3.41.0",
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
    "UPL": {
      "name": "Universal Permissive License, Version 1.0",
      "url": "http://opensource.org/licenses/UPL",
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
      "graalCompilerSourceEdition": "ignore",
    },

    "com.oracle.mxtool.junit" : {
      "subDir" : "java",
      "sourceDirs" : ["src"],
      "dependencies" : [
        "JUNIT",
      ],
      "requires" : [
        "java.management",
      ],
      "javaCompliance" : "1.8+",
      "checkstyleVersion" : "8.36.1",
      "graalCompilerSourceEdition": "ignore",
    },

    "com.oracle.mxtool.junit.jdk9" : {
      "subDir" : "java",
      "sourceDirs" : ["src"],
      "dependencies" : [
        "JUNIT",
      ],
      "requiresConcealed" : {
        "java.base" : [
          "jdk.internal.module",
        ],
      },
      "multiReleaseJarVersion": "9",
      "overlayTarget" : "com.oracle.mxtool.junit",
      "checkPackagePrefix" : False,
      "requires" : [
        "java.management",
        "jdk.unsupported",
      ],
      "javaCompliance" : "9+",
      "checkstyle" : "com.oracle.mxtool.junit",
      "graalCompilerSourceEdition": "ignore",
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
      "graalCompilerSourceEdition": "ignore",
    },

    "com.oracle.mxtool.jacoco" : {
      "subDir" : "java",
      "sourceDirs" : ["src"],
      "javaCompliance" : "1.8+",
      "checkstyle" : "com.oracle.mxtool.junit",
      "dependencies" : [
        "JACOCOREPORT_0.8.13",
        "JOPTSIMPLE_4_6",
      ],
      "graalCompilerSourceEdition": "ignore",
    },

    "com.oracle.mxtool.webserver" : {
      "subDir" : "java",
      "sourceDirs" : ["src"],
      "javaCompliance" : "1.8+",
      "checkstyle" : "com.oracle.mxtool.junit",
      "graalCompilerSourceEdition": "ignore",
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
          },
          "loongarch64" : {
            "cflags" : ["-fPIC", "-Wall", "-Werror", "-O", "-g", "-DJVMTI_ASM_ARCH=loongarch64", "-std=gnu99"],
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
      "graalCompilerSourceEdition": "ignore",
    },
    "com.oracle.gcc.ninja.toolchain": {
      "class": "NinjaToolchainTemplate",
      "template": "ninja-toolchains/gcc.ninja_template",
      "output_file": "gcc.ninja_template",
    },
    "com.oracle.msvc.ninja.toolchain": {
      "class": "NinjaToolchainTemplate",
      "template": "ninja-toolchains/msvc.ninja_template",
      "output_file": "msvc.ninja_template",
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
      "graalCompilerSourceEdition": "ignore",
    },

    "MX_JACOCO_REPORT" : {
      "subDir" : "java",
      "mainClass" : "com.oracle.mxtool.jacoco.JacocoReport",
      "dependencies" : ["com.oracle.mxtool.jacoco"],
      "graalCompilerSourceEdition": "ignore",
    },

    "MX_MICRO_BENCHMARKS" : {
      "subDir" : "java",
      "dependencies" : ["com.oracle.mxtool.jmh_1_21"],
      "graalCompilerSourceEdition": "ignore",
    },

    "GCC_NINJA_TOOLCHAIN": {
      "native": True,
      "platformDependent": False,
      "description": "ninja rules for a GCC toolchain found on the PATH",
      "layout": {
        "toolchain.ninja": "dependency:com.oracle.gcc.ninja.toolchain",
      },
      "maven": False,
      "graalCompilerSourceEdition": "ignore",
    },

    "MSVC_NINJA_TOOLCHAIN": {
      "native": True,
      "platformDependent": False,
      "description": "ninja rules for a MSVC toolchain found on the PATH",
      "layout": {
        "toolchain.ninja": "dependency:com.oracle.msvc.ninja.toolchain",
      },
      "maven": False,
      "graalCompilerSourceEdition": "ignore",
    },

    "DEFAULT_NINJA_TOOLCHAIN": {
      "native": True,
      "platformDependent": True,
      "description": "Default ninja rules for an OS-dependent toolchain found on the PATH",
      "native_toolchain": {
        "kind": "ninja",
        "target": {
          # all defaults (host compiler, host os/arch/libc, no variant)
        },
      },
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
              "./": "extracted-dependency:MSVC_NINJA_TOOLCHAIN",
            },
            "asm_requires_cpp": True,
          },
        },
      },
      "maven": False,
      "graalCompilerSourceEdition": "ignore",
    },
    "DEFAULT_CMAKE_TOOLCHAIN": {
      "native": True,
      "platformDependent": True,
      "description": "Default (empty) ninja toolchain for an OS-dependent toolchain found on the PATH",
      "native_toolchain": {
        "kind": "cmake",
        "target": {
          # all defaults (host compiler, host os/arch/libc, no variant)
        },
      },
      "layout": {
        "toolchain.cmake": "string:",
      },
      "maven": False,
      "graalCompilerSourceEdition": "ignore",
    },
  },
}
