# Dynamic imports

The `suite.py` file of a suite typically defines static dependencies to other suites.
Sometimes it is desirable to combine suites that do not statically depend on each other.
This is typically the case when some kind of dependency inversion is at play.
For example a language implemented with the Truffle API usually only statically depends on the `truffle` suite and not on the `compiler` suite.
However the `compiler` suite from graal provides an additional implementation of the truffle runtime that supports compilations.
As a result it might be useful to combine such suites together.
This can be achieved with *dynamic imports*.

Dynamic imports can be specified on the command line as an mx argument:
`--dynamicimports` is a comma-separated list of suites to be dynamically imported (the shorter `--dy` version can also be used).
For suites that are in a subfolder of a repository, their name should be prefixed with a `/`.
For example:

    mx --dy /compiler ...

This requires the `compiler` suite to already be checked-out. For example:

```
- workspace
  |- graal
  |  |- compiler
  |  |  '- mx.compiler
  |  '- truffle
  |     '- mx.truffle
  '- mylang
     '- mx.mylang
```

In such a structure, `mx --dy /compiler ...` could be run from `workspace/mylang`.

Dynamic imports can also be set through the following environment variables:
- `DYNAMIC_IMPORTS`: comma-separated list of suites that are always dynamically imported
- `DEFAULT_DYNAMIC_IMPORTS`: comma-separated list of suites that are dynamically imported only if dynamic imports are not specified (via `--dynamicimports` or `DYNAMIC_IMPORTS`)

## Versioned dynamic imports

In some cases, it is desirable that such dynamically imported suites be automatically located and retrieved at a specific
version if it is not available locally.
This can be done by setting the `dynamic` attribute of a suite import to `True` in the `suite.py` file.
For example:

```python
suite = {
    "imports": {
        "suites": [
            {
                "name": "compiler",
                "subdir": True,
                "dynamic": True,  # makes this import dynamic!
                "version": "48b6b625b43b09f451dac5d82ca87569a1a01c61",
                "urls": [
                    {"url" : "https://github.com/graalvm/graal.git", "kind" : "git"},
                    {"url" : "https://curio.ssw.jku.at/nexus/content/repositories/snapshots", "kind" : "binary"},
                ]
            },
        ]
    }
}
```

With this definition, the `compiler` import would only be activated when using `--dy /compiler`.
If it is not available locally, it is cloned at the specified version using the provided URLs
(cloning the sources by default or binaries if the suite is mentioned in `MX_BINARY_SUITES`).