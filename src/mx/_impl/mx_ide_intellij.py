#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2007, 2020, Oracle and/or its affiliates. All rights reserved.
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
#

try:
    # Use more secure defusedxml library, if available
    from defusedxml.ElementTree import parse as etreeParse
except ImportError:
    from xml.etree.ElementTree import parse as etreeParse

import os
import sys
# TODO use defusedexpat?
import re
import glob
from argparse import ArgumentParser, REMAINDER
from os.path import join, basename, dirname, exists, isdir, realpath
from io import StringIO
from dataclasses import dataclass

from . import mx, mx_util
from . import mx_ideconfig
from . import mx_javamodules

from .ide import project_processor


# IntelliJ SDK types.
intellij_java_sdk_type = 'JavaSDK'
intellij_python_sdk_type = 'Python SDK'
intellij_ruby_sdk_type = 'RUBY_SDK'


@dataclass
class IntellijConfig:
    python_projects: bool = True
    external_projects: bool = True
    java_modules: bool = True
    native_projects: bool = False
    max_java_compliance: int = 99
    import_inner_classes: bool = False
    on_save_actions: bool = False
    refresh_only: bool = False
    do_fsck_projects: bool = True
    mx_distributions: bool = False
    args: ... = None


@mx.command('mx', 'intellijinit')
def intellijinit_cli(args):
    """(re)generate Intellij project configurations"""
    parser = ArgumentParser(prog='mx ideinit')
    parser.add_argument('--no-python-projects', action='store_false', dest='python_projects', help='Do not generate projects for the mx python projects.')
    parser.add_argument('--no-external-projects', action='store_false', dest='external_projects', help='Do not generate external projects.')
    parser.add_argument('--no-java-projects', '--mx-python-modules-only', action='store_false', dest='java_modules', help='Do not generate projects for the java projects.')
    parser.add_argument('--native-projects', action='store_true', dest='native_projects', help='Generate native projects.')
    parser.add_argument('--max-java-compliance', dest='max_java_compliance', type=int, default=16, help='Cap the Java compliance at this value. IntelliJ requires an acceptance of a legal notice for beta Java specifications.')
    parser.add_argument('--import-inner-classes', action='store_true', dest='import_inner_classes', help='Configure auto-import to insert inner class imports.')
    parser.add_argument('--on-save-actions', action='store_true', dest='on_save_actions', help='Generate On Save Actions: checkstyle format and optimize imports.')
    parser.add_argument('--mx-distributions', action='store_true', dest='mx_distributions', help='Generate Ant powered build of mx distributions (generated Ant scripts delegate to `mx archive {DIST}, bundled Ant plugin must be enabled in IntelliJ).')
    parser.add_argument('args', nargs=REMAINDER, metavar='...')

    extra_args = os.environ.get('MX_INTELLIJINIT_DEFAULTS', '').split()
    if extra_args:
        mx.log("Applying extra arguments from MX_INTELLIJINIT_DEFAULTS environment variable")
    config = parser.parse_args(extra_args + args, namespace=IntellijConfig())
    intellijinit(config)


def intellijinit(config: IntellijConfig):
    # In a multiple suite context, the .idea directory in each suite
    # has to be complete and contain information that is repeated
    # in dependent suites.
    declared_modules = set()
    referenced_modules = set()
    sdks = intellij_read_sdks()

    suites = mx.suites(True)

    if config.python_projects and mx._mx_suite not in suites:
        suites.append(mx._mx_suite)

    for suite in suites:
        config.java_modules = config.java_modules and not suite.isBinarySuite()
        _intellij_suite(suite, declared_modules, referenced_modules, sdks, suite != mx.primary_suite(), config)

    if len(referenced_modules - declared_modules) != 0:
        mx.abort(f'Some referenced modules are missing from modules.xml: {referenced_modules - declared_modules}')

    if config.python_projects:
        # Module for the MX source code
        module_src = mx.XMLDoc()
        module_src.open('module', attributes={'type': 'PYTHON_MODULE', 'version': '4'})
        module_src.open('component', attributes={'name': 'NewModuleRootManager', 'inherit-compiler-output': 'true'})
        module_src.element('exclude-output')
        module_src.open('content', attributes={'url': 'file://$MODULE_DIR$'})
        module_src.element('sourceFolder', attributes={'url': 'file://$MODULE_DIR$', 'isTestSource': 'false'})
        module_src.close('content')
        module_src.element('orderEntry', attributes={'type': 'jdk', 'jdkType': intellij_python_sdk_type, 'jdkName': intellij_get_python_sdk_name(sdks, 'mx')})
        module_src.element('orderEntry', attributes={'type': 'sourceFolder', 'forTests': 'false'})
        module_src.close('component')
        module_src.close('module')
        mx.update_file(join(mx._mx_suite.dir, 'src', 'mx.iml'), module_src.xml(indent='  ', newl='\n'))

        # Module for the MX tests
        module_tests = mx.XMLDoc()
        module_tests.open('module', attributes={'type': 'PYTHON_MODULE', 'version': '4'})
        module_tests.open('component', attributes={'name': 'NewModuleRootManager', 'inherit-compiler-output': 'true'})
        module_tests.element('exclude-output')
        module_tests.open('content', attributes={'url': 'file://$MODULE_DIR$'})
        module_tests.element('sourceFolder', attributes={'url': 'file://$MODULE_DIR$', 'isTestSource': 'true'})
        module_tests.close('content')
        module_tests.element('orderEntry', attributes={'type': 'jdk', 'jdkType': intellij_python_sdk_type, 'jdkName': intellij_get_python_sdk_name(sdks, 'mx')})
        module_tests.element('orderEntry', attributes={'type': 'sourceFolder', 'forTests': 'false'})
        # Add dependency on mx source code module
        module_tests.element('orderEntry', attributes={'type': 'module', 'module-name': 'mx'})
        module_tests.close('component')
        module_tests.close('module')
        mx.update_file(join(mx._mx_suite.dir, 'tests', 'mx_tests.iml'), module_tests.xml(indent='  ', newl='\n'))

    if config.do_fsck_projects and not config.refresh_only:
        mx_ideconfig.fsckprojects([])

