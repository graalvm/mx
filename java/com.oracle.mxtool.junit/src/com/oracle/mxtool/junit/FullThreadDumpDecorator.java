/*
 * Copyright (c) 2022, Oracle and/or its affiliates. All rights reserved.
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

import java.io.PrintStream;
import java.lang.management.LockInfo;
import java.lang.management.ManagementFactory;
import java.lang.management.MonitorInfo;
import java.lang.management.ThreadInfo;
import java.lang.management.ThreadMXBean;
import org.junit.runner.notification.Failure;

/**
 * Prints full thread dump in case of JUnit test timeout.
 */
public class FullThreadDumpDecorator extends MxRunListenerDecorator {

    private static final String TEST_TIMED_OUT = "test timed out";

    FullThreadDumpDecorator(MxRunListener l) {
        super(l);
    }

    @Override
    public void testFailed(Failure failure) {
        super.testFailed(failure);
        String message = failure.getMessage();
        if (message != null && message.startsWith(TEST_TIMED_OUT)) {
            printFullThreadDump(getWriter());
        }
    }

    static void printFullThreadDump(PrintStream out) {
        out.println("\nDUMPING ALL THREADS ON TIMEOUT:\n");
        ThreadMXBean threadBean = ManagementFactory.getThreadMXBean();
        ThreadInfo[] allThreads = threadBean.dumpAllThreads(true, true);
        for (ThreadInfo ti : allThreads) {
            dumpThread(threadBean, ti, out);
        }
        if (threadBean.isSynchronizerUsageSupported()) {
            long[] threadIds = threadBean.findDeadlockedThreads();
            if (threadIds != null) {
                out.println("Found Java-level deadlock:");
                ThreadInfo[] deadlockedThreads = threadBean.getThreadInfo(threadIds);
                for (ThreadInfo ti : deadlockedThreads) {
                    dumpThread(threadBean, ti, out);
                }
            }
        }
    }

    private static void dumpThread(ThreadMXBean threadBean, ThreadInfo ti, PrintStream out) {
        long id = ti.getThreadId();
        Thread.State state = ti.getThreadState();
        boolean haveCPUTime = threadBean.isThreadCpuTimeSupported() && threadBean.isThreadCpuTimeEnabled();
        boolean haveElapsedTime = haveCPUTime && threadBean.isThreadContentionMonitoringSupported() && threadBean.isThreadContentionMonitoringEnabled();
        String threadHeader = String.format(
                        "\"%s\" %s prio=%d cpu=%s elapsed=%s tid=%d %s\n   java.lang.Thread.State: %s",
                        ti.getThreadName(),
                        ti.isDaemon() ? "daemon" : "",
                        ti.getPriority(),
                        haveCPUTime ? TimingDecorator.valueToString(threadBean.getThreadCpuTime(id)) : "N/A",
                        haveElapsedTime ? TimingDecorator.valueToString(threadBean.getThreadCpuTime(id) + (ti.getBlockedTime() + ti.getWaitedTime()) * 1_000_000) : "N/A",
                        id,
                        state.name().toLowerCase(),
                        state.name());
        out.println(threadHeader);
        StackTraceElement[] stackTrace = ti.getStackTrace();
        MonitorInfo[] monitors = ti.getLockedMonitors();
        LockInfo[] synchronizers = ti.getLockedSynchronizers();
        for (int i = 0; i < stackTrace.length; i++) {
            StackTraceElement stackTraceElement = stackTrace[i];
            String frame = String.format("\tat %s", stackTraceElement);
            out.println(frame);
            for (MonitorInfo mi : monitors) {
                if (mi.getLockedStackDepth() == i) {
                    out.println("\t- locked " + mi);
                }
            }
        }
        if (synchronizers.length > 0) {
            out.println("\n   Locked ownable synchronizers:");
            for (LockInfo li : synchronizers) {
                out.println("\t- " + li);
            }
        }
        out.println();
    }

}
