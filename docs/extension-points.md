# Suite extension points

Most of mx is configured declaratively through `suite.py`, but suites can also add behavior.
As a rule, structure belongs in `suite.py` and code belongs in `mx_<suite>.py`.

The extension module is loaded from the suite's mx metadata directory, next to `suite.py`.
For a suite named `example`, the file name is:

```text
mx.example/mx_example.py
```

## What the extension module is for

A suite extension module is the place to:

* add or override mx commands for the suite
* define custom project and distribution classes referenced from `suite.py`
* hook suite-specific tasks into `mx gate`
* register projects or distributions dynamically
* perform suite-specific initialization that cannot be expressed as data

## Lifecycle hooks

### `mx_init(suite)`

If present, this function is called when the suite extension module is loaded.

Use it for registrations that should happen as soon as the suite is known, such as command registration, gate runner registration, or other global setup.

In existing suites, equivalent initialization is often done directly in the global scope of `mx_<suite>.py` instead of inside `mx_init(suite)`.
Either way, keep that work cheap: expensive initialization in the extension module adds to mx startup time.

### `mx_post_parse_cmd_line(opts)`

If present, this function is called after command line parsing and after the suite graph has been loaded.

Use it for setup that depends on parsed options or on the fully initialized suite graph.

## Commands

Suites can add commands by registering them from `mx_<suite>.py`.

One API is the `mx.command` decorator.
`mx.update_commands(...)` is also supported and is useful when a suite wants to add several commands at once or override an existing command.

```python
import mx

@mx.command("example", "hello", "")
def hello(args):
    print("hello from example")
```

The suite name associates the command with the suite.
If a command name already exists, the suite can override it.

## Custom project and distribution classes

A project or distribution entry in `suite.py` can specify a custom `"class"`.

That class must be defined in the suite extension module.
mx looks it up there when loading the suite.

```python
"projects": {
    "example.generated": {
        "class": "GeneratedJavaProject",
        ...
    }
}
```

This is the main extension point for changing the build process itself.

Typical reasons to use a custom class are:

* computing sources or outputs dynamically
* adding custom build dependencies
* running non-standard build tools
* producing non-standard packaged outputs

For projects, the key hook is usually a custom `getBuildTask()` implementation.
For distributions, the corresponding hook is also `getBuildTask()`, and packaging-oriented subclasses can additionally customize methods such as `getArchivableResults()`.

If the custom class is only a variation of an existing mx concept, it is usually best to subclass the closest built-in base class instead of starting from scratch.

## Dynamically registered projects and distributions

Some suites cannot reasonably enumerate all their constituents statically in `suite.py`.
For those cases, the extension module can define:

```python
def mx_register_dynamic_suite_constituents(register_project, register_distribution):
    ...
```

mx calls this hook while loading suite metadata.

Use it when projects or distributions are derived from other metadata, generated matrices, or external discovery logic.

The hook receives both `register_project` and `register_distribution` callbacks.

This hook complements `suite.py`; it does not replace it.
Keep stable, human-authored structure in `suite.py` and use this hook only for constituents that are genuinely dynamic.

## Gate integration

Suites can participate in `mx gate` from their extension module.

The main APIs are in `mx_gate`:

* `mx_gate.add_gate_runner(suite, runner)` adds suite-specific gate tasks after the common mx gate tasks.
* `mx_gate.prepend_gate_runner(suite, runner)` adds suite-specific gate tasks before the common mx gate tasks.
* `mx_gate.opt_out_common_gate_tasks(...)` lets a primary suite remove or narrow common mx gate tasks.
* `mx_gate.add_gate_argument(...)` adds suite-specific command line arguments to `mx gate`.

A gate runner receives the parsed gate arguments and a task list.
The runner appends tasks to that list.

This mechanism is used for custom style checks, test phases, verification steps, and other suite policy that belongs in the gate but not in the default mx gate task set.

## JAR assembly hooks

When a suite needs to customize how a JAR distribution is assembled, a `JARDistribution` can be customized from Python code.

The two most important hooks are:

* `set_archiveparticipant(...)` for participating in archive assembly
* `add_module_info_compilation_participant(...)` for contributing additional javac arguments when mx compiles generated `module-info.java`

These are more specialized than custom distribution classes and are typically used when the suite wants to adjust the contents or metadata of an otherwise standard JAR distribution.

## How to choose an extension point

Use the least powerful mechanism that solves the problem:

* If the structure is static, keep it in `suite.py`.
* If a built-in project or distribution type already matches, use it directly.
* If only a command or gate task is needed, register it in `mx_<suite>.py`.
* If the build or packaging semantics differ, use a custom `"class"`.
* If the set of constituents is computed, use `mx_register_dynamic_suite_constituents(...)`.

Keeping that boundary clear makes suites easier to understand and keeps `suite.py` machine-readable.

## Related topics

* [The structure of `suite.py`](suite-py.md)
* [Packaging with distributions](packaging.md)
