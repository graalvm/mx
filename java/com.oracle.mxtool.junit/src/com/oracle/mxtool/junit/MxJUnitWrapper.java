/*
 * Copyright (c) 2014, 2017, Oracle and/or its affiliates. All rights reserved.
 * DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS FILE HEADER.
 *
 * This code is free software; you can redistribute it and/or modify it
 * under the terms of the GNU General Public License version 2 only, as
 * published by the Free Software Foundation.  Oracle designates this
 * particular file as subject to the "Classpath" exception as provided
 * by Oracle in the LICENSE file that accompanied this code.
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
import java.io.FileOutputStream;
import java.io.FileReader;
import java.io.IOException;
import java.io.OutputStream;
import java.io.PrintStream;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.ServiceLoader;
import java.util.Set;
import java.util.TreeSet;
import java.util.zip.GZIPOutputStream;

import org.junit.internal.JUnitSystem;
import org.junit.internal.RealSystem;
import org.junit.runner.Description;
import org.junit.runner.JUnitCore;
import org.junit.runner.Request;
import org.junit.runner.Result;
import org.junit.runner.Runner;
import org.junit.runner.manipulation.Filter;
import org.junit.runner.notification.Failure;
import org.junit.runner.notification.RunListener;
import org.junit.runner.notification.RunNotifier;
import org.junit.runners.ParentRunner;
import org.junit.runners.model.RunnerScheduler;

import junit.runner.Version;
import sun.misc.Signal;

public class MxJUnitWrapper {

    // Unit tests that start a JVM subprocess can use these system properties to
    // add --add-exports and --add-opens as necessary to the JVM command line.
    //
    // Known usages:
    // jdk.graal.compiler.test.SubprocessUtil.getPackageOpeningOptions()
    public static final String OPENED_PACKAGES_PROPERTY_NAME = "com.oracle.mxtool.junit.opens";
    public static final String EXPORTED_PACKAGES_PROPERTY_NAME = "com.oracle.mxtool.junit.exports";

    public static class MxJUnitConfig {

        public boolean verbose = false;
        public boolean veryVerbose = false;
        public boolean enableTiming = false;
        public boolean failFast = false;
        public boolean color = false;
        public boolean eagerStackTrace = false;
        public boolean gcAfterTest = false;
        public boolean recordResults = false;
        public int repeatCount = 1;
        public int maxClassFailures;
        public String recordFailed;
        public String recordPassed;
        public String jsonResults;
        /**
         * This field is ignored and is only retained for backwards compatibility.
         */
        public String jsonResultTags;

        /**
         * Max time in seconds allowed for a single test.
         */
        public Long maxTestTime;
    }

    private static class RepeatingRunner extends Runner {

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

    private static class RepeatingRequest extends Request {

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

    private static volatile boolean ctrlCPressed = false;

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
        Signal.handle(new Signal("INT"), signal -> {
            ctrlCPressed = true;
            System.exit(1);
        });

        JUnitSystem system = new RealSystem();
        JUnitCore junitCore = new JUnitCore();
        system.out().println("MxJUnitCore");
        system.out().println("JUnit version " + Version.id());

        MxJUnitRequest.Builder builder = new MxJUnitRequest.Builder();
        MxJUnitConfig config = new MxJUnitConfig();

        String[] expandedArgs = expandArgs(args);
        int i = 0;
        List<String> testSpecs = new ArrayList<>();
        List<String> openPackagesSpecs = new ArrayList<>();
        while (i < expandedArgs.length) {
            String each = expandedArgs[i];
            if (each.charAt(0) == '-') {
                // command line arguments
                if (each.contentEquals("-JUnitVerbose")) {
                    config.verbose = true;
                    config.enableTiming = true;
                } else if (each.contentEquals("-JUnitOpenPackages")) {
                    openPackagesSpecs.add(parseStringArg(system, expandedArgs, each, ++i));
                } else if (each.contentEquals("-JUnitVeryVerbose")) {
                    config.verbose = true;
                    config.veryVerbose = true;
                    config.enableTiming = true;
                } else if (each.contentEquals("-JUnitMaxClassFailures")) {
                    config.maxClassFailures = parseIntArg(system, expandedArgs, each, ++i);
                } else if (each.contentEquals("-JUnitFailFast")) {
                    config.maxClassFailures = 1;
                } else if (each.contentEquals("-JUnitEnableTiming")) {
                    config.enableTiming = true;
                } else if (each.contentEquals("-JUnitMaxTestTime")) {
                    config.maxTestTime = (long) parseIntArg(system, expandedArgs, each, ++i);
                } else if (each.contentEquals("-JUnitColor")) {
                    config.color = true;
                } else if (each.contentEquals("-JUnitEagerStackTrace")) {
                    config.eagerStackTrace = true;
                } else if (each.contentEquals("-JUnitGCAfterTest")) {
                    config.gcAfterTest = true;
                } else if (each.contentEquals("-JUnitRecordResults")) {
                    config.recordResults = true;
                } else if (each.contentEquals("-JUnitRecordPassed")) {
                    config.recordPassed = parseStringArg(system, expandedArgs, each, ++i);
                } else if (each.contentEquals("-JUnitRecordFailed")) {
                    config.recordFailed = parseStringArg(system, expandedArgs, each, ++i);
                } else if (each.contentEquals("-JUnitRepeat")) {
                    config.repeatCount = parseIntArg(system, expandedArgs, each, ++i);
                } else if (each.contentEquals("-JUnitJsonResults")) {
                    config.jsonResults = parseStringArg(system, expandedArgs, each, ++i);
                } else {
                    system.out().println("Unknown command line argument: " + each);
                }

            } else {
                testSpecs.add(each);
            }
            i++;
        }

        ModuleSupport moduleSupport = new ModuleSupport(system.out());
        Set<String> opened = new TreeSet<>();
        Set<String> exported = new TreeSet<>();
        for (String spec : openPackagesSpecs) {
            moduleSupport.openPackages(spec, "-JUnitOpenPackages", opened, exported);
        }

        for (String spec : testSpecs) {
            try {
                builder.addTestSpec(spec);
            } catch (MxJUnitRequest.BuilderException ex) {
                system.out().println(ex.getMessage());
                System.exit(1);
            }
        }

        moduleSupport.processAddModulesAnnotations(builder.getClasses());
        MxJUnitRequest request = builder.build();
        moduleSupport.processAddExportsAnnotations(request.classes, opened, exported);

        if (!opened.isEmpty()) {
            System.setProperty(OPENED_PACKAGES_PROPERTY_NAME, String.join(System.lineSeparator(), opened));
        }
        if (!exported.isEmpty()) {
            System.setProperty(EXPORTED_PACKAGES_PROPERTY_NAME, String.join(System.lineSeparator(), exported));
        }

        for (RunListener p : ServiceLoader.load(RunListener.class)) {
            junitCore.addListener(p);
        }

        Result result = runRequest(junitCore, system, config, request);
        System.exit(result.wasSuccessful() ? 0 : -result.getFailureCount());
    }

    public static int parseIntArg(JUnitSystem system, String[] args, String name, int index) {
        if (index >= args.length) {
            system.out().printf("Must include argument for %s%n", name);
            System.exit(1);
        }
        try {
            return Integer.parseInt(args[index]);
        } catch (NumberFormatException e) {
            system.out().printf("Expected integer argument for %s. Found: %s%n", name, args[index]);
            System.exit(1);
            throw e;
        }
    }

    public static String parseStringArg(JUnitSystem system, String[] args, String name, int index) {
        if (index >= args.length) {
            system.out().printf("Must include argument for %s%n", name);
            System.exit(1);
        }
        return args[index];
    }

    private static PrintStream openFile(JUnitSystem system, String name) {
        File file = new File(name).getAbsoluteFile();
        try {
            OutputStream os = new FileOutputStream(file);
            if (name.endsWith(".gz")) {
                os = new GZIPOutputStream(os);
            }
            return new PrintStream(os, true);
        } catch (IOException e) {
            system.out().println("Could not open " + file + " for writing: " + e);
            System.exit(1);
            return null;
        }
    }

    public static Result runRequest(JUnitCore junitCore, JUnitSystem system, MxJUnitConfig config, MxJUnitRequest mxRequest) {
        return runRequest(junitCore, system, config, mxRequest, Filter.ALL);
    }

    public static Result runRequest(JUnitCore junitCore, JUnitSystem system, MxJUnitConfig config, MxJUnitRequest mxRequest, Filter filter) {
        Request request = mxRequest.getRequest();
        final int classesCount;
        if (filter != Filter.ALL) {
            request = request.filterWith(filter);
            classesCount = findTestClasses(request.getRunner().getDescription(), new HashSet<>()).size();
        } else {
            classesCount = mxRequest.classes.size();
        }

        final TextRunListener textListener;
        if (config.veryVerbose) {
            textListener = new VerboseTextListener(system, classesCount, VerboseTextListener.SHOW_ALL_TESTS);
        } else if (config.verbose) {
            textListener = new VerboseTextListener(system, classesCount);
        } else {
            textListener = new TextRunListener(system);
        }
        List<MxJUnitWrapper.Timing<Description>> maxTestTimeExceeded = new ArrayList<>();
        TimingAndDiskUsageDecorator timings = config.enableTiming || config.maxTestTime != null ? new TimingAndDiskUsageDecorator(textListener, config.maxTestTime, maxTestTimeExceeded) : null;
        MxRunListener mxListener = timings != null ? timings : textListener;
        ResultCollectorDecorator resultLoggerDecorator = null;

        final boolean failingFast;
        if (config.failFast && config.maxClassFailures == 0) {
            failingFast = true;
            config.maxClassFailures = 1;
        } else {
            failingFast = false;
        }

        if (config.color) {
            mxListener = new AnsiTerminalDecorator(mxListener);
        }
        if (config.eagerStackTrace) {
            mxListener = new EagerStackTraceDecorator(mxListener);
        }
        if (config.gcAfterTest) {
            mxListener = new GCAfterTestDecorator(mxListener);
        }
        if (config.recordResults) {
            PrintStream passed = openFile(system, "passed.txt");
            PrintStream failed = openFile(system, "failed.txt");
            mxListener = new TestResultLoggerDecorator(passed, failed, mxListener);
        }
        if (config.recordFailed != null || config.recordPassed != null) {
            resultLoggerDecorator = new ResultCollectorDecorator(mxListener);
            mxListener = resultLoggerDecorator;
        }

        if (config.jsonResults != null) {
            mxListener = new JsonResultsDecorator(mxListener, openFile(system, config.jsonResults));
        }

        mxListener = new FullThreadDumpDecorator(mxListener);

        junitCore.addListener(TextRunListener.createRunListener(mxListener, mxRequest.missingClasses));

        if (mxRequest.methodName == null) {
            if (config.maxClassFailures > 0) {
                Runner runner = request.getRunner();
                if (runner instanceof ParentRunner) {
                    ParentRunner<?> parentRunner = (ParentRunner<?>) runner;
                    parentRunner.setScheduler(new RunnerScheduler() {
                        int failureCount = 0;
                        Failure lastFailure;

                        public void schedule(Runnable childStatement) {
                            Failure failure = textListener.getLastFailure();
                            if (failure != null) {
                                if (failure != lastFailure) {
                                    lastFailure = failure;
                                    ++failureCount;
                                    if (failureCount == config.maxClassFailures && !failingFast) {
                                        system.out().printf("Stopping after failures in %s test classes (use --max-class-failures option to adjust failure limit)%n", config.maxClassFailures);
                                    }
                                }
                            }
                            if (failureCount + maxTestTimeExceeded.size() < config.maxClassFailures) {
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
            if (config.maxClassFailures != 0) {
                system.out().println("Single method selected - fail fast or max failure limit not supported");
            }
        }

        if (config.repeatCount != 1) {
            request = new RepeatingRequest(request, config.repeatCount);
        }

        final ResultCollectorDecorator finalResultLoggerDecorator = resultLoggerDecorator;
        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            if (config.enableTiming) {
                printTimings(timings, classesCount);
            }
            if (config.recordFailed != null || config.recordPassed != null) {
                PrintStream passed = getResultStream(system, config.recordPassed);
                PrintStream failed = getResultStream(system, config.recordFailed);
                printResult(finalResultLoggerDecorator, passed, failed);
            }
        }));

        Result result = junitCore.run(request);
        if (!maxTestTimeExceeded.isEmpty()) {
            maxTestTimeExceeded.sort(Collections.reverseOrder());
            // Match output format of org.junit.internal.TextListener.printFooter
            system.out().println();
            system.out().println("FAILURES!!!");
            system.out().printf("Tests exceeded max time of %d seconds (specified by -JUnitMaxTestTime or --max-test-time): %d%n", config.maxTestTime, maxTestTimeExceeded.size());
            for (MxJUnitWrapper.Timing<Description> timing : maxTestTimeExceeded) {
                system.out().printf(" %,10d ms    %s [timehog] %n", timing.value, timing.subject);
            }

            // Add a failure to the final result so that it reports false for Report.wasSuccessful()
            RuntimeException ex = new RuntimeException(maxTestTimeExceeded.size() + " tests exceeded max time");
            Failure failure = new Failure(Description.createTestDescription("<all classes>", "<all methods>"), ex);
            result.getFailures().add(failure);
        }
        return result;
    }

    private static Set<String> findTestClasses(Description desc, Set<String> classes) {
        if (desc.isTest()) {
            classes.add(desc.getClassName());
        }
        for (Description child : desc.getChildren()) {
            findTestClasses(child, classes);
        }
        return classes;
    }

    private static PrintStream getResultStream(JUnitSystem system, String file) {
        if (file == null) {
            return null;
        }
        if (file.equals("-")) {
            return System.out;
        }
        return openFile(system, file);
    }

    public static class Timing<T> implements Comparable<Timing<T>> {
        final T subject;
        final long value;

        Timing(T subject, long value) {
            this.subject = subject;
            this.value = value;
        }

        public int compareTo(Timing<T> o) {
            if (this.value < o.value) {
                return -1;
            }
            if (this.value > o.value) {
                return 1;
            }
            return 0;
        }
    }

    // Should never need to customize so using a system property instead
    // of a command line option for customization is fine.
    private static final int TIMINGS_TO_PRINT = Integer.getInteger("mx.junit.timings_to_print", 10);

    private static void printTimings(TimingAndDiskUsageDecorator timings, int classesCount) {
        if (TIMINGS_TO_PRINT != 0) {
            List<Timing<Class<?>>> classTimes = new ArrayList<>(timings.classTimes.size());
            List<Timing<Description>> testTimes = new ArrayList<>(timings.testTimes.size());
            for (Map.Entry<Class<?>, Long> e : timings.classTimes.entrySet()) {
                classTimes.add(new Timing<>(e.getKey(), e.getValue()));
            }
            for (Map.Entry<Description, Long> e : timings.testTimes.entrySet()) {
                testTimes.add(new Timing<>(e.getKey(), e.getValue()));
            }
            classTimes.sort(Collections.reverseOrder());
            testTimes.sort(Collections.reverseOrder());

            System.out.println();
            System.out.printf("%d longest running test classes after running %d of %d classes:%n", TIMINGS_TO_PRINT, classTimes.size(), classesCount);
            for (int i = 0; i < TIMINGS_TO_PRINT && i < classTimes.size(); i++) {
                Timing<Class<?>> timing = classTimes.get(i);
                System.out.printf(" %,10d ms    %s%n", timing.value, timing.subject.getName());
            }
            System.out.printf("%d longest running tests:%n", TIMINGS_TO_PRINT);
            for (int i = 0; i < TIMINGS_TO_PRINT && i < testTimes.size(); i++) {
                Timing<Description> timing = testTimes.get(i);
                System.out.printf(" %,10d ms    %s%n", timing.value, timing.subject);
            }
            Object[] current = timings.getCurrentTestDuration();
            if (current != null && !ctrlCPressed) {
                System.out.printf("Test %s not finished after %d ms%n", current[0], current[1]);

                FullThreadDumpDecorator.printFullThreadDump(System.out);
            }
        }
    }

    private static void printResult(ResultCollectorDecorator results, PrintStream passed, PrintStream failed) {
        if (passed != null && !results.getPassed().isEmpty()) {
            boolean isStdOut = passed.equals(System.out);
            if (isStdOut) {
                System.out.println("Passed tests:");
            }
            String prefix = isStdOut ? "  " : "";
            results.getPassed().stream().map(d -> prefix + getFormattedDescription(d)).forEach(passed::println);
        }
        if (failed != null && !results.getFailed().isEmpty()) {
            boolean isStdout = failed.equals(System.out);
            if (isStdout) {
                System.out.println("Failing tests:");
            }
            String prefix = isStdout ? "  " : "";
            results.getFailed().stream().map(d -> prefix + getFormattedDescription(d.getDescription())).forEach(failed::println);
        }
    }

    private static String getFormattedDescription(Description description) {
        return description.getClassName() + "#" + description.getMethodName();
    }

    /**
     * Expand any arguments starting with @ and return the resulting argument array.
     *
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
