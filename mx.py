#!/usr/bin/env python
"""
Main entry point for running mx.
"""

import sys
import runpy
from pathlib import Path


def patch_path():
    """
    Prepends the location of the main mx package as well as the `oldnames`
    directory to `sys.path`.

    We prepend because otherwise this file is recognized as the `mx` module and
    not `src/mx`.
    """
    base_dir = Path(__file__).parent.absolute()
    # Include the parent directory of this script in the python path variable,
    # then allow loading of the mx module
    sys.path.insert(0, str(base_dir / 'src'))
    # The following allows the use of existing module names
    sys.path.insert(0, str(base_dir / 'oldnames'))


if __name__ == "__main__":
    patch_path()
    runpy.run_module("mx")
