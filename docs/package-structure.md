# Mx Package Structure

Starting with version 7.0.0, mx is undergoing major internal reworkings to convert it into a python package with a
proper API instead of a loose set of individual python modules.

To achieve this, a new directory structure was introduced for the python source code:
```
├── mx     # Bash launcher
├── mx.cmd # Batch launcher
├── mx.py  # Python launcher
├── src
│  ├── mx
│  │  ├── __init__.py
│  │  ├── __main__.py
│  │  ├── _impl
│  │  │  ├── __init__.py
│  │  │  ├── mx.py
│  │  │  ├── mx_benchmark.py
│  │  │  ├── mx_benchplot.py
│  │  │  ├── mx_bisect.py
│  │  │  ⋮
│  ├── mx_benchmark.py
│  ├── mx_bisect.py
⋮  ⋮
```

The `src` directory is now part of the python search path (before it was the repository root directory).
In there, the `mx` directory contains the `mx` python package and all the `mx*.py` files in the repository root now live
in the `_impl` directory.

## Goals

The main goals of this restructuring are:

* Modernize the codebase by using the de-factor standard python package structure.
* Allow for refactoring, while keeping the public API intact (through the use of proxies)
  * This means we can take our time to restructure mx and define a new public API
* Limit the public API
    * Shrink current API to what's used externally
    * Any new code is implicitly private
    * New symbols (functions, classes) have to be explicitly exported.

## Proxy Modules

To not break existing mx suite code, all the original mx modules (`mx` and the various `mx_` modules) are still
available and are still needed to access any mx functionality.
This is done by having proxy modules in the `src` directory that import (and thus re-export) all public symbols of the
original modules from `mx._impl`.

**Note:** Not all `mx_*` files have a corresponding proxy module. This was done to cut down on the size of API and to
not unnecessarily expose functionality that is not currently and should not be used externally.

The proxy modules expose all public symbol (not prefixed with an underscore) defined in the original module.
This is done by the original module listing those symbols in its `__all__` variable and the proxy simply doing a
wildcard import.
In addition, some private symbols (prefixed with an underscore) are also exposed (explicitly imported by the proxy)
because they are already used in existing code.

## Using The Package In Your Code

For now, keep importing and using the `mx_*` modules, as before.
Imports of the `mx` module are essentially importing the `mx` package because they have the same name, so the `mx`
package (in `mx/__init__.py`) acts as the proxy for `_impl/mx.py`.

For the time being, the purpose of the mx package is to allow for larger
refactoring, while not breaking existing user code.
Because of that, the mx package will not immediately expose new files and symbols.
Instead, code is hidden in subpackages and submodules prefixed with an underscore (e.g. `_impl`), which may change
without notice, and you should never import.

## Writing New Code

This section aims to provide some guidance for how and where to make changes and add new code in the mx source code.

At the moment, we want to refrain from making any module publicly accessible through the `mx` package; suite code should
still access mx functionality exclusively through the proxy files.

To this end, consider the following when writing code for mx:
* Implementation happens in `src/mx`
  * The original mx source files are now in `src/mx/_impl`
  * **Do not write implementations in the proxy files in `src`!**
* New code should be private by default
  * Make new files private (either they or one of their parent directories should be prefixed with an underscore)

**Note:** None of this prevents users from accessing "private" code. But doing so requires accessing symbols prefixed
with an underscore, which are by convention private.

### Adding New Files

Because new files are now submodules of the `mx` package, they no longer have to be prefixed with `mx_`.

It is recommended to place any new files into `src/mx/_impl` or one of its subdirectories.

### Adding New Symbols in Existing Files

If you don't want/need the symbols to be accessible from the outside, you need to make sure the symbol is not accessible.
Ideally, your code is in a file that is already private (either it or one of its parent directories are prefixed with an
underscore).
In that case, there is nothing else that you need to do.
If the code is in a public file, prefix the symbols with an underscore.

If the new symbols should be accessible from the outside, you need to set up appropriate "exports" through one of the
proxy files.
In the `_impl/mx*.py` files, simply add the symbol name to `__all__` and the name is exposed through the corresponding
proxy.
If the symbol is in another file, please reach out to the mx team for how to best make it available.
