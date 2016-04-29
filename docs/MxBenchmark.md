
# Design document for the `mx benchmark` command

Contacts: Aleksandar Prokopec, Gilles Duboscq

Based on lengthy discussions and feedback we got from different teams, we decided to
refine the `mx benchmark` command and parts of the related infrastructure.
This design document summarizes what we plan to do and why.


## Requirements

The following table is our analysis of the requirements by different projects:

stakeholders   | `expe` | `repr` | `cmp1` | `cmp2` | `agg1` | `agg2` | `agg3` | `down` 
---------------|--------|--------|--------|--------|--------|--------|--------|--------
fastr          |   yes  |   yes  |   no   |   no   |   yes  |   yes  |   no   |   yes  
graal-js       |   yes  |   yes  |   no   |   no   |   yes  |   yes  |   no   |   yes  
jruby          |   yes  |   yes  |   no   |   no   |   yes  |   yes  |   no   |   yes  
truffle        |   yes  |   yes  |  yes   |   yes  |   yes  |   yes  |   no   |   yes  
graal-compiler |   yes  |   yes  |  yes   |   yes  |   yes  |   yes  |   yes  |   yes  
svm            |   yes  |   yes  |  yes   |   yes  |   yes  |   yes  |   yes  |   yes  
walnut?        |   yes  |   yes  |   no   |   no   |   yes  |   yes  |   no   |   yes  
managers       |   no   |   no   |   no   |   no   |   yes  |   yes  |   yes  |   no   

Legend:

- `expe` - Experimentation: ability to experiment with different flags from the command
           line, during development.
  1. It should be easy to specify different command-line flags.
  2. It should be possible to "borrow" part of the configuration -- e.g. `graal-js`.
     should be able to easily specify that it wants to use `graal-enterprise`.
- `repr` - Reproducibility: ability to reproduce a benchmark exactly, especially when it
           depends on the state of several source code repositories.
- `cmp1` - Comparison between `host-vm`s and their configs across subgroups -- i.e. run
           `fastr` benchmarks or `graal-js` benchmarks, and show time series for
           `graal-core` and `graal-enterprise`.
- `cmp2` - Comparison between `guest-vm`s and `host-vm`s -- i.e. show performance charts
           for different combinations of guest VMs and host VMs.
- `agg1` - Aggregating scores or metric values across `key=bench-suite+host-vm+guest-vm`
- `agg2` - Aggregating the information from `agg1` across `key=subgroup`
- `agg3` - Aggregating the information from `agg2` across `key=group`
- `down` - Ability to test downstream dependencies. For example, `graal-core` must be
           able to checkout a downstream repo such as `graal-js` and run its benchmarks.

Above, when we say `host-vm` or `guest-vm`, we actually mean all the dimensions that
uniquely specify the name of the VM, and the specific configuration of that VM.

At the same time, we also need to leave the `mx benchmark` command fairly flexible.
Since different teams already have some benchmarking infrastructure in place,
it should be easy for them to port it, as long as the benchmarks produce the right
outputs.


## Goals

The requirement analysis reveals several main goals:

- Allow different suites to decide on their own how a host VM, or guest VM, gets
  specified in the command line, but establish a recommended convention.
- Add some utilities to `mx_benchmark.py` that will optionally allow different suites
  to select a part of the configuration. In particular, choosing one of the registered
  sets of host JVMs to do benchmarking should be easy.
- Encode more specific information into our datapoints besides just `vm` and `config`,
  and we need to be consistent about what is a host VM and what is a guest VM.
- Encode more version information to ensure reproducibility.


## Proposal

The proposal is three-fold -- the first part concerns changes in the schema, the second
part concerns changes in `mx_benchmark.py`. Third part ensures reproducibility.


### Schema changes

First, we will add the following obligatory dimensions to the schema.
We define a *runtime* as a stack of VMs that execute a benchmark.
With that in mind:

- `host-vm` -- The lowest level in the execution stack. This can be `v8`, `server`,
               `client`, `jvmci`, `spidermonkey`, etc.
- `host-vm-config` -- The name of a particular configuration for `host-vm`.
- `guest-vm` -- The second level in the execution stack. This can be `fastr`, `jruby`,
                `graal-js`, etc.
- `guest-vm-config` -- The name of a particular configuration for `guest-vm`.

We will deprecate the following fields:

