#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2019, Oracle and/or its affiliates. All rights reserved.
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
import itertools
from . import mx

class JavaCompliance(mx.Comparable):
    """
    Represents one or more major Java versions.
    Example valid compliance specifications and the JDKs they match:
        "8+"       - jdk8, jdk9, jdk10, ...
        "1.8"      - jdk8
        "8..12"    - jdk8, jdk9, jdk10, jdk11, jdk12
        "8,13+"    - jdk8, jdk13, jdk14, ...
        "8..9,13+" - jdk8, jdk9, jdk13, jdk14, ...
        "8,11,13+" - jdk8, jdk11, jdk13, jdk14, ...
    There can be multiple parts to a version string specifying a non-contiguous range.
    Part N of a multi-part version string must have a strict upper bound (i.e. cannot end with "+")
    and its upper bound must be less than the lower bound of part N+1. Only major versions less
    than 10 can have an optional "1." prefix. The lowest recognized major version is 2.
    """

    # Examples: "8", "13"
    _int_re = re.compile(r'(\d+)$')

    # Example: "1.8..13"
    _version_range_re = re.compile(r'(1\.)?(\d+)\.\.(1\.)?(\d+)$')

    # Example: "13+"
    _open_range_re = re.compile(r'(1\.)?(\d+)\+$')

    # Examples: "1.8", "13"
    _singleton_range_re = re.compile(r'(1\.)?(\d+)$')

    @staticmethod
    def _error_prefix(spec, part_index, part):
        return f'JavaCompliance("{spec}"): Part {part_index} ("{part}")'

    class _Range(mx.Comparable):
        """
        Represents a contiguous range of version values.
        """
        def __init__(self, low, high):
            self._low = low
            self._high = high

        def __repr__(self):
            if self._low == self._high:
                return str(self._low)
            if self._high is None:
                return str(self._low) + '+'
            return f'{self._low}..{self._high}'

        def __cmp__(self, other):
            r = mx.compare(self._low, other._low)
            if r != 0:
                return r
            if self._high is None:
                if other._high is None:
                    return 0
                # self has no high bound, other does
                return 1
            elif other._high is None:
                # other has no high bound, self does
                return -1
            return mx.compare(self._high, other._high)

        def __hash__(self):
            return self._low ** (self._high or 1)

        def __contains__(self, other):
            if isinstance(other, int):
                value = int(other)
                if value < self._low:
                    return False
                if self._high is None:
                    return True
                return value <= self._high
            elif isinstance(other, JavaCompliance._Range):
                if other._high is None:
                    # open range is considered not match, e.g. '1.8+' not in '1.8..11'
                    return False
                if other._low < self._low:
                    return False
                if self._high is None:
                    return True
                return other._high <= self._high
            return False

        def _values(self, stop=None):
            """
            Returns an iterator over all the Java versions in this range stopping at `stop - 1`.
            If `stop` is None and this is an open ended range, this will generate an infinite sequence.
            """
            if self._high is None:
                if stop is None:
                    return itertools.count(self._low)
                return iter(range(self._low, stop))
            return iter(range(self._low, self._high + 1))

    def __init__(self, spec, parse_error=None, context=None):
        """
        Creates a JavaCompliance based on `spec`.

        :param spec: an int specifying a Java version or a str specifying one or more Java versions
        :param parse_error: if not None, then it must be a callable that will be called if
                      `spec` is not a valid compliance specification. It will be called with
                      an error message and it must raise an exception (i.e. it cannot return
                      normally). If None, then `mx.abort` is called.
        :param context: the context argument if `mx.abort` is called
        """
        if parse_error is None:
            parse_error = lambda m: mx.abort(m, context=context)

        def _error(part, index, msg):
            parse_error(f'JavaCompliance("{spec}"): Part {index} ("{part}") {msg}')

        def _check_value(value, value_desc='value'):
            value = int(value)
            if value < 2:
                _error(value, 0, f'has unsupported {value_desc} since it is less than 2')
            return value

        int_spec = spec if isinstance(spec, int) else int(spec) if isinstance(spec, str) and JavaCompliance._int_re.match(spec) else None
        if int_spec is not None:
            value = _check_value(spec)
            self._parts = (JavaCompliance._Range(value, value),)
            return

        if not isinstance(spec, str):
            spec = str(spec)
        parts = spec.split(',')

        def _parse_part(part, index):
            def _part_error(msg):
                _error(part, index, msg)

            def _check_part_value(prefix, value, value_desc):
                value = _check_value(value, value_desc)
                if prefix and value > 9:
                    _part_error(f'cannot have "1." prefix on {value_desc} since {value_desc} > 9')
                return value

            m = JavaCompliance._version_range_re.match(part)
            if m:
                low = _check_part_value(m.group(1), m.group(2), 'low bound')
                high = _check_part_value(m.group(3), m.group(4), 'high bound')
                if low >= high:
                    _part_error(f'has low bound ({low}) greater or equal to high bound ({high})')
                return JavaCompliance._Range(low, high)
            m = JavaCompliance._open_range_re.match(part)
            if m:
                low = _check_part_value(m.group(1), m.group(2), 'bound')
                return JavaCompliance._Range(low, None)
            m = JavaCompliance._singleton_range_re.match(part)
            if m:
                low = _check_part_value(m.group(1), m.group(2), 'bound')
                return JavaCompliance._Range(low, low)
            _part_error('is not a recognized version range')

        self._parts = tuple((_parse_part(parts[i], i) for i in range(len(parts))))
        if len(self._parts) > 1:
            for i in range(1, len(self._parts)):
                first = self._parts[i - 1]
                second = self._parts[i]
                if first._high is None:
                    _error(first, i - 1, 'must have a high bound')
                if second._low <= first._high:
                    _error(first, i - 1, f'must have a high bound ({first._high}) less than the low bound ({second._low}) of part {i} ("{second}")')

    @property
    def value(self):
        return self._parts[0]._low

    def __str__(self):
        if self.value >= 9:
            return str(self.value)
        return '1.' + str(self.value)

    def __repr__(self):
        return ','.join((repr(b) for b in self._parts))

    def _high_bound(self):
        return self._parts[-1]._high

    def __cmp__(self, other):
        if isinstance(other, str):
            other = JavaCompliance(other)
        return mx.compare(self._parts, other._parts)

    def __contains__(self, other):
        if isinstance(other, (int, str)):
            other = JavaCompliance(other)
        return all(any((other_part in self_part) for self_part in self._parts) for other_part in other._parts)

    def __hash__(self):
        return hash(self._parts)

    def _is_exact_bound(self):
        return self.value == self._high_bound()

    def _exact_match(self, version):
        assert isinstance(version, mx.VersionSpec)
        if len(version.parts) > 0:
            if len(version.parts) > 1 and version.parts[0] == 1:
                # First part is a '1',  e.g. '1.8.0'.
                value = version.parts[1]
            else:
                # No preceding '1', e.g. '9-ea'. Used for Java 9 early access releases.
                value = version.parts[0]
            return any((value in b for b in self._parts))
        return False

    def as_version_check(self):
        if self._is_exact_bound():
            versionDesc = str(self)
        elif self._high_bound() is None:
            versionDesc = '>=' + str(self)
        else:
            versionDesc = 'in ' + repr(self)
        versionCheck = self._exact_match
        return (versionCheck, versionDesc)

    def _values(self, stop=None):
        """
        Returns an iterator over all the Java versions that match this compliance object
        up to but not including `stop`. If `stop` is None and this is an open ended
        compliance, this will generate an infinite sequence.
        """
        return itertools.chain(*(p._values(stop=stop) for p in self._parts))

    def highest_specified_value(self):
        """
        Gets the highest explicitly specified value of this Java compliance.
        Examples:
           8+        --> 8
           8,13+     --> 13
           8,11,13+  --> 13
           8..11,13+ --> 13
        """
        highest_part = self._parts[-1]
        return highest_part._high or highest_part._low

