/*
 * Copyright (c) 2014, 2014, Oracle and/or its affiliates. All rights reserved.
 * DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS FILE HEADER.
 *
 * This code is free software; you can redistribute it and/or modify it
 * under the terms of the GNU General Public License version 2 only, as
 * published by the Free Software Foundation.
 *
 * This code is distributed in the hope that it will be useful, but WITHOUT
 * ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
 * FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
 * version 2 for more details (a copy is included in the LICENSE file that
 * accompanied this code).
 *
 * You should have received a copy of the GNU General Public License version
 * 2 along with this work; if not, write to the Free Software Foundation,
 * Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301 USA.
 *
 * Please contact Oracle, 500 Oracle Parkway, Redwood Shores, CA 94065 USA
 * or visit www.oracle.com if you need additional information or have any
 * questions.
 */
package com.oracle.mxtool.junit;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.io.IOException;
import java.io.PrintStream;
import java.lang.annotation.Annotation;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import org.junit.internal.JUnitSystem;
import org.junit.internal.RealSystem;
import org.junit.runner.Description;
import org.junit.runner.JUnitCore;
import org.junit.runner.Request;
import org.junit.runner.Result;
import org.junit.runner.Runner;
import org.junit.runner.notification.Failure;
import org.junit.runner.notification.RunNotifier;
import org.junit.runners.ParentRunner;
import org.junit.runners.model.RunnerScheduler;

import junit.runner.Version;

public class MxJUnitWrapper {

    static class RepeatingRunner extends Runner {

        private final Runner parent;
        private int repeat;

        RepeatingRunner(Runner parent, int repeat) {
            this.parent = parent;
            this.repeat = repeat;
        }

        @Override
        public Description getDescription() {
            return parent.getDescription();
        }

        @Override
        public void run(RunNotifier notifier) {
            for (int i = 0; i < repeat; i++) {
                parent.run(notifier);
            }
        }

        @Override
        public int testCount() {
            return super.testCount() * repeat;
        }
    }

    static class RepeatingRequest extends Request {

        private final Request request;
        private final int repeat;

        RepeatingRequest(Request request, int repeat) {
            this.request = request;
            this.repeat = repeat;
        }

        @Override
        public Runner getRunner() {
            return new RepeatingRunner(request.getRunner(), repeat);
        }
    }

