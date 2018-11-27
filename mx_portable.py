import sys

if sys.version_info[0] < 3:
    from StringIO import StringIO     #pylint: disable=unused-import
    import __builtin__ as builtins    #pylint: disable=unused-import
    from urllib2 import urlopen, build_opener, install_opener, HTTPError, URLError #pylint: disable=unused-import
    from urlparse import urlparse, urlsplit #pylint: disable=unused-import
else:
    from io import StringIO           #pylint: disable=unused-import
    import builtins                   #pylint: disable=unused-import
    from urllib.request import urlopen, build_opener, install_opener #pylint: disable=unused-import,E0611
    from urllib.error import HTTPError, URLError #pylint: disable=unused-import,E0611
    from urllib.parse import urlparse, urlsplit #pylint: disable=unused-import,E0611
