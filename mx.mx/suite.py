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
      "digest": "sha512:305cb927e15cb709c61378d8b878daba5c9118190ddcca4283005e8228394e58434dfd49e13378b589ac690c2302203220eb14a82098f815d6d9e4a1fe519415",
      "sourceDigest": "sha512:5fc1841122dcdfb207a4984627672ffc2f7355c79c9cfd1f3e63601192f34facc60d2901864a2b09f99a0ea5ee193a8ac1f9d1b008264b74d6d4430ebaeeb70a",
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
      "digest": "sha512:857619474934be2a3c02e852d8edb308494d72afa4c3a72d973a7c635f5845a4499b7309bbac1b16ffcdde3882e9e3f831cf5190e8880fd49b79d6fcaf82f7bb",
      "sourceDigest": "sha512:80ff964df42835f752fe52b25e9840fe394400076b033d1d3ca80e2850b9b5549c6c618b4b1bcd86ee422628e4b5623118a2b860b24d3fbd439547422b1523ba",
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
      "digest": "sha512:0bb033b176c8893bfceba098381f5fef429096d5fe9c6b3eb6fdaac63d88dd059d44f3f296851573fe461888288ca2fa61dadae30530fa08fb3d6214c27915fe",
      "sourceDigest": "sha512:6f903251a03d1da10272693d86ecb5ba3ef3b388b38236788ef6bb3cf44a3bf37062feba1bcd176bace4fdde01d5c9e496633d670c53f45c01983bea3083b82c",
      "maven": {
        "groupId": "org.ow2.asm",
        "artifactId": "asm-analysis",
        "version": "9.3",
      },
      "dependencies" : ["ASM_TREE_9.3"],
      "license": "BSD-new",
    },

    "ASM_COMMONS_9.3": {
      "digest": "sha512:0bd9c61553808b8a12822f009ea5622918033a9fa8cb6e3ef319bbff08dda00cf439b5653f25d8f3362f02166530a0eabe2664f1169bcd63e2ed93a603c13874",
      "sourceDigest": "sha512:0bcf0465187935f48e45a1ba9dec7f5b60408cc9087547c79ea83748bdcddf7653d7941fc2f442065c7b415172868d6a117215bc2b9f3fbfcafd527818e1b86c",
      "maven": {
        "groupId": "org.ow2.asm",
        "artifactId": "asm-commons",
        "version": "9.3",
      },
      "dependencies" : ["ASM_9.3", "ASM_TREE_9.3", "ASM_ANALYSIS_9.3"],
      "license": "BSD-new",
    },

    "ASM_TREE_9.3": {
      "digest": "sha512:666318e09f4ae02652a64ce2ddd4dd51275a1917108061155aa8d1d9956e9d54bc259d0586ed7cd745c6ac00ab54fbfdd577f6ce915a158fc2eef373d65d445c",
      "sourceDigest": "sha512:80a2828c214e1dd78accbeaefe70f8810756f3fecd8928f48dafe074c7d677ad0ffb8d695fa447e704cbda8fc622586e23dacf1479eca219e7300b7a8c9e77a6",
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
      "digest": "sha1:b5c481685b6a8ca91c0d46f28f886a444354daa5",
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
        "digest": "sha1:c9ba885abfe975cda123bf6f8f0a69a1b46956d0",
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
        "digest": "sha1:fc9dff4bb36d627bdc553de77e1f17efd790876c",
        "sourceDigest": "sha512:e8d3b49129ade2f7a27461f702e9f8ec6421b27e666055ca13e914b1bfe3b8c067ee17094477752fdebdded109718f581a1ae42579e5cef990f531eb61bfe921",
        "license": "EPL-2.0",
        "maven": {
            "groupId": "org.apiguardian",
            "artifactId": "apiguardian-api",
            "version": "1.1.0",
        }
    },

    "OPENTEST4J": {
        "digest": "sha1:28c11eb91f9b6d8e200631d46e20a7f407f2a046",
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
        "digest": "sha1:7644a14b329e76b5fe487628b50fb5eab6ba7d26",
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
      "digest": "sha1:f2a64a42cf73077062c2386db0598062b7480d91",
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
      "digest": "sha1:1752cad2579e20c2b224602fe846fc660fb35805",
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
      "digest": "sha1:c0833bd6de29dd77f8d071025b97b8b434308cd3",
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
      "digest": "sha1:d866de2950859ca1c7996351d7b3d97428083cd0",
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
      "digest": "sha1:517d3b96b4ed89700a5086ec504fc02d8b526e79",
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
      "digest": "sha1:dfdeb2688341f7566c5943be7607a413d753ab70",
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
      "digest": "sha1:b852fb028de645ad2852bbe998e084d253f450a5",
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
      "digest": "sha1:0174aa0077e9db596e53d7f9ec37556d9392d5a6",
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
      "digest": "sha1:c90da86c534257d09defae5eead0b94d3086e749",
      "sourceDigest": "sha512:75fc4e3846a51ca5cfa344518a6b369e0830f1a451b320a82d0466a4f341297503fdd758fa4873fa758b06741d87dd60dd616cd66a04a35d70971622da819e67",
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
