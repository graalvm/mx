## Loading the Project into IDEs

### IntelliJ

*For the time being, IntelliJ support is intended mainly for editing experience. There is limited support for building
mx based projects from within the IDE.*

Download and install the latest IntelliJ IDEA Community Edition: [https://www.jetbrains.com/idea/download/](https://www.jetbrains.com/idea/download/)

Change the IntelliJ maximum memory to 2 GB or more. As per the [instructions](https://www.jetbrains.com/idea/help/increasing-memory-heap.html#d1366197e127), from the main menu choose **Help | Edit Custom VM Options** and modify the **-Xmx** and **-Xms** options.

Open IntelliJ and go to **Preferences > Plugins > Browse Repositories**. Install the following plugins:

* [Eclipse Code Formatter](https://plugins.jetbrains.com/plugin/6546): formats code according to Eclipse
* [Checkstyle-IDEA](https://plugins.jetbrains.com/plugin/1065): runs style checks as you develop
* [FindBugs-IDEA](https://plugins.jetbrains.com/plugin/3847): looks for suspicious code
* [Python Plugin](https://plugins.jetbrains.com/idea/plugin/631-python): python plugin
* [Markdown Navigator](https://plugins.jetbrains.com/plugin/7896-markdown-navigator): markdown plugin

Make sure you have [`mx`](https://github.com/graalvm/mx) installed and updated (`mx update`). Then, to initialize IntelliJ project files, go to the root of your project and invoke: `mx intellijinit`

Open the folder of your freshly initialized project from IntelliJ (**IntelliJ IDEA > File > Open…**). All depending projects will be included automatically.

Configure the `Eclipse Code Formatter` (**IntelliJ IDEA > Preferences > Other Settings > Eclipse Code Formatter**):

1. Set "Use the Eclipse code formatter"
2. Choose the right version of the formatter for your project (e.g., 4.5 vs 4.6)

Recommended _Format on Save_ configuration (**IntelliJ IDEA > Preferences > Tools > Actions on Save**):

1. Check "Reformat code" (Files:Java, Changed lines only)
2. Check "Optimize imports" (Files:Java)
3. Check "Run code cleanup". This removes unused imports.

At the moment, points 1 and 2 can be automatically configured by passing `--on-save-actions` to `mx intellijinit`.

Use `MX_INTELLIJINIT_DEFAULTS` environment variable to set default options and flags for the `mx intellijinit` command.
The value is split using spaces as delimiter and prepended to the arguments passed on the command line.

Use `mx intellijinit --help` to view all the options and flags that allow further customization
of the IntelliJ projects generation.


#### Building From Within IntelliJ

When building Java sources, `mx build` invokes Java compiler to produce class files and then bundles those classfiles
to jars and other distributions according to the configuration in `suite.py` files.

IntelliJ is configured to build the same classfiles as `mx build` would produce. However, for the time being, the code
that invokes Java compiler inside `mx build` is separate from the code that configures the options for Java compiler
in IntelliJ and there may be inconsistencies leading to compilation errors in IntelliJ.

Mx Java projects are represented as Java modules in IntelliJ. Java mx distributions and mx libraries are represented
as IntelliJ "libraries". The dependencies between IntelliJ Java modules and libraries should reflect the dependencies
on the mx side.

The recommended approach is to start with manual `mx build` to build everything necessary for the project,
then trigger a build from within the IDE, which rebuilds all the Java classfiles, because IntelliJ refuses to reuse
classfiles built outside of IDE. After that, one can continue with edit & compile cycle in the IDE and the
subsequent compilations should be fast and incremental (tip: you can use "build file" or "build package" to make
them even faster). If you know which mx distributions are affected by your changes, you can manually invoke
the right `mx archive @ABC` and skip full `mx build` (useful in combination with
[linky layout](layout-distributions.md#linky_layout)).

`mx intellijinit --mx-distributions` also generates IntelliJ "artifacts", which correspond to MX distributions.
Those artifacts are dummy and use Ant post-processing step to delegate to `mx archive @ARTIFACT_NAME`.
Moreover, the artifacts depend on other IntelliJ artifacts and Java modules to reflect the dependency structure
on the mx side. However, IntelliJ seems to ignore this and always invokes the post-processing step for all the
artifacts regardless of whether their dependencies changed or not, which makes this slow and impractical. If you
still want to use this feature, make sure that the bundled Ant plugin is enabled in **Preferences > Plugins > Installed**
(you may get `Unknown artifact properties: ant-postprocessing.` errors in your project artifacts otherwise).


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
You may set the `WORKSPACE` environment variable to an Eclipse workspace directory, otherwise the workspace is expected to be a parent of the primary suite.
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

#### Mx and Suite Development

Using the [PyDev](https://www.pydev.org/) plugin, eclipse can be made into a python IDE.

The mx folders for the mx suites appear as their own projects (e.g. `mx.compiler`).
The mx source code itself appears as a project called `mx`.

##### Formatting

The PyDev plugin has built-in support for the *Black* formatter since version 7.0.3.

Under `Window > PyDev > Editor > Code Style > Code Formatter`, select `Black` for `Formatter style?` to use *Black* for formatting.

In the same setting window, a `black` executable with the correct version should be configured, see
the [Style Guide](./Styleguide.md) for more information.

To auto-format on save, select `Auto-format editor contents before saving?` under `Window > PyDev > Editor > Save Actions`.

### VSCode
This section describes how to set up VSCode for development.

VSCode is supported via the Eclipse-based [Language Support for Java](https://marketplace.visualstudio.com/items?itemName=redhat.java).
Follow the instructions of the plugin to set it up first.

First run `mx build` to ensure any annotation processor paths are created, otherwise VSCode may not pick it up properly.
Run `mx vscodeinit` to create the project configurations.
This generates Eclipse project configurations and a `.code-workspace` file to open in VSCode.
It will print instructions about how to import and which workspace file to open:

```
----------------------------------------------
VSCode project generation successfully completed for /home/dev/graalpython.code-workspace

The recommended next steps are:
 1) Run mx build. This ensures all shaded JARs and annotation processors are built.
 2) Open VSCode.
 3) Make sure you have installed the 'Language Support for Java' extension.
 4) Open /home/dev/graalpython.code-workspace as workspace.

Note that setting MX_BUILD_EXPLODED=true can improve build times. See "Exploded builds" in the mx README.md.
----------------------------------------------
```

Use `File` > `Open Workspace from File...` and select the `.code-workspace` file.

> After updating your sources and re-running `mx vscodeinit`, new projects may be created and old ones removed. This usually results in an error message indicating that a project is missing another required Java project. To handle this, you simply need repeat the steps above for importing projects.

In order to debug with VSCode, you should launch using the `-d` global option.

### Emacs

The [`lsp-java`](https://emacs-lsp.github.io/lsp-java/) package uses the same language server as VSCode and can open the same projects.
However there are a few things to watch out for.

First, prepare the IDE configuration files as for VSCode: Run `mx build` and then `mx vscodeinit`.
From you emacs session, you can use the interactive command `lsp-load-vscode-workspace` to load the code workspace file.

Because mx stores `src_gen` in a sibling of the source directory, while the language server will find and index these files, Emacs' `lsp-mode` will not associate them with the right folder.
In order to fix this, you can add the following advice:
```
(defun my/lsp-find-session-folder-with-mx (oldfun session file-name)
  (or (funcall oldfun session file-name)
      (funcall oldfun session
               (replace-regexp-in-string
                 "/mxbuild/\\(jdk[0-9]+/\\)?" "/"
                 file-name))))
(advice-add #'lsp-find-session-folder :around #'my/lsp-find-session-folder-with-mx)
```

For interactive evaluation during debugging to work, the Java LSP server needs a project name.
You can pick any from your workspace, it does not really matter as long as it exists.
Then register a debug template for [`dap-mode`](https://emacs-lsp.github.io/dap-mode/):
```
(dap-register-debug-template
 "Java Attach to MX project"
 (list :type "java"
       :request "attach"
       :hostName "localhost"
       :projectName "com.oracle.graal.python" ;; <-- use a project from your workspace
       :port 8000)))
```

Now, if you launch the workspace, you may find you get a lot of errors about JDK classes not being found.
This indicates that the JDK that `mx vscodeinit` configured is not configured in your workspace.
Check the `.code-workspace` file that you imported from: it will have a `"settings"` key with a `"java.configuration.runtimes"` nested key.
These have to be configured for Emacs as well.
Shut down the workspace and find the preferences file by evaluating the following snippet:
```
(find-file (concat lsp-java-workspace-dir "/.metadata/.plugins/org.eclipse.core.runtime/.settings/org.eclipse.jdt.launching.prefs"))
```
You will see one or more `vm` keys, you can just modify (and/or duplicate) these so their `name`  and `path` values match those in the `.code-workspace` file's `java.configuration.runtimes` section.
You only need to do this once, that preferences file persists unless removed by hand.

If you find yourself often switching workspaces, consider creating yourself a shortcut that changes the `lsp-java-workspace-dir`, `lsp-java-workspace-cache-dir`, and `lsp-session-file` for each so you do not overload the LSP server.

#### Experimental parallel distribution building

The options above for Eclipse apply to VSCode as well.
Read above for how to use `MX_IDE_ECLIPSE_ASYNC_DISTRIBUTIONS`.

#### Mx and Suite Development

VSCode is a capable Python IDE, so just adding the `mx.*` folders to your workspace is enough.
Upon opening a Python file for the first time, VSCode will ask if it should install the recommended extensions.

##### Formatting

You can use the [Black Formatter](https://marketplace.visualstudio.com/items?itemName=ms-python.black-formatter) extension.
See the [Style Guide](./Styleguide.md) for more information on custom options.
