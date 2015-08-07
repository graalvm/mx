import sys, inspect, re, types, bisect
from collections import OrderedDict
import mx

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

    def __str__(self):
        return str("MxCompatibility({})".format(self.version()))

    def __repr__(self):
        return str(self)

class MxCompatibility520(MxCompatibility500):
    @staticmethod
    def version():
        return mx.VersionSpec("5.2.0")

    def supportsLicenses(self):
        return True

    def supportedMavenMetadata(self):
        return ['library-coordinates', 'suite-url', 'suite-developer', 'dist-description']

class MxCompatibility522(MxCompatibility520):
    @staticmethod
    def version():
        return mx.VersionSpec("5.2.2")

    def licenseAttribute(self):
        return 'license'

    def licensesAttribute(self):
        return 'licenses'

    def defaultLicenseAttribute(self):
        return 'defaultLicense'


def minVersion():
    _ensureCompatLoaded()
    return _versionsMap.keys()[0]

def getMxCompatibility(version):
    if version < minVersion():  # ensures compat loaded
        return None
    keys = _versionsMap.keys()
    return _versionsMap[keys[bisect.bisect_right(keys, version)-1]]

_versionsMap = OrderedDict()

def _ensureCompatLoaded():
    if not _versionsMap:

        def flattenClassTree(tree):
            root = tree[0][0]
            assert isinstance(root, types.TypeType), root
            yield root
            if len(tree) > 1:
                assert len(tree) == 2
                rest = tree[1]
                assert isinstance(rest, types.ListType), rest
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
