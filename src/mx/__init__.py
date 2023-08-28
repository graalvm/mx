# mx exports its own open symbol which redefines a builtin
from ._impl.mx import *  # pylint: disable=redefined-builtin

# For some reason these private symbols are used externally
from ._impl.mx import (
    _mx_path,
    _opts,
    _replaceResultsVar,
    _addSubprocess,
    _cache_dir,
    _check_global_structures,
    _chunk_files_for_command_line,
    _encode,
    _entries_to_classpath,
    _get_dependency_path,
    _missing_dep_message,
    _mx_home,
    _mx_suite,
    _needsUpdate,
    _removeSubprocess,
)

from mx.legacy.oldnames import redirect as _redirect

# Unlike all the modules in oldnames, this module is used for both the legacy
# access and access in the package system to the `mx` module because there is
# no good way to overload the name.
_redirect(__name__, "mx._impl." + __name__, capture_writes=False)