def intellij_read_sdks():
    sdks = dict()
    # https://www.jetbrains.com/help/idea/2023.2/directories-used-by-the-ide-to-store-settings-caches-plugins-and-logs.html
    if mx.is_linux() or mx.is_openbsd() or mx.is_sunos():
        xmlSdks = glob.glob(os.path.expanduser("~/.IdeaIC*/config/options/jdk.table.xml")) + \
          glob.glob(os.path.expanduser("~/.IntelliJIdea*/config/options/jdk.table.xml")) + \
          glob.glob(os.path.expanduser("~/.config/JetBrains/IdeaIC*/options/jdk.table.xml")) + \
          glob.glob(os.path.expanduser("~/.config/JetBrains/IntelliJIdea*/options/jdk.table.xml"))
    elif mx.is_darwin():
        xmlSdks = \
          glob.glob(os.path.expanduser("~/Library/Application Support/JetBrains/IdeaIC*/options/jdk.table.xml")) + \
          glob.glob(os.path.expanduser("~/Library/Application Support/JetBrains/IntelliJIdea*/options/jdk.table.xml")) + \
          glob.glob(os.path.expanduser("~/Library/Preferences/IdeaIC*/options/jdk.table.xml")) + \
          glob.glob(os.path.expanduser("~/Library/Preferences/IntelliJIdea*/options/jdk.table.xml"))
    elif mx.is_windows():
        xmlSdks = \
            glob.glob(os.path.expandvars("%APPDATA%/JetBrains/IdeaIC*/options/jdk.table.xml")) + \
            glob.glob(os.path.expandvars("%APPDATA%/JetBrains/IntelliJIdea*/options/jdk.table.xml")) + \
            glob.glob(os.path.expandvars("%LOCALAPPDATA%/JetBrains/IdeaIC*/options/jdk.table.xml")) + \
            glob.glob(os.path.expandvars("%LOCALAPPDATA%/JetBrains/IntelliJIdea*/options/jdk.table.xml"))
    else:
        mx.warn(f"Location of IntelliJ SDK definitions on {mx.get_os()} is unknown")
        return sdks
    if len(xmlSdks) == 0:
        mx.warn("IntelliJ SDK definitions not found")
        return sdks

    verRE = re.compile(r'^.*[/\\]\.?(IntelliJIdea|IdeaIC)([^/\\]+)[/\\].*$')
    def verSort(path):
        match = verRE.match(path)
        return match.group(2) + (".a" if match.group(1) == "IntellijIC" else ".b")

    xmlSdks.sort(key=verSort, reverse=True)

    sdk_version_regexes = {
        # Examples:
        #   java version "21"
        #   GraalVM version 21 (vendor name may change)
        #   Oracle OpenJDK 11.0.18 - aarch64
        #   Oracle OpenJDK 21.0.2
        #   Oracle OpenJDK 26 - aarch64
        intellij_java_sdk_type: re.compile(r'^java\s+version\s+"([^"]+)"$|'
                                           r'^(?:.+ )?version\s+(.+)$|'
                                           r'^([\d._]+)$|'
                                           r'^Oracle OpenJDK ([\d._]+).*$'),
        intellij_python_sdk_type: re.compile(r'^Python\s+(.+)$'),

        # Examples:
        #   truffleruby 19.2.0-dev-2b2a7f81, like ruby 2.6.2, Interpreted JVM [x86_64-linux]
        #   ver.2.2.4p230 ( revision 53155) p230
        intellij_ruby_sdk_type: re.compile(r'^\D*(\d[^ ,]+)')
    }

    sdk_languages = {
        intellij_java_sdk_type: 'Java',
        intellij_python_sdk_type: 'Python',
        intellij_ruby_sdk_type: 'Ruby'
    }

    for xmlSdk in xmlSdks:
        mx.log(f'Parsing {xmlSdk} for SDK definitions')
        for sdk in etreeParse(xmlSdk).getroot().findall("component[@name='ProjectJdkTable']/jdk[@version='2']"):
            name = sdk.find("name").get("value")
            kind = sdk.find("type").get("value")
            home_path = sdk.find("homePath").get("value")
            home = realpath(os.path.expanduser(home_path.replace('$USER_HOME$', '~')))
            if home.find('$APPLICATION_HOME_DIR$') != -1:
                # Don't know how to convert this into a real path so ignore it
                continue

            if home in sdks:
                # First SDK in sorted list of jdk.table.xml files wins
                continue

            version_re = sdk_version_regexes.get(kind)
            if not version_re or sdk.find("version") is None:
                # ignore unknown kinds
                continue

            sdk_version = sdk.find("version").get("value")
            match = version_re.match(sdk_version)
            if match:
                version = next(filter(None, match.groups()), None)
                lang = sdk_languages[kind]
                if kind == intellij_python_sdk_type:
                    from .mx_util import min_required_python_version_str
                    if mx.VersionSpec(version) < mx.VersionSpec(min_required_python_version_str):
                        # Ignore Python SDKs whose version is less than that required by mx
                        continue
                sdks[home] = {'name': name, 'type': kind, 'version': version}
                mx.log(f"  Found {lang} SDK {home} with values {sdks[home]}")
            else:
                mx.warn(f"  Couldn't understand {kind} version specification \"{sdk_version}\" for {home}")
    return sdks

def intellij_get_java_sdk_name(sdks, jdk):
    if jdk.home in sdks:
        sdk = sdks[jdk.home]
        if sdk['type'] == intellij_java_sdk_type:
            return sdk['name']
    return str(jdk.javaCompliance)

def intellij_get_python_sdk_name(sdks, requestor=None):
    # First look for SDK matching current python executable
    exe = realpath(sys.executable)
    if exe in sdks:
        sdk = sdks[exe]
        return sdk['name']

    # Now look for any Python SDK
    for sdk in sdks.values():
        if sdk['type'] == intellij_python_sdk_type:
            return sdk['name']

    context = f' for {requestor}' if requestor else ''
    gen_name = f"Python {sys.version_info[0]}.{sys.version_info[1]}"
    mx.log(f"Could not find Python SDK{context} in Intellij configurations, using name based on {exe}: {gen_name}.")
    return gen_name

def intellij_get_ruby_sdk_name(sdks):
    for sdk in sdks.values():
        if sdk['type'] == intellij_ruby_sdk_type and 'truffleruby-jvm' in sdk['name']:
            return sdk['name']
    for sdk in sdks.values():
        if sdk['type'] == intellij_ruby_sdk_type:
            return sdk['name']
    return "truffleruby"

_not_intellij_filename = re.compile(r'[^a-zA-Z0-9]')

def _intellij_library_file_name(library_name, unique_library_file_names):
    def _gen_name(n=None):
        suffix = '' if n is None else str(n)
        return _not_intellij_filename.sub('_', library_name) + suffix + '.xml'

    # Find a unique name like intellij does
    file_name = _gen_name()
    i = 2
    while file_name in unique_library_file_names:
        file_name = _gen_name(i)
        i += 1

    unique_library_file_names.add(file_name)
    return file_name