def _test():
    """
    Mx suite specific tests.
    """

    from collections import namedtuple

    # JavaCompliance tests
    good_specs = [
        (2, True),
        (1.2, True),
        (11, True),
        (200, True),
        ('2', True),
        ('1.2', True),
        ('1.8', True),
        ('1.5+', False),
        ('2..4', False),
        ('1.8..9', False),
        ('2..3,4+', False),
        ('2..3,4,7+', False),
        ('2..3,4..5,7+', False),
        ('2..3,4..5,7,8,9,10,15..18,120', False),
    ]
    bad_specs = [
        1,
        '1',
        '1.1',
        '1.10',
        '1.8..1.10',
        '1.10+',
        '2..1',
        '2..2',
        '1,,3',
        '1..3+',
        '1+,4..5',
        '13+ignored',
        '1..3,7..5',
        '4,7,1..3,',
        '4..5,1..3',
    ]
    range_case = namedtuple('range_case', ['spec', 'range_spec', 'should_match'])
    range_specs = [
        range_case('1.8', '1.8', True),
        range_case('11', '11', True),
        range_case('17', '17', True),
        range_case('1.8', '1.7', False),
        range_case('1.8', '11', False),
        range_case('17', '1.8', False),
        range_case('1.8', '11..17', False),
        range_case('11', '11..17', True),
        range_case('15', '11..17', True),
        range_case('17', '11..17', True),
        range_case('19', '11..17', False),
        range_case('11..17', '11..17', True),
        range_case('13..14', '11..17', True),
        range_case('11..19', '11..17', False),
        range_case('16', '11..15,17', False),
        range_case('11..12,14..15', '11..15,17', True),
        range_case('11,12,13,14,15,16,17', '11..17', True),
        range_case('11+', '11..17', False),
    ]
    for spec, exact in good_specs:
        p = mx.JavaCompliance(spec)
        assert p._is_exact_bound() is exact, p

        # Just ensure these methods execute without exception
        p.as_version_check()
        p._values(stop=20)
        hash(p)

        if mx.get_opts().verbose:
            if isinstance(spec, str):
                spec = '"' + spec + '"'
            mx.log(f'{spec}: str="{str(p)}", repr="{repr(p)}", hash={hash(p)}')
    for spec in bad_specs:
        class SpecError(Exception):
            pass
        def _parse_error(msg):
            if mx.get_opts().verbose:
                mx.log('saw expected SpecError: ' + msg)
            raise SpecError(msg)
        try:
            mx.JavaCompliance(spec, parse_error=_parse_error)
            mx.abort(f'expected SpecError while parsing "{spec}"')
        except SpecError:
            pass
    for spec, range_spec, should_match in range_specs:
        match = spec in mx.JavaCompliance(range_spec)
        assert match == should_match, f'"{spec}" in "{range_spec}" should returns {should_match}'
