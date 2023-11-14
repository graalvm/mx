#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2015, Oracle and/or its affiliates. All rights reserved.
# DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS FILE HEADER.
#
# This code is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 2 only, as
# published by the Free Software Foundation.
#
# This code is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
# version 2 for more details (a copy is included in the LICENSE file that
# accompanied this code).
#
# You should have received a copy of the GNU General Public License version
# 2 along with this work; if not, write to the Free Software Foundation,
# Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Please contact Oracle, 500 Oracle Parkway, Redwood Shores, CA 94065 USA
# or visit www.oracle.com if you need additional information or have any
# questions.
#
# ----------------------------------------------------------------------------------------------------

import sys, inspect, re, bisect
from collections import OrderedDict
from os.path import join
from . import mx

class MxCompatibility500(object):
    @staticmethod
    def version():
        return mx.VersionSpec("5.0.0")

    def supportsLicenses(self):
        return False

    def licenseAttribute(self):
        return 'licence'

    def licensesAttribute(self):
        return 'licences'

    def defaultLicenseAttribute(self):
        return 'defaultLicence'

    def supportedMavenMetadata(self):
        return []

    def supportsRepositories(self):
        return False

    def newestInputIsTimeStampFile(self):
        '''
        Determines if the 'newestInput' parameter of BuildTask.needsBuild()
        is a TimeStampFile or a simple time stamp (i.e. a float).
        '''
        return False

    def getSuiteOutputRoot(self, suite):
        return suite.dir

    def mavenDeployJavadoc(self):
        return False

    def validate_maven_javadoc(self):
        return False

    def mavenSupportsClassifier(self):
        return False

    def checkstyleVersion(self):
        return '6.0'

    def checkDependencyJavaCompliance(self):
        """
        Determines if a project must have a higher or equal Java compliance level
        than a project it depends upon.
        """
        return False

    def improvedImportMatching(self):
        return False

    def verifySincePresent(self):
        return []

    def moduleDepsEqualDistDeps(self):
        """
        Determines if the constituents of a module derived from a distribution are
        exactly the same as the constituents of the distribution.
        """
        return False

    def useDistsForUnittest(self):
        """
        Determines if Unittest uses jars from distributions for testing.
        """
        return False

    def excludeDisableJavaDebuggging(self):
        """
        Excludes the misspelled class name.
        """
        return False

    def makePylintVCInputsAbsolute(self):
        """
        Makes pylint input paths discovered by VC absolute.
        """
        return False

    def disableImportOfTestProjects(self):
        """
        Requires that test projects can only be imported by test projects.
        """
        return False

    def useJobsForMakeByDefault(self):
        """
        Uses -j for make by default, can be prevented using `single_job` attribute on the project.
        """
        return False

    def overwriteProjectAttributes(self):
        """
        Attributes from the configuration that are not explicitly handled overwrite values set by the constructor.
        """
        return True

    def requireJsonifiableSuite(self):
        return False

    def supportSuiteImportGitBref(self):
        return True

    def enforceTestDistributions(self):
        return False

    def deprecateIsTestProject(self):
        return False

    def filterFindbugsProjectsByJavaCompliance(self):
        """
        Should selection of projects to analyze with FindBugs filter
        out projects whose Java compliance is greater than 8.
        """
        return False

    def addVersionSuffixToExplicitVersion(self):
        return False

    def __str__(self):
        return str(f"MxCompatibility({self.version()})")

    def __repr__(self):
        return str(self)

    def jarsUseJDKDiscriminant(self):
        """
        Should `mx.JARDistribution` use the jdk version used for the build as a `Dependency._extra_artifact_discriminant`
        to avoid collisions of build artifacts when building with different JAVA_HOME/EXTRA_JAVA_HOMES settings.
        """
        return False

    def check_package_locations(self):
        """
        Should `canonicalizeprojects` check whether the java package declarations and source location match.
        """
        return False

    def check_checkstyle_config(self):
        """
        Should sanity check Checkstyle configuration for a project.
        """
        return False

    def verify_multirelease_projects(self):
        """
        Should multi-release projects be verified (see mx.verifyMultiReleaseProjects).
        """
        return False

    def spotbugs_version(self):
        """
        Which version of findbugs/spotbugs should be used?
        """
        return "3.0.0"

    def automatic_overlay_distribution_deps(self):
        """
        When a distribution depends on a project that has versioned overlays, are the
        overlay projects automatically added as dependencies to the distribution?
        """
        return False

    def supports_disjoint_JavaCompliance_range(self):
        """
        Specifies if disjoint JavaCompliance ranges (e.g. "8,13+") are supported.
        """
        return False

    def maven_deploy_unsupported_is_error(self):
        """
        Specifies if trying to deploy a distribution whose type is not supported is an error.
        """
        return False

    def enhanced_module_usage_info(self):
        """
        Returns True if a Java project must specify its use of concealed packages with
        a "requiresConcealed" attribute and use of modules other than java.base with
        a "requires" attribute.
        """
        return False

    def get_sigtest_jar(self):
        """
        Returns the proper version of the SIGTEST jar used by `mx sigtest`.
        """
        return mx.library('SIGTEST_1_2').get_path(resolve=True)

    def fix_extracted_dependency_prefix(self):
        """
        Returns True if the `./` prefix should be removed from `extracted-dependency` sources of layout distributions.
        """
        return False

    def is_using_jdk_headers_implicitly(self, project):
        """Returns whether a native project is using JDK headers implicitly.

        The use of JDK headers is implied if any build dependency is a Java project with JNI headers.
        """
        assert project.isNativeProject()
        is_using_jdk_headers = any(d.isJavaProject() and d.include_dirs for d in project.buildDependencies)
        if is_using_jdk_headers and project.suite._output_root_includes_config():
            project.abort('This project is using JDK headers implicitly. For MX_OUTPUT_ROOT_INCLUDES_CONFIG=true to '
                          'work, it must set the "use_jdk_headers" attribute explicitly.')
        return is_using_jdk_headers

    def bench_suite_needs_suite_args(self):
        """
        Returns whether extracting the benchmark suite name depends on the `bmSuiteArgs` or not.
        """
        return False

    def enforce_spec_compliant_exports(self):
        """Returns whether modular multi-release JARs must have spec compliant exports."""
        return False

    def jmh_dist_benchmark_extracts_add_opens_from_manifest(self):
        """Returns whether jmh benchmarks should extract --add-opens and --add-exports from the manifest file to
        place it explicitly on the command line."""
        return False

    def spotbugs_limited_to_8(self):
        """
        Specifies if running spotbugs limited to projects whose javaCompliance is JDK 8.
        """
        return True

    def proguard_supported_jdk_version(self):
        """
        Returns the maximum JDK version supported by ProGuard.
        """
        return 17

    def proguard_libs(self):
        """
        Returns the list of ProGuard libraries.
        """
        return {
            'BASE': '7_2_0_beta1',
            'RETRACE': '7_2_0_beta1',
        }

    def strict_verify_file_path(self):
        """
        Returns whether we use strict verify of ci file paths or not
        """
        return False

    def gate_spotbugs_strict_mode(self):
        """
        True if spotbugs mx gate --strict-mode should be propagated to spotbugs.
        """
        return False

    def gate_strict_tags_and_tasks(self):
        """
        True if mx gate --tags and --task should fail if they do not match any task.
        """
        return False

    def gate_run_pyformat(self) -> bool:
        """
        True if mx gate should run pyformat under the style tag
        """
        return False


