import sys

if sys.version_info[0] < 3:
    from StringIO import StringIO                    #pylint: disable=unused-import
    import __builtin__ as builtins                   #pylint: disable=unused-import
    import urllib2                                   #pylint: disable=unused-import
    urllib_request = urllib2
    urllib_error = urllib2
    del urllib2
    import urlparse as urllib_parse                  #pylint: disable=unused-import
else:
    from io import StringIO                          #pylint: disable=unused-import
    import builtins                                  #pylint: disable=unused-import
    import urllib.request as urllib_request          #pylint: disable=unused-import,no-name-in-module
    import urllib.error as urllib_error              #pylint: disable=unused-import,no-name-in-module
    import urllib.parse as urllib_parse              #pylint: disable=unused-import,no-name-in-module
