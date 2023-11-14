#!/usr/bin/env python
"""
Main entry point for running mx.
"""

# Looking for something?
# The mx implementation code has moved to src/mx/_impl
# See `docs/package-structure.md` for more details

import sys
import runpy
from pathlib import Path


def patch_path():
    """
    Prepends the location of the main mx package and the legacy files to
    `sys.path`.

    We prepend, because otherwise this file is recognized as the `mx` module
    and not `src/mx`.
    """
    base_dir = Path(__file__).parent.absolute()
    # Include the sibling directory 'src' of this script in the python search
    # path, this allows loading of the mx module
    sys.path.insert(0, str(base_dir / "src"))


if __name__ == "__main__":
    patch_path()
    runpy.run_module("mx")
