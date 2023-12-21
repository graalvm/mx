# Multi-target native projects

Mx supports cross-building native projects for targets different than the host.

Every project that should be bulit for multiple targets has to specify which targets it can be built
for. Additionally, a toolchain has to be provided for each target. Mx then automatically matches the
toolchains to the projects, to build all multi-target projects for all selected targets.

## Target specification

A "target" is a combination of operating system, CPU architecture, standard C library and code
generation variant. A target is specified as a `dict` with the following keys:

* `os`: The operating system.
  Defaults to the host OS.
* `arch`: The CPU architecture.
  Defaults to the host CPU architecture.
* `libc`: The standard C library.
  If the target OS is "linux", possible values are "glibc" and "musl", and the default is the host
  libc. If the host is not Linux (i.e. we're cross-compiling to Linux) then it defaults to "glibc".
  For non-Linux targets, the default and only possible value is "default".
* `variant`: The code generation variant.
  This can be used to express things like different optimization levels, debug builds,
  instrumentations and so on.

## Toolchain specification

In order to cross-build to a target different from the host, a toolchain has to be provided.

A "toolchain" is an mx distribution (i.e. an entry in the `distributions` entry in `suite.py`) with
a `native_toolchain` property, containing a `dict` with the following keys:

* `kind`: What build system this toolchain is for (see below).
* `target`: A dict with the specification of the target this toolchain is producing code for.
* `compiler`: A name for the compiler this toolchain is using.
  This can be used if there are different compilers capable of producing code for the same target,
  e.g. LLVM and GCC. This attribute is optional, it defaults to the value "host", which means the
  toolchain is not providing its own compiler but using the one that's installed on the host.

### Toolchain kinds

Mx supports building native projects with `ninja` or `cmake`. Currently mx supports only `ninja` for
multi-target projects, so only a single toolchain kind is supported:

* `ninja`
  A ninja toolchain is a distribution with a file `toolchain.ninja` in its root.
  That file is included in the generated `build.ninja` file.
  Mx provides the `DEFAULT_NINJA_TOOLCHAIN` toolchain for the host target.

More toolchain kinds can be provided by custom subclasses of the `MultitargetProject` class, by
overriding the `toochain_kind` property and providing a proper multi-target aware implementation of
the abstract methods `_archivable_results` and `_build_task`.

## Multi-target native projects

A "multi-target" project is a project that can be built for multiple targets. To make a project
multi-target, specify the `multitarget` property as a dict or list of dicts. The attributes are the
same as for the target specification, except that the values are lists of strings:

* `os`: Which operating systems this project can be built for.
  Defaults to only the host OS.
* `arch`: Which CPU architectures this project can be built for.
  Defaults to only the host architecture.
* `libc`: Which standard C libraries this project can be built for.
  Defaults to only the default libc for each OS.
* `variant`: Which code generation variants this project can be built for.
  Default to all.
* `compiler`: Which compilers can be used for building this project, in order of preference.
  Each target (i.e. os/arch/libc/variant combination) will be built with the first compiler from
  this list that supports this target.
  Defaults to `["host", "*"]`, i.e. any compiler, but prefer the compiler from the host.

All attributes support the special value "*" to mean "all".

Specifying multiple values for multiple attributes means all combinations are supported. For better
control over what exact combinations are supported, a list of dicts can be provided instead of a
single dict.

For example, consider this multitarget specification:
```
"multitarget": [
  {"os": ["linux", "darwin"], "arch": ["amd64", "aarch64"], "compiler": ["llvm", "host"]},
  {"os": ["windows"], "arch": ["amd64"]},
}
```

This means this project can be built to target all combinations of linux/darwin on amd64/aarch64,
i.e. linux/amd64, linux/aarch64, darwin/amd64 and darwin/aarch64. On all these combinations, we
prefer building with the "llvm" compiler, but also support building with the "host" compiler.
Additionally, the project can be built for windows/amd64, but there we prefer the "host" compiler.

## Target selection

By default, mx only builds for the default target of the host system.

Multi-target building can be enabled by specifying the `--multitarget <target>` commandline option,
or by setting the `MULTITARGET` environment variable to a comma-separated list of targets.

In this option, a target is specified as an `<os>-<arch>-<libc>[-<variant>]` tuple, where each
component can also be `*` to indicate "all". `<os>`, `<arch>` and `<libc>` can be `default` to
indicate the default for the host.

The default behavior can be overwritten for each individual multi-target project by specifying the
following attributes:

* `default_targets`: list of str
  The default targets to build for this project if the `--multitarget` argument is not specified.
* `always_build_targets`: list of str
  The targets that should always be built, regardless of the `--multitarget` argument.