class MxCompatibility520(MxCompatibility500):
    @staticmethod
    def version():
        return mx.VersionSpec("5.2.0")

    def supportsLicenses(self):
        return True

    def supportedMavenMetadata(self):
        return ['library-coordinates', 'suite-url', 'suite-developer', 'dist-description']

class MxCompatibility521(MxCompatibility520):
    @staticmethod
    def version():
        return mx.VersionSpec("5.2.1")

    def supportsRepositories(self):
        return True

class MxCompatibility522(MxCompatibility521):
    @staticmethod
    def version():
        return mx.VersionSpec("5.2.2")

    def licenseAttribute(self):
        return 'license'

    def licensesAttribute(self):
        return 'licenses'

    def defaultLicenseAttribute(self):
        return 'defaultLicense'

class MxCompatibility533(MxCompatibility522):
    @staticmethod
    def version():
        return mx.VersionSpec("5.3.3")

    def newestInputIsTimeStampFile(self):
        return True

class MxCompatibility555(MxCompatibility533):
    @staticmethod
    def version():
        return mx.VersionSpec("5.5.5")

    def getSuiteOutputRoot(self, suite):
        return join(suite.dir, 'mxbuild')

class MxCompatibility566(MxCompatibility555):
    @staticmethod
    def version():
        return mx.VersionSpec("5.6.6")

    def mavenDeployJavadoc(self):
        return True

