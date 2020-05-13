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

from __future__ import print_function

import sys

try:
    import defusedxml #pylint: disable=unused-import
    from defusedxml.ElementTree import parse as etreeParse
except ImportError:
    from xml.etree.ElementTree import parse as etreeParse
import os
# TODO use defusedexpat?
import re
import glob
from argparse import ArgumentParser, REMAINDER
from os.path import join, basename, dirname, exists, isdir, realpath

import mx
import mx_ideconfig
import mx_javamodules


# Temporary imports and (re)definitions while porting mx from Python 2 to Python 3
if sys.version_info[0] < 3:
    from StringIO import StringIO
else:
    from io import StringIO


# IntelliJ SDK types.
intellij_java_sdk_type = 'JavaSDK'
intellij_python_sdk_type = 'Python SDK'
intellij_ruby_sdk_type = 'RUBY_SDK'


@mx.command('mx', 'intellijinit')
def intellijinit_cli(args):
    """(re)generate Intellij project configurations"""
    parser = ArgumentParser(prog='mx ideinit')
    parser.add_argument('--no-python-projects', action='store_false', dest='pythonProjects', help='Do not generate projects for the mx python projects.')
    parser.add_argument('--no-external-projects', action='store_false', dest='externalProjects', help='Do not generate external projects.')
    parser.add_argument('--no-java-projects', '--mx-python-modules-only', action='store_false', dest='javaModules', help='Do not generate projects for the java projects.')
    parser.add_argument('--native-projects', action='store_true', dest='nativeProjects', help='Generate native projects.')
    parser.add_argument('remainder', nargs=REMAINDER, metavar='...')
    args = parser.parse_args(args)
    intellijinit(args.remainder, mx_python_modules=args.pythonProjects, java_modules=args.javaModules,
                 generate_external_projects=args.externalProjects, native_projects=args.nativeProjects)


def intellijinit(args, refreshOnly=False, doFsckProjects=True, mx_python_modules=True, java_modules=True,
                 generate_external_projects=True, native_projects=False):
    # In a multiple suite context, the .idea directory in each suite
    # has to be complete and contain information that is repeated
    # in dependent suites.
    declared_modules = set()
    referenced_modules = set()
    sdks = intellij_read_sdks()
    for suite in mx.suites(True) + ([mx._mx_suite] if mx_python_modules else []):
        _intellij_suite(args, suite, declared_modules, referenced_modules, sdks, refreshOnly, mx_python_modules,
                        generate_external_projects, java_modules and not suite.isBinarySuite(), suite != mx.primary_suite(),
                        generate_native_projects=native_projects)

    if len(referenced_modules - declared_modules) != 0:
        mx.abort('Some referenced modules are missing from modules.xml: {}'.format(referenced_modules - declared_modules))

    if mx_python_modules:
        # mx module
        moduleXml = mx.XMLDoc()
        moduleXml.open('module', attributes={'type': 'PYTHON_MODULE', 'version': '4'})
        moduleXml.open('component', attributes={'name': 'NewModuleRootManager', 'inherit-compiler-output': 'true'})
        moduleXml.element('exclude-output')
        moduleXml.open('content', attributes={'url': 'file://$MODULE_DIR$'})
        moduleXml.element('sourceFolder', attributes={'url': 'file://$MODULE_DIR$', 'isTestSource': 'false'})
        for d in set((p.subDir for p in mx._mx_suite.projects if p.subDir)):
            moduleXml.element('excludeFolder', attributes={'url': 'file://$MODULE_DIR$/' + d})
        if dirname(mx._mx_suite.get_output_root()) == mx._mx_suite.dir:
            moduleXml.element('excludeFolder', attributes={'url': 'file://$MODULE_DIR$/' + basename(mx._mx_suite.get_output_root())})
        moduleXml.close('content')
        moduleXml.element('orderEntry', attributes={'type': 'jdk', 'jdkType': intellij_python_sdk_type, 'jdkName': intellij_get_python_sdk_name(sdks)})
        moduleXml.element('orderEntry', attributes={'type': 'sourceFolder', 'forTests': 'false'})
        moduleXml.close('component')
        moduleXml.close('module')
        mxModuleFile = join(mx._mx_suite.dir, basename(mx._mx_suite.dir) + '.iml')
        mx.update_file(mxModuleFile, moduleXml.xml(indent='  ', newl='\n'))

    if doFsckProjects and not refreshOnly:
        mx_ideconfig.fsckprojects([])