- `vm` -- VM is ambiguous and could make cross-subgroup comparisons complicated
- `config.name` -- same for `config.name` since it applies only to one VM

We will not use the `-c, --configuration` flag for the `mx benchmark` command.
Instead, suites themselves should take care to populate these fields correctly.
The server will apply proper validation on `host-vm` and `guest-vm`.


### Mx changes

We will leave the top-level `BenchmarkSuite` object as-is -- this is the most general
way to define a benchmark class. In fact, is probably preferable that this class changes
as little as possible, to minimize the impact on other teams.


#### Java benchmark suite

We will change the `JavaBenchmarkSuite` implementation to accept an additional argument:

- `--jvm-config` -- the name of the config

Which configs are available depends on what is specified in Mx's existing `--vm` flag.
Note that this flag refers only to Java-related VMs in Mx, and cannot be used to
specify, for example, `v8`.

If `--vm=jvmci`, then for `--jvm-config`:

- `"graal-core"` -- sets flags to enable Graal core
- `"graal-enterprise"` -- sets flags to enable Graal enterprise

If `--vm=server`, then for `--jvm-config`, e.g.:

- `"default"` -- no special flags sent to the server

Here is an example command line:

    mx --vm=jvmci benchmark -p ./results.json dacapo:jython \
      -- --jvm-config=graal-core -XX:+PrintGC \
      -- --iters=10

Command-line interpolation must work as follows:

    <config-specific-vm-args> <user-vm-args> <main-class> <user-run-args>


#### Suites for other languages

We recommend that other language benchmarks use a similar approach
(but this is not mandatory).
For example, GraalJS could have a flag `--jsvm`, which can be set to `graal-js`,
`nashorn`, `v8`, `spidermonkey`, etc.
If it is set to `graal-js` or `nashorn`, then the actual underlying VM is taken from
Mx's existing `--vm` flag.
In this case, an additional `--jvm-config` flag is allowed, with the same semantics as
for the `JavaBenchmarkSuite`.
Furthermore, if guest VMs such as `graal-js` or `nashorn` have multiple configurations,
then these should be specified with an additional flag to the suite, for example,
`--jsvm-config`.
The suite must be able to understand the values for that config.

Here is an example command line:

    mx --vm=jvmci benchmark octane:* \
      -- --jsvm=graal-js --jvm-config=noinlining -Xmx2G \
      -- --iters=10

Similarly, FastR suites can decide to use flags such as `--rvm` and `--rvm-config`,
and `--jvm-config` where applicable.


#### JavaVM objects

For the purposes of running benchmarks in the context of `JavaBenchmarkSuite`,
we will introduce the following class:

    class JavaVm:
      def exec(vmFlags, runFlags):
        """Runs this Java VM with the specified VM and run arguments.

        Besides the exit code and the stdout, it returns a dictionary of extra
        dimensions that should be embedded into the datapoint.

        :param list vmFlags: List of VM flags.
        :param list runFlags: List of run flags.
        :return: A tuple with exit-code, stdout, and a dictionary with extra dimensions.
        :rtype: tuple
        """
        raise NotImplementedException()

We will have one class for each pair of a `--vm` jvm-config.

Objects of this type will be registered in this dictionary, so that other suites can
potentially use them:

    _bm_suite_java_vms = {}


### Adding suite version information to datapoints

All datapoints will get an extra commit revision for all the extra suites that were
loaded to execute the benchmark.

For example, a `fastr` benchmark could get:

    extra.graal-core-rev = a6c875a44fed

This will be ensured by the overall harness, not the specific suites.


## Conclusion

Here's a summary of how the proposal fulfills the requirements:

- `expe` - It is easy to both specify extra command-line flags, and it allows suites to
           reuse parts of the infrastructure, such as the `JavaVm`.
- `repr` - Ensured by the extra `-rev` fields.
- `cmp1` - The new combinations of `host-vm` and `guest-vm` allow this.
- `cmp2` - The new combinations of `host-vm` and `guest-vm` allow this.
- `agg1` - Will be addressed by UI changes, not the concern of Mx.
- `agg2` - Will be addressed by server and UI changes, not the concern of Mx.
- `agg3` - Will be addressed by server and UI changes, not the concern of Mx.
- `down` - The `ci.hocon` files can encode which downstream dependencies need to be
           tested.
