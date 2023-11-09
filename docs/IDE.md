## Loading the Project into IDEs

### IntelliJ

Download and install the latest IntelliJ IDEA Community Edition: [https://www.jetbrains.com/idea/download/](https://www.jetbrains.com/idea/download/)

Change the IntelliJ maximum memory to 2 GB or more. As per the [instructions](https://www.jetbrains.com/idea/help/increasing-memory-heap.html#d1366197e127), from the main menu choose **Help | Edit Custom VM Options** and modify the **-Xmx** and **-Xms** options.

Enable parallel builds in **Preferences > Build, Execution, Deployment > Compiler > Compile independent modules in parallel**.

Open IntelliJ and go to **Preferences > Plugins > Browse Repositories**. Install the following plugins:

* [Eclipse Code Formatter](https://plugins.jetbrains.com/plugin/6546): formats code according to Eclipse
* [Checkstyle-IDEA](https://plugins.jetbrains.com/plugin/1065): runs style checks as you develop
* [FindBugs-IDEA](https://plugins.jetbrains.com/plugin/3847): looks for suspicious code
* [Python Plugin](https://plugins.jetbrains.com/idea/plugin/631-python): python plugin
* [Markdown Navigator](https://plugins.jetbrains.com/plugin/7896-markdown-navigator): markdown plugin

Check that the bundled Ant plugin is enabled in **Preferences > Plugins > Installed** (you may get `Unknown artifact properties: ant-postprocessing.` errors in your project artifacts otherwise).

Make sure you have [`mx`](https://github.com/graalvm/mx) installed and updated (`mx update`). Then, to initialize IntelliJ project files, go to the root of your project and invoke: `mx intellijinit`

Open the folder of your freshly initialized project from IntelliJ (**IntelliJ IDEA > File > Open…**). All depending projects will be included automatically.

Configure the `Eclipse Code Formatter` (**IntelliJ IDEA > Preferences > Other Settings > Eclipse Code Formatter**):

1. Set "Use the Eclipse code formatter"
2. Choose the right version of the formatter for your project (e.g., 4.5 vs 4.6)

Recommended _Format on Save_ configuration (**IntelliJ IDEA > Preferences > Tools > Actions on Save**):

1. Check "Reformat code" (Files:Java, Changed lines only)
2. Check "Optimize imports" (Files:Java)
3. Check "Run code cleanup". This removes unused imports.

#### Making IntelliJ Feel Similar to Eclipse (Optional)

Set IntelliJ to use the Eclipse compiler by going to *IntelliJ IDEA > Preferences > Build, Execution, Deployment > Java Compiler*
To make IntelliJ work the same way as Eclipse with respect to Problems View and recompilation you need to:

1. In preferences set the "Make project automatically" flag.
2. Open the problems view:  View > Tool Windows > Problems
3. Navigate the problems with Cmd ⌥ ↑ and Cmd ⌥ ↓

#### Mx and Suite Development

Developing mx itself and downstream can also be done using IntelliJ with the python plugin (or PyCharm)
and `mx intellijinit` (in the mx repository or any other mx suite) as described above is sufficient to add projects for
the mx sources and all reachable mx suites.

The mx source code is generated as an IntelliJ project named `mx`. In the *Project* view, it will appear
as `src [mx]` (similarly there is the `mx_tests` project that appears as `tests [mx_tests]`).

##### Formatting

Since 2023.2, IntelliJ with the python plugin (and PyCharm) have built-in support for the *Black* formatter.
It can be enabled under `Settings > Tools > Black` and it is recommended to turn on both `On code reformat`
and `On save`.
In the same setting window, a `black` executable with the correct version should be configured, see
the [Style Guide](./Styleguide.md) for more information.

By default, this will produce a notification popup everytime *Black* fails to format a file, including when the file is
ignored by the formatter.
This can become annoying and can be turned off under:

```
Settings > Appearance & Behavior > Notifications > Black > Popup type: No popup
```

As of 2023.2, there is no way to separately configure the different popup severities (error vs. informational).

### Eclipse
This section describes how to set up Eclipse for development. For convenience, `$GRAAL` denotes your local repository.

Eclipse can be downloaded [here](http://download.eclipse.org/eclipse/downloads/). Use the latest released version.

Once you have installed Eclipse, if you have multiple Java versions on your computer, you should edit [eclipse.ini](http://wiki.eclipse.org/Eclipse.ini) to [specify the JVM](http://wiki.eclipse.org/Eclipse.ini#Specifying_the_JVM) that Eclipse will be run with. It must be run with a JDK 9 or later VM. For example:
```
-vm
/usr/lib/jvm/jdk-9.0.4/bin/java
```

Run `mx eclipseinit` to create the Eclipse project configurations.
This will print the following instructions on how to import projects:

```
Please restart Eclipse instances for this workspace to see some of the effects.
----------------------------------------------
Eclipse project generation successfully completed for:
  ./graal/sdk
  ./graal/truffle

The recommended next steps are:
 1) Open Eclipse with workspace path: ./graal/workspace
 2) Open project import wizard using: File -> Import -> Existing Projects into Workspace -> Next.
 3) For "select root directory" enter path ./graal/workspace
 4) Make sure "Search for nested projects" is checked and press "Finish".

 hint) If you select "Close newly imported projects upon completion" then the import is more efficient.
       Projects needed for development can be opened conveniently using the generated Suite working sets from the context menu.
 5) Update the type filters (Preferences -> Java -> Appearance -> Type Filters) so that `jdk.*` and `org.graalvm.*` are not filtered.
    Without this, code completion will not work for JVMCI and Graal code.
----------------------------------------------
Ensure that these Execution Environments have a Compatible JRE in Eclipse (Preferences -> Java -> Installed JREs -> Execution Environments):
  JavaSE-1.8
----------------------------------------------

```
Any time Eclipse updates a class file used by the compiler, the updated classes are automatically deployed to the right place so that the next execution of the VM will see the changes.

> After updating your sources and re-running `mx eclipseint`, new Eclipse projects made be created and old ones removed. This usually results in an Eclipse error message indicating that a project is missing another required Java project. To handle this, you simply need repeat the steps above for importing projects.

In order to debug with Eclipse, you should launch using the `-d` global option.

By default Eclipse generates a working set for each mx suite e.g. named `Suite truffle`.

#### Experimental parallel distribution building

Distribution builders (all upper-case imported projects) build synchronously when building the workspace.
Since building distributions can take some time and this might block using the IDE it is possible to run such builders in parallel by setting the environment variable `MX_IDE_ECLIPSE_ASYNC_DISTRIBUTIONS=true` in `~/.mx/env`.
A downside of this option is that Eclipse will no longer show when it is building distributions.
However, it is typically enough to wait a few seconds before running other `mx` commands like `mx unittest` that expect the distributions to be built.

It is planned to enable this feature by default in the future when more feedback has been collected.