class MxCompatibility5616(MxCompatibility566):
    @staticmethod
    def version():
        return mx.VersionSpec("5.6.16")

    def checkstyleVersion(self):
        return '6.15'

class MxCompatibility59(MxCompatibility5616):
    @staticmethod
    def version():
        return mx.VersionSpec("5.9.0")

    def verifySincePresent(self):
        return ['-verifysincepresent']

class MxCompatibility5200(MxCompatibility59):
    @staticmethod
    def version():
        return mx.VersionSpec("5.20.0")

    def checkDependencyJavaCompliance(self):
        return True

    def improvedImportMatching(self):
        return True

class MxCompatibility5344(MxCompatibility5200):
    @staticmethod
    def version():
        return mx.VersionSpec("5.34.4")

    def moduleDepsEqualDistDeps(self):
        return True

class MxCompatibility5590(MxCompatibility5344):
    @staticmethod
    def version():
        return mx.VersionSpec("5.59.0")

    def useDistsForUnittest(self):
        return True

class MxCompatibility5680(MxCompatibility5590):
    @staticmethod
    def version():
        return mx.VersionSpec("5.68.0")

    def excludeDisableJavaDebuggging(self):
        return True

class MxCompatibility51104(MxCompatibility5680):
    @staticmethod
    def version():
        return mx.VersionSpec("5.110.4")

    def makePylintVCInputsAbsolute(self):
        return True

class MxCompatibility51120(MxCompatibility51104):
    @staticmethod
    def version():
        return mx.VersionSpec("5.113.0")

    def disableImportOfTestProjects(self):
        return True


class MxCompatibility51150(MxCompatibility51120):
    @staticmethod
    def version():
        return mx.VersionSpec("5.115.0")

    def useJobsForMakeByDefault(self):
        return True


class MxCompatibility51247(MxCompatibility51150):
    @staticmethod
    def version():
        return mx.VersionSpec("5.124.7")

    def overwriteProjectAttributes(self):
        return False

class MxCompatibility51330(MxCompatibility51247):
    @staticmethod
    def version():
        return mx.VersionSpec("5.133.0")

    def requireJsonifiableSuite(self):
        return True

class MxCompatibility51380(MxCompatibility51330):
    @staticmethod
    def version():
        return mx.VersionSpec("5.138.0")

    def supportSuiteImportGitBref(self):
        return False

class MxCompatibility51400(MxCompatibility51380):
    @staticmethod
    def version():
        return mx.VersionSpec("5.140.0")

    def enforceTestDistributions(self):
        return True

    def deprecateIsTestProject(self):
        return True

class MxCompatibility51492(MxCompatibility51400):
    @staticmethod
    def version():
        return mx.VersionSpec("5.149.2")

    def filterFindbugsProjectsByJavaCompliance(self):
        return True

class MxCompatibility51760(MxCompatibility51492):
    @staticmethod
    def version():
        return mx.VersionSpec("5.176.0")

    def addVersionSuffixToExplicitVersion(self):
        return True

