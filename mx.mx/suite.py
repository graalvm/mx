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
        "http://repo1.maven.org/maven2/org/apidesign/javadoc/codesnippet-doclet/0.9/codesnippet-doclet-0.9.jar",
      ],
      "sha1" : "4de316ba4d1e646dc44f92e4b1c4501d79afe595",
    },

    "JUNIT" : {
      "urls" : [
        "https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/junit-4.11.jar",
        "https://search.maven.org/remotecontent?filepath=junit/junit/4.11/junit-4.11.jar",
      ],
      "sha1" : "4e031bb61df09069aeb2bffb4019e7a5034a4ee0",
      "eclipse.container" : "org.eclipse.jdt.junit.JUNIT_CONTAINER/4",
      "sourceUrls" : [
        "https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/junit-4.11-sources.jar",
        "https://search.maven.org/remotecontent?filepath=junit/junit/4.11/junit-4.11-sources.jar",
      ],
      "sourceSha1" : "28e0ad201304e4a4abf999ca0570b7cffc352c3c",
      "dependencies" : ["HAMCREST"],
      "licence" : "CPL",
      "maven" : {
      	"groupId" : "junit",
    	"artifactId" : "junit",
    	"version" : "4.11",
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

    "JMH" : {
      "sha1" : "7e1577cf6e1f1326b78a322d206fa9412fd41ae9",
      "urls" : ["https://lafo.ssw.uni-linz.ac.at/pub/jmh/jmh-runner-1.11.2.jar"],
      "sourceSha1" : "12a67f0dcdfe7e43218bf38c1d7fd766122a3dc7",
      "sourceUrls" : ["https://lafo.ssw.uni-linz.ac.at/pub/jmh/jmh-runner-1.11.2-sources.jar"],
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
  },

  "projects" : {

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

}