    /**
     * Run the tests contained in the classes named in the <code>args</code>. A single test method
     * can be specified by adding #method after the class name. Only a single test can be run in
     * this way. If all tests run successfully, exit with a status of 0. Otherwise exit with a
     * status of 1. Write feedback while tests are running and write stack traces for all failed
     * tests after the tests all complete.
     *
     * @param args names of classes in which to find tests to run
     */
    public static void main(String... args) {
        JUnitSystem system = new RealSystem();
        JUnitCore junitCore = new JUnitCore();
        system.out().println("MxJUnitCore");
        system.out().println("JUnit version " + Version.id());
        List<Class<?>> classes = new ArrayList<>();
        String methodName = null;
        List<Failure> missingClasses = new ArrayList<>();
        boolean verbose = false;
        boolean veryVerbose = false;
        boolean enableTiming = false;
        boolean failFast = false;
        boolean color = false;
        boolean eagerStackTrace = false;
        boolean gcAfterTest = false;
        int repeatCount = 1;

        String[] expandedArgs = expandArgs(args);
        for (int i = 0; i < expandedArgs.length; i++) {
            String each = expandedArgs[i];
            if (each.charAt(0) == '-') {
                // command line arguments
                if (each.contentEquals("-JUnitVerbose")) {
                    verbose = true;
                } else if (each.contentEquals("-JUnitVeryVerbose")) {
                    veryVerbose = true;
                } else if (each.contentEquals("-JUnitFailFast")) {
                    failFast = true;
                } else if (each.contentEquals("-JUnitEnableTiming")) {
                    enableTiming = true;
                } else if (each.contentEquals("-JUnitColor")) {
                    color = true;
                } else if (each.contentEquals("-JUnitEagerStackTrace")) {
                    eagerStackTrace = true;
                } else if (each.contentEquals("-JUnitGCAfterTest")) {
                    gcAfterTest = true;
                } else if (each.contentEquals("-JUnitRepeat")) {
                    if (i + 1 >= expandedArgs.length) {
                        system.out().println("Must include argument for -JUnitRepeat");
                        System.exit(1);
                    }
                    try {
                        repeatCount = Integer.parseInt(expandedArgs[++i]);
                    } catch (NumberFormatException e) {
                        system.out().println("Expected integer argument for -JUnitRepeat. Found: " + expandedArgs[i]);
                        System.exit(1);
                    }
                } else {
                    system.out().println("Unknown command line argument: " + each);
                }

            } else {
                /*
                 * Entries of the form class#method are handled specially. Only one can be specified
                 * on the command line as there's no obvious way to build a runner for multiple
                 * ones.
                 */
                if (methodName != null) {
                    system.out().println("Only a single class and method can be specified: " + each);
                    System.exit(1);
                } else if (each.contains("#")) {
                    String[] pair = each.split("#");
                    if (pair.length != 2) {
                        system.out().println("Malformed class and method request: " + each);
                        System.exit(1);
                    } else if (classes.size() != 0) {
                        system.out().println("Only a single class and method can be specified: " + each);
                        System.exit(1);
                    } else {
                        methodName = pair[1];
                        each = pair[0];
                    }
                }
                try {
                    Class<?> cls = Class.forName(each, false, MxJUnitWrapper.class.getClassLoader());
                    if ((cls.getModifiers() & Modifier.ABSTRACT) == 0) {
                        classes.add(cls);
                    }
                } catch (ClassNotFoundException e) {
                    system.out().println("Could not find class: " + each);
                    Description description = Description.createSuiteDescription(each);
                    Failure failure = new Failure(description, e);
                    missingClasses.add(failure);
                }
            }
        }
        final TextRunListener textListener;
        if (veryVerbose) {
            textListener = new VerboseTextListener(system, VerboseTextListener.SHOW_ALL_TESTS);
        } else if (verbose) {
            textListener = new VerboseTextListener(system);
        } else {
            textListener = new TextRunListener(system);
        }
        MxRunListener mxListener = textListener;
        if ((veryVerbose || verbose) && enableTiming) {
            mxListener = new TimingDecorator(mxListener);
        }
        if (color) {
            mxListener = new AnsiTerminalDecorator(mxListener);
        }
        if (eagerStackTrace) {
            mxListener = new EagerStackTraceDecorator(mxListener);
        }
        if (gcAfterTest) {
            mxListener = new GCAfterTestDecorator(mxListener);
        }
        junitCore.addListener(TextRunListener.createRunListener(mxListener));

        if (System.getProperty("java.specification.version").compareTo("1.9") >= 0) {
            addExports(classes, system.out());
        }

        Request request;
        if (methodName == null) {
            request = Request.classes(classes.toArray(new Class<?>[0]));
            if (failFast) {
                Runner runner = request.getRunner();
                if (runner instanceof ParentRunner) {
                    ParentRunner<?> parentRunner = (ParentRunner<?>) runner;
                    parentRunner.setScheduler(new RunnerScheduler() {
                        public void schedule(Runnable childStatement) {
                            if (textListener.getLastFailure() == null) {
                                childStatement.run();
                            }
                        }

                        public void finished() {
                        }
                    });
                } else {
                    system.out().println("Unexpected Runner subclass " + runner.getClass().getName() + " - fail fast not supported");
                }
            }
        } else {
            if (failFast) {
                system.out().println("Single method selected - fail fast not supported");
            }
            request = Request.method(classes.get(0), methodName);
        }
        if (repeatCount != 1) {
            request = new RepeatingRequest(request, repeatCount);
        }
        Result result = junitCore.run(request);
        for (Failure each : missingClasses) {
            result.getFailures().add(each);
        }
        System.exit(result.wasSuccessful() ? 0 : 1);
    }

    private static final Pattern MODULE_PACKAGE_RE = Pattern.compile("([^/]+)/(.+)");

    /**
     * Adds the super types of {@code cls} to {@code supertypes}.
     */
    private static void gatherSupertypes(Class<?> cls, Set<Class<?>> supertypes) {
        if (!supertypes.contains(cls)) {
            supertypes.add(cls);
            Class<?> superclass = cls.getSuperclass();
            if (superclass != null) {
                gatherSupertypes(superclass, supertypes);
            }
            for (Class<?> iface : cls.getInterfaces()) {
                gatherSupertypes(iface, supertypes);
            }
        }
    }

