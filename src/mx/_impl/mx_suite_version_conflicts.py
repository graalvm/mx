#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2026, Oracle and/or its affiliates. All rights reserved.
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

"""Helpers for detecting and resolving suite version conflicts during discovery."""

from collections import OrderedDict, namedtuple


def _mx_module():
    """Returns the lazily imported `mx` implementation module."""
    from . import mx as _mx
    return _mx


PendingVersionConflict = namedtuple(
    'PendingVersionConflict',
    [
        'suite_import_name',
        'importing_suite_name',
        'discovered_suite_name',
        'collocated_suite_name',
        'other_importer_name',
        'allow_repo_update',
    ],
)


def resolve_suite_version_conflict(suite_name, existing_suite, existing_version, existing_importer, other_import, other_importing_suite, dry_run=False):
    """Returns the version to update to for a suite import mismatch, or `None` if no update should occur."""
    _mx = _mx_module()
    conflict_resolution = _mx._opts.version_conflict_resolution
    if other_import.dynamicImport and (not existing_suite or not existing_suite.dynamicallyImported) and conflict_resolution != 'latest_all':
        return None
    if not other_import.version:
        return None
    if conflict_resolution == 'suite':
        if other_importing_suite:
            conflict_resolution = other_importing_suite.versionConflictResolution
        elif not dry_run:
            _mx.warn("Conflict resolution was set to 'suite' but importing suite is not available")

    if conflict_resolution == 'ignore':
        if not dry_run:
            _mx.warn(
                f"mismatched import versions on '{suite_name}' in '{other_importing_suite.name}' ({other_import.version}) "
                f"and '{existing_importer.name if existing_importer else '?'}' ({existing_version})"
            )
        return None
    if conflict_resolution in ('latest', 'latest_all'):
        if not existing_suite or not existing_suite.vc:
            return None
        if existing_suite.vc.kind != other_import.kind:
            return None
        if not isinstance(existing_suite, _mx.SourceSuite):
            if dry_run:
                return 'ERROR'
            _mx.abort(
                f"mismatched import versions on '{suite_name}' in '{other_importing_suite.name}' and "
                f"'{existing_importer.name if existing_importer else '?'}', 'latest' conflict resolution is only supported for source suites"
            )
        if not existing_suite.vc.exists(existing_suite.vc_dir, rev=other_import.version):
            return other_import.version
        resolved = existing_suite.vc.latest(existing_suite.vc_dir, other_import.version, existing_suite.vc.parent(existing_suite.vc_dir))
        if existing_suite.vc.parent(existing_suite.vc_dir) == resolved:
            return None
        return resolved
    if conflict_resolution == 'none':
        if dry_run:
            return 'ERROR'
        _mx.abort(
            f"mismatched import versions on '{suite_name}' in '{other_importing_suite.name}' ({other_import.version}) "
            f"and '{existing_importer.name if existing_importer else '?'}' ({existing_version})"
        )
    return None


