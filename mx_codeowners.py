#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2023, Oracle and/or its affiliates. All rights reserved.
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

import argparse
import fnmatch
import logging
import os

import mx

class TomlParsingException(Exception):
    pass

def load_toml_from_fd(fd):
    try:
        import tomllib
        try:
            return tomllib.load(fd)
        except tomllib.TOMLDecodeError:
            raise TomlParsingException()
    except ImportError:
        # Try another library
        pass

    try:
        import toml
        try:
            return toml.load(fd)
        except toml.TomlDecodeError:
            raise TomlParsingException()
    except ImportError:
        # Try another library
        pass

    # No other libraries to try, aborting
    mx.abort("Could not find any suitable TOML library.")


def whitespace_split_(inp):
    if isinstance(inp, str):
        return inp.split()
    else:
        return inp

def is_some_item_in_set(items, the_set):
    for i in items:
        if i in the_set:
            return True
    return False

class FileOwners:
    def __init__(self, src_root):
        self.src = os.path.abspath(src_root)

    def get_path_components(self, filepath):
        res = []
        while filepath != '':
            (dirs, filename) = os.path.split(filepath)
            res.append(filepath)
            filepath = dirs
        return reversed(res)

    def parse_ownership(self, fd, name):
        try:
            tree = load_toml_from_fd(fd)
            logging.debug("Tree is %s", tree)
            for rule in tree.get('rule', []):
                if not 'files' in rule:
                    logging.warning("Ignoring rule %s in %s as it contains no files", rule, name)
                    continue
                if (not 'any' in rule) and (not 'all' in rule):
                    logging.warning("Ignoring rule %s in %s as it contains no owner specification", rule, name)
                    continue

                rule['files'] = whitespace_split_(rule['files'])
                optional_owners = whitespace_split_(rule.get('any', []))
                if optional_owners:
                    for pat in rule['files']:
                        yield pat, optional_owners, "any"
                mandatory_owners = whitespace_split_(rule.get('all', []))
                if mandatory_owners:
                    for pat in rule['files']:
                        yield pat, mandatory_owners, "all"

        except TomlParsingException:
            logging.warning("Ignoring invalid input from %s", name)

    def parse_ownership_from_files(self, files):
        for fo in files:
            try:
                full_path = os.path.join(self.src, fo)
                with open(full_path, 'rb') as f:
                    for i in self.parse_ownership(f, full_path):
                        yield i
            except IOError:
                pass

    def get_owners_of(self, filepath):
        components = ['.'] + list(self.get_path_components(filepath))
        filename = os.path.split(filepath)[1]
        owners_files = [
            os.path.join(i, 'OWNERS.toml')
            for i in components[:-1]
        ]
        result = {}
        ownership = self.parse_ownership_from_files(owners_files)
        for pat, owners, modifiers in ownership:
            if fnmatch.fnmatch(filename, pat):
                if "all" in modifiers:
                    result["all"] = sorted(owners)
                if "any" in modifiers:
                    result["any"] = sorted(owners)
        return result

def summarize_owners(all_owners):
    must_review = set()
    anyof_reviewers = []

    for owners in all_owners:
        for owner in owners.get('all', []):
            must_review.add(owner)

    for owners in all_owners:
        if owners.get('any', []):
            # One reviewer is already present? Skip this completely
            if not is_some_item_in_set(owners['any'], must_review):
                anyof_reviewers.append(owners['any'])

    return {
        "all": sorted(must_review),
        "any": list(set(map(tuple, anyof_reviewers))),
    }


@mx.command('mx', 'codeowners')
def codeowners(args):
    """Code owners check"""
    parser = argparse.ArgumentParser(prog='mx codeowners')
    parser.add_argument('files', metavar='FILENAME', nargs='*', help='Filenames to list owners of')
    args = parser.parse_args(args)

    owners = FileOwners('.')
    file_owners = [owners.get_owners_of(f) for f in args.files]
    reviewers = summarize_owners(file_owners)

    if reviewers['all']:
        print("Mandatory reviewers (all of these must review):")
        for i in reviewers['all']:
            print(" o", i)
    if reviewers['any']:
        print("Any-of reviewers (at least one from each line):")
        for i in reviewers['any']:
            print(" o", ' or '.join(i))

