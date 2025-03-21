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

import os, sys
from os.path import join, exists
from io import StringIO

from . import mx, mx_util
from . import mx_ideconfig
from . import mx_ide_eclipse

@mx.command('mx', 'netbeansinit')
def netbeansinit(args, refreshOnly=False, buildProcessorJars=True, doFsckProjects=True):
    """(re)generate NetBeans project configurations"""

    jdks = set()
    for suite in mx.suites(True) + [mx._mx_suite]:
        _netbeansinit_suite(args, jdks, suite, refreshOnly, buildProcessorJars)

    if doFsckProjects and not refreshOnly:
        mx_ideconfig.fsckprojects([])
    mx.log('If using NetBeans:')
    # http://stackoverflow.com/questions/24720665/cant-resolve-jdk-internal-package
    mx.log('  1. Edit etc/netbeans.conf in your NetBeans installation and modify netbeans_default_options variable to include "-J-DCachingArchiveProvider.disableCtSym=true"')
    mx.log('  2. Ensure that the following platform(s) are defined (Tools -> Java Platforms):')
    for jdk in jdks:
        mx.log('        JDK_' + str(jdk.version))
    mx.log('  3. Open/create a Project Group for the directory containing the projects (File -> Project Group -> New Group... -> Folder of Projects)')

