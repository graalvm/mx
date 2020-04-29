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
import re, json
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
                return
    @staticmethod
    def parse_common_json(common_path):
        with open(common_path) as common_file:
            common_cfg = json.load(common_file)

        for distribution in common_cfg["jdks"]:
            JdkDistribution.parse(distribution, common_cfg["jdks"][distribution]["version"])

    @staticmethod
    def choose_dist(quiet=False):
        if quiet:
            return JdkDistribution.by_name(JdkDistribution._DEFAULT_JDK)

        index = 1
        for dist in JdkDistribution._jdk_distributions:
            default = " " if dist.get_name() != JdkDistribution._DEFAULT_JDK else "*"
            print("[{index}]{default} {name} | {version}".format(index=index,
            name=dist.get_name().ljust(15), version=dist.get_version(), default=default))
            index += 1
        while True:
            print("Select JDK>"), # pylint: disable=expression-not-assigned
            try:
                index = int(input()) - 1
                return JdkDistribution._jdk_distributions[index]
            except (SyntaxError, NameError, IndexError):
                pass

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

    def get_archive(self):
        return self._archive

    def get_url(self):
        return self._url

    def get_name(self):
        return self._name

    def get_version(self):
        return self._version

    def get_short_version(self):
        return self._short_version

    def get_jdk_folder(self):
        return "{}-{}".format(self.get_name(), self.get_short_version())

    def get_full_jdk_path(self, jdk_path):
        return join(jdk_path, self.get_jdk_folder())

class OpenJDK8(JdkDistribution):
    _name = "openjdk8"
    def __init__(self, version):
        JdkDistribution.__init__(self, version)
        machine = mx.get_os() + '-' + mx.get_arch()
        self._filename = "openjdk-{}-{}".format(version, machine)
        self._short_version = re.sub(r".*(jvmci.*)", "\\1", version)
        self._archive = "{}.tar.gz".format(self._filename)
        self._url = ("{GITHUB_URL}/graalvm/openjdk8-jvmci-builder/"
                    "{GITHUB_RELEASES}/{short_version}/{archive}"
                    ).format(GITHUB_URL=GITHUB_URL, GITHUB_RELEASES=GITHUB_RELEASES,
                    short_version=self._short_version, archive=self._archive)

class OpenJDK11(JdkDistribution):
    _name = "openjdk11"
    def __init__(self, version):
        JdkDistribution.__init__(self, version)
        machine = self.get_machine()
        self._short_version = version.replace("+", "_")
        self._filename = "OpenJDK11U-jdk_{machine}_hotspot_{short_version}".format(short_version=self._short_version, machine=machine)
        self._archive = "{}.tar.gz".format(self._filename)
        self._url = ("{GITHUB_URL}/AdoptOpenJDK/openjdk11-binaries/"
                    "{GITHUB_RELEASES}/jdk-{version}/{archive}"
                    ).format(GITHUB_URL=GITHUB_URL, GITHUB_RELEASES=GITHUB_RELEASES,
                    version=version, archive=self._archive)

    def get_machine(self):
        return mx.get_arch().replace("amd", "x") + "_" + mx.get_os().replace("darwin", "mac")

class LabsJDKCE(JdkDistribution):
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