    /**
     * Updates modules specified in {@code AddExport} annotations on {@code classes} to export
     * concealed packages to the annotation classes' declaring modules.
     */
    private static void addExports(List<Class<?>> classes, PrintStream out) {
        Set<Class<?>> types = new HashSet<>();
        for (Class<?> cls : classes) {
            gatherSupertypes(cls, types);
        }
        for (Class<?> cls : types) {
            Annotation[] annos = cls.getAnnotations();
            for (Annotation a : annos) {
                Class<? extends Annotation> annotationType = a.annotationType();
                if (annotationType.getSimpleName().equals("AddExports")) {
                    Optional<String[]> value = getElement("value", String[].class, a);
                    if (value.isPresent()) {
                        for (String export : value.get()) {
                            Matcher m = MODULE_PACKAGE_RE.matcher(export);
                            if (m.matches()) {
                                String moduleName = m.group(1);
                                String packageName = m.group(2);
                                JLRModule module = JLRModule.find(moduleName);
                                if (module == null) {
                                    out.printf("%s: Cannot find module named %s specified in \"AddExports\" annotation: %s%n", cls.getName(), moduleName, a);
                                } else {
                                    module.addExports(packageName, JLRModule.fromClass(cls));
                                    module.addOpens(packageName, JLRModule.fromClass(cls));
                                }
                            } else {
                                out.printf("%s: Ignoring \"AddExports\" annotation with value not matching <module>/<package> pattern: %s%n", cls.getName(), a);
                            }
                        }
                    } else {
                        out.printf("%s: Ignoring \"AddExports\" annotation without `String value` element: %s%n", cls.getName(), a);
                    }
                }
            }
        }
    }

    /**
     * Gets the value of the element named {@code name} of type {@code type} from {@code annotation}
     * if present.
     *
     * @return the requested element value wrapped in an {@link Optional} or
     *         {@link Optional#empty()} if {@code annotation} has no element named {@code name}
     * @throws AssertionError if {@code annotation} has an element of the given name but whose type
     *             is not {@code type} or if there's some problem reading the value via reflection
     */
    private static <T> Optional<T> getElement(String name, Class<T> type, Annotation annotation) {
        Class<? extends Annotation> annotationType = annotation.annotationType();
        Method valueAccessor = null;
        try {
            valueAccessor = annotationType.getMethod(name);
            if (!valueAccessor.getReturnType().equals(type)) {
                throw new AssertionError(String.format("Element %s of %s is of type %s, not %s ", name, annotationType.getName(), valueAccessor.getReturnType().getName(), type.getName()));
            }
        } catch (NoSuchMethodException e) {
            return Optional.empty();
        }
        try {
            return Optional.of(type.cast(valueAccessor.invoke(annotation)));
        } catch (Exception e) {
            throw new AssertionError(String.format("Could not read %f element from %s", name, annotation), e);
        }
    }

    /**
     * Gets the command line for the current process.
     *
     * @return the command line arguments for the current process or {@code null} if they are not
     *         available
     */
    public static List<String> getProcessCommandLine() {
        String processArgsFile = System.getenv().get("MX_SUBPROCESS_COMMAND_FILE");
        if (processArgsFile != null) {
            try {
                return Files.readAllLines(new File(processArgsFile).toPath());
            } catch (IOException e) {
            }
        }
        return null;
    }

    /**
     * Expand any arguments starting with @ and return the resulting argument array.
     *
     * @param args
     * @return the expanded argument array
     */
    private static String[] expandArgs(String[] args) {
        List<String> result = null;
        for (int i = 0; i < args.length; i++) {
            String arg = args[i];
            if (arg.length() > 0 && arg.charAt(0) == '@') {
                if (result == null) {
                    result = new ArrayList<>();
                    for (int j = 0; j < i; j++) {
                        result.add(args[j]);
                    }
                    expandArg(arg.substring(1), result);
                }
            } else if (result != null) {
                result.add(arg);
            }
        }
        return result != null ? result.toArray(new String[0]) : args;
    }

    /**
     * Add each line from {@code filename} to the list {@code args}.
     *
     * @param filename
     * @param args
     */
    private static void expandArg(String filename, List<String> args) {
        BufferedReader br = null;
        try {
            br = new BufferedReader(new FileReader(filename));

            String buf;
            while ((buf = br.readLine()) != null) {
                args.add(buf);
            }
            br.close();
        } catch (IOException ioe) {
            ioe.printStackTrace();
            System.exit(2);
        } finally {
            try {
                if (br != null) {
                    br.close();
                }
            } catch (IOException ioe) {
                ioe.printStackTrace();
                System.exit(3);
            }
        }
    }
}
