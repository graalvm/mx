/*
 * Copyright (c) 2014, 2018, Oracle and/or its affiliates. All rights reserved.
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

import java.io.IOException;
import java.nio.file.FileStore;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import org.junit.runner.Description;
import org.junit.runner.notification.Failure;

/**
 * Timing and disk usage support for JUnit test runs.
 */
class TimingAndDiskUsageDecorator extends MxRunListenerDecorator {

    private long startTime;
    private long classStartTime;
    private Description currentTest;

    /**
     * Time in milliseconds per test class.
     */
    final Map<Class<?>, Long> classTimes;

    /**
     * Time in milliseconds per test.
     */
    final Map<Description, Long> testTimes;

    /**
     * Time taken by the last test in milliseconds.
     */
    private Long testTimeMS;

    /**
     * Max time in seconds for a passing test before it is added to {@link #maxTestTimeExceeded}. If
     * null, then no max time has been set.
     */
    private final Long maxTestTime;

    /**
     * Collects the tests that pass but run longer than {@link #maxTestTime}.
     */
    private final List<MxJUnitWrapper.Timing<Description>> maxTestTimeExceeded;

    private final FileStore fileStore;
    private final String totalDiskSpace;

    TimingAndDiskUsageDecorator(TextRunListener l, Long maxTestTime, List<MxJUnitWrapper.Timing<Description>> maxTestTimeExceeded) {
        super(l);
        this.classTimes = new ConcurrentHashMap<>();
        this.testTimes = new ConcurrentHashMap<>();
        FileStore fs = initFileStore();
        this.fileStore = fs;
        this.totalDiskSpace = fs == null ? null : initTotalDiskSpace(fs);
        this.maxTestTime = maxTestTime;
        this.maxTestTimeExceeded = maxTestTimeExceeded;
    }

    @Override
    public void testClassStarted(Class<?> clazz) {
        classStartTime = System.nanoTime();
        super.testClassStarted(clazz);
    }

    @Override
    public void testClassFinished(Class<?> clazz, int numPassed, int numFailed, int numIgnored, int numAssumptionFailed) {
        long totalTime = System.nanoTime() - classStartTime;
        super.testClassFinished(clazz, numPassed, numFailed, numIgnored, numAssumptionFailed);
        if (beVerbose()) {
            getWriter().print(' ' + valueToString(totalTime) + getDiskStats());
        }
        classTimes.put(clazz, totalTime / 1_000_000);
    }

    @Override
    public void testStarted(Description description) {
        currentTest = description;
        startTime = System.nanoTime();
        super.testStarted(description);
    }

    @Override
    public void testFailed(Failure failure) {
        stopTestTiming(failure.getDescription());
        super.testFailed(failure);
    }

    @Override
    public void testSucceeded(Description description) {
        long timeMS = stopTestTiming(description);
        if (maxTestTime != null) {
            long maxTestTimeMS = maxTestTime * 1000;
            if (timeMS > maxTestTimeMS) {
                maxTestTimeExceeded.add(new MxJUnitWrapper.Timing<>(description, timeMS));
            }
        }
        super.testSucceeded(description);
    }

    private long stopTestTiming(Description description) {
        testTimeMS = (System.nanoTime() - startTime) / 1_000_000;
        testTimes.put(description, testTimeMS);
        return testTimeMS;
    }

    @Override
    public void testFinished(Description description) {
        super.testFinished(description);
        if (beVerbose()) {
            getWriter().print(" " + testTimeMS + " ms");
        }
        currentTest = null;
        testTimeMS = null;
    }

    static String valueToString(long valueNS) {
        long timeWholeMS = valueNS / 1_000_000;
        long timeFractionMS = (valueNS / 100_000) % 10;
        return String.format("%d.%d ms", timeWholeMS, timeFractionMS);
    }

    /**
     * Gets the test currently started but not yet completed along with the number of milliseconds
     * it has been executing.
     *
     * @return {@code null} if there is no test currently executing
     */
    public Object[] getCurrentTestDuration() {
        Description current = currentTest;
        if (current != null) {
            long timeMS = (System.nanoTime() - startTime) / 1_000_000;
            return new Object[]{current, timeMS};
        }
        return null;
    }

    private static final String[] SIZE_UNITS = {"", "K", "M", "G"};

    static String humanFormat(long num) {
        double n = num;

        for (String unit : SIZE_UNITS) {
            if (Math.abs(n) < 1024) {
                return String.format("%3.1f%sB", n, unit);
            }
            n /= 1024;
        }
        return String.format("%.1fTB", n);
    }

    private String getDiskStats() {
        String diskStats = "";
        if (fileStore != null) {
            try {
                diskStats = String.format(", [disk (free/total): %s/%s]",
                                humanFormat(fileStore.getUnallocatedSpace()),
                                totalDiskSpace);
            } catch (IOException e) {
                diskStats = String.format(", [disk (free/total): %s]", e);
            }
        }
        return diskStats;
    }

    private static FileStore initFileStore() {
        FileStore fs = null;
        try {
            fs = Files.getFileStore(Paths.get("."));
        } catch (IOException e) {
            System.err.printf("Could not obtain FileStore for %s: %s%n",
                            Paths.get(".").toAbsolutePath(), e);
        }
        return fs;
    }

    private static String initTotalDiskSpace(FileStore fs) {
        try {
            return humanFormat(fs.getTotalSpace());
        } catch (IOException e) {
            e.printStackTrace();
            return null;
        }
    }
}