def intellij_read_sdks():
    sdks = dict()
    if mx.is_linux() or mx.is_openbsd() or mx.is_sunos() or mx.is_windows():
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
    else:
        mx.warn("Location of IntelliJ SDK definitions on {} is unknown".format(mx.get_os()))
        return sdks
    if len(xmlSdks) == 0:
        mx.warn("IntelliJ SDK definitions not found")
        return sdks

    verRE = re.compile(r'^.*[/\\]\.?(IntelliJIdea|IdeaIC)([^/\\]+)[/\\].*$')
    def verSort(path):
        match = verRE.match(path)
        return match.group(2) + (".a" if match.group(1) == "IntellijIC" else ".b")

    xmlSdks.sort(key=verSort)
    xmlSdk = xmlSdks[-1]  # Pick the most recent IntelliJ version, preferring Ultimate over Community edition.
    mx.log("Using SDK definitions from {}".format(xmlSdk))

    versionRegexes = {}
    versionRegexes[intellij_java_sdk_type] = re.compile(r'^java\s+version\s+"([^"]+)"$|^([\d._]+)$')
    versionRegexes[intellij_python_sdk_type] = re.compile(r'^Python\s+(.+)$')
    # Examples:
    #   truffleruby 19.2.0-dev-2b2a7f81, like ruby 2.6.2, Interpreted JVM [x86_64-linux]
    #   ver.2.2.4p230 ( revision 53155) p230
    versionRegexes[intellij_ruby_sdk_type] = re.compile(r'^\D*(\d[^ ,]+)')

    for sdk in etreeParse(xmlSdk).getroot().findall("component[@name='ProjectJdkTable']/jdk[@version='2']"):
        name = sdk.find("name").get("value")
        kind = sdk.find("type").get("value")
        home = realpath(os.path.expanduser(sdk.find("homePath").get("value").replace('$USER_HOME$', '~')))
        if home.find('$APPLICATION_HOME_DIR$') != -1:
            # Don't know how to convert this into a real path so ignore it
            continue
        versionRE = versionRegexes.get(kind)
        if not versionRE or sdk.find("version") is None:
            # ignore unknown kinds
            continue

        match = versionRE.match(sdk.find("version").get("value"))
        if match:
            version = match.group(1)
            sdks[home] = {'name': name, 'type': kind, 'version': version}
            mx.logv("Found SDK {} with values {}".format(home, sdks[home]))
        else:
            mx.warn("Couldn't understand Java version specification \"{}\" for {} in {}".format(sdk.find("version").get("value"), home, xmlSdk))
    return sdks

def intellij_get_java_sdk_name(sdks, jdk):
    if jdk.home in sdks:
        sdk = sdks[jdk.home]
        if sdk['type'] == intellij_java_sdk_type:
            return sdk['name']
    return str(jdk.javaCompliance)

def intellij_get_python_sdk_name(sdks):
    exe = realpath(sys.executable)
    if exe in sdks:
        sdk = sdks[exe]
        if sdk['type'] == intellij_python_sdk_type:
            return sdk['name']
    return "Python {v[0]}.{v[1]} ({exe})".format(v=sys.version_info, exe=exe)

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


