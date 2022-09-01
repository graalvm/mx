/*
 * Copyright (c) 2021, Oracle and/or its affiliates. All rights reserved.
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
import java.util.ArrayList;
import java.util.List;

import org.junit.runner.Description;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;

public class JsonResultsDecorator extends MxRunListenerDecorator {
    private final PrintStream output;
    private boolean hasContent;
    private long startTime;
    private final List<TestResult> testResults = new ArrayList<>();

    static class TestResult {
        final String description;
        final String result;
        final long duration;

        TestResult(String description, String result, long duration) {
            this.description = description;
            this.result = result;
            this.duration = duration;
        }
    }

    JsonResultsDecorator(MxRunListener l, PrintStream output) {
        super(l);
        this.output = output;
    }

    @Override
    public void testRunStarted(Description description) {
        super.testRunStarted(description);
    }

    @Override
    public void testRunFinished(Result result) {
        super.testRunFinished(result);
        outputTestResults();
        output.close();
    }

    @Override
    public void testSucceeded(Description description) {
        super.testSucceeded(description);
        String result = "SUCCESS";
        long duration = System.nanoTime() - startTime;
        testResults.add(new TestResult(description.getDisplayName(), result, duration));
    }

    @Override
    public void testFailed(Failure failure) {
        super.testFailed(failure);
        String result = "FAILED";
        long duration = System.nanoTime() - startTime;
        testResults.add(new TestResult(failure.getDescription().getDisplayName(), result, duration));
    }

    @Override
    public void testIgnored(Description description) {
        super.testIgnored(description);
        String result = "IGNORED";
        long duration = System.nanoTime() - startTime;
        testResults.add(new TestResult(description.getDisplayName(), result, duration));
    }

    @Override
    public void testStarted(Description description) {
        super.testStarted(description);
        // start each time an atomic test is started
        // then substract it from current time once the test is finished
        startTime = System.nanoTime();
    }

    @Override
    public void testClassStarted(Class<?> clazz) {
        super.testClassStarted(clazz);
    }

    private void outputTestResults() {
        if (hasContent) {
            output.print(',');
        }
        output.print("[");
        for (int i = 0; i < testResults.size(); i++) {
            output.print("{\"name\":\"");
            output.print(escape(testResults.get(i).description));
            output.print("\", \"status\":\"");
            output.print(testResults.get(i).result);
            output.print("\", \"duration\":\"");
            output.print(String.format("%.2f", testResults.get(i).duration / 1000000.0f));
            if (i == testResults.size() - 1) {
                output.print("\"}");
                break;
            }
            output.print("\"},");
        }
        output.print("]");
        hasContent = true;
    }

    /**
     * Escapes non-ascii printable characters as well as special JSON characters
     * (https://tools.ietf.org/html/rfc4627#section-2.5) in {@code s}.
     */
    private static String escape(String s) {
        // try to do nothing
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c < 0x20 || c == '\\' || c == '"' || c > 0x7F) {
                return escape(s, i);
            }
        }
        return s;
    }

    private static String escape(String s, int start) {
        // actually escape
        int lengthEstimate = (int) (s.length() * 1.1f) + 5;
        StringBuilder sb = new StringBuilder(lengthEstimate);
        sb.append(s, 0, start);
        for (int i = start; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '\\':
                    sb.append("\\\\");
                    break;
                case '"':
                    sb.append("\\\"");
                    break;
                case '\b':
                    sb.append("\\b");
                    break;
                case '\n':
                    sb.append("\\n");
                    break;
                case '\t':
                    sb.append("\\t");
                    break;
                case '\f':
                    sb.append("\\f");
                    break;
                case '\r':
                    sb.append("\\r");
                    break;
                default:
                    if (c < 0x20 || c > 0x7F) {
                        sb.append(String.format("\\u%04x", (int) c));
                    } else {
                        sb.append(c);
                    }
                    break;
            }
        }
        return sb.toString();
    }
}
