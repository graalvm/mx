suite = {
  "name" : "mx",
  "libraries" : {

    # ------------- Libraries -------------
    # TODO update when jacoco 0.8.9 is released
    "JACOCOCORE_0.8.9.202211161124": {
      "urls" : [
        "https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/jacoco/0.8.9.202211161124/org.jacoco.core-0.8.9-20221116.112445-21.jar",
        "https://oss.sonatype.org/content/repositories/snapshots/org/jacoco/org.jacoco.core/0.8.9-SNAPSHOT/org.jacoco.core-0.8.9-20221116.112445-21.jar",
      ],
      "digest": "sha512:3f80b97d0683d7120de437e558a44f7d331d53fce24ac850a9c0dc84b168149f0c3f4b2707a1b5776256163c75ea442f022b97fc74aa42a595ae6b8027937dc8",
      #"sourceDigest": "sha512:1eb671bad9b14e87b9ae18ff2905d4c6af9e5f5517cacb2509b689162392066d2c45b8d87238dc11d94bc3c86899e3fe2ccb03cf44200eeec2927e3716d9d111",
      "maven": {
        "groupId": "org.jacoco",
        "artifactId": "org.jacoco.core",
        "version": "0.8.9.202211161124",
      },
      "dependencies" : ["ASM_9.4", "ASM_COMMONS_9.4", "ASM_TREE_9.4"],
      "license": "EPL-2.0",
    },

    "JACOCOAGENT_0.8.9.202211161124": {
      "urls" : [
        "https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/jacoco/0.8.9.202211161124/org.jacoco.agent-0.8.9-20221116.112445-21-runtime.jar",
        "https://oss.sonatype.org/content/repositories/snapshots/org/jacoco/org.jacoco.agent/0.8.9-SNAPSHOT/org.jacoco.agent-0.8.9-20221116.112445-21-runtime.jar",
      ],
      "digest": "sha512:80bef0e7c9cdd27008185c036c82e6e6938d4a6df1f54ba3d16bd0364eff8619f54bc6a57a1a8257fe2dd59e85b93771af54c3cedfb74766cd73d3c3d6ecedbd",
      "maven": {
        "groupId": "org.jacoco",
        "artifactId": "org.jacoco.agent",
        "version": "0.8.9.202211161124",
        "classifier": "runtime",
      },
      "license": "EPL-2.0",
    },

    "JACOCOREPORT_0.8.9.202211161124": {
      "urls" : [
        "https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/jacoco/0.8.9.202211161124/org.jacoco.report-0.8.9-20221116.112445-21.jar",
        "https://oss.sonatype.org/content/repositories/snapshots/org/jacoco/org.jacoco.report/0.8.9-SNAPSHOT/org.jacoco.report-0.8.9-20221116.112445-21.jar",
      ],
      "digest": "sha512:47baa5e92bf65c34a00f69b36597f34c0d541ee8a3a2f568695e7fc5c1e9d9468c7db7e382eb1061499ed703e90fc57ceab8a0c7e8924e7fe709fddf50fc5edc",
      #"sourceDigest": "sha512:6fd2f2f967eaaaf83c42218cefb3734eb63145d122bdf504d022ea130655793d0b75be182119a2f776fe16dcb1a07a8883600d222b18aae21e76d54df20a805c",
      "maven": {
        "groupId": "org.jacoco",
        "artifactId": "org.jacoco.report",
        "version": "0.8.9.202211161124",
      },
      "dependencies" : ["JACOCOCORE_0.8.9.202211161124"],
      "license": "EPL-2.0",
    },

    "ASM_9.4": {
      "digest": "sha512:41e6d8f67faa63e3993692d6606cbc68ec43d140e0232c5aee2ef7dbeea289ad5711ce04407c771e8baef844ead5f838d8b248e20a06e3fd5c41c52d3340a459",
      "sourceDigest": "sha512:a0bedd89c91c649269a4f718729f6f8a889c206a382480e842d7ca16b671ecb77a1df2388b63f7aa483bf1ff847873bc53efc470e526e50c714bf22e3912227c",
      "maven": {
        "groupId": "org.ow2.asm",
        "artifactId": "asm",
        "version": "9.4",
      },
      "license": "BSD-new",
    },

    "ASM_ANALYSIS_9.4": {
      "digest": "sha512:c507d357d3bde8279b8cfe907a82c595a44242de8397a7e096c5fb7fb1fdc25e7797ed79fa99c6965c5ba5ccc55b3e7dc7a77d55947976ce2184488fd4b90c5f",
      "sourceDigest": "sha512:bfcca1059a2fc5dae998615e006dda282a86a6e6a12bb43955816620642770c2cf5b1bc8d619cb4e7c3d1920a06cec2b51386571b92f3bf5025e2da0d1236822",
      "maven": {
        "groupId": "org.ow2.asm",
        "artifactId": "asm-analysis",
        "version": "9.4",
      },
      "dependencies" : ["ASM_TREE_9.4"],
      "license": "BSD-new",
    },

    "ASM_COMMONS_9.4": {
      "digest": "sha512:53e0acd2ad3bdf9ecbe08fc44a2d696f896cf52ef705aba27f7240c4ef23c71a38ab81f00159777746cf894a660301a9727ff06dccf35f8da2abc34366382d05",
      "sourceDigest": "sha512:688d56a1b4fb6f7d86b79b7493a848851892910d00067a0c5effdaf7132266ec7a1ba57a8248c2fd6c0ebdef18a4918908a36e85f5927b9acb55448047a1e333",
      "maven": {
        "groupId": "org.ow2.asm",
        "artifactId": "asm-commons",
        "version": "9.4",
      },
      "dependencies" : ["ASM_9.4", "ASM_TREE_9.4", "ASM_ANALYSIS_9.4"],
      "license": "BSD-new",
    },

    "ASM_TREE_9.4": {
      "digest": "sha512:8d008d5fd37640046ad57d8fbf803f1965a6a55a3521453411d07d48900da6436446d495daebabd705549ecec989f4d9de9434ade4ac482e94edc46ad564e02b",
      "sourceDigest": "sha512:552adb9543b7478a783c29497e0b8373867fd31830bd52d6578fa6747a921b50f618924f74d7b7a522fcf3a41ccc6099970254c5a520f14bc821ee1b66d32b4a",
      "maven": {
        "groupId": "org.ow2.asm",
        "artifactId": "asm-tree",
        "version": "9.4",
      },
      "dependencies" : ["ASM_9.4"],
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

    "CODESNIPPET-DOCLET_0.81" : {
      "maven" : {
        "groupId" : "org.apidesign.javadoc",
        "artifactId" : "codesnippet-doclet",
        "version" : "0.81",
      },
      "digest": "sha512:16b521dbf0ca497a0808b37d3f3304c21c89fc9739fae3afa05600f405142fdc2e0d9f200e428142ef6bb13d6ba48019c236c02eb1ec7dada34b9ee3f2b096d6",
    },

    "JUNIT" : {
      "digest": "sha512:5974670c3d178a12da5929ba5dd9b4f5ff461bdc1b92618c2c36d53e88650df7adbf3c1684017bb082b477cb8f40f15dcf7526f06f06183f93118ba9ebeaccce",
      "sourceDigest": "sha512:5c36f1671b1567919baa633e01765cf8e67c75f37f52876e11f764e3fccfa7b3c2b4cf2214b8956fd58a06f502694c80a208e8b88bcaca3893fc9c62820322a2",
      "dependencies" : ["HAMCREST"],
      "licence" : "CPL",
      "maven" : {
        "groupId" : "junit",
        "artifactId" : "junit",
        "version" : "4.12",
      }
    },

    "JUNIT-JUPITER": {
      "digest": "sha512:b5e91555946eeee06eb2c1b6cf3ce3c0514df5d0878e9dcfc78975e49b420433cc32c06793de6df4f15cc8fdc510a57f1bfc19e373b74631f9f1e32a4cee969d",
      "sourceDigest": "sha512:ff962502df582bdd191a6ddc72662203e0eadac2d848c255ca8aabb60e84756223c9eecd1c73a75a192f1692e92bdfbe2daf735002e32c2b22000747ff793df9",
      "license": "EPL-2.0",
      "dependencies": ["JUNIT-JUPITER-API", "JUNIT-JUPITER-PARAMS"],
      "maven": {
        "groupId": "org.junit.jupiter",
        "artifactId": "junit-jupiter",
        "version": "5.6.2",
      }
    },

    "JUNIT-JUPITER-API": {
        "digest": "sha512:8f05e1cd7abe6b7662dcf0136827fe1917b5d6716bc632399d1abaeca7d0afddc90766700faa39ecd1ce122586fb0e3a081a3acb3b5449c4bd4fe590c64d6905",
        "sourceDigest": "sha512:cfa10341a1be531ecc1cf064a179fe70b56e05812e3f5547e376ae8f8d53bdbab21ce3089e99c184421cbf817573935e36efeaeea6a4daa129583db20f7fe583",
        "license": "EPL-2.0",
        "dependencies": ["APIGUARDIAN-API", "OPENTEST4J"],
        "maven": {
            "groupId": "org.junit.jupiter",
            "artifactId": "junit-jupiter-api",
            "version": "5.6.2",
        }
    },

    "APIGUARDIAN-API": {
        "digest": "sha512:eb05878cf282e971a7fff0ff4a1b7b90d61e6405ea368b19832177269b21f66ad4de211f6abdd762165a72e1c19781a6df1187e6c1cce1ae2cbf0e913fc5f504",
        "sourceDigest": "sha512:e8d3b49129ade2f7a27461f702e9f8ec6421b27e666055ca13e914b1bfe3b8c067ee17094477752fdebdded109718f581a1ae42579e5cef990f531eb61bfe921",
        "license": "EPL-2.0",
        "maven": {
            "groupId": "org.apiguardian",
            "artifactId": "apiguardian-api",
            "version": "1.1.0",
        }
    },

    "OPENTEST4J": {
        "digest": "sha512:17f77797a260eb2bd1666a90e25efc79a5413afa9df1c1cb6c4cd1949d61c38b241e3bb20956396b5f54d144720303d72a2ac00bc5bf245a260a3c3099e01c74",
        "sourceDigest": "sha512:273324c995654f0c7edc5dbf7cd9233f7f3fe400c45e042669f3c25d6476485a738e6baf8f61d08e8a5559dd0b07deae77849059d910d53deabd36424d0fa4ab",
        "license": "EPL-2.0",
        "dependencies": ["JUNIT-PLATFORM-COMMONS"],
        "maven": {
            "groupId": "org.opentest4j",
            "artifactId": "opentest4j",
            "version": "1.2.0",
        }
    },

    "JUNIT-PLATFORM-COMMONS": {
        "digest": "sha512:f46a9197398006a9b01d72f4cfed4959871b585e81fd0871068d99868028d9d09fd3e40e3398cbef3bb3ad062af496f60c659e53f72ac3388c964e594dec978f",
        "sourceDigest": "sha512:be62915e41df44f2cfd38e3584019000ad91eb29fae771244a57338d9d968fe283a1252806742996bbc29f8aad4ccd0b9c0120d3409d7b526e9131c626b51a91",
        "license": "EPL-2.0",
        "dependencies": ["APIGUARDIAN-API"],
        "maven": {
            "groupId": "org.junit.platform",
            "artifactId": "junit-platform-commons",
            "version": "1.6.2",
        }
    },

    "JUNIT-JUPITER-PARAMS": {
      "digest": "sha512:5f44d4c9bbfd6ca37bfffd2f2c8b8c9fa9fa58c163104c27526f92689d1031e925875251288b92bf946941359aab17083e70443d6172917853ecb6da36e451fc",
      "sourceDigest": "sha512:f68f5daa7c992dfbdf9d6374cea4401f4e4a1a83c9bafec76a349ac8a75b1bf776772c77245bcd181fbfa6214418edde3490822e92c0f1314a0a7ebe105b1a15",
      "license": "EPL-2.0",
      "dependencies": ["APIGUARDIAN-API"],
      "maven": {
        "groupId": "org.junit.jupiter",
        "artifactId": "junit-jupiter-params",
        "version": "5.6.2",
      }
    },

    "JUNIT-PLATFORM-ENGINE": {
      "digest": "sha512:9cd0926e5525c478692950fef24075641a57ba09c0a9f57d25a1c27ba4f9a5b5541574f90e8fcfb877b3bad676f4a17d0c4080cf8ef7efec9db1f67ede3694dd",
      "sourceDigest": "sha512:c98e5fd839feb486325867b5a740c11842856f20b97259b9635c4359f3b86299cb7b73926443b06d6eeee9b69f4fc0c63e9231f546a822db2a60f0bc1b30ec38",
      "license": "EPL-2.0",
      "dependencies": ["APIGUARDIAN-API", "OPENTEST4J"],
      "maven": {
        "groupId": "org.junit.platform",
        "artifactId": "junit-platform-engine",
        "version": "1.6.2",
      }
    },

    "JUNIT-JUPITER-ENGINE": {
      "digest": "sha512:054e831ab0a815a59b7e401e1a07911e41d5f0938153d3c4f2f8834e69ad04bd2a9b50c8728df5e70095b1a5288b44e9e0456353e804ba1a947504f7fd283175",
      "sourceDigest": "sha512:279e993d9a81797609e43f6888b6cc63dccbd5308d4d6f0f096dc4e5cbf5bba3482480e7e66cc6c196bf2617ad5249069d7aa18fc71c91cee5797bd2cd711c3e",
      "license": "EPL-2.0",
      "dependencies": ["JUNIT-JUPITER-API", "APIGUARDIAN-API", "JUNIT-PLATFORM-ENGINE"],
      "maven": {
        "groupId": "org.junit.jupiter",
        "artifactId": "junit-jupiter-engine",
        "version": "5.6.2",
      }
    },

    "JUNIT-PLATFORM-LAUNCHER": {
      "digest": "sha512:9c48fced4c879781102393b90aed41fd25996a3109015aa9e1f65391c93dacacd47131fad9b894238cb6a7679cb9fb203c73dae6d2bb684fc8af1a22f6b3dc37",
      "sourceDigest": "sha512:1edaac661f73d3aaf70241a3f251cbb94d4a52997c73c858fed5bc1323ce952d5cc7d73e252ab89770b0ac401a0807a915520efe27174a2c5ce925ffb7d29ccb",
      "license": "EPL-2.0",
      "dependencies": ["APIGUARDIAN-API", "JUNIT-PLATFORM-ENGINE"],
      "maven": {
        "groupId": "org.junit.platform",
        "artifactId": "junit-platform-launcher",
        "version": "1.6.2",
      }
    },

    "JUNIT-PLATFORM-REPORTING": {
      "digest": "sha512:78d11d1abd918388a7a156010877dd9d3874fae04d2bf1436e15cf164e24bdefd363b57d36c4f12a3b1b741f1af82b20d788fdf081e1293dbde722f27879eb96",
      "sourceDigest": "sha512:58b0c139fff6886ac7e15bd74d99a6d3987e787c67b72b7b944a75418557ac653d70dcff9b9783be62d41905dd46d5e04b18045a8b6868d8788e66f53ed1d4ed",
      "license": "EPL-2.0",
      "dependencies": ["APIGUARDIAN-API", "JUNIT-PLATFORM-LAUNCHER"],
      "maven": {
        "groupId": "org.junit.platform",
        "artifactId": "junit-platform-reporting",
        "version": "1.6.2",
      }
    },

    "JUNIT-PLATFORM-CONSOLE": {
      "digest": "sha512:1129bf4e5299ec32e91d63edda0a8af5d1402a39a9913e366b638728ca232261abf894074304f66d61344b3cb1502a09f3c2ee6140a8859a89ed9bef8c336704",
      "sourceDigest": "sha512:39f5fa057621f84b418b5d58972c242fbbf262af80e6d33e6db2f7601da39bc9c492be9a8f1789497b68f0b0b3c2a5006f60e82e40f6ce2e757f7a62990caa06",
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

    "ORG_JSON_20211205" : {
      "digest": "sha512:bcfada5d9f87bd6494e2c9b4d8da2a700b262eb2541296cf5f38a6e4c8dddf496f1db4bb8b10277dcdf8882a7942ab84b5d73e636312c2b193cf3d5d2969ef82",
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

    "NINJA" : {
      "packedResource" : True,
      "version" : "1.10.2",
      "os_arch" : {
        "linux" : {
          "amd64" : {
            # Built from the same source as https://github.com/ninja-build/ninja/releases/download/v{version}/ninja-linux.zip,
            # but on a system with older glibc for maximum compatibility with older Linux distributions.
            "urls" : ["https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/ninja-{version}-linux-amd64.zip"],
            "digest": "sha512:203be0ba85c899530cbf8d27f9f2a2e8247ae3cea66ea3f9f2e2f159cc4583bf424c130791f9ac6d70a4abf53e48291a696704b0670272ceb5ab63d00003acaf"
          },
          "aarch64" : {
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
            "urls" : ["https://lafo.ssw.jku.at/pub/graal-external-deps/ninja-{version}-linux-amd64-musl.zip"],
            "digest": "sha512:5f23099cac6d9e852c2368930ecf0eb859afc17aeba48cbcba844ecb7a020e30aae2f637186544d780a1319162a4b4dc8b230996f19ce0b4f1aeb61be6a56653"
          }
        },
        "darwin" : {
          "amd64" : {
            "urls" : ["https://github.com/ninja-build/ninja/releases/download/v{version}/ninja-mac.zip"],
            "digest": "sha512:bcd12f6a3337591306d1b99a7a25a6933779ba68db79f17c1d3087d7b6308d245daac08df99087ff6be8dc7dd0dcdbb3a50839a144745fa719502b3a7a07260b"
          },
          "aarch64" : {
            "urls" : ["https://github.com/ninja-build/ninja/releases/download/v{version}/ninja-mac.zip"],
            "digest": "sha512:bcd12f6a3337591306d1b99a7a25a6933779ba68db79f17c1d3087d7b6308d245daac08df99087ff6be8dc7dd0dcdbb3a50839a144745fa719502b3a7a07260b"
          }
        },
        "windows" : {
          "amd64" : {
            "urls" : ["https://github.com/ninja-build/ninja/releases/download/v{version}/ninja-win.zip"],
            "digest": "sha512:6004140d92e86afbb17b49c49037ccd0786ce238f340f7d0e62b4b0c29ed0d6ad0bab11feda2094ae849c387d70d63504393714ed0a1f4d3a1f155af7a4f1ba3"
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
        "JACOCOREPORT_0.8.9.202211161124",
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
