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
import json
import mx

_urlrewrites = []  # list of URLRewrite objects

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
    :param function onError: called with error message argument if urlrewrite is badly formed
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
    for pattern, attrs in urlrewrite.items():
        replacement = attrs.pop('replacement', None)
        sha1 = attrs.pop('sha1', None)
        if replacement is None:
            raise Exception('URL rewrite for pattern "' + pattern + '" is missing "replacement" entry')
        if len(attrs) != 0:
            raise Exception('Unsupported attributes found for URL rewrite "' + pattern + '": ' + str(attrs))
        try:
            pattern = re.compile(pattern)
        except Exception as e: # pylint: disable=broad-except
            onError('Error parsing URL rewrite pattern "' + pattern + '": ' + str(e))
        urlrewrite = URLRewrite(pattern, replacement, sha1)
        mx.logvv("Registering url rewrite: " + str(urlrewrite))
        _urlrewrites.append(urlrewrite)

def register_urlrewrites_from_env(name):
    """
    Appends rewrite rules denoted by the environment variable named by `name`.
    If the environment variable has a non-empty value it must either be an JSON
    object describing a single rewrite rule, a JSON array describing a list of
    rewrite rules or a file containing one of these JSON values.

    :param str name: name of an environment variable denoting URL rewrite rules
    """
    value = mx.get_env(name, None)
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

def _geturlrewrite(url):
    """
    Finds the first registered URL rewrite rule that matches `url` and returns it.

    :param str url: a URL to match against the registered rewrite rules
    :return: `URLRewrite` rule that matches `url` or `None`
    """
    jar_url = mx._JarURL.parse(url)
    if jar_url:
        url = jar_url.base_url

    for urlrewrite in _urlrewrites:
        res = urlrewrite._rewrite(url)
        if res:
            return urlrewrite

    return None

def _applyurlrewrite(urlrewrite, url):
    """
    Applies an URL rewrite rule to `url`.
    Handles JAR URL references.
    """
    if urlrewrite:
        # Rewrite rule exists, use it.
        jar_url = mx._JarURL.parse(url)
        if jar_url:
            jar_url.base_url = urlrewrite._rewrite(jar_url.base_url)
            res = str(jar_url)
        else:
            res = urlrewrite._rewrite(url)
        mx.logvv("Rewrote '{}' to '{}'".format(url, res))
        return res
    else:
        # Rewrite rule does not exist.
        return url

def rewriteurl(url):
    """
    Finds the first registered URL rewrite rule that matches `url` and returns the replacement `url`
    provided by the rule.

    :param str url: a URL to match against the registered rewrite rules
    :return: the value of `url` rewritten according to the first matching rewrite URL or unmodified if no rules match
    :rtype: str
    """
    urlrewrite = _geturlrewrite(url)
    return _applyurlrewrite(urlrewrite, url)

def _rewrite_urls_and_sha1(urls, sha1):
    """
    Rewrites URL list and SHA1 as defined by rewriting rules.

    :param urls: an URL list to rewrite
    :param sha1: an SHA1 to rewrite
    :return: a tuple of rewritten URL list and rewritten SHA1
    """
    result = []
    for url in urls:
        urlrewrite = _geturlrewrite(url)
        result.append(_applyurlrewrite(urlrewrite, url))
        if urlrewrite and urlrewrite.sha1:
            sha1 = urlrewrite.sha1
    return (result, sha1)

def urlrewrite_cli(args):
    """rewrites the given URL using MX_URLREWRITES"""
    assert len(args) == 1
    print(rewriteurl(args[0]))

class URLRewrite(object):
    """
    Represents a regular expression based rewrite rule that can be applied to a URL.

    :param :class:`re.RegexObject` pattern: a regular expression for matching URLs
    :param replacement: the replacement URL to use for a URL matched by `pattern`
    :param sha1: the replacement SHA1 to use for a URL matched by `pattern`
    """

    def __init__(self, pattern, replacement, sha1):
        self.pattern = pattern
        # Make sure to use str rather than unicode.
        # Some code paths elsewhere depend on this.
        self.replacement = str(replacement)
        self.sha1 = str(sha1) if sha1 else None

    def _rewrite(self, url):
        match = self.pattern.match(url)
        if match:
            return self.pattern.sub(self.replacement, url)
        else:
            return None

    def __str__(self):
        return self.pattern.pattern + ' -> ' + self.replacement
