suite = {
  "name" : "mx",
  "libraries" : {

    # ------------- Libraries -------------

    "JACOCOAGENT" : {
      "urls" : ["https://lafo.ssw.uni-linz.ac.at/pub/jacoco/jacocoagent-0.7.1-1.jar"],
      "sha1" : "2f73a645b02e39290e577ce555f00b02004650b0",
    },

    "JACOCOREPORT" : {
      "urls" : ["https://lafo.ssw.uni-linz.ac.at/pub/jacoco/jacocoreport-0.7.1-2.jar"],
      "sha1" : "a630436391832d697a12c8f7daef8655d7a1efd2",
    },

    "FINDBUGS_DIST" : {
      "urls" : [
        "https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/findbugs-3.0.0.zip",
        "http://sourceforge.net/projects/findbugs/files/findbugs/3.0.0/findbugs-3.0.0.zip/download",
      ],
      "sha1" : "6e56d67f238dbcd60acb88a81655749aa6419c5b",
    },

    "SIGTEST" : {
      "urls" : [
        "http://hg.netbeans.org/binaries/A7674A6D78B7FEA58AF76B357DAE6EA5E3FDFBE9-apitest.jar",
      ],
      "sha1" : "a7674a6d78b7fea58af76b357dae6ea5e3fdfbe9",
    },

    "CODESNIPPET-DOCLET" : {
      "urls" : [
        "http://repo1.maven.org/maven2/org/apidesign/javadoc/codesnippet-doclet/0.21/codesnippet-doclet-0.21.jar",
      ],
      "sha1" : "7c4b9aaa6e86e46351ea498dcbae4bca618e3b04",
    },

    "JUNIT" : {
      "urls" : [
        "https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/junit-4.12.jar",
        "https://search.maven.org/remotecontent?filepath=junit/junit/4.12/junit-4.12.jar",
      ],
      "sha1" : "2973d150c0dc1fefe998f834810d68f278ea58ec",
      "sourceUrls" : [
        "https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/junit-4.12-sources.jar",
        "https://search.maven.org/remotecontent?filepath=junit/junit/4.12/junit-4.12-sources.jar",
      ],
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

    "HAMCREST" : {
      "urls" : [
        "https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/hamcrest-core-1.3.jar",
        "https://search.maven.org/remotecontent?filepath=org/hamcrest/hamcrest-core/1.3/hamcrest-core-1.3.jar",
      ],
      "sha1" : "42a25dc3219429f0e5d060061f71acb49bf010a0",
      "sourceUrls" : [
        "https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/hamcrest-core-1.3-sources.jar",
        "https://search.maven.org/remotecontent?filepath=org/hamcrest/hamcrest-core/1.3/hamcrest-core-1.3-sources.jar",
      ],
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

    "JMH": {
      "sha1": "df111ae8e92bfd84fe135b844c4e3a910e1b8497",
      "urls": ["https://lafo.ssw.uni-linz.ac.at/pub/jmh/jmh-runner-1.12.jar"],
      "sourceSha1": "b8c0f381c83c08b36244ab116025f87841e6b251",
      "sourceUrls": ["https://lafo.ssw.uni-linz.ac.at/pub/jmh/jmh-runner-1.12-sources.jar"],
      "licence": "GPLv2-CPE",
    },

    "JACKPOT" : {
      "urls" : [
        "https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/jackpot-8.1-20151011.220626.jar",
      ],
      "sha1" : "b5f91770afd3b8ce645e7b967a1f266ab472053b",
    },

    "PROGUARD" : {
      "urls" : [
        "http://lafo.ssw.uni-linz.ac.at/graal-external-deps/proguard-base-5.3.1.jar",
        "https://repo1.maven.org/maven2/net/sf/proguard/proguard-base/5.3.1/proguard-base-5.3.1.jar",
      ],
      "sha1" : "996a984a7e230fdcfc269d66a6c91fd1587edd50",
    },

    "PROGUARD_RETRACE" : {
      "urls" : [
        "http://lafo.ssw.uni-linz.ac.at/graal-external-deps/proguard-retrace-5.3.1.jar",
        "https://repo1.maven.org/maven2/net/sf/proguard/proguard-retrace/5.3.1/proguard-retrace-5.3.1.jar",
      ],
      "sha1" : "4a57d643d2ded6ebcf4b7bcdab8fcf3d2588aa1b",
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
    "MIT" : {
      "name" : "MIT License",
      "url" : "http://opensource.org/licenses/MIT"
    },
    "Apache-2.0" : {
      "name" : "Apache License 2.0",
      "url" : "https://opensource.org/licenses/Apache-2.0"
    },
  },

  "projects" : {

    "com.oracle.mxtool.bench" : {
      "subDir" : "java",
      "sourceDirs" : ["src"],
      "dependencies" : [
        "JMH",
      ],
      "javaCompliance" : "1.8",
      "annotationProcessors" : ["JMH"],
    },

    "com.oracle.mxtool.jmh_1_18" : {
      "subDir" : "java",
      "sourceDirs" : ["src"],
      "dependencies" : [
        "JMH_1_18",
      ],
      "javaCompliance" : "1.8",
      "annotationProcessors" : ["JMH_1_18"],
    },

    "com.oracle.mxtool.junit" : {
      "subDir" : "java",
      "sourceDirs" : ["src"],
      "dependencies" : [
        "JUNIT",
      ],
      "javaCompliance" : "1.8",
    },

    "com.oracle.mxtool.compilerserver" : {
      "subDir" : "java",
      "sourceDirs" : ["src"],
      "javaCompliance" : "1.7+", # jdk7 or later
    },

    "com.oracle.mxtool.checkcopy" : {
      "subDir" : "java",
      "sourceDirs" : ["src"],
      "javaCompliance" : "1.8",
    },
  },

  "distributions" : {

    "JUNIT_TOOL" : {
      "subDir" : "java",
      "dependencies" : [
        "com.oracle.mxtool.junit"
      ],
    },
  },

}
