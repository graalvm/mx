# Layout distributions

Layout distributions are archives that can be created by describing their internal layout.
For example:
```python
suite = {
    "distributions": {
        "EXAMPLE_DIST1": {
            "layout": {
                "lib/": "file:libs/*",
                "include/": [
                    "file:include/*",
                    "extracted-dependency:DEVEL/include/*"
                ],
                "LICENCE": "file:misc/license",
            }
        }
    }
}
```

A distribution uses the "layout" mechanism as soon as it has a `layout` attribute.
The example above would create a distribution that contains 2 directories: `lib` and `include`.
The `lib` directory contains the files matched by `<suite-dir>/libs/*`.
The `include` directory contains the files matched by `<suite-dir>/include/*` as well as all the files contained in the
`DEVEL` archive matching `include/*` (`DEVEL` can be a library or an other distribution).
The distribution also contains a `LICENCE` file at the root which is copied from `<suite-dir>/misc/license`.

## Layout dictionary
The layout dictionary contains destinations as keys and sources as values.
With the above example, `lib/` is a destination directory in the archive while `file:libs/*` is the source of the files
that are added to this directory.

### Destination
If the destination ends with a `/`, a directory with that name will be created in the archive and all the source files
will be copied into this directory.
On the contrary, if the destination does not end with a `/` then it is the name which should be used when copying the source.
In this case there can be only a single source (similar to the `-T` flag of `cp`).

### Sources
The values in the layout dictionary can either be a string or a list if there are multiple sources.
Each source is usually a string with a prefix denoting the type of source.

The following types are available:
* `file` copies files from the suite directory into the archive.
  The `file:` prefix is followed by a glob pattern describing which files should be copied. For example: `file:libs/*`.
* `dependency` copies the result of an other dependency (distributions, libraries, projects, etc.).
  The `dependency:` prefix is followed by a dependency name.
  Like in the rest of the suite definition, dependencies from other suites should be qualified (`<suite-name>:<dependency-name>`).

  If that dependency produces multiple files they can be selected by appending `/` followed by a glob pattern
  e.g., `dependency:SOME_JAR/*.src.zip`.
  Some distributions produce multiple files but logically have a "main" output file,
  in this case, if the `/<pattern>` is omitted, that "main" output is selected.
  For example `depedency:SOME_JAR` selects `some-jar.jar`.
* `extracted-dependency` extracts the contents of a tar or jar dependency (distributions & libraries).
  The `extracted-dependency:` prefix is followed by a dependency name (potentially qualified by the suite name).

  If only certain files should be extracted, a `/` followed by a glob pattern can be appended.
* `link` creates a symbolic link.
  The `link:` prefix should be followed by the content of the link (a relative path from the directory containing the link).
* `string` creates a file with the content following the `string:` prefix.

Note that glob patterns do not match `.*` files by default.

Note that when using a glob pattern to select a source, every element matched by the pattern will be (recursively) copied like `cp` would.
In particular `"lib/": "file:libs/libz.so"` will produce `lib/libz.so` in the archive, not `lib/libs/libz.so`!
The same is true for `dependency` and `extracted-dependency`.

The simple string syntax for source is complemented by a dict syntax which explicitly splits the different parts of the source
and sometimes provides additional functionality. For example `extracted-dependency:DEVEL/include/*` expands to:
```
{
    "source_type": "extracted-dependency",
    "dependency": "DEVEL",
    "path": "include/*",
}
```
The argument to `file` and `link` are expanded into a `path` property.
The argument to `string` is expanded into `value` property.

In their expanded forms, the `file`, `dependency` and `extracted-dependency` support an `exclude` attribute which can be used to exclude elements.
It is a glob pattern or a list of glob patterns.
If any pattern matches, the element is excluded.
The pattern is rooted at the same level as the inclusion pattern.

## Example
Putting all this together, here is a more complete example: 
```python
suite = {
    "distributions": {
        "EXAMPLE_DIST2": {
            "layout": {
                "./": [
                    "file:foo/bar"
                    "file:baz/*"
                ],
                "LICENCE": "misc/license",
                "lib/": [
                    "dependency:GEO",
                    "extracted-dependency:GIS-DB/data/*",
                    {
                        "source_type": "extracted-dependency",
                        "dependency": "GIS-DB2",
                        "path": "share/*",
                        "exclude": ['share/*.o', 'share/*.b']
                    },
                ],
                "share/lib": "link:../lib",
                "VERSION": "string:0.42",
            }
        }
    }
}
```

This would result in an archive with the following contents:
```
- LICENCE
- VERSION
- bar
  '- ... (the contents of <suite-dir>/foo/bar)
- ...  (the files and directories found in  <suite-dir>/baz)
- lib
  |- geo.jar
  |- ... (the files under data in GIS-DB)
  '- ... (the files under share in GIS-DB2 which do not end in .o ir .b)
- share
  '- lib -> ../lib
```