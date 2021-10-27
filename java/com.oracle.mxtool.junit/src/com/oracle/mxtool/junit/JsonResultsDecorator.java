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
import java.util.Arrays;
import java.util.Formatter;
import java.util.Locale;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;

import org.junit.runner.Description;
import org.junit.runner.notification.Failure;
import org.junit.runner.Result;

public class JsonResultsDecorator extends MxRunListenerDecorator {
    private final PrintStream output;
    private final String jsonResultTags;
    private boolean hasContent;
    private long startTime;

    JsonResultsDecorator(MxRunListener l, PrintStream output, String jsonResultTags) {
        super(l);
        this.output = output;
        if (jsonResultTags != null) {
            String[] tags = jsonResultTags.split(",");
            if (tags.length > 0) {
                this.jsonResultTags = Arrays.stream(tags).distinct().map(JsonResultsDecorator::escape).collect(Collectors.joining("\",\"", "\",\"", ""));

            } else {
                this.jsonResultTags = null;
            }
        } else {
            this.jsonResultTags = null;
        }
    }

    @Override
    public void testRunStarted(Description description) {
        super.testRunStarted(description);
        output.print('[');
    }

    @Override
    public void testRunFinished(Result result) {
        super.testRunFinished(result);
        output.print(']');
        output.close();
    }

    @Override
    public void testSucceeded(Description description) {
        super.testSucceeded(description);
        String result = "SUCCESS";
        outputItem(description.getDisplayName(), result);
    }

    @Override
    public void testFailed(Failure failure) {
        super.testFailed(failure);
        String result = "FAILED";
        outputItem(failure.getDescription().getDisplayName(), result);
    }

    @Override
    public void testIgnored(Description description) {
        super.testIgnored(description);
        String result = "IGNORED";
        outputItem(description.getDisplayName(), result);
    }

    @Override
    public void testStarted(Description description) {
        super.testStarted(description);
        startTime = System.nanoTime();
    }

    @Override
    public void testClassStarted(Class<?> clazz) {
        super.testClassStarted(clazz);
        startTime = System.nanoTime();
    }

    private void outputItem(String name, String result) {
        long totalTime = System.nanoTime() - startTime;
        if (hasContent) {
            output.print(',');
        }
        output.print("{\"type\":\"test-result\",\"test\":\"");
        output.print(escape(name));
        output.print("\",\"result\":\"");
        output.print(escape(result));
        output.print("\",\"time\":");
        output.print(TimeUnit.NANOSECONDS.toMicros(totalTime));
        output.print(",\"tags\":[\"java");
        output.print(getJavaSpecificationVersion());
        if (this.jsonResultTags != null) {
            output.print(this.jsonResultTags);
        }
        output.print("\"]}");
        hasContent = true;
        startTime = 0;
    }

    private static String escape(String s) {
        // try to do nothing
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            // see https://tools.ietf.org/html/rfc4627#section-2.5
            if (c < 0x20 || c == '\\' || c == '"') {
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
                    if (c < 0x20) {
                        new Formatter(sb, Locale.US).format("\\u%04x", (int) c);
                    } else {
                        sb.append(c);
                    }
                    break;
            }
        }
        return sb.toString();
    }

    private static String getJavaSpecificationVersion() {
        String value = System.getProperty("java.specification.version");

        /*
         * Sometimes retrieving version property may not return a value, or other times the string
         * "java7" may be returned when java is not utilized for the purpose of the test; for these
         * cases "no-java" is returned
         */
        if (value == null || value.isEmpty() || value.equalsIgnoreCase("java7")) {
            return "no-java";
        }

        if (value.startsWith("1.")) {
            value = value.substring(2);
        }
        return value;
    }
}