class MxCompatibility5181(MxCompatibility51760):
    @staticmethod
    def version():
        return mx.VersionSpec("5.181.0")

    def jarsUseJDKDiscriminant(self):
        return True

class MxCompatibility5194(MxCompatibility5181):
    @staticmethod
    def version():
        return mx.VersionSpec("5.194.0")

    def check_package_locations(self):
        return True

class MxCompatibility51950(MxCompatibility5194):
    @staticmethod
    def version():
        return mx.VersionSpec("5.195.0")

    def mavenSupportsClassifier(self):
        return True

class MxCompatibility51951(MxCompatibility51950):
    @staticmethod
    def version():
        return mx.VersionSpec("5.195.1")

    def check_checkstyle_config(self):
        return True

class MxCompatibility52061(MxCompatibility51951):
    @staticmethod
    def version():
        return mx.VersionSpec("5.206.1")

    def verify_multirelease_projects(self):
        return True

class MxCompatibility52102(MxCompatibility52061):
    @staticmethod
    def version():
        return mx.VersionSpec("5.210.2")

    def spotbugs_version(self):
        return "4.4.2"

class MxCompatibility52230(MxCompatibility52102):
    @staticmethod
    def version():
        return mx.VersionSpec("5.223.0")

    def automatic_overlay_distribution_deps(self):
        return True

    def supports_disjoint_JavaCompliance_range(self):
        return True


class MxCompatibility52290(MxCompatibility52230):
    @staticmethod
    def version():
        return mx.VersionSpec("5.229.0")

    def maven_deploy_unsupported_is_error(self):
        return True

class MxCompatibility52310(MxCompatibility52290):
    @staticmethod
    def version():
        return mx.VersionSpec("5.231.0")

    def enhanced_module_usage_info(self):
        return True


class MxCompatibility52710(MxCompatibility52310):
    @staticmethod
    def version():
        return mx.VersionSpec("5.271.0")

    def validate_maven_javadoc(self):
        return True


class MxCompatibility52791(MxCompatibility52710):
    @staticmethod
    def version():
        return mx.VersionSpec("5.279.1")

    def get_sigtest_jar(self):
        return mx.library('SIGTEST_1_3').get_path(resolve=True)


class MxCompatibility52820(MxCompatibility52791):
    @staticmethod
    def version():
        return mx.VersionSpec("5.282.0")

    def fix_extracted_dependency_prefix(self):
        return True


class MxCompatibility53000(MxCompatibility52820):
    @staticmethod
    def version():
        return mx.VersionSpec("5.300.0")

    def is_using_jdk_headers_implicitly(self, project):
        assert project.isNativeProject()
        if any(d.isJavaProject() and d.include_dirs for d in project.buildDependencies):
            project.abort('This project is using JDK headers implicitly. Instead, it must set the "use_jdk_headers" '
                          'attribute explicitly.')
        return False

class MxCompatibility53010(MxCompatibility53000):
    @staticmethod
    def version():
        return mx.VersionSpec("5.301.0")

    def bench_suite_needs_suite_args(self):
        return True


class MxCompatibility53169(MxCompatibility53010):
    @staticmethod
    def version():
        return mx.VersionSpec("5.316.9")

    def enforce_spec_compliant_exports(self):
        return True


class MxCompatibility531615(MxCompatibility53169):
    @staticmethod
    def version():
        return mx.VersionSpec("5.316.15")

    def jmh_dist_benchmark_extracts_add_opens_from_manifest(self):
        return True


class MxCompatibility655(MxCompatibility531615):
    @staticmethod
    def version():
        return mx.VersionSpec("6.5.5")

    def spotbugs_version(self):
        return "4.7.1"

    def spotbugs_limited_to_8(self):
        return False


class MxCompatibility670(MxCompatibility655):
    @staticmethod
    def version():
        return mx.VersionSpec("6.7.0")

    def proguard_supported_jdk_version(self):
        return 19

    def proguard_libs(self):
        return {
            'CORE': '9_0_3',
            'BASE': '7_2_0_beta1',
            'RETRACE': '7_2_0_beta1',
        }