def _intellij_suite(args, s, declared_modules, referenced_modules, sdks, refreshOnly=False, mx_python_modules=False,
                    generate_external_projects=True, java_modules=True, module_files_only=False, generate_native_projects=False):
    libraries = set()
    jdk_libraries = set()

    ideaProjectDirectory = join(s.dir, '.idea')

    modulesXml = mx.XMLDoc()
    if not module_files_only and not s.isBinarySuite():
        mx.ensure_dir_exists(ideaProjectDirectory)
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
            # Lastest Idea 2018.2 only understands JDK_11 so clamp at that value
            return 'JDK_' + str(min(compliance.value, 11))
        return 'JDK_1_' + str(compliance.value)

    def _intellij_external_project(externalProjects, sdks, host):
        if externalProjects:
            for project_name, project_definition in externalProjects.items():
                if not project_definition.get('path', None):
                    mx.abort("external project {} is missing path attribute".format(project_name))
                if not project_definition.get('type', None):
                    mx.abort("external project {} is missing type attribute".format(project_name))

                supported = ['path', 'type', 'source', 'test', 'excluded', 'load_path']
                unknown = set(project_definition.keys()) - frozenset(supported)
                if unknown:
                    mx.abort("There are unsupported {} keys in {} external project".format(unknown, project_name))

                path = os.path.realpath(join(host.dir, project_definition["path"]))
                module_type = project_definition["type"]

                moduleXml = mx.XMLDoc()
                moduleXml.open('module',
                               attributes={'type': {'ruby': 'RUBY_MODULE',
                                                    'python': 'PYTHON_MODULE',
                                                    'web': 'WEB_MODULE'}.get(module_type, 'UKNOWN_MODULE'),
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
                    moduleXml.element('orderEntry', attributes={'type': 'jdk', 'jdkType': intellij_python_sdk_type, 'jdkName': intellij_get_python_sdk_name(sdks)})
                elif module_type == "web":
                    # nothing to do
                    pass
                else:
                    mx.abort("External project type {} not supported".format(module_type))

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

    if generate_external_projects:
        for p in s.projects_recursive() + mx._mx_suite.projects_recursive():
            _intellij_external_project(getattr(p, 'externalProjects', None), sdks, p)

    max_checkstyle_version = None
    compilerXml = None

    if java_modules:
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

            mx.ensure_dir_exists(p.dir)

            processors = p.annotation_processors()
            if processors:
                annotationProcessorProfiles.setdefault((p.source_gen_dir_name(),) + tuple(processors), []).append(p)

            intellijLanguageLevel = _complianceToIntellijLanguageLevel(p.javaCompliance)

            moduleXml = mx.XMLDoc()
            moduleXml.open('module', attributes={'type': 'JAVA_MODULE', 'version': '4'})

            moduleXml.open('component', attributes={'name': 'NewModuleRootManager', 'LANGUAGE_LEVEL': intellijLanguageLevel, 'inherit-compiler-output': 'false'})
            moduleXml.element('output', attributes={'url': 'file://$MODULE_DIR$/' + p.output_dir(relative=True)})

            moduleXml.open('content', attributes={'url': 'file://$MODULE_DIR$'})
            for src in p.srcDirs:
                srcDir = join(p.dir, src)
                mx.ensure_dir_exists(srcDir)
                moduleXml.element('sourceFolder', attributes={'url':'file://$MODULE_DIR$/' + src, 'isTestSource': str(p.is_test_project())})
            for name in ['.externalToolBuilders', '.settings', 'nbproject']:
                _intellij_exclude_if_exists(moduleXml, p, name)
            moduleXml.close('content')

            if processors:
                moduleXml.open('content', attributes={'url': 'file://' + p.get_output_root()})
                genDir = p.source_gen_dir()
                mx.ensure_dir_exists(genDir)
                moduleXml.element('sourceFolder', attributes={'url':'file://' + p.source_gen_dir(), 'isTestSource': str(p.is_test_project()), 'generated': 'true'})
                for name in [basename(p.output_dir())]:
                    _intellij_exclude_if_exists(moduleXml, p, name, output=True)
                moduleXml.close('content')

            moduleXml.element('orderEntry', attributes={'type': 'sourceFolder', 'forTests': 'false'})

            proj = p

            dependencies_project_packages = set()

            def should_process_dep(dep, edge):
                if dep.isTARDistribution() or dep.isNativeProject() or dep.isArchivableProject() or dep.isResourceLibrary():
                    mx.logv("Ignoring dependency from {} to {}".format(proj.name, dep.name))
                    return False
                return True

            def process_dep(dep, edge):
                if dep is proj:
                    return
                if dep.isLibrary() or dep.isJARDistribution() or dep.isMavenProject():
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
                        mx.logv("{} skipping {} for {}".format(p, dep, jdk)) #pylint: disable=undefined-loop-variable
                elif dep.isJreLibrary():
                    pass
                elif dep.isClasspathDependency():
                    moduleXml.element('orderEntry', attributes={'type': 'library', 'name': dep.name, 'level': 'project'})
                else:
                    mx.abort("Dependency not supported: {0} ({1})".format(dep, dep.__class__.__name__))

            p.walk_deps(preVisit=should_process_dep, visit=process_dep, ignoredEdges=[mx.DEP_EXCLUDED])

            moduleXml.element('orderEntry', attributes={'type': 'jdk', 'jdkType': intellij_java_sdk_type, 'jdkName': intellij_get_java_sdk_name(sdks, jdk)})

            moduleXml.close('component')

            if compilerXml and jdk.javaCompliance >= '9':
                moduleDeps = p.get_concealed_imported_packages(jdk=jdk)
                if moduleDeps:
                    exports = sorted([(m, pkgs) for m, pkgs in moduleDeps.items() if dependencies_project_packages.isdisjoint(pkgs)])
                    if exports:
                        args = []
                        exported_modules = set()
                        for m, pkgs in exports:
                            args += ['--add-exports={}/{}=ALL-UNNAMED'.format(m, pkg) for pkg in pkgs]
                            exported_modules.add(m)
                        roots = set(jdk.get_root_modules())
                        observable_modules = jdk.get_modules()
                        default_module_graph = mx_javamodules.get_transitive_closure(roots, observable_modules)
                        module_graph = mx_javamodules.get_transitive_closure(roots | exported_modules, observable_modules)
                        extra_modules = module_graph - default_module_graph
                        if extra_modules:
                            args.append('--add-modules=' + ','.join((m.name for m in extra_modules)))
                        if not additionalOptionsOverrides:
                            additionalOptionsOverrides = True
                            compilerXml.open('component', {'name': 'JavacSettings'})
                            compilerXml.open('option', {'name': 'ADDITIONAL_OPTIONS_OVERRIDE'})
                        compilerXml.element('module', {'name': p.name, 'options': ' '.join(args)})

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
            moduleFile = join(p.dir, p.name + '.iml')
            mx.update_file(moduleFile, moduleXml.xml(indent='  ', newl='\n'))

            if not module_files_only:
                declared_modules.add(p.name)
                moduleFilePath = "$PROJECT_DIR$/" + os.path.relpath(moduleFile, s.dir)
                modulesXml.element('module', attributes={'fileurl': 'file://' + moduleFilePath, 'filepath': moduleFilePath})
        if additionalOptionsOverrides:
            compilerXml.close('option')
            compilerXml.close('component')

    if mx_python_modules:
        # mx.<suite> python module:
        moduleXml = mx.XMLDoc()
        moduleXml.open('module', attributes={'type': 'PYTHON_MODULE', 'version': '4'})
        moduleXml.open('component', attributes={'name': 'NewModuleRootManager', 'inherit-compiler-output': 'true'})
        moduleXml.element('exclude-output')
        moduleXml.open('content', attributes={'url': 'file://$MODULE_DIR$'})
        moduleXml.element('sourceFolder', attributes={'url': 'file://$MODULE_DIR$', 'isTestSource': 'false'})
        for d in os.listdir(s.mxDir):
            directory = join(s.mxDir, d)
            if isdir(directory) and mx.dir_contains_files_recursively(directory, r".*\.java"):
                moduleXml.element('excludeFolder', attributes={'url': 'file://$MODULE_DIR$/' + d})
        moduleXml.close('content')
        moduleXml.element('orderEntry', attributes={'type': 'jdk', 'jdkType': intellij_python_sdk_type, 'jdkName': intellij_get_python_sdk_name(sdks)})
        moduleXml.element('orderEntry', attributes={'type': 'sourceFolder', 'forTests': 'false'})
        processes_suites = {s.name}

        def _mx_projects_suite(visited_suite, suite_import):
            if suite_import.name in processes_suites:
                return
            processes_suites.add(suite_import.name)
            dep_suite = mx.suite(suite_import.name)
            moduleXml.element('orderEntry', attributes={'type': 'module', 'module-name': basename(dep_suite.mxDir)})
            moduleFile = join(dep_suite.mxDir, basename(dep_suite.mxDir) + '.iml')
            if not module_files_only:
                declared_modules.add(basename(dep_suite.mxDir))
                moduleFilePath = "$PROJECT_DIR$/" + os.path.relpath(moduleFile, s.dir)
                modulesXml.element('module', attributes={'fileurl': 'file://' + moduleFilePath, 'filepath': moduleFilePath})
            dep_suite.visit_imports(_mx_projects_suite)
        s.visit_imports(_mx_projects_suite)
        moduleXml.element('orderEntry', attributes={'type': 'module', 'module-name': 'mx'})
        moduleXml.close('component')
        moduleXml.close('module')
        moduleFile = join(s.mxDir, basename(s.mxDir) + '.iml')
        mx.update_file(moduleFile, moduleXml.xml(indent='  ', newl='\n'))
        if not module_files_only:
            declared_modules.add(basename(s.mxDir))
            moduleFilePath = "$PROJECT_DIR$/" + os.path.relpath(moduleFile, s.dir)
            modulesXml.element('module', attributes={'fileurl': 'file://' + moduleFilePath, 'filepath': moduleFilePath})

            declared_modules.add(basename(mx._mx_suite.dir))
            mxModuleFile = join(mx._mx_suite.dir, basename(mx._mx_suite.dir) + '.iml')
            mxModuleFilePath = "$PROJECT_DIR$/" + os.path.relpath(mxModuleFile, s.dir)
            modulesXml.element('module', attributes={'fileurl': 'file://' + mxModuleFilePath, 'filepath': mxModuleFilePath})

    if generate_native_projects:
        _intellij_native_projects(s, module_files_only, declared_modules, modulesXml)

    if generate_external_projects:
        _intellij_external_project(s.suiteDict.get('externalProjects', None), sdks, s)

    if not module_files_only:
        modulesXml.close('modules')
        modulesXml.close('component')
        modulesXml.close('project')
        moduleXmlFile = join(ideaProjectDirectory, 'modules.xml')
        mx.update_file(moduleXmlFile, modulesXml.xml(indent='  ', newl='\n'))

    if java_modules and not module_files_only:
        unique_library_file_names = set()
        librariesDirectory = join(ideaProjectDirectory, 'libraries')

        mx.ensure_dir_exists(librariesDirectory)

        def make_library(name, path, source_path, suite_dir):
            libraryXml = mx.XMLDoc()

            libraryXml.open('component', attributes={'name': 'libraryTable'})
            libraryXml.open('library', attributes={'name': name})
            libraryXml.open('CLASSES')
            pathX = mx.relpath_or_absolute(path, suite_dir, prefix='$PROJECT_DIR$')
            libraryXml.element('root', attributes={'url': 'jar://' + pathX + '!/'})
            libraryXml.close('CLASSES')
            libraryXml.element('JAVADOC')
            if sourcePath:
                libraryXml.open('SOURCES')
                if os.path.isdir(sourcePath):
                    sourcePathX = mx.relpath_or_absolute(sourcePath, suite_dir, prefix='$PROJECT_DIR$')
                    libraryXml.element('root', attributes={'url': 'file://' + sourcePathX})
                else:
                    source_pathX = mx.relpath_or_absolute(source_path, suite_dir, prefix='$PROJECT_DIR$')
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
            sourcePath = None
            if library.isLibrary():
                path = library.get_path(True)
                if library.sourcePath:
                    sourcePath = library.get_source_path(True)
            elif library.isMavenProject():
                path = library.get_path(True)
                sourcePath = library.get_source_path(True)
            elif library.isJARDistribution():
                path = library.path
                if library.sourcesPath:
                    sourcePath = library.sourcesPath
            elif library.isClasspathDependency():
                path = library.classpath_repr()
            else:
                mx.abort('Dependency not supported: {} ({})'.format(library.name, library.__class__.__name__))
            make_library(library.name, path, sourcePath, s.dir)

        jdk = mx.get_jdk()
        updated = False
        for library in jdk_libraries:
            if library.classpath_repr(jdk) is not None:
                if make_library(library.name, library.classpath_repr(jdk), library.get_source_path(jdk), s.dir):
                    updated = True
        if jdk_libraries and updated:
            mx.log("Setting up JDK libraries using {0}".format(jdk))

        # Set annotation processor profiles up, and link them to modules in compiler.xml

        compilerXml.open('component', attributes={'name': 'CompilerConfiguration'})

        compilerXml.element('option', attributes={'name': "DEFAULT_COMPILER", 'value': 'Javac'})
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

        if java_modules:
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
        mx.ensure_dir_exists(join(ideaProjectDirectory, 'runConfigurations'))
        mx.update_file(runConfigFile, runConfig.xml(indent='  ', newl='\n'))

        if java_modules:
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
                        custom_eclipse = join(dirname(custom_eclipse), 'Eclipse', 'plugins')
                    if not exists(custom_eclipse_exe):
                        mx.abort('Custom eclipse "{}" does not exist'.format(custom_eclipse_exe))
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

        if java_modules:
            # Write codestyle settings
            mx.ensure_dir_exists(join(ideaProjectDirectory, 'codeStyles'))

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

            # mx integration
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
            mx.ensure_dir_exists(artifactsDir)
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
                for javaProject in [dep for dep in dist.deps if dep.isLibrary() or dep.isDistribution()]:
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

        suites_for_vcs = mx.suites() + ([mx._mx_suite] if mx_python_modules else [])
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

        mx.ensure_dir_exists(p.dir)

        moduleXml = mx.XMLDoc()
        moduleXml.open('module', attributes={'type': 'CPP_MODULE'})

        moduleXml.open('component', attributes={'name': 'NewModuleRootManager', 'inherit-compiler-output': 'false'})

        moduleXml.open('content', attributes={'url': 'file://$MODULE_DIR$'})
        for src in p.srcDirs:
            srcDir = join(p.dir, src)
            mx.ensure_dir_exists(srcDir)
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