def _intellij_suite(s, declared_modules, referenced_modules, sdks, module_files_only: bool, config: IntellijConfig):
    libraries = set()
    jdk_libraries = set()

    project_dir = s.dir
    ideaProjectDirectory = join(project_dir, '.idea')

    # supported types for intellij modules
    module_types = {'ruby': 'RUBY_MODULE',
                    'python': 'PYTHON_MODULE',
                    'web': 'WEB_MODULE',
                    'docs': 'DOCS_MODULE',
                    'ci': 'CI_MODULE'}

    modulesXml = mx.XMLDoc()
    if not module_files_only and not s.isBinarySuite():
        mx_util.ensure_dir_exists(ideaProjectDirectory)
        nameFile = join(ideaProjectDirectory, '.name')
        mx.update_file(nameFile, s.name)
        modulesXml.open('project', attributes={'version': '4'})
        modulesXml.open('component', attributes={'name': 'ProjectModuleManager'})
        modulesXml.open('modules')


    def _intellij_exclude_if_exists(xml, p, name, output=False):
        root = p.get_output_root() if output else p.dir
        path = join(root, name)
        if exists(path):
            excludeRoot = p.get_output_root() if output else '$MODULE_DIR$'
            excludePath = join(excludeRoot, name)
            xml.element('excludeFolder', attributes={'url':'file://' + excludePath})

    annotationProcessorProfiles = {}

    def _complianceToIntellijLanguageLevel(compliance):
        # they changed the name format starting with JDK_10
        if compliance.value >= 10:
            if config.max_java_compliance < compliance.value:
                mx.warn(f"Requested Java compliance {compliance.value} is higher than maximum ({config.max_java_compliance}). Consider passing '--max-java-compliance'.")
            return 'JDK_' + str(min(compliance.value, config.max_java_compliance))
        return 'JDK_1_' + str(compliance.value)

    def _intellij_external_project(externalProjects, sdks, host):
        if externalProjects:
            for project_name, project_definition in externalProjects.items():
                if not project_definition.get('path', None):
                    mx.abort(f"external project {project_name} is missing path attribute")
                if not project_definition.get('type', None):
                    mx.abort(f"external project {project_name} is missing type attribute")

                supported = ['path', 'type', 'source', 'test', 'excluded', 'load_path']
                unknown = set(project_definition.keys()) - frozenset(supported)
                if unknown:
                    mx.abort(f"There are unsupported {unknown} keys in {project_name} external project")

                path = os.path.realpath(join(host.dir, project_definition["path"]))
                module_type = project_definition["type"]

                moduleXml = mx.XMLDoc()
                moduleXml.open('module',
                               attributes={'type': module_types.get(module_type, 'UKNOWN_MODULE'),
                                           'version': '4'})
                moduleXml.open('component',
                               attributes={'name': 'NewModuleRootManager', 'inherit-compiler-output': 'true'})
                moduleXml.element('exclude-output')

                moduleXml.open('content', attributes={'url': 'file://$MODULE_DIR$'})
                for name in project_definition.get('source', []):
                    moduleXml.element('sourceFolder',
                                      attributes={'url':'file://$MODULE_DIR$/' + name, 'isTestSource': str(False)})
                for name in project_definition.get('test', []):
                    moduleXml.element('sourceFolder',
                                      attributes={'url':'file://$MODULE_DIR$/' + name, 'isTestSource': str(True)})
                for name in project_definition.get('excluded', []):
                    _intellij_exclude_if_exists(moduleXml, type('', (object,), {"dir": path})(), name)
                moduleXml.close('content')

                if module_type == "ruby":
                    moduleXml.element('orderEntry', attributes={'type': 'jdk', 'jdkType': intellij_ruby_sdk_type, 'jdkName': intellij_get_ruby_sdk_name(sdks)})
                elif module_type == "python":
                    moduleXml.element('orderEntry', attributes={'type': 'jdk', 'jdkType': intellij_python_sdk_type, 'jdkName': intellij_get_python_sdk_name(sdks, project_name)})
                elif module_type in ["web", "docs", "ci"]:
                    # nothing to do
                    pass
                else:
                    mx.abort(f"External project type {module_type} not supported")

                moduleXml.element('orderEntry', attributes={'type': 'sourceFolder', 'forTests': 'false'})
                moduleXml.close('component')

                load_paths = project_definition.get('load_path', [])
                if load_paths:
                    if not module_type == "ruby":
                        mx.abort("load_path is supported only for ruby type external project")
                    moduleXml.open('component', attributes={'name': 'RModuleSettingsStorage'})
                    load_paths_attributes = {}
                    load_paths_attributes['number'] = str(len(load_paths))
                    for i, name in enumerate(load_paths):
                        load_paths_attributes["string" + str(i)] = "$MODULE_DIR$/" + name
                    moduleXml.element('LOAD_PATH', load_paths_attributes)
                    moduleXml.close('component')

                moduleXml.close('module')
                moduleFile = join(path, project_name + '.iml')
                mx.update_file(moduleFile, moduleXml.xml(indent='  ', newl='\n'))

                if not module_files_only:
                    declared_modules.add(project_name)
                    moduleFilePath = "$PROJECT_DIR$/" + os.path.relpath(moduleFile, s.dir)
                    modulesXml.element('module', attributes={'fileurl': 'file://' + moduleFilePath, 'filepath': moduleFilePath})

    # Import ci directories
    visited_suites = {s.name: s}

    # visitor function for visit imports
    def collect_suites(importing_suite, suite_import):
        if suite_import.name not in visited_suites:
            imported_suite = mx.suite(suite_import.name)
            visited_suites[suite_import.name] = imported_suite
            imported_suite.visit_imports(collect_suites)

    # populate visited_suites dict
    s.visit_imports(collect_suites)

    root_projects_paths = set([suite.vc_dir for suite in visited_suites.values() if suite.vc_dir])
    resource_search_paths = [suite.dir for suite in visited_suites.values()]
    resource_search_paths.extend(root_projects_paths)
    resource_search_paths = set(resource_search_paths)

    def create_intellij_module(resource_path, module_type):
        directory_path = join(resource_path, module_type)
        if isdir(directory_path):
            resource_name = basename(resource_path)
            project_name = ''
            if resource_path not in root_projects_paths:
                project_name = basename(dirname(resource_path)) + '_'

            # the type is used as prefix in order to group all files into one module
            module_name = f"{module_type}.{project_name}{resource_name}"
            module_file_name = module_name + ".iml"

            moduleXml = mx.XMLDoc()
            moduleXml.open('module', attributes={'type': module_types[module_type], 'version': '4'})
            moduleXml.open('component', attributes={'name': 'NewModuleRootManager', 'inherit-compiler-output': 'true'})

            moduleXml.element('exclude-output')
            moduleXml.element('content', attributes={'url': 'file://$MODULE_DIR$'})
            moduleXml.element('orderEntry', attributes={'type': 'sourceFolder', 'forTests': 'false'})

            moduleXml.close('component')
            moduleXml.close('module')

            moduleFile = join(directory_path, module_file_name)
            mx.update_file(moduleFile, moduleXml.xml(indent='  ', newl='\n'))

            if not module_files_only:
                module_file_path = mx.relpath_or_absolute(moduleFile, mx.primary_suite().dir, prefix='$PROJECT_DIR$')
                declared_modules.add(module_name)
                modulesXml.element('module', attributes={'fileurl': 'file://' + module_file_path, 'filepath': module_file_path})

    for resource_search_path in resource_search_paths:
        create_intellij_module(resource_search_path, "ci")
        create_intellij_module(resource_search_path, "docs")

    if config.external_projects:
        for p in s.projects_recursive() + mx._mx_suite.projects_recursive():
            _intellij_external_project(getattr(p, 'externalProjects', None), sdks, p)

    max_checkstyle_version = None
    compilerXml = None

    if config.java_modules:
        if not module_files_only:
            compilerXml = mx.XMLDoc()
            compilerXml.open('project', attributes={'version': '4'})

        # The IntelliJ parser seems to mishandle empty ADDITIONAL_OPTIONS_OVERRIDE elements
        # so only emit the section if there will be something in it.
        additionalOptionsOverrides = False
        assert not s.isBinarySuite()
        # create the modules (1 IntelliJ module = 1 mx project/distribution)
        for p in s.projects_recursive() + mx._mx_suite.projects_recursive():
            if not p.isJavaProject():
                continue

            jdk = mx.get_jdk(p.javaCompliance)
            assert jdk

            # Value of the $MODULE_DIR$ IntelliJ variable and parent directory of the .iml file.
            module_dir = mx_util.ensure_dir_exists(p.dir)

            processors = p.annotation_processors()
            if processors:
                annotationProcessorProfiles.setdefault((p.source_gen_dir_name(),) + tuple(processors), []).append(p)

            intellijLanguageLevel = _complianceToIntellijLanguageLevel(p.javaCompliance)

            moduleXml = mx.XMLDoc()
            moduleXml.open('module', attributes={'type': 'JAVA_MODULE', 'version': '4'})

            moduleXml.open('component', attributes={'name': 'NewModuleRootManager', 'LANGUAGE_LEVEL': intellijLanguageLevel, 'inherit-compiler-output': 'false'})
            moduleXml.element('output', attributes={'url': 'file://$MODULE_DIR$/' + os.path.relpath(p.output_dir(), module_dir)})

            moduleXml.open('content', attributes={'url': 'file://$MODULE_DIR$'})
            for src in p.srcDirs:
                if hasattr(p, 'shadedDeps') and src == p.source_gen_dir():
                    continue
                srcDir = mx_util.ensure_dir_exists(join(p.dir, src))
                moduleXml.element('sourceFolder', attributes={'url':'file://$MODULE_DIR$/' + os.path.relpath(srcDir, module_dir), 'isTestSource': str(p.is_test_project())})
            for name in ['.externalToolBuilders', '.settings', 'nbproject']:
                _intellij_exclude_if_exists(moduleXml, p, name)
            moduleXml.close('content')

            if processors or hasattr(p, 'shadedDeps'):
                moduleXml.open('content', attributes={'url': 'file://' + p.get_output_root()})
                genDir = p.source_gen_dir()
                mx_util.ensure_dir_exists(genDir)
                moduleXml.element('sourceFolder', attributes={'url':'file://' + p.source_gen_dir(), 'isTestSource': str(p.is_test_project()), 'generated': 'true'})
                for name in [basename(p.output_dir())]:
                    _intellij_exclude_if_exists(moduleXml, p, name, output=True)
                moduleXml.close('content')

            moduleXml.element('orderEntry', attributes={'type': 'sourceFolder', 'forTests': 'false'})

            proj = p

            dependencies_project_packages = set()

            def should_process_dep(dep, edge):
                if dep.isTARDistribution() or dep.isNativeProject() or dep.isArchivableProject() or dep.isResourceLibrary():
                    mx.logv(f"Ignoring dependency from {proj.name} to {dep.name}")
                    return False
                return True

            def process_dep(dep, edge):
                if dep is proj:
                    return
                if dep.isLibrary() or dep.isJARDistribution() or dep.isLayoutDirDistribution():
                    libraries.add(dep)
                    moduleXml.element('orderEntry', attributes={'type': 'library', 'name': dep.name, 'level': 'project'})
                elif dep.isJavaProject():
                    dependencies_project_packages.update(dep.defined_java_packages())
                    referenced_modules.add(dep.name)
                    moduleXml.element('orderEntry', attributes={'type': 'module', 'module-name': dep.name})
                elif dep.isJdkLibrary():
                    jdk_libraries.add(dep)
                    if jdk.javaCompliance < dep.jdkStandardizedSince:
                        moduleXml.element('orderEntry', attributes={'type': 'library', 'name': dep.name, 'level': 'project'})
                    else:
                        mx.logv(f"{p} skipping {dep} for {jdk}") #pylint: disable=undefined-loop-variable
                elif dep.isJreLibrary():
                    pass
                elif dep.isClasspathDependency():
                    moduleXml.element('orderEntry', attributes={'type': 'library', 'name': dep.name, 'level': 'project'})
                else:
                    mx.abort(f"Dependency not supported: {dep} ({dep.__class__.__name__})")

            p.walk_deps(preVisit=should_process_dep, visit=process_dep, ignoredEdges=[mx.DEP_EXCLUDED])

            moduleXml.element('orderEntry', attributes={'type': 'jdk', 'jdkType': intellij_java_sdk_type, 'jdkName': intellij_get_java_sdk_name(sdks, jdk)})

            moduleXml.close('component')

            additional_options_override = {}

            if compilerXml and jdk.javaCompliance >= '9':
                moduleDeps = p.get_concealed_imported_packages(jdk=jdk)
                args = []
                if moduleDeps:
                    exports = sorted([(m, pkgs) for m, pkgs in moduleDeps.items() if dependencies_project_packages.isdisjoint(pkgs)])
                    if exports:
                        exported_modules = set()
                        for m, pkgs in exports:
                            args += [f'--add-exports={m}/{pkg}=ALL-UNNAMED' for pkg in pkgs]
                            exported_modules.add(m)
                        roots = set(jdk.get_root_modules())
                        observable_modules = jdk.get_modules()
                        default_module_graph = mx_javamodules.get_transitive_closure(roots, observable_modules)
                        module_graph = mx_javamodules.get_transitive_closure(roots | exported_modules, observable_modules)
                        extra_modules = module_graph - default_module_graph
                        if extra_modules:
                            args.append('--add-modules=' + ','.join((m.name for m in extra_modules)))

                if 'jdk.incubator.vector' in getattr(p, 'requires', []):
                    args.append('--add-modules=jdk.incubator.vector')

                if args:
                    additional_options_override[p.name] = args

            if compilerXml:
                jni_gen_dir = p.jni_gen_dir()
                if jni_gen_dir:
                    javac_options = additional_options_override.setdefault(p.name, [])
                    javac_options.append('-h ' + jni_gen_dir)

                if getattr(p, "javaPreviewNeeded", None):
                    javac_options = additional_options_override.setdefault(p.name, [])
                    javac_options.append('--enable-preview')

                if additional_options_override:
                    if not additionalOptionsOverrides:
                        additionalOptionsOverrides = True
                        compilerXml.open('component', {'name': 'JavacSettings'})
                        compilerXml.open('option', {'name': 'ADDITIONAL_OPTIONS_OVERRIDE'})
                    for module_name, javac_options in additional_options_override.items():
                        if javac_options:
                            compilerXml.element('module', {'name': module_name, 'options': ' '.join(javac_options)})

            # Checkstyle
            csConfig, checkstyleVersion, checkstyleProj = p.get_checkstyle_config()
            if csConfig:
                max_checkstyle_version = max(max_checkstyle_version, mx.VersionSpec(checkstyleVersion)) if max_checkstyle_version else mx.VersionSpec(checkstyleVersion)

                moduleXml.open('component', attributes={'name': 'CheckStyle-IDEA-Module'})
                moduleXml.open('option', attributes={'name': 'configuration'})
                moduleXml.open('map')
                moduleXml.element('entry', attributes={'key': "checkstyle-version", 'value': checkstyleVersion})
                moduleXml.element('entry', attributes={'key': "active-configuration", 'value': "PROJECT_RELATIVE:" + join(checkstyleProj.dir, ".checkstyle_checks.xml") + ":" + checkstyleProj.name})
                moduleXml.close('map')
                moduleXml.close('option')
                moduleXml.close('component')

            moduleXml.close('module')
            moduleFile = join(module_dir, p.name + '.iml')
            mx.update_file(moduleFile, moduleXml.xml(indent='  ', newl='\n').rstrip())

            if not module_files_only:
                declared_modules.add(p.name)
                moduleFilePath = "$PROJECT_DIR$/" + os.path.relpath(moduleFile, project_dir)
                modulesXml.element('module', attributes={'fileurl': 'file://' + moduleFilePath, 'filepath': moduleFilePath})
        if additionalOptionsOverrides:
            compilerXml.close('option')
            compilerXml.close('component')

    if config.python_projects and s.mxDir:

        def _python_module(suite):
            """
            Gets a tuple describing the IntelliJ module for the python sources of `suite`. The tuple
            consists of the module name, module directory and the name of the .iml in the module directory.
            """
            assert suite.mxDir, suite
            name = basename(suite.mxDir)
            module_dir = suite.mxDir
            return name, mx_util.ensure_dir_exists(module_dir), name + '.iml'

        def _add_declared_module(suite):
            if not module_files_only:
                name, module_dir, iml_file = _python_module(suite)
                declared_modules.add(name)
                moduleFilePath = "$PROJECT_DIR$/" + os.path.relpath(join(module_dir, iml_file), project_dir)
                modulesXml.element('module', attributes={'fileurl': 'file://' + moduleFilePath, 'filepath': moduleFilePath})

        # mx.<suite> python module:
        _, module_dir, iml_file = _python_module(s)
        moduleXml = mx.XMLDoc()
        moduleXml.open('module', attributes={'type': 'PYTHON_MODULE', 'version': '4'})
        moduleXml.open('component', attributes={'name': 'NewModuleRootManager', 'inherit-compiler-output': 'true'})
        moduleXml.element('exclude-output')

        moduleXml.open('content', attributes={'url': 'file://$MODULE_DIR$'})
        moduleXml.element('sourceFolder', attributes={'url': 'file://$MODULE_DIR$/' + os.path.relpath(s.mxDir, module_dir), 'isTestSource': 'false'})
        for d in os.listdir(s.mxDir):
            directory = join(s.mxDir, d)
            if isdir(directory) and mx.dir_contains_files_recursively(directory, r".*\.java"):
                moduleXml.element('excludeFolder', attributes={'url': 'file://$MODULE_DIR$/' + os.path.relpath(directory, module_dir)})
        moduleXml.close('content')

        moduleXml.element('orderEntry', attributes={'type': 'jdk', 'jdkType': intellij_python_sdk_type, 'jdkName': intellij_get_python_sdk_name(sdks, f'suite {s}')})
        moduleXml.element('orderEntry', attributes={'type': 'sourceFolder', 'forTests': 'false'})

        def _with_suite(suite, suite_name):
            if not suite.mxDir:
                return
            dep_module_name, _, _ = _python_module(suite)
            moduleXml.element('orderEntry', attributes={'type': 'module', 'module-name': dep_module_name})
            _add_declared_module(suite)
        project_processor.iter_projects(s, _with_suite)

        if s.name != 'mx':
            moduleXml.element('orderEntry', attributes={'type': 'module', 'module-name': 'mx.mx'})
        # Add dependency on the mx intellij module, the module containing the mx source code
        moduleXml.element('orderEntry', attributes={'type': 'module', 'module-name': 'mx'})
        moduleXml.close('component')
        moduleXml.close('module')
        moduleFile = join(module_dir, iml_file)
        mx.update_file(moduleFile, moduleXml.xml(indent='  ', newl='\n'))
        _add_declared_module(s)
        if s != mx._mx_suite:
            _add_declared_module(mx._mx_suite)

        if not module_files_only:
            mx_module_file = join(mx._mx_suite.dir, 'src', 'mx.iml')
            moduleFilePath = "$PROJECT_DIR$/" + os.path.relpath(mx_module_file, project_dir)
            modulesXml.element('module', attributes={'fileurl': 'file://' + moduleFilePath, 'filepath': moduleFilePath})

            mx_tests_module_file = join(mx._mx_suite.dir, 'tests', 'mx_tests.iml')
            moduleFilePath = "$PROJECT_DIR$/" + os.path.relpath(mx_tests_module_file, project_dir)
            modulesXml.element('module', attributes={'fileurl': 'file://' + moduleFilePath, 'filepath': moduleFilePath})

    if config.native_projects:
        _intellij_native_projects(s, module_files_only, declared_modules, modulesXml)

    if config.external_projects:
        _intellij_external_project(s.suiteDict.get('externalProjects', None), sdks, s)

    if not module_files_only:
        modulesXml.close('modules')
        modulesXml.close('component')
        modulesXml.close('project')
        moduleXmlFile = join(ideaProjectDirectory, 'modules.xml')
        mx.update_file(moduleXmlFile, modulesXml.xml(indent='  ', newl='\n'))

    if config.java_modules and not module_files_only:
        unique_library_file_names = set()
        librariesDirectory = mx_util.ensure_dir_exists(join(ideaProjectDirectory, 'libraries'))

        mx_util.ensure_dir_exists(librariesDirectory)

        def make_library(name, path, source_path, suite_dir):
            libraryXml = mx.XMLDoc()

            libraryXml.open('component', attributes={'name': 'libraryTable'})
            libraryXml.open('library', attributes={'name': name})
            if path:
                libraryXml.open('CLASSES')
                pathX = mx.relpath_or_absolute(path, suite_dir, prefix='$PROJECT_DIR$')
                libraryXml.element('root', attributes={'url': 'jar://' + pathX + '!/'})
                libraryXml.close('CLASSES')
            libraryXml.element('JAVADOC')
            if source_path:
                libraryXml.open('SOURCES')
                source_pathX = mx.relpath_or_absolute(source_path, suite_dir, prefix='$PROJECT_DIR$')
                if os.path.isdir(source_path):
                    libraryXml.element('root', attributes={'url': 'file://' + source_pathX})
                else:
                    libraryXml.element('root', attributes={'url': 'jar://' + source_pathX + '!/'})
                libraryXml.close('SOURCES')
            else:
                libraryXml.element('SOURCES')
            libraryXml.close('library')
            libraryXml.close('component')

            libraryFile = join(librariesDirectory, _intellij_library_file_name(name, unique_library_file_names))
            return mx.update_file(libraryFile, libraryXml.xml(indent='  ', newl='\n'))

        # Setup the libraries that were used above
        for library in libraries:
            path = None
            source_path = None
            if library.isLibrary():
                path = library.get_path(True)
                if library.sourcePath:
                    source_path = library.get_source_path(True)
            elif library.isJARDistribution():
                path = library.path
                # don't report the source path since the source already exists in the project
                # and IntelliJ sometimes picks the source zip instead of the real source file
            elif library.isLayoutDirDistribution():
                # IntelliJ is somehow unhappy about directory being used as "classes", so we use
                # it as "sources". This library is artificial anyway and is only used to express
                # dependencies
                source_path = library.classpath_repr()
            elif library.isClasspathDependency():
                path = library.classpath_repr()
            else:
                mx.abort(f'Dependency not supported: {library.name} ({library.__class__.__name__})')
            make_library(library.name, path, source_path, s.dir)

        jdk = mx.get_jdk()
        updated = False
        for library in jdk_libraries:
            if library.classpath_repr(jdk) is not None:
                if make_library(library.name, library.classpath_repr(jdk), library.get_source_path(jdk), s.dir):
                    updated = True
        if jdk_libraries and updated:
            mx.log(f"Setting up JDK libraries using {jdk}")

        # Set annotation processor profiles up, and link them to modules in compiler.xml

        compilerXml.open('component', attributes={'name': 'CompilerConfiguration'})

        compilerXml.element('option', attributes={'name': "DEFAULT_COMPILER", 'value': 'Javac'})
        compilerXml.element('option', attributes={'name': "BUILD_PROCESS_HEAP_SIZE", 'value': '2500'})
        # using the --release option with javac interferes with using --add-modules which is required for some projects
        compilerXml.element('option', attributes={'name': "USE_RELEASE_OPTION", 'value': 'false'})
        compilerXml.element('resourceExtensions')
        compilerXml.open('wildcardResourcePatterns')
        compilerXml.element('entry', attributes={'name': '!?*.java'})
        compilerXml.close('wildcardResourcePatterns')
        if annotationProcessorProfiles:
            compilerXml.open('annotationProcessing')
            for t, modules in sorted(annotationProcessorProfiles.items()):
                source_gen_dir = t[0]
                processors = t[1:]
                compilerXml.open('profile', attributes={'default': 'false', 'name': '-'.join([ap.name for ap in processors]) + "-" + source_gen_dir, 'enabled': 'true'})
                compilerXml.element('sourceOutputDir', attributes={'name': join(os.pardir, source_gen_dir)})
                compilerXml.element('sourceTestOutputDir', attributes={'name': join(os.pardir, source_gen_dir)})
                compilerXml.open('processorPath', attributes={'useClasspath': 'false'})

                # IntelliJ supports both directories and jars on the annotation processor path whereas
                # Eclipse only supports jars.
                for apDep in processors:
                    def processApDep(dep, edge):
                        if dep.isLibrary() or dep.isJARDistribution():
                            compilerXml.element('entry', attributes={'name': mx.relpath_or_absolute(dep.path, s.dir, prefix='$PROJECT_DIR$')})
                        elif dep.isProject():
                            compilerXml.element('entry', attributes={'name': mx.relpath_or_absolute(dep.output_dir(), s.dir, prefix='$PROJECT_DIR$')})
                    apDep.walk_deps(visit=processApDep)
                compilerXml.close('processorPath')
                for module in modules:
                    compilerXml.element('module', attributes={'name': module.name})
                compilerXml.close('profile')
            compilerXml.close('annotationProcessing')

        compilerXml.close('component')

    if compilerXml:
        compilerXml.close('project')
        compilerFile = join(ideaProjectDirectory, 'compiler.xml')
        mx.update_file(compilerFile, compilerXml.xml(indent='  ', newl='\n'))

    if not module_files_only:
        # Write misc.xml for global JDK config
        miscXml = mx.XMLDoc()
        miscXml.open('project', attributes={'version' : '4'})

        if config.java_modules:
            mainJdk = mx.get_jdk()
            miscXml.open('component', attributes={'name' : 'ProjectRootManager', 'version': '2', 'languageLevel': _complianceToIntellijLanguageLevel(mainJdk.javaCompliance), 'project-jdk-name': intellij_get_java_sdk_name(sdks, mainJdk), 'project-jdk-type': intellij_java_sdk_type})
            miscXml.element('output', attributes={'url' : 'file://$PROJECT_DIR$/' + os.path.relpath(s.get_output_root(), s.dir)})
            miscXml.close('component')
        else:
            miscXml.element('component', attributes={'name' : 'ProjectRootManager', 'version': '2', 'project-jdk-name': intellij_get_python_sdk_name(sdks), 'project-jdk-type': intellij_python_sdk_type})

        miscXml.close('project')
        miscFile = join(ideaProjectDirectory, 'misc.xml')
        mx.update_file(miscFile, miscXml.xml(indent='  ', newl='\n'))

        # Generate a default configuration for debugging Graal
        runConfig = mx.XMLDoc()
        runConfig.open('component', attributes={'name' : 'ProjectRunConfigurationManager'})
        runConfig.open('configuration', attributes={'default' :'false', 'name' : 'GraalDebug', 'type' : 'Remote', 'factoryName': 'Remote'})
        runConfig.element('option', attributes={'name' : 'USE_SOCKET_TRANSPORT', 'value' : 'true'})
        runConfig.element('option', attributes={'name' : 'SERVER_MODE', 'value' : 'false'})
        runConfig.element('option', attributes={'name' : 'SHMEM_ADDRESS', 'value' : 'javadebug'})
        runConfig.element('option', attributes={'name' : 'HOST', 'value' : 'localhost'})
        runConfig.element('option', attributes={'name' : 'PORT', 'value' : '8000'})
        runConfig.open('RunnerSettings', attributes={'RunnerId' : 'Debug'})
        runConfig.element('option', attributes={'name' : 'DEBUG_PORT', 'value' : '8000'})
        runConfig.element('option', attributes={'name' : 'LOCAL', 'value' : 'false'})
        runConfig.close('RunnerSettings')
        runConfig.element('method')
        runConfig.close('configuration')
        runConfig.close('component')
        runConfigFile = join(ideaProjectDirectory, 'runConfigurations', 'GraalDebug.xml')
        mx_util.ensure_dir_exists(join(ideaProjectDirectory, 'runConfigurations'))
        mx.update_file(runConfigFile, runConfig.xml(indent='  ', newl='\n'))

        if config.java_modules:
            # Eclipse formatter config
            corePrefsSources = s.eclipse_settings_sources().get('org.eclipse.jdt.core.prefs')
            uiPrefsSources = s.eclipse_settings_sources().get('org.eclipse.jdt.ui.prefs')
            if corePrefsSources:
                miscXml = mx.XMLDoc()
                miscXml.open('project', attributes={'version' : '4'})
                out = StringIO()
                print('# GENERATED -- DO NOT EDIT', file=out)
                for source in corePrefsSources:
                    print('# Source:', source, file=out)
                    with open(source) as fileName:
                        for line in fileName:
                            if line.startswith('org.eclipse.jdt.core.formatter.'):
                                print(line.strip(), file=out)
                formatterConfigFile = join(ideaProjectDirectory, 'EclipseCodeFormatter.prefs')
                mx.update_file(formatterConfigFile, out.getvalue())
                importConfigFile = None
                if uiPrefsSources:
                    out = StringIO()
                    print('# GENERATED -- DO NOT EDIT', file=out)
                    for source in uiPrefsSources:
                        print('# Source:', source, file=out)
                        with open(source) as fileName:
                            for line in fileName:
                                if line.startswith('org.eclipse.jdt.ui.importorder') \
                                        or line.startswith('org.eclipse.jdt.ui.ondemandthreshold') \
                                        or line.startswith('org.eclipse.jdt.ui.staticondemandthreshold'):
                                    print(line.strip(), file=out)
                    importConfigFile = join(ideaProjectDirectory, 'EclipseImports.prefs')
                    mx.update_file(importConfigFile, out.getvalue())
                miscXml.open('component', attributes={'name' : 'EclipseCodeFormatterProjectSettings'})
                miscXml.open('option', attributes={'name' : 'projectSpecificProfile'})
                miscXml.open('ProjectSpecificProfile')
                miscXml.element('option', attributes={'name' : 'formatter', 'value' : 'ECLIPSE'})
                custom_eclipse_exe = mx.get_env('ECLIPSE_EXE')
                if custom_eclipse_exe:
                    custom_eclipse = dirname(custom_eclipse_exe)
                    if mx.is_darwin():
                        custom_eclipse = join(dirname(custom_eclipse), 'Eclipse')
                    if not exists(custom_eclipse_exe):
                        mx.abort(f'Custom eclipse "{custom_eclipse_exe}" does not exist')
                    miscXml.element('option', attributes={'name' : 'eclipseVersion', 'value' : 'CUSTOM'})
                    miscXml.element('option', attributes={'name' : 'pathToEclipse', 'value' : custom_eclipse})
                miscXml.element('option', attributes={'name' : 'pathToConfigFileJava', 'value' : '$PROJECT_DIR$/.idea/' + basename(formatterConfigFile)})
                if importConfigFile:
                    miscXml.element('option', attributes={'name' : 'importOrderConfigFilePath', 'value' : '$PROJECT_DIR$/.idea/' + basename(importConfigFile)})
                    miscXml.element('option', attributes={'name' : 'importOrderFromFile', 'value' : 'true'})

                miscXml.close('ProjectSpecificProfile')
                miscXml.close('option')
                miscXml.close('component')
                miscXml.close('project')
                miscFile = join(ideaProjectDirectory, 'eclipseCodeFormatter.xml')
                mx.update_file(miscFile, miscXml.xml(indent='  ', newl='\n'))

        if config.java_modules:
            # Write codestyle settings
            mx_util.ensure_dir_exists(join(ideaProjectDirectory, 'codeStyles'))

            codeStyleConfigXml = mx.XMLDoc()
            codeStyleConfigXml.open('component', attributes={'name': 'ProjectCodeStyleConfiguration'})
            codeStyleConfigXml.open('state')
            codeStyleConfigXml.element('option', attributes={'name': 'USE_PER_PROJECT_SETTINGS', 'value': 'true'})
            codeStyleConfigXml.close('state')
            codeStyleConfigXml.close('component')
            codeStyleConfigFile = join(ideaProjectDirectory, 'codeStyles', 'codeStyleConfig.xml')
            mx.update_file(codeStyleConfigFile, codeStyleConfigXml.xml(indent='  ', newl='\n'))

            codeStyleProjectXml = mx.XMLDoc()
            codeStyleProjectXml.open('component', attributes={'name': 'ProjectCodeStyleConfiguration'})
            codeStyleProjectXml.open('code_scheme', attributes={'name': 'Project', 'version': '173'})
            codeStyleProjectXml.open('JavaCodeStyleSettings')
            # We cannot entirely disable wildcards import, but we can set the threshold to an insane number.
            if config.import_inner_classes:
                codeStyleProjectXml.element('option', attributes={'name': 'INSERT_INNER_CLASS_IMPORTS', 'value': 'true'})
            codeStyleProjectXml.element('option', attributes={'name': 'CLASS_COUNT_TO_USE_IMPORT_ON_DEMAND', 'value': '65536'})
            codeStyleProjectXml.element('option', attributes={'name': 'NAMES_COUNT_TO_USE_IMPORT_ON_DEMAND', 'value': '65536'})
            codeStyleProjectXml.close('JavaCodeStyleSettings')
            codeStyleProjectXml.close('code_scheme')
            codeStyleProjectXml.close('component')
            codeStyleProjectFile = join(ideaProjectDirectory, 'codeStyles', 'Project.xml')
            mx.update_file(codeStyleProjectFile, codeStyleProjectXml.xml(indent='  ', newl='\n'))

            # Write checkstyle-idea.xml for the CheckStyle-IDEA
            checkstyleXml = mx.XMLDoc()
            checkstyleXml.open('project', attributes={'version': '4'})
            checkstyleXml.open('component', attributes={'name': 'CheckStyle-IDEA'})
            checkstyleXml.open('option', attributes={'name' : "configuration"})
            checkstyleXml.open('map')

            if max_checkstyle_version:
                checkstyleXml.element('entry', attributes={'key': "checkstyle-version", 'value': str(max_checkstyle_version)})

            # Initialize an entry for each style that is used
            checkstyleConfigs = set([])
            for p in s.projects_recursive():
                if not p.isJavaProject():
                    continue
                csConfig, checkstyleVersion, checkstyleProj = p.get_checkstyle_config()
                if not csConfig or csConfig in checkstyleConfigs:
                    continue
                checkstyleConfigs.add(csConfig)
                checkstyleXml.element('entry', attributes={'key' : "location-" + str(len(checkstyleConfigs)), 'value': "PROJECT_RELATIVE:" + join(checkstyleProj.dir, ".checkstyle_checks.xml") + ":" + checkstyleProj.name})

            checkstyleXml.close('map')
            checkstyleXml.close('option')
            checkstyleXml.close('component')
            checkstyleXml.close('project')
            checkstyleFile = join(ideaProjectDirectory, 'checkstyle-idea.xml')
            mx.update_file(checkstyleFile, checkstyleXml.xml(indent='  ', newl='\n'))

            # If it doesn't already exist: write basic workspace.xml with Save actions and build in parallel option
            workspace_path = join(ideaProjectDirectory, 'workspace.xml')
            if exists(workspace_path):
                if config.on_save_actions:
                    mx.warn("File workspace.xml already exists. The flag `--on-save-actions` is ignored. "
                            "Run `mx ideclean` and re-run `mx intellijinit` to get workspace.xml regenerated, "
                            "but note that it will remove any customizations you may have in workspace.xml!")
            else:
                workspaceXml = mx.XMLDoc()
                workspaceXml.open('project', attributes={'version': '4'})

                if config.on_save_actions:
                    workspaceXml.open('component', attributes={'name': 'FormatOnSaveOptions'})
                    workspaceXml.element('option', attributes={'name': 'myFormatOnlyChangedLines', 'value': 'false'})
                    workspaceXml.element('option', attributes={'name': 'myRunOnSave', 'value': 'true'})
                    workspaceXml.element('option', attributes={'name': 'myAllFileTypesSelected', 'value': 'false'})
                    workspaceXml.open('option', attributes={'name': 'mySelectedFileTypes'})
                    workspaceXml.open('set')
                    workspaceXml.element('option', attributes={'value': 'JAVA'})
                    workspaceXml.close('set')
                    workspaceXml.close('option')
                    workspaceXml.close('component')

                    workspaceXml.open('component', attributes={'name': 'OptimizeOnSaveOptions'})
                    workspaceXml.element('option', attributes={'name': 'myRunOnSave', 'value': 'true'})
                    workspaceXml.element('option', attributes={'name': 'myAllFileTypesSelected', 'value': 'false'})
                    workspaceXml.open('option', attributes={'name': 'mySelectedFileTypes'})
                    workspaceXml.open('set')
                    workspaceXml.element('option', attributes={'value': 'JAVA'})
                    workspaceXml.close('set')
                    workspaceXml.close('option')
                    workspaceXml.close('component')

                workspaceXml.open('component', attributes={'name': 'CompilerWorkspaceConfiguration'})
                workspaceXml.element('option', attributes={'name': 'PARALLEL_COMPILATION', 'value': 'true'})
                workspaceXml.close('component')

                workspaceXml.close('project')
                mx.update_file(workspace_path, workspaceXml.xml(indent='  ', newl='\n'))

            if config.mx_distributions:
                # We delegate to `mx archive {DISTRIBUTION}` using Ant script.
                # The Ant script is executed as "ant-postprocessing" step of an artificial IntelliJ artifact that we
                # create for each MX distribution. The artificial IntelliJ artifact is configured to "contain" (depend
                # on) all the dependencies of the given MX distribution. See IDE.md for some more info.
                def antTargetName(dist):
                    return 'archive_' + dist.name

                def artifactFileName(dist):
                    return dist.name.replace('.', '_').replace('-', '_') + '.xml'
                validDistributions = [dist for dist in mx.sorted_dists() if not dist.suite.isBinarySuite() and not dist.isTARDistribution()]

                # 1) Make an ant file for archiving the distributions.
                antXml = mx.XMLDoc()
                antXml.open('project', attributes={'name': s.name, 'default': 'archive'})
                for dist in validDistributions:
                    antXml.open('target', attributes={'name': antTargetName(dist)})
                    antXml.open('exec', attributes={'executable': sys.executable})
                    antXml.element('arg', attributes={'value': join(mx._mx_home, 'mx.py')})
                    antXml.element('arg', attributes={'value': 'archive'})
                    antXml.element('arg', attributes={'value': '@' + dist.name})
                    antXml.close('exec')
                    antXml.close('target')

                antXml.close('project')
                antFile = join(ideaProjectDirectory, 'ant-mx-archive.xml')
                mx.update_file(antFile, antXml.xml(indent='  ', newl='\n'))

                # 2) Tell IDEA that there is an ant-build.
                ant_mx_archive_xml = 'file://$PROJECT_DIR$/.idea/ant-mx-archive.xml'
                metaAntXml = mx.XMLDoc()
                metaAntXml.open('project', attributes={'version': '4'})
                metaAntXml.open('component', attributes={'name': 'AntConfiguration'})
                metaAntXml.open('buildFile', attributes={'url': ant_mx_archive_xml})
                metaAntXml.close('buildFile')
                metaAntXml.close('component')
                metaAntXml.close('project')
                metaAntFile = join(ideaProjectDirectory, 'ant.xml')
                mx.update_file(metaAntFile, metaAntXml.xml(indent='  ', newl='\n'))

                # 3) Make an artifact for every distribution
                validArtifactNames = {artifactFileName(dist) for dist in validDistributions}
                artifactsDir = join(ideaProjectDirectory, 'artifacts')
                mx_util.ensure_dir_exists(artifactsDir)
                for fileName in os.listdir(artifactsDir):
                    filePath = join(artifactsDir, fileName)
                    if os.path.isfile(filePath) and fileName not in validArtifactNames:
                        os.remove(filePath)

                for dist in validDistributions:
                    artifactXML = mx.XMLDoc()
                    artifactXML.open('component', attributes={'name': 'ArtifactManager'})
                    artifactXML.open('artifact', attributes={'build-on-make': 'true', 'name': dist.name})
                    artifactXML.open('output-path', data='$PROJECT_DIR$/mxbuild/artifacts/' + dist.name)
                    artifactXML.close('output-path')
                    artifactXML.open('properties', attributes={'id': 'ant-postprocessing'})
                    artifactXML.open('options', attributes={'enabled': 'true'})
                    artifactXML.open('file', data=ant_mx_archive_xml)
                    artifactXML.close('file')
                    artifactXML.open('target', data=antTargetName(dist))
                    artifactXML.close('target')
                    artifactXML.close('options')
                    artifactXML.close('properties')
                    artifactXML.open('root', attributes={'id': 'root'})
                    for javaProject in [dep for dep in dist.archived_deps() if dep.isJavaProject()]:
                        artifactXML.element('element', attributes={'id': 'module-output', 'name': javaProject.name})
                    for javaProject in [dep for dep in dist.deps if dep.isLibrary() or (dep.isDistribution() and dep in validDistributions)]:
                        artifactXML.element('element', attributes={'id': 'artifact', 'artifact-name': javaProject.name})
                    artifactXML.close('root')
                    artifactXML.close('artifact')
                    artifactXML.close('component')

                    artifactFile = join(artifactsDir, artifactFileName(dist))
                    mx.update_file(artifactFile, artifactXML.xml(indent='  ', newl='\n'))

        def intellij_scm_name(vc_kind):
            if vc_kind == 'git':
                return 'Git'
            elif vc_kind == 'hg':
                return 'hg4idea'

        vcsXml = mx.XMLDoc()
        vcsXml.open('project', attributes={'version': '4'})
        vcsXml.open('component', attributes={'name': 'VcsDirectoryMappings'})

        suites_for_vcs = mx.suites() + ([mx._mx_suite] if config.python_projects else [])
        sourceSuitesWithVCS = [vc_suite for vc_suite in suites_for_vcs if vc_suite.isSourceSuite() and vc_suite.vc is not None]
        uniqueSuitesVCS = {(vc_suite.vc_dir, vc_suite.vc.kind) for vc_suite in sourceSuitesWithVCS}
        for vcs_dir, kind in uniqueSuitesVCS:
            vcsXml.element('mapping', attributes={'directory': vcs_dir, 'vcs': intellij_scm_name(kind)})

        vcsXml.close('component')
        vcsXml.close('project')

        vcsFile = join(ideaProjectDirectory, 'vcs.xml')
        mx.update_file(vcsFile, vcsXml.xml(indent='  ', newl='\n'))

        # TODO look into copyright settings