class SuiteVersionConflictTracker:
    """Tracks cross-repository suite version conflicts during discovery traversal."""

    def __init__(
        self,
        primary,
        discovered,
        ancestor_names,
        importer_names,
        vc_dir_to_suite_names,
        versions_from,
        update_existing,
        was_cloned_or_updated_during_discovery,
        update_repo,
        log_discovery,
        resolve_suite_version_conflict,
    ):
        """Initializes conflict tracking around the mutable discovery state owned by `mx.py`."""
        self._primary = primary
        self._discovered = discovered
        self._ancestor_names = ancestor_names
        self._importer_names = importer_names
        self._vc_dir_to_suite_names = vc_dir_to_suite_names
        self._versions_from = versions_from
        self._update_existing = update_existing
        self._was_cloned_or_updated_during_discovery = was_cloned_or_updated_during_discovery
        self._update_repo = update_repo
        self._log_discovery = log_discovery
        self._resolve_suite_version_conflict = resolve_suite_version_conflict
        self._pending_version_conflicts = []
        self._pending_version_conflict_keys = set()

    def _is_imported_by_primary(self, discovered_suite):
        """Checks whether `discovered_suite` is already reachable from the primary suite."""
        for suite_name in self._vc_dir_to_suite_names[discovered_suite.vc_dir]:
            if self._primary.name == suite_name:
                return True
            if self._primary.name in self._importer_names[suite_name]:
                assert self._primary.get_import(suite_name), self._primary.name + ' ' + suite_name
                if not self._primary.get_import(suite_name).dynamicImport:
                    return True
        return False

    def _should_ignore_conflict_edge(self, imported_suite, importer_name):
        """Applies `version_from` precedence rules to a candidate conflicting edge."""
        vc_suites = self._vc_dir_to_suite_names[imported_suite.vc_dir]
        for suite_with_from, (from_suite, _) in self._versions_from.items():
            if suite_with_from not in vc_suites:
                continue
            suite_with_from_and_ancestors = {suite_with_from}
            suite_with_from_and_ancestors |= vc_suites & self._ancestor_names[suite_with_from]
            if imported_suite.name in suite_with_from_and_ancestors:
                if importer_name != from_suite:
                    if imported_suite.name == suite_with_from:
                        self._log_discovery(
                            f"Ignoring {importer_name} -> {imported_suite.name} because of "
                            f"version_from({suite_with_from}) = {from_suite} (fast-path)"
                        )
                        return True
                    if from_suite not in self._ancestor_names:
                        self._log_discovery(
                            f"Temporarily ignoring {importer_name} -> {imported_suite.name} because of "
                            f"version_from({suite_with_from}) = {from_suite} ({from_suite} is not yet discovered)"
                        )
                        return True
                    vc_from_suite_and_ancestors = {from_suite}
                    vc_from_suite_and_ancestors |= vc_suites & self._ancestor_names[from_suite]
                    if imported_suite.name not in vc_from_suite_and_ancestors:
                        self._log_discovery(
                            f"Ignoring {importer_name} -> {imported_suite.name} because of "
                            f"version_from({suite_with_from}) = {from_suite}"
                        )
                        return True
        return False

    def _warn_conflicting_versions(self, suite_import, importing_suite, collocated_suite_name, other_importer_name, other_importers_import):
        """Emits the existing version-conflict warning format for a recorded mismatch."""
        _mx = _mx_module()
        if suite_import.name == collocated_suite_name:
            _mx.warn(
                f"{importing_suite.name} and {other_importer_name} import different versions of "
                f"{collocated_suite_name}: {suite_import.version} vs. {other_importers_import.version}"
            )
        else:
            _mx.warn(
                f"{importing_suite.name} and {other_importer_name} import different versions of "
                f"{collocated_suite_name} (collocated with {suite_import.name}): "
                f"{suite_import.version} vs. {other_importers_import.version}"
            )

    def _effective_conflict_resolution(self, importing_suite):
        """Returns the conflict-resolution mode that applies to `importing_suite`."""
        _mx = _mx_module()
        conflict_resolution = getattr(_mx._opts, 'version_conflict_resolution', 'suite')
        if conflict_resolution == 'suite':
            conflict_resolution = importing_suite.versionConflictResolution
        return conflict_resolution

    def _resolution_cache_key(self, discovered_suite, other_importers_import, suite_import, importing_suite):
        """Builds a cache key for Git-backed conflict resolution checks when they are reusable."""
        conflict_resolution = self._effective_conflict_resolution(importing_suite)
        if conflict_resolution in ('latest', 'latest_all'):
            return (
                discovered_suite.vc_dir,
                other_importers_import.version,
                suite_import.version,
                bool(suite_import.dynamicImport),
                conflict_resolution,
            )
        return None

    def _get_cached_resolution(self, resolution_cache, cache_key, discovered_suite, other_importers_import, other_importer, suite_import, importing_suite, dry_run):
        """Computes or reuses a cached conflict-resolution result."""
        if cache_key is not None and cache_key in resolution_cache:
            return resolution_cache[cache_key]
        resolution = self._resolve_suite_version_conflict(
            discovered_suite.name,
            discovered_suite,
            other_importers_import.version,
            other_importer,
            suite_import,
            importing_suite,
            dry_run=dry_run,
        )
        if cache_key is not None:
            resolution_cache[cache_key] = resolution
        return resolution

    def check_and_handle_version_conflict(self, suite_import, importing_suite, discovered_suite):
        """Checks whether a re-reached suite import conflicts with prior importers and handles it."""
        if importing_suite.vc_dir == discovered_suite.vc_dir:
            return True
        if self._is_imported_by_primary(discovered_suite):
            self._log_discovery(f"Re-reached {suite_import.name} from {importing_suite.name}, nothing to do (imported by primary)")
            return True
        if self._should_ignore_conflict_edge(discovered_suite, importing_suite.name):
            return True
        for collocated_suite_name in self._vc_dir_to_suite_names[discovered_suite.vc_dir]:
            for other_importer_name in self._importer_names[collocated_suite_name]:
                if other_importer_name == importing_suite.name:
                    continue
                if self._should_ignore_conflict_edge(discovered_suite, other_importer_name):
                    continue
                other_importer = self._discovered[other_importer_name]
                other_importers_import = other_importer.get_import(collocated_suite_name)
                if other_importers_import.version and suite_import.version and other_importers_import.version != suite_import.version:
                    if suite_import.name == collocated_suite_name:
                        self._log_discovery(
                            f"Re-reached {collocated_suite_name} from {importing_suite.name} with conflicting version compared to {other_importer_name}"
                        )
                    else:
                        self._log_discovery(
                            f"Re-reached {collocated_suite_name} (collocated with {suite_import.name}) from "
                            f"{importing_suite.name} with conflicting version compared to {other_importer_name}"
                        )
                    allow_repo_update = self._update_existing or self._was_cloned_or_updated_during_discovery(discovered_suite)
                    if self._update_existing:
                        resolved = self._resolve_suite_version_conflict(
                            discovered_suite.name,
                            discovered_suite,
                            other_importers_import.version,
                            other_importer,
                            suite_import,
                            importing_suite,
                        )
                        if resolved and self._update_repo(discovered_suite, resolved, forget=True):
                            return False
                    else:
                        conflict = PendingVersionConflict(
                            suite_import.name,
                            importing_suite.name,
                            discovered_suite.name,
                            collocated_suite_name,
                            other_importer_name,
                            allow_repo_update,
                        )
                        if conflict not in self._pending_version_conflict_keys:
                            self._pending_version_conflict_keys.add(conflict)
                            self._pending_version_conflicts.append(conflict)
                else:
                    if suite_import.name == collocated_suite_name:
                        self._log_discovery(
                            f"Re-reached {collocated_suite_name} from {importing_suite.name} with same version as {other_importer_name}"
                        )
                    else:
                        self._log_discovery(
                            f"Re-reached {collocated_suite_name} (collocated with {suite_import.name}) from "
                            f"{importing_suite.name} with same version as {other_importer_name}"
                        )
        return True

    def process_pending_version_conflicts(self):
        """Resolves all deferred cross-repository version conflicts after discovery traversal finishes."""
        repos_to_update = OrderedDict()
        resolution_cache = {}
        for conflict in self._pending_version_conflicts:
            discovered_suite = self._discovered.get(conflict.discovered_suite_name)
            importing_suite = self._discovered.get(conflict.importing_suite_name)
            other_importer = self._discovered.get(conflict.other_importer_name)
            if discovered_suite is None or importing_suite is None or other_importer is None:
                continue
            if discovered_suite.vc_dir in repos_to_update:
                continue
            suite_import = importing_suite.get_import(conflict.suite_import_name)
            other_importers_import = other_importer.get_import(conflict.collocated_suite_name)
            if suite_import is None or other_importers_import is None:
                continue
            if not other_importers_import.version or not suite_import.version or other_importers_import.version == suite_import.version:
                continue
            cache_key = self._resolution_cache_key(discovered_suite, other_importers_import, suite_import, importing_suite)
            if conflict.allow_repo_update:
                resolved = self._get_cached_resolution(
                    resolution_cache,
                    cache_key,
                    discovered_suite,
                    other_importers_import,
                    other_importer,
                    suite_import,
                    importing_suite,
                    dry_run=False,
                )
                if resolved:
                    repos_to_update[discovered_suite.vc_dir] = (discovered_suite, resolved)
            else:
                resolution = self._get_cached_resolution(
                    resolution_cache,
                    cache_key,
                    discovered_suite,
                    other_importers_import,
                    other_importer,
                    suite_import,
                    importing_suite,
                    dry_run=True,
                )
                if resolution is not None:
                    self._warn_conflicting_versions(
                        suite_import,
                        importing_suite,
                        conflict.collocated_suite_name,
                        conflict.other_importer_name,
                        other_importers_import,
                    )
        return repos_to_update
