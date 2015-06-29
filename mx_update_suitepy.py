#
# Copyright (c) 2007, 2015, Oracle and/or its affiliates. All rights reserved.
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

import shutil
from os.path import join, relpath

_indent = None

def update_suite_file(self, backup=True):
    '''
    Write an updated suite.py file from current data, backing up old one in suite_py().orig if requested
    '''
    suite_file = self.suite_py()
    if backup:
        shutil.copy(suite_file, join(suite_file, 'orig'))

    with open(suite_file, 'w') as f:
        class Indent:
            def __init__(self, f):
                # can't access f in outer scope in 2.x
                self.sf = f
                self.incIndent = 2
                self.indent = 0 if _indent is None else _indent.indent

            def __enter__(self):
                self.indent += self.incIndent
                global _indent
                self._save_indent = _indent
                _indent = self
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                self.indent -= self.incIndent
                global _indent
                _indent = self._save_indent

            def writeIndent(self):
                ''' write the current indent '''
                for _ in range(self.indent):
                    self.sf.write(' ')

            def write(self, t):
                ''' write the current indent followed by t '''
                self.writeIndent()
                self.sf.write(t)

            def writenl(self, t):
                ''' write the current indent followed by t and a nl'''
                self.writeIndent()
                self.sf.write(t + '\n')

            def writecnl(self, t):
                ''' write the current indent followed by t, a comma and a nl'''
                self.writenl(t + ',')

            def writeqname(self, t):
                '''  "t" '''
                self.sf.write('"' + t + '"')

            def writeqnameBra(self, t):
                ''' write the current indent followed by "t", a comma and a nl'''
                self.writeIndent()
                self.writeqname(t)
                self.sf.write(" : {\n")

            def writeKeyValueNL(self, key, value):
                ''' write the current indent followed by "key" : "name", a comma and a nl'''
                self.writeIndent()
                self.writeqname(key)
                self.sf.write(" : ")
                self.writeqname(value)
                self.sf.write(',\n')

            def writeStringList(self, key, stringList):
                self.writeIndent()
                self.writeqname(key)
                self.sf.write(" : [")
                if len(stringList) > 1:
                    f.write('\n')
                    with Indent(self.sf):
                        for s in stringList:
                            _indent.writeIndent()
                            _indent.writeqname(s)
                            _indent.f.write(',\n')
                    self.writeIndent()
                elif len(stringList) == 1:
                    self.writeqname(stringList[0])
                self.sf.write("],\n")


        f.write('suite = {\n')

        with Indent(f):
            _indent.writeKeyValueNL("mxversion", str(self.requiredMxVersion))
            _indent.writeKeyValueNL("name", self.name)
            _indent.writenl('')
            # imports
            _indent.writeqnameBra("imports")
            with Indent(f):
                if self.suite_imports:
                    _indent.writenl('"suites" = [')
                    with Indent(f):
                        for suite_import in self.suite_imports:
                            _indent.writenl('{')
                            with Indent(f):
                                _indent.writeKeyValueNL("name", suite_import.name)
                                _indent.writeKeyValueNL("kind", suite_import.kind)
                                if suite_import.version:
                                    _indent.writeKeyValueNL("version", suite_import.version)
                                if suite_import.urls:
                                    _indent.writeStringList("urls", suite_import.urls)
                            _indent.writecnl('}')
                    _indent.writecnl(']')

                f.write('\n')
                if self.jreLibs:
                    _indent.writeqnameBra("jrelibraries")
                    with Indent(f):
                        for jrelib in self.jrelibs:
                            _indent.writeqnameBra(jrelib.name)
                            with Indent(f):
                                _indent.writeKeyValueNL("jar", jrelib.jar)
                        _indent.writecnl('}')
                    _indent.writecnl('}')

                f.write('\n')
                if self.libs:
                    _indent.writeqnameBra("libraries")
                    with Indent(f):
                        for lib in self.libs:
                            _indent.writeqnameBra(lib.name)
                            with Indent(f):
                                _indent.writeKeyValueNL("path", lib.path)
                                if len(lib.urls) > 0:
                                    _indent.writeStringList("urls", lib.urls)
                                _indent.writeKeyValueNL("sha1", lib.sha1)
                            _indent.writecnl('}')
                            f.write('\n')
                    _indent.writecnl('}')
            # end of imports
            _indent.writecnl('}')

            # projects
            if len(self.projects) > 0:
                f.write('\n')
                _indent.writeqnameBra("projects")
                with Indent(f):
                    for p in self.projects:
                        _indent.writeqnameBra(p.name)
                        with Indent(f):
                            if p.subDir:
                                _indent.writeKeyValueNL("subDir", p.subDir)
                            _indent.writeStringList("sourceDirs", p.srcDirs)
                            if p.deps:
                                _indent.writeStringList("dependencies", p.deps)
                            if hasattr(p, "_declaredAnnotationProcessors"):
                                _indent.writeStringList("annotationProcessors", p._declaredAnnotationProcessors)
                            if p.checkstyleProj:
                                _indent.writeKeyValueNL("checkstyle", p.checkstyleProj)
                            if p.javaCompliance:
                                _indent.writeKeyValueNL("javaCompliance", str(p.javaCompliance))
                            if p.native:
                                _indent.writeKeyValueNL("native", "true")
                            if p.workingSets:
                                _indent.writeKeyValueNL("workingSets", p.workingSets)
                            if hasattr(p, "jacoco"):
                                _indent.writeKeyValueNL("jacoco", p.jacoco)
                            _indent.writecnl('}')
                        f.write('\n')
                # end of projects
                _indent.writecnl('}')

            if len(self.dists) > 0:
                f.write('\n')
                _indent.writeqnameBra("distributions")
                with Indent(f):
                    for d in self.dists:
                        if not d.isProcessorDistribution:
                            _indent.writeqnameBra(d.name)
                            with Indent(f):
                                _indent.writeKeyValueNL("path", relpath(d.path, d.suite.dir))
                                if d.subDir:
                                    _indent.writeKeyValueNL("subDir", d.subDir, d.suite.dir)
                                if d.sourcesPath:
                                    _indent.writeKeyValueNL("sourcesPath", relpath(d.sourcesPath))
                                if d.javaCompliance:
                                    _indent.writeKeyValueNL("javaCompliance", str(d.javaCompliance))
                                if d.mainClass:
                                    _indent.writeKeyValueNL("mainClass", str(d.mainClass))
                                if d.deps:
                                    _indent.writeStringList("dependencies", d.deps)
                                if d.excludedDependencies:
                                    _indent.writeStringList("exclude", d.excludedDependencies)
                            _indent.writecnl('}')

                            f.write('\n')
                # end of distributions
                _indent.writecnl('}')

        # end of suite
        f.write('}\n')