class MxCompatibility680(MxCompatibility670):
    @staticmethod
    def version():
        return mx.VersionSpec("6.8.0")

    def strict_verify_file_path(self):
        return True


class MxCompatibility691(MxCompatibility680):
    @staticmethod
    def version():
        return mx.VersionSpec("6.9.1")

    def proguard_libs(self):
        return {
            'BASE': '7_3_0_beta1',
            'RETRACE': '7_3_0_beta1',
        }

class MxCompatibility6120(MxCompatibility691):
    @staticmethod
    def version():
        return mx.VersionSpec("6.12.0")

    def spotbugs_version(self):
        return "4.7.3"

class MxCompatibility6160(MxCompatibility6120):
    @staticmethod
    def version():
        return mx.VersionSpec("6.16.0")

    def proguard_supported_jdk_version(self):
        return 20

    def proguard_libs(self):
        return {
            'BASE': '7_3_2_alpha',
            'RETRACE': '7_3_2_alpha',
        }

class MxCompatibility6170(MxCompatibility6160):
    @staticmethod
    def version():
        return mx.VersionSpec("6.17.0")

    def proguard_supported_jdk_version(self):
        return 20

    def proguard_libs(self):
        return {
            'BASE': '7_3_2',
            'RETRACE': '7_3_2',
        }

class MxCompatibility6190(MxCompatibility6170):
    @staticmethod
    def version():
        return mx.VersionSpec("6.19.0")

    def gate_spotbugs_strict_mode(self):
        return True


class MxCompatibility6240(MxCompatibility6190):
    @staticmethod
    def version():
        return mx.VersionSpec("6.24.0")

    def gate_strict_tags_and_tasks(self):
        return True


class MxCompatibility6270(MxCompatibility6240):
    @staticmethod
    def version():
        return mx.VersionSpec("6.27.0")

    def proguard_supported_jdk_version(self):
        return 21

    def proguard_libs(self):
        return {
            'CORE': '9_0_8_JDK21_BACKPORT',
            'BASE': '7_3_2_JDK21_BACKPORT',
            'RETRACE': '7_3_2',
        }


class MxCompatibility6271(MxCompatibility6270):
    @staticmethod
    def version():
        return mx.VersionSpec("6.27.1")

    def spotbugs_version(self):
        return "4.7.3_JDK21_BACKPORT"


class MxCompatibility704(MxCompatibility6271):
    @staticmethod
    def version():
        return mx.VersionSpec("7.0.4")

    def gate_run_pyformat(self) -> bool:
        return True


def minVersion():
    _ensureCompatLoaded()
    return list(_versionsMap)[0]

def getMxCompatibility(version):
    """:rtype: MxCompatibility500"""
    if version < minVersion():  # ensures compat loaded
        return None
    keys = list(_versionsMap.keys())
    return _versionsMap[keys[bisect.bisect_right(keys, version)-1]]

_versionsMap = OrderedDict()

def _ensureCompatLoaded():
    if not _versionsMap:

        def flattenClassTree(tree):
            root = tree[0][0]
            assert isinstance(root, type), root
            yield root
            if len(tree) > 1:
                assert len(tree) == 2
                rest = tree[1]
                assert isinstance(rest, list), rest
                for c in flattenClassTree(rest):
                    yield c

        classes = []
        regex = re.compile(r'^MxCompatibility[0-9a-z]*$')
        for name, clazz in inspect.getmembers(sys.modules[__name__], inspect.isclass):
            m = regex.match(name)
            if m:
                classes.append(clazz)

        previousVersion = None
        for clazz in flattenClassTree(inspect.getclasstree(classes)):
            if clazz == object:
                continue
            assert previousVersion is None or previousVersion < clazz.version()
            previousVersion = clazz.version()
            _versionsMap[previousVersion] = clazz()
