#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2015, Oracle and/or its affiliates. All rights reserved.
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

import re
import os
import json

_urlrewrites = [] # list of URLRewrite objects

def register_urlrewrite(urlrewrite, onError=None):
    """
    Appends a URL rewrite rule to the current rewrite rules.
    A URL rewrite rule is a dict where the key is a regex for matching a URL and the value describes
    how to rewrite.

    :Example:

    {
      "https://git.acme.com/(.*).git" : {
         "replacement" : "https://my.company.com/foo-git-cache/\1.git",
      }
    }

    :param urlrewrite: a URL rewrite rule
    :type urlrewrite: dict or URLRewrite
    :param function onError: called with error message argument if urlwrewrite is badly formed
    """

    if onError is None:
        def _error(msg):
            raise Exception(msg)
        onError = _error

    if isinstance(urlrewrite, URLRewrite):
        _urlrewrites.append(urlrewrite)
        return
    if not isinstance(urlrewrite, dict) or len(urlrewrite) != 1:
        onError('A URL rewrite rule must be a dict with a single entry')
    for pattern, attrs in urlrewrite.iteritems():
        replacement = attrs.pop('replacement', None)
        if replacement is None:
            raise Exception('URL rewrite for pattern "' + pattern + '" is missing "replacement" entry')
        if len(attrs) != 0:
            raise Exception('Unsupported attributes found for URL rewrite "' + pattern + '": ' + str(attrs))
        try:
            pattern = re.compile(pattern)
        except Exception as e: # pylint: disable=broad-except
            onError('Error parsing URL rewrite pattern "' + pattern +'": ' + str(e))
        urlrewrite = URLRewrite(pattern, replacement)
        _urlrewrites.append(urlrewrite)

def register_urlrewrites_from_env(name):
    """
    Appends rewrite rules denoted by the environment variable named by `name`.
    If the environment variable has a non-empty value it must either be an JSON
    object describing a single rewrite rule, a JSON array describing a list of
    rewrite rules or a file containing one of these JSON values.

    :param str name: name of an environment variable denoting URL rewrite rules
    """
    value = os.environ.get(name, None)
    if value:
        def raiseError(msg):
            raise Exception('Error processing URL rewrite rules denoted by environment variable ' + name + ':\n' + msg)

        value = value.strip()
        if value[0] not in '{[':
            with open(value) as fp:
                jsonValue = fp.read().strip()
        else:
            jsonValue = value

        def loadJson(jsonValue):
            try:
                return json.loads(jsonValue)
            except ValueError as e:
                raise Exception('Error parsing JSON object denoted by ' + name + ' environment variable:\n' + str(e))

        if jsonValue:
            rewrites = loadJson(jsonValue) # JSON root is always either list or dict
            if isinstance(rewrites, dict):
                rewrites = [rewrites]
            for rewrite in rewrites:
                register_urlrewrite(rewrite, raiseError)

def rewriteurl(url):
    """
    Finds the first registered URL rewrite rule that matches `url` and returns the replacement
    provided by the rule.

    :param str url: a URL to match against the registered rerwrite rules
    :return: the value of `url` rewritten according to the first matching rewrite URL or unmodified
             if no rules match
    :rtype: str
    """
    for urlrewrite in _urlrewrites:
        res = urlrewrite._rewrite(url)
        if res:
            return res
    return url

class URLRewrite(object):
    """
    Represents a regular expression based rewrite rule that can be applied to a URL.

    :param :class:`re.RegexObject` pattern: a regular expression for matching URLs
    :param str replacement: the replacement to use for a URL matched by `pattern`
    """

    def __init__(self, pattern, replacement):
        self.pattern = pattern
        self.replacement = replacement

    def _rewrite(self, url):
        match = self.pattern.match(url)
        if match:
            return self.pattern.sub(self.replacement, url)
        else:
            return None

    def __str__(self):
        return self.pattern.pattern + ' -> ' + self.replacement
