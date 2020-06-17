#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2020, Oracle and/or its affiliates. All rights reserved.
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
import re
import mx
from os.path import join

GITHUB_URL = "https://github.com"
GITHUB_RELEASES = "releases/download"

class JdkDistribution(object):
    _jdk_distributions = []
    _DEFAULT_JDK = "labsjdk-ce-11"

    @staticmethod
    def parse(name, version):
        for dist in JdkDistribution.__subclasses__():
            if dist._name == name:
                dist(version)

    @staticmethod
    def choose_dist(quiet=False):
        if quiet:
            return JdkDistribution.by_name(JdkDistribution._DEFAULT_JDK)

        index = 1
        default_choice = 1
        for dist in JdkDistribution._jdk_distributions:
            if dist.get_name() == JdkDistribution._DEFAULT_JDK:
                default_choice = index
                default = "*"
            else:
                default = " "
            print("[{index}]{default} {name} | {version}".format(index=index,
            name=dist.get_name().ljust(25), version=dist.get_version(), default=default))
            index += 1
        while True:
            try:
                try:
                    choice = input("Select JDK>")
                except SyntaxError: # Empty line
                    choice = ""

                if choice == "":
                    index = default_choice - 1
                else:
                    index = int(choice) - 1

                if index < 0:
                    raise IndexError

                return JdkDistribution._jdk_distributions[index]
            except (SyntaxError, NameError, IndexError):
                mx.warn("Invalid selection!")

    @staticmethod
    def by_name(name):
        for dist in JdkDistribution._jdk_distributions:
            if dist.get_name() == name:
                return dist
        mx.abort("Unknown JDK distribution")

    def __init__(self, version):
        self._version = version
        self._jdk_distributions.append(self)

    def get_filename(self):
        return self._filename

    def get_archive_name(self):
        return self._archive

    def get_url(self):
        return self._url

    def get_name(self):
        return self._name

    def get_version(self):
        return self._version

    def get_short_version(self):
        return self._short_version

    def get_folder_name(self):
        return "{}-{}".format(self.get_name(), self.get_short_version())

    def get_final_path(self, jdk_path):
        return join(jdk_path, self.get_folder_name())

class OpenJDK8(JdkDistribution):
    _name = "openjdk8"
    def __init__(self, version):
        JdkDistribution.__init__(self, version)
        machine = mx.get_os() + '-' + mx.get_arch()
        self._filename = "openjdk-{}-{}".format(version, machine)
        self._short_version = re.sub(r".*(jvmci.*)", "\\1", version)
        self._archive = "{}.tar.gz".format(self._filename)
        self._url = ("{GITHUB_URL}/graalvm/graal-jvmci-8/"
                    "{GITHUB_RELEASES}/{short_version}/{archive}"
                    ).format(GITHUB_URL=GITHUB_URL, GITHUB_RELEASES=GITHUB_RELEASES,
                    short_version=self._short_version, archive=self._archive)

class OpenJDK8Debug(JdkDistribution):
    _name = "openjdk8"
    def __init__(self, version):
        JdkDistribution.__init__(self, version)
        machine = mx.get_os() + '-' + mx.get_arch()
        self._filename = "openjdk-{}-fastdebug-{}".format(version, machine)
        self._short_version = re.sub(r".*(jvmci.*)", "\\1", version)
        self._archive = "{}.tar.gz".format(self._filename)
        self._url = ("{GITHUB_URL}/graalvm/graal-jvmci-8/"
                    "{GITHUB_RELEASES}/{short_version}/{archive}"
                    ).format(GITHUB_URL=GITHUB_URL, GITHUB_RELEASES=GITHUB_RELEASES,
                    short_version=self._short_version, archive=self._archive)

    def get_name(self):
        return self._name + "-fastdebug"

class LabsJDK11CE(JdkDistribution):
    _name = "labsjdk-ce-11"
    def __init__(self, version):
        JdkDistribution.__init__(self, version)
        machine = mx.get_os() + '-' + mx.get_arch()
        self._filename = "labsjdk-{}-{}".format(version, machine)
        self._short_version = re.sub(r".*(jvmci.*)", "\\1", version)
        self._archive = "{}.tar.gz".format(self._filename)
        self._url = ("{GITHUB_URL}/graalvm/labs-openjdk-11/"
                    "{GITHUB_RELEASES}/{short_version}/{archive}"
                    ).format(GITHUB_URL=GITHUB_URL, GITHUB_RELEASES=GITHUB_RELEASES,
                    short_version=self._short_version, archive=self._archive)

class LabsJDK11CEDebug(JdkDistribution):
    _name = "labsjdk-ce-11"
    def __init__(self, version):
        JdkDistribution.__init__(self, version)
        machine = mx.get_os() + '-' + mx.get_arch()
        self._filename = "labsjdk-{}-debug-{}".format(version, machine)
        self._short_version = re.sub(r".*(jvmci.*)", "\\1", version)
        self._archive = "{}.tar.gz".format(self._filename)
        self._url = ("{GITHUB_URL}/graalvm/labs-openjdk-11/"
                    "{GITHUB_RELEASES}/{short_version}/{archive}"
                    ).format(GITHUB_URL=GITHUB_URL, GITHUB_RELEASES=GITHUB_RELEASES,
                    short_version=self._short_version, archive=self._archive)

    def get_name(self):
        return self._name + "-debug"
