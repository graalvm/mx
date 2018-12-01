import sys

def _agregate_module(name, *args):
    """
    Creates a module with the name 'name' and adds all the symbols from the
    argument modules to it.
    """
    from types import ModuleType
    result = ModuleType(name)
    for mod in args:
        for symbol in mod.__all__:
            result.__dict__[symbol] = mod.__dict__[symbol]
    return result

if sys.version_info[0] < 3:
    from StringIO import StringIO     #pylint: disable=unused-import
    import __builtin__ as builtins    #pylint: disable=unused-import
    import urllib2 #pylint: disable=unused-import
    import urlparse #pylint: disable=unused-import
else:
    from io import StringIO           #pylint: disable=unused-import
    import builtins                   #pylint: disable=unused-import
    import urllib.request             #pylint: disable=unused-import,no-name-in-module
    import urllib.error               #pylint: disable=unused-import,no-name-in-module
    urllib2 = _agregate_module('urllib2', urllib.request, urllib.error)
    import urllib.parse as urlparse #pylint: disable=unused-import,no-name-in-module
