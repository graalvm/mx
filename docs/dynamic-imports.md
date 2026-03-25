# Dynamic imports

The `suite.py` file of a suite typically defines static dependencies to other suites.
Sometimes it is desirable to combine suites that do not statically depend on each other.
This is typically the case when some kind of dependency inversion is at play.
For example a language implemented with the Truffle API usually only statically depends on the `truffle` suite and not on the `compiler` suite.
However the `compiler` suite from graal provides an additional implementation of the truffle runtime that supports compilations.
As a result it might be useful to combine such suites together.
This can be achieved with *dynamic imports*.

## When to use dynamic imports

Dynamic imports are for optional composition between suites.
They are a good fit when a suite can use another suite if it is present, but does not require it for its normal build.
Typical cases are:

* dependency inversion between suites
* optional compiler, tooling or runtime integrations
* optional tests, launchers or packaging layers that should not become unconditional suite imports

If a suite is always required for normal development and build of another suite, a regular static suite import is required.

Dynamic imports can be specified on the command line as an mx argument: `--dynamicimports` is a comma-separated list of suites to be dynamically imported (the shorter `--dy` version can also be used).
For suites that are in a subfolder of a repository, their name should be prefixed with a `/`.
For example:

    mx --dy /compiler ...

This requires the `compiler` suite to already be checked-out.
For example:

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

## Declared and ad-hoc dynamic imports

There are two related but different mechanisms:

* An **ad-hoc dynamic import** is specified only on the command line or via the environment.
  This is useful when you want to compose suites for one invocation without changing any `suite.py` file.
* A **declared dynamic import** is an entry in `imports["suites"]` with `"dynamic": True`.
  This is useful when the optional relationship is part of the suite design and the suite wants to record the import's metadata such as version, URLs, `subdir`, or `foreign`.

The practical difference is that an ad-hoc dynamic import only names the suite to be added.
It does not by itself describe where mx should fetch that suite from or which version to use.
As a result, it is mainly suited for suites that are already available locally (e.g. in the same repo) through the selected suite model.

A declared dynamic import is different: it is still optional, but once activated it behaves like a normal suite import with recorded metadata.
This is the form to use when the optional import should be reproducible or fetchable.

This also explains why a declared dynamic import still needs activation via `--dy`, `DYNAMIC_IMPORTS`, or `DEFAULT_DYNAMIC_IMPORTS`: declaration says that the relationship exists, activation says that this particular mx invocation should include it.

The `vm` suite in the `graal` repository contains several concrete examples of declared dynamic imports for optional language and tooling components.
For example, it declares `graal-js` as an optional subdirectory suite:

```python
{
    "name": "graal-js",
    "subdir": True,
    "dynamic": True,
    "version": "03d0952f738564024f9f2743ed44a96ff1185ba1",
    "urls": [
        {"url": "https://github.com/graalvm/graaljs.git", "kind": "git"},
    ]
}
```

and `graalpython` as an optional imported suite with an explicit repository URL:

```python
{
    "name": "graalpython",
    "dynamic": True,
    "version": "cc992337891dc6f2dfe88ebb26691917eb8c09a4",
    "urls": [
        {"url": "https://github.com/graalvm/graalpython.git", "kind": "git"},
    ]
}
```

These declarations record the import metadata in `suite.py`, but they still do nothing unless activated for a particular invocation, for example with `mx --dy /graal-js ...` or `mx --dy graalpython ...`.

## Versioned dynamic imports

In some cases, it is desirable that such dynamically imported suites be automatically located and retrieved at a specific version if it is not available locally.
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
                ]
            },
        ]
    }
}
```

With this definition, the `compiler` import would only be activated when using `--dy /compiler`.
The `subdir: True` property indicates that `compiler` lives in a repository subdirectory instead of at the repository root, which is why the command-line form uses `/compiler`.
If it is not available locally, it is cloned at the specified version using the provided source URLs.

This is the key difference from a command-line-only dynamic import: the command line activates the optional import, while the declaration in `suite.py` supplies the import metadata.
If both are present, the declared import gives mx the version and URL information that the ad-hoc command-line form does not carry.