def _intellij_native_projects(s, module_files_only, declared_modules, modulesXml):
    for p in s.projects_recursive() + mx._mx_suite.projects_recursive():
        if not p.isNativeProject():
            continue

        mx_util.ensure_dir_exists(p.dir)

        moduleXml = mx.XMLDoc()
        moduleXml.open('module', attributes={'type': 'CPP_MODULE'})

        moduleXml.open('component', attributes={'name': 'NewModuleRootManager', 'inherit-compiler-output': 'false'})

        moduleXml.open('content', attributes={'url': 'file://$MODULE_DIR$'})
        for src in p.srcDirs:
            srcDir = join(p.dir, src)
            mx_util.ensure_dir_exists(srcDir)
            moduleXml.element('sourceFolder', attributes={'url': 'file://$MODULE_DIR$/' + src,
                                                          'isTestSource': str(p.is_test_project())})
        moduleXml.close('content')

        moduleXml.element('orderEntry', attributes={'type': 'sourceFolder', 'forTests': 'false'})

        moduleXml.close('component')
        moduleXml.close('module')
        moduleFile = join(p.dir, p.name + '.iml')
        mx.update_file(moduleFile, moduleXml.xml(indent='  ', newl='\n'))

        if not module_files_only:
            declared_modules.add(p.name)
            moduleFilePath = "$PROJECT_DIR$/" + os.path.relpath(moduleFile, s.dir)
            modulesXml.element('module', attributes={'fileurl': 'file://' + moduleFilePath, 'filepath': moduleFilePath})
