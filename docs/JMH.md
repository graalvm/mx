## Quick Start

If you want to run an *in-repo* JMH benchmark, try:

```
mx benchmark jmh-dist:* -- --jvm-config=default
```

If you want to run a JMH benchmark in an external jar, try:

```
mx benchmark jmh-jar:* -- --jmh-jar=path/to/benchmarks.jar --jvm-config=default
```

If you do not know, continue reading.

---

# JMH Micro Benchmark Harness Integration

This guide describes how the [JMH] micro benchmark harness is integrated in [mx].

The first question is whether the micro benchmarks are provided in an [**external jar**](#external-jar) file
or if the benchmarks sources are [**in the repository**](#in-repo).

## External Jars <a name="external-jar"></a>
The *external jars* are usually built via maven following the instructions on the [JMH webpage][JMH].
Usually, those jars are self-contained and can be executed via `java -jar benchmarks.jar`,
or when going through [mx] using `mx vm -jar benchmarks.jar`.

However, [mx] provides a wrapper for [mx benchmark] that performs the data parsing.
The recommended way of using this is creating a sub-class of `JMHJarBenchmarkSuite`.
Here is an example snippet taken from `mx_benchmark.py`:

```python
class JMHJarMxBenchmarkSuite(JMHJarBenchmarkSuite):

    def name(self):
        return "jmh-jar"

    def group(self):
        return "Graal"

    def subgroup(self):
        return "mx"

add_bm_suite(JMHJarMxBenchmarkSuite())
```

The `group` and `subgroup` methods set the corresponding dimensions in the result json.
The `name` method defines the name under which the suite is registered to [mx benchmark],
i.e., the name used on command line to execute the [benchmark suite].

Since the same [benchmark suite] can be used for different jars,
the `--jmh-name` parameter can be used to provide a better name for the result json.

### Example:
```
mx benchmark jmh-jar:* --results-file=results.json -- --jmh-name=api-benchmarks --jmh-jar=path/to/benchmarks.jar --jvm-config=default
```

This executes the [JMH] benchmarks in the `benchmarks.jar` with the `default` JVM config.
[mx benchmark] will create a file `results.json` with the results and the dimensions
`group=Graal`, `subgroup=mx`, `bench-suite=jmh-api-benchmark`.
Other dimensions, like `benchmark`, `metric.name`, and of course `metric.value`,
are extracted from the [JMH] output.

> **Note:** The `JMHJarMxBenchmarkSuite` is available in [mx] itself.
> Other projects should define their own sub-class and set an appropriate `group` and `subgroup`.


## In-Repo Benchmarks <a name="in-repo"></a>

Keeping the benchmarks *in the repository* offers several advantages.
First, it improves the user experience since there is no need for downloading an external jar
or cloning an additional repository.
Also, adding new benchmarks is as simple as adding new [JUnit] tests.
However, the most significant advantages is that it allows to create
*whitebox* benchmarks.
Similar to *whitebox testing*, those benchmarks have access to the implementation
details and can benchmark specific parts only.

In order to set up a JMH benchmark from scratch one needs to
1. create an [mx project],
2. create an [mx distribution] and
3. sub-class `JMHDistBenchmarkSuite`.

In the following all steps will be discussed in details.

### Create an [mx project]

The [mx project] is the place where the actual benchmarks live.
To make a project a [JMH] project simply add a [JMH] *library* to the `dependencies`
*and* also to the `annotationProcessors`.
We have multiple version of [JMH] available.
At the time of writing `JMH_1_21` is the most recent one.
Here an example, again from [mx]:

```python
"projects" : {
  # ...
  "com.oracle.mxtool.jmh_1_21" : {
    "subDir" : "java",
    "sourceDirs" : ["src"],
    "dependencies" : [
      "JMH_1_21",
    ],
    "javaCompliance" : "1.8",
    "annotationProcessors" : ["JMH_1_21"],
  }
  # ...
}
```

### Create an [mx distributions]

To turn projects into jar files they are organized in [mx distributions].
To create a [JMH] distribution it is sufficient to put a project with a [JMH] dependency to it.
A distribution can contain multiple [JMH] projects.
However, different [JMH] versions should not be mixed into one distribution.

```python
"distributions" : {
  # ...
  "MX_MICRO_BENCHMARKS" : {
    "subDir" : "java",
    "dependencies" : ["com.oracle.mxtool.jmh_1_21"],
  }
  # ...
}
```

The example above will produce a `mx-micro-benchmarks.jar` in the `mxbuild/dists` folder.
[mx] automatically add the `mainClass` attribute with the value `org.openjdk.jmh.Main`
to [JMH] distributions, in case no main class was specified.

#### Distribution Dependencies

For *whitebox benchmark* it is advisable to add *distribution dependencies* otherwise
the jar files will contain all dependencies.

```python
"distDependencies" : [
  "GRAAL",
]
```

The downside of this is that the jar is no longer self-contained, i.e.,
in order to run it one needs to specify a *classpath* containing all the distribution dependencies.
However, the `JMHDistBenchmarkSuite` takes care of this so this is not an issue when running via [mx].

### Sub-classing `JMHDistBenchmarkSuite`

The `JMHDistBenchmarkSuite` implements the logic for running [mx distributions] based [JMH] benchmarks.
It deals with usual java benchmark arguments like `--jvm` and `--jvm-config`.
Projects should create sub-class of `JMHDistBenchmarkSuite` to set an appropriate `group` and `subgroup`.
For example:

```python
class JMHDistMxBenchmarkSuite(JMHDistBenchmarkSuite):
    def name(self):
        return "jmh-dist"

    def group(self):
        return "Graal"

    def subgroup(self):
        return "mx"

add_bm_suite(JMHDistMxBenchmarkSuite())
```

Per default *all* [JMH] distributions are targeted.
Projects can override `JMHDistBenchmarkSuite.filter_distribution` to customize this behavior.

### Example:
```
mx benchmark jmh-dist:* --results-file=results.json -- --jvm-config=default
```

This execute the [JMH] benchmarks included in a [JMH] distribution with the `default` JVM config.
[mx benchmark] will create a file `results.json` with the results and the dimensions
`group=Graal`, `subgroup=mx`.
The `bench-suite` dimension is the name of the distribution prefixed with `jmh-`.
Other dimensions, like `benchmark`, `metric.name`, and of course `metric.value`,
are extracted from the [JMH] output.

It is also possible to execute only the benchmarks from a single distribution.
To do so replace asterisk (`*`) in the mx benchmark command line with the distribution name, e.g. `jmh-dist:MX_MICRO_BENCHMARKS`.


> **Note:** The `jmh-dist` benchmark suite defined in [mx] is not available in other projects.
> They should define their own sub-class of `JMHDistBenchmarkSuite` and set an appropriate `group` and `subgroup`.


[JMH]: http://openjdk.java.net/projects/code-tools/jmh/
[mx]: ../README.md
[JUnit]: ../README.md#junit
[mx benchmark]: ../README.md
[benchmark suite]: ../README.md
[mx distributions]: ../README.md
[mx project]: ../README.md