def _netbeansinit_project(p, jdks=None, files=None, libFiles=None, dists=None):
    dists = [] if dists is None else dists
    nb_dir = mx_util.ensure_dir_exists(join(p.dir))
    nbproject_dir = mx_util.ensure_dir_exists(join(nb_dir, 'nbproject'))

    jdk = mx.get_jdk(p.javaCompliance)
    assert jdk

    if jdks is not None:
        jdks.add(jdk)

    execDir = mx.primary_suite().dir

    out = mx.XMLDoc()
    out.open('project', {'name' : p.name, 'default' : 'default', 'basedir' : '.'})
    out.element('description', data='Builds, tests, and runs the project ' + p.name + '.')
    out.element('available', {'file' : 'nbproject/build-impl.xml', 'property' : 'build.impl.exists'})
    out.element('import', {'file' : 'nbproject/build-impl.xml', 'optional' : 'true'})
    out.element('extension-point', {'name' : '-mx-init'})
    out.element('available', {'file' : 'nbproject/build-impl.xml', 'property' : 'mx.init.targets', 'value' : 'init'})
    out.element('property', {'name' : 'mx.init.targets', 'value' : ''})
    out.element('bindtargets', {'extensionPoint' : '-mx-init', 'targets' : '${mx.init.targets}'})

    out.open('target', {'name' : '-post-init'})
    out.open('pathconvert', {'property' : 'comma.javac.classpath', 'pathsep' : ','})
    out.element('path', {'path' : '${javac.classpath}'})
    out.close('pathconvert')

    out.open('restrict', {'id' : 'missing.javac.classpath'})
    out.element('filelist', {'dir' : '${basedir}', 'files' : '${comma.javac.classpath}'})
    out.open('not')
    out.element('exists')
    out.close('not')
    out.close('restrict')

    out.element('property', {'name' : 'missing.javac.classpath', 'refid' : 'missing.javac.classpath'})

    out.open('condition', {'property' : 'no.dependencies', 'value' : 'true'})
    out.element('equals', {'arg1' : '${missing.javac.classpath}', 'arg2' : ''})
    out.close('condition')

    out.element('property', {'name' : 'no.dependencies', 'value' : 'false'})

    out.open('condition', {'property' : 'no.deps'})
    out.element('equals', {'arg1' : '${no.dependencies}', 'arg2' : 'true'})
    out.close('condition')

    out.close('target')
    out.open('target', {'name' : 'clean'})
    out.open('exec', {'executable' : sys.executable, 'failonerror' : 'true', 'dir' : execDir})
    out.element('env', {'key' : 'JAVA_HOME', 'value' : jdk.home})
    out.element('arg', {'value' : os.path.abspath(__file__)})
    out.element('arg', {'value' : 'clean'})
    out.element('arg', {'value' : '--projects'})
    out.element('arg', {'value' : p.name})
    out.close('exec')
    out.close('target')
    out.open('target', {'name' : 'compile'})
    out.open('exec', {'executable' : sys.executable, 'failonerror' : 'true', 'dir' : execDir})
    out.element('env', {'key' : 'JAVA_HOME', 'value' : jdk.home})
    out.element('arg', {'value' : os.path.abspath(__file__)})
    out.element('arg', {'value' : 'build'})
    dependsOn = p.name
    for d in dists:
        dependsOn = dependsOn + ',' + d.name
    out.element('arg', {'value' : '--only'})
    out.element('arg', {'value' : dependsOn})
    out.element('arg', {'value' : '--force-javac'})
    out.element('arg', {'value' : '--no-native'})
    out.element('arg', {'value' : '--no-daemon'})
    out.close('exec')
    out.close('target')
    out.open('target', {'name' : 'package', 'if' : 'build.impl.exists'})
    out.element('antcall', {'target': '-package', 'inheritall': 'true', 'inheritrefs': 'true'})
    out.close('target')
    out.open('target', {'name' : '-package', 'depends' : '-mx-init'})
    out.element('loadfile', {'srcFile' : join(p.suite.get_output_root(), 'netbeans.log'), 'property' : 'netbeans.log', 'failonerror' : 'false'})
    out.element('echo', {'message' : '...truncated...${line.separator}', 'output' : join(p.suite.get_output_root(), 'netbeans.log')})
    out.element('echo', {'message' : '${netbeans.log}'})
    for d in dists:
        if d.isDistribution():
            out.element('touch', {'file' : '${java.io.tmpdir}/' + d.name})
            out.element('echo', {'message' : d.name + ' set to now${line.separator}', 'append' : 'true', 'output' : join(p.suite.get_output_root(), 'netbeans.log')})
    out.open('copy', {'todir' : '${build.classes.dir}', 'overwrite' : 'true'})
    out.element('resources', {'refid' : 'changed.files'})
    out.close('copy')
    if len(p.annotation_processors()) > 0:
        out.open('copy', {'todir' : '${src.ap-source-output.dir}'})
        out.open('fileset', {'dir': '${cos.src.dir.internal}/../sources/'})
        out.element('include', {'name': '**/*.java'})
        out.close('fileset')
        out.close('copy')
    out.open('exec', {'executable' : '${ant.home}/bin/ant', 'spawn' : 'true'})
    out.element('arg', {'value' : '-f'})
    out.element('arg', {'value' : '${ant.file}'})
    out.element('arg', {'value' : 'packagelater'})
    out.close('exec')
    out.close('target')
    for d in dists:
        if d.isDistribution():
            out.open('target', {'name' : 'checkpackage-' + d.name})
            out.open('tstamp')
            out.element('format', {'pattern' : 'S', 'unit' : 'millisecond', 'property' : 'at.' + d.name})
            out.close('tstamp')
            out.element('touch', {'file' : '${java.io.tmpdir}/' + d.name, 'millis' : '${at.' + d.name + '}0000'})
            out.element('echo', {'message' : d.name + ' touched to ${at.' + d.name + '}0000${line.separator}', 'append' : 'true', 'output' : join(p.suite.get_output_root(), 'netbeans.log')})
            out.element('sleep', {'seconds' : '3'})
            out.open('condition', {'property' : 'mx.' + d.name, 'value' : sys.executable})
            out.open('islastmodified', {'millis' : '${at.' + d.name + '}0000', 'mode' : 'equals'})
            out.element('file', {'file' : '${java.io.tmpdir}/' + d.name})
            out.close('islastmodified')
            out.close('condition')
            out.element('echo', {'message' : d.name + ' defined as ' + '${mx.' + d.name + '}${line.separator}', 'append' : 'true', 'output' : join(p.suite.get_output_root(), 'netbeans.log')})
            out.close('target')
            out.open('target', {'name' : 'packagelater-' + d.name, 'depends' : 'checkpackage-' + d.name, 'if' : 'mx.' + d.name})
            out.open('exec', {'executable' : '${mx.' + d.name + '}', 'failonerror' : 'true', 'dir' : execDir, 'output' : join(p.suite.get_output_root(), 'netbeans.log'), 'append' : 'true'})
            out.element('env', {'key' : 'JAVA_HOME', 'value' : jdk.home})
            out.element('arg', {'value' : os.path.abspath(__file__)})
            out.element('arg', {'value' : 'build'})
            out.element('arg', {'value' : '-f'})
            out.element('arg', {'value' : '--only'})
            out.element('arg', {'value' : d.name})
            out.element('arg', {'value' : '--force-javac'})
            out.element('arg', {'value' : '--no-native'})
            out.element('arg', {'value' : '--no-daemon'})
            out.close('exec')
            out.close('target')
    dependsOn = ''
    sep = ''
    for d in dists:
        dependsOn = dependsOn + sep + 'packagelater-' + d.name
        sep = ','
    out.open('target', {'name' : 'packagelater', 'depends' : dependsOn})
    out.close('target')
    out.open('target', {'name' : 'jar', 'depends' : 'compile'})
    out.close('target')
    out.element('target', {'name' : 'test', 'depends' : 'run'})
    out.element('target', {'name' : 'test-single', 'depends' : 'run'})
    out.open('target', {'name' : 'run'})
    out.element('property', {'name' : 'test.class', 'value' : p.name})
    out.open('exec', {'executable' : sys.executable, 'failonerror' : 'true', 'dir' : execDir})
    out.element('env', {'key' : 'JAVA_HOME', 'value' : jdk.home})
    out.element('arg', {'value' : os.path.abspath(__file__)})
    out.element('arg', {'value' : 'unittest'})
    out.element('arg', {'value' : '${test.class}'})
    out.close('exec')
    out.close('target')
    out.element('target', {'name' : 'debug-test', 'depends' : 'debug'})
    out.open('target', {'name' : 'debug', 'depends' : '-mx-init'})
    out.element('property', {'name' : 'test.class', 'value' : p.name})
    out.open('nbjpdastart', {'addressproperty' : 'jpda.address', 'name' : p.name})
    out.open('classpath')
    out.open('fileset', {'dir' : '..'})
    out.element('include', {'name' : '*/bin/'})
    out.close('fileset')
    out.close('classpath')
    out.open('sourcepath')
    out.element('pathelement', {'location' : 'src'})
    out.close('sourcepath')
    out.close('nbjpdastart')
    out.open('exec', {'executable' : sys.executable, 'failonerror' : 'true', 'dir' : execDir})
    out.element('env', {'key' : 'JAVA_HOME', 'value' : jdk.home})
    out.element('arg', {'value' : os.path.abspath(__file__)})
    out.element('arg', {'value' : '-d'})
    out.element('arg', {'value' : '--attach'})
    out.element('arg', {'value' : '${jpda.address}'})
    out.element('arg', {'value' : 'unittest'})
    out.element('arg', {'value' : '${test.class}'})
    out.close('exec')
    out.close('target')
    out.open('target', {'name' : 'javadoc'})
    out.open('exec', {'executable' : sys.executable, 'failonerror' : 'true', 'dir' : execDir})
    out.element('env', {'key' : 'JAVA_HOME', 'value' : jdk.home})
    out.element('arg', {'value' : os.path.abspath(__file__)})
    out.element('arg', {'value' : 'javadoc'})
    out.element('arg', {'value' : '--projects'})
    out.element('arg', {'value' : p.name})
    out.element('arg', {'value' : '--force'})
    out.close('exec')
    out.element('nbbrowse', {'file' : 'javadoc/index.html'})
    out.close('target')
    out.close('project')
    mx.update_file(join(nb_dir, 'build.xml'), out.xml(indent='\t', newl='\n'))
    if files is not None:
        files.append(join(nb_dir, 'build.xml'))

    out = mx.XMLDoc()
    out.open('project', {'xmlns' : 'http://www.netbeans.org/ns/project/1'})
    out.element('type', data='org.netbeans.modules.java.j2seproject')
    out.open('configuration')
    out.open('data', {'xmlns' : 'http://www.netbeans.org/ns/j2se-project/3'})
    out.element('name', data=p.name)
    out.element('explicit-platform', {'explicit-source-supported' : 'true'})
    out.open('source-roots')
    out.element('root', {'id' : 'src.dir'})
    if len(p.annotation_processors()) > 0:
        out.element('root', {'id' : 'src.ap-source-output.dir', 'name' : 'Generated Packages'})
    out.close('source-roots')
    out.open('test-roots')
    out.close('test-roots')
    out.close('data')

    firstDep = []

    def processDep(dep, edge):
        if dep is p:
            return

        if dep.isProject():
            n = dep.name.replace('.', '_')
            if not firstDep:
                out.open('references', {'xmlns' : 'http://www.netbeans.org/ns/ant-project-references/1'})
                firstDep.append(dep)

            out.open('reference')
            out.element('foreign-project', data=n)
            out.element('artifact-type', data='jar')
            out.element('script', data='build.xml')
            out.element('target', data='jar')
            out.element('clean-target', data='clean')
            out.element('id', data='jar')
            out.close('reference') #pylint: disable=too-many-function-args
    p.walk_deps(visit=processDep, ignoredEdges=[mx.DEP_EXCLUDED])

    if firstDep:
        out.close('references')

    out.close('configuration')
    out.close('project')
    mx.update_file(join(nbproject_dir, 'project.xml'), out.xml(indent='    ', newl='\n'))
    if files is not None:
        files.append(join(nbproject_dir, 'project.xml'))

    out = StringIO()
    jdkPlatform = 'JDK_' + str(jdk.version)

    annotationProcessorEnabled = "false"
    annotationProcessorSrcFolder = ""
    annotationProcessorSrcFolderRef = ""
    if len(p.annotation_processors()) > 0:
        annotationProcessorEnabled = "true"
        mx_util.ensure_dir_exists(p.source_gen_dir())
        annotationProcessorSrcFolder = os.path.relpath(p.source_gen_dir(), nb_dir)
        annotationProcessorSrcFolder = annotationProcessorSrcFolder.replace('\\', '\\\\')
        annotationProcessorSrcFolderRef = "src.ap-source-output.dir=" + annotationProcessorSrcFolder

    canSymlink = not (mx.is_windows() or mx.is_cygwin()) and 'symlink' in dir(os)
    if canSymlink:
        nbBuildDir = join(nbproject_dir, 'build')
        apSourceOutRef = "annotation.processing.source.output=" + annotationProcessorSrcFolder
        if os.path.lexists(nbBuildDir):
            os.unlink(nbBuildDir)
        os.symlink(p.output_dir(), nbBuildDir)
    else:
        nbBuildDir = p.output_dir()
        apSourceOutRef = ""
    mx_util.ensure_dir_exists(p.output_dir())

    mx_ide_eclipse.copy_eclipse_settings(nb_dir, p)

    content = """
annotation.processing.enabled=""" + annotationProcessorEnabled + """
annotation.processing.enabled.in.editor=""" + annotationProcessorEnabled + """
""" + apSourceOutRef + """
annotation.processing.processors.list=
annotation.processing.run.all.processors=true
application.title=""" + p.name + """
application.vendor=mx
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.eclipseFormatterActiveProfile=
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.eclipseFormatterEnabled=true
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.eclipseFormatterLocation=
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.enableFormatAsSaveAction=true
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.linefeed=
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.preserveBreakPoints=true
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.SaveActionModifiedLinesOnly=false
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.showNotifications=false
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.sourcelevel=
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.useProjectPref=true
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.useProjectSettings=true
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.eclipseFormatterActiveProfile=
auxiliary.org-netbeans-spi-editor-hints-projects.perProjectHintSettingsEnabled=true
auxiliary.org-netbeans-spi-editor-hints-projects.perProjectHintSettingsFile=nbproject/cfg_hints.xml
build.classes.dir=${build.dir}
build.classes.excludes=**/*.java,**/*.form
# This directory is removed when the project is cleaned:
build.dir=""" + nbBuildDir + """
$cos.update=package
$cos.update.resources=changed.files
compile.on.save=true
build.generated.sources.dir=${build.dir}/generated-sources
# Only compile against the classpath explicitly listed here:
build.sysclasspath=ignore
build.test.classes.dir=${build.dir}/test/classes
build.test.results.dir=${build.dir}/test/results
# Uncomment to specify the preferred debugger connection transport:
#debug.transport=dt_socket
debug.classpath=\\
${run.classpath}
debug.test.classpath=\\
${run.test.classpath}
# This directory is removed when the project is cleaned:
dist.dir=dist
dist.jar=${dist.dir}/""" + p.name + """.jar
dist.javadoc.dir=${dist.dir}/javadoc
endorsed.classpath=
excludes=
includes=**
jar.compress=false
java.main.action=test
# Space-separated list of extra javac options
javac.compilerargs=-XDignore.symbol.file
javac.deprecation=false
javac.source=""" + str(p.javaCompliance) + """
javac.target=""" + str(p.javaCompliance) + """
javac.test.classpath=\\
${javac.classpath}:\\
${build.classes.dir}
javadoc.additionalparam=
javadoc.author=false
javadoc.encoding=${source.encoding}
javadoc.noindex=false
javadoc.nonavbar=false
javadoc.notree=false
javadoc.private=false
javadoc.splitindex=true
javadoc.use=true
javadoc.version=false
javadoc.windowtitle=
manifest.file=manifest.mf
meta.inf.dir=${src.dir}/META-INF
mkdist.disabled=false
platforms.""" + jdkPlatform + """.home=""" + jdk.home + """
platform.active=""" + jdkPlatform + """
run.classpath=\\
${javac.classpath}:\\
${build.classes.dir}
# Space-separated list of JVM arguments used when running the project
# (you may also define separate properties like run-sys-prop.name=value instead of -Dname=value
# or test-sys-prop.name=value to set system properties for unit tests):
run.jvmargs=
run.test.classpath=\\
${javac.test.classpath}:\\
${build.test.classes.dir}
test.src.dir=./test
""" + annotationProcessorSrcFolderRef + """
source.encoding=UTF-8""".replace(':', os.pathsep).replace('/', os.sep)
    print(content, file=out)

    # Workaround for NetBeans "too clever" behavior. If you want to be
    # able to press F6 or Ctrl-F5 in NetBeans and run/debug unit tests
    # then the project must have its main.class property set to an
    # existing class with a properly defined main method. Until this
    # behavior is remedied, we specify a well known Truffle class
    # that will be on the class path for most Truffle projects.
    # This can be overridden by defining a netbeans.project.properties
    # attribute for a project in suite.py (see below).
    print("main.class=com.oracle.truffle.api.impl.Accessor", file=out)

    # Add extra properties specified in suite.py for this project
    if hasattr(p, 'netbeans.project.properties'):
        properties = getattr(p, 'netbeans.project.properties')
        for prop in [properties] if isinstance(properties, str) else properties:
            print(prop, file=out)

    mainSrc = True
    for src in p.srcDirs:
        srcDir = mx_util.ensure_dir_exists(join(p.dir, src))
        ref = 'file.reference.' + p.name + '-' + src
        print(ref + '=' + os.path.relpath(srcDir, nb_dir), file=out)
        if mainSrc:
            print('src.dir=${' + ref + '}', file=out)
            mainSrc = False
        else:
            print('src.' + src + '.dir=${' + ref + '}', file=out)

    javacClasspath = []

    def newDepsCollector(into):
        return lambda dep, edge: into.append(dep) if dep.isLibrary() or dep.isJdkLibrary() or dep.isProject() or dep.isClasspathDependency() else None

    deps = []
    p.walk_deps(visit=newDepsCollector(deps))
    annotationProcessorOnlyDeps = []
    if len(p.annotation_processors()) > 0:
        for apDep in p.annotation_processors():
            resolvedApDeps = []
            apDep.walk_deps(visit=newDepsCollector(resolvedApDeps))
            for resolvedApDep in resolvedApDeps:
                if not resolvedApDep in deps:
                    deps.append(resolvedApDep)
                    annotationProcessorOnlyDeps.append(resolvedApDep)

    annotationProcessorReferences = []

    for dep in deps:
        if dep == p:
            continue

        if dep.isLibrary() or dep.isJdkLibrary():
            if dep.isLibrary():
                path = dep.get_path(resolve=True)
                sourcePath = dep.get_source_path(resolve=True)
            else:
                path = dep.classpath_repr(jdk, resolve=True)
                sourcePath = dep.get_source_path(jdk)
            if path:
                if os.sep == '\\':
                    path = path.replace('\\', '\\\\')
                ref = 'file.reference.' + dep.name + '-bin'
                print(ref + '=' + path, file=out)
                if libFiles:
                    libFiles.append(path)
            if sourcePath:
                if os.sep == '\\':
                    sourcePath = sourcePath.replace('\\', '\\\\')
                print('source.reference.' + dep.name + '-bin=' + sourcePath, file=out)
        elif dep.isProject():
            n = dep.name.replace('.', '_')
            relDepPath = os.path.relpath(dep.dir, nb_dir).replace(os.sep, '/')
            if canSymlink:
                depBuildPath = join('nbproject', 'build')
            else:
                depBuildPath = 'dist/' + dep.name + '.jar'
            ref = 'reference.' + n + '.jar'
            print('project.' + n + '=' + relDepPath, file=out)
            print(ref + '=${project.' + n + '}/' + depBuildPath, file=out)
        elif dep.isJreLibrary():
            continue
        elif dep.isClasspathDependency():
            extra = [di for di in dep.deps if di not in deps]
            if dep.isDistribution() and dep.deps and not extra:
                # ignore distribution classpath dependencies that only contain other explicit dependencies
                continue
            path = dep.classpath_repr(resolve=True)
            sourcePath = dep.get_source_path(jdk) if hasattr(dep, 'get_source_path') else None
            if path:
                if os.sep == '\\':
                    path = path.replace('\\', '\\\\')
                ref = 'file.reference.' + dep.name + '-bin'
                print(ref + '=' + path, file=out)
                if libFiles:
                    libFiles.append(path)
                if sourcePath:
                    if os.sep == '\\':
                        sourcePath = sourcePath.replace('\\', '\\\\')
                    print('source.reference.' + dep.name + '-bin=' + sourcePath, file=out)

        if not dep in annotationProcessorOnlyDeps:
            javacClasspath.append('${' + ref + '}')
        else:
            annotationProcessorReferences.append('${' + ref + '}')

    print('javac.classpath=\\\n    ' + (os.pathsep + '\\\n    ').join(javacClasspath), file=out)
    print('javac.processorpath=' + (os.pathsep + '\\\n    ').join(['${javac.classpath}'] + annotationProcessorReferences), file=out)
    print('javac.test.processorpath=' + (os.pathsep + '\\\n    ').join(['${javac.test.classpath}'] + annotationProcessorReferences), file=out)

    mx.update_file(join(nbproject_dir, 'project.properties'), out.getvalue())
    out.close()

    if files is not None:
        files.append(join(nbproject_dir, 'project.properties'))

    for source in p.suite.netbeans_settings_sources().get('cfg_hints.xml'):
        with open(source) as fp:
            content = fp.read()
    mx.update_file(join(nbproject_dir, 'cfg_hints.xml'), content)

    if files is not None:
        files.append(join(p.dir, 'nbproject', 'cfg_hints.xml'))

def _netbeansinit_suite(args, jdks, suite, refreshOnly=False, buildProcessorJars=True):
    netbeans_dir = mx_util.ensure_dir_exists(suite.get_mx_output_dir())
    configZip = mx.TimeStampFile(join(netbeans_dir, 'netbeans-config.zip'))
    configLibsZip = join(netbeans_dir, 'netbeans-config-libs.zip')
    if refreshOnly and not configZip.exists():
        return

    if mx_ideconfig._check_ide_timestamp(suite, configZip, 'netbeans'):
        mx.logv('[NetBeans configurations are up to date - skipping]')
        return

    files = []
    libFiles = []
    for p in suite.projects:
        if not p.isJavaProject():
            continue

        if exists(join(p.dir, 'plugin.xml')):  # eclipse plugin project
            continue

        includedInDists = [d for d in suite.dists if p in d.archived_deps()]
        _netbeansinit_project(p, jdks, files, libFiles, includedInDists)

    mx_ideconfig._zip_files(files, suite.dir, configZip.path)
    mx_ideconfig._zip_files(libFiles, suite.dir, configLibsZip)
