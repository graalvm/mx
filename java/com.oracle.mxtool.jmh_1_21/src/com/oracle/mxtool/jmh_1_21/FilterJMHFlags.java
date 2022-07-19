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
package com.oracle.mxtool.jmh_1_21;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import joptsimple.OptionParser;
import joptsimple.OptionSet;
import joptsimple.OptionSpec;

import org.openjdk.jmh.runner.options.CommandLineOptionException;
import org.openjdk.jmh.runner.options.CommandLineOptions;

/**
 * Utility program for selecting the JMH options or benchmark filters from a JMH command line. This
 * program uses JMH's own command line parser to identify options and filters. Depending on the
 * selected mode, it prints either options and their optional argument values or all benchmark
 * filters, always with one option/value/filter per line.
 */
public class FilterJMHFlags {

    private enum Action {
        ExtractOptions,
        ExtractFilters
    }

    public static void main(String[] args) {
        if (args.length < 1) {
            printUsageAndExit();
        }
        Action action = null;
        if (args[0].equals("--action=ExtractOptions")) {
            action = Action.ExtractOptions;
        } else if (args[0].equals("--action=ExtractFilters")) {
            action = Action.ExtractFilters;
        } else {
            printUsageAndExit();
        }

        OptionSet options = null;
        try {
            options = parseOptions(Arrays.copyOfRange(args, 1, args.length));
        } catch (Throwable t) {
            System.err.println("error: " + t);
            System.exit(1);
        }

        switch (action) {
            case ExtractOptions:
                printOptions(options);
                break;
            case ExtractFilters:
                printFilters(options);
                break;
            default:
                assert false;
        }
    }

    private static void printUsageAndExit() {
        System.err.println("usage: FilterJMHFlags --action=<ExtractOptions|ExtractFilters> jmhFlag...");
        System.exit(1);
    }

    private static OptionSet parseOptions(String[] args) throws NoSuchFieldException, IllegalAccessException,
                    CommandLineOptionException {
        CommandLineOptions jmhOptions = new CommandLineOptions(args);
        Field parserField = CommandLineOptions.class.getDeclaredField("parser");
        parserField.setAccessible(true);
        OptionParser parser = (OptionParser) parserField.get(jmhOptions);
        /*
         * The CommandLineOptions constructor has already parsed the command line, but the results
         * aren't accessible as a single object. Therefore, parse again.
         */
        OptionSet options = parser.parse(args);
        return options;
    }

    /**
     * Print options and their values. All options and values are separated by newlines, except that
     * multiple values for one option are separated by commas. For example, the command line:
     *
     * <pre>
     *     -bm thrpt -bm avgt -jvmArgs='-XX:Foo=foo -XX:-Bar' -r=2
     * </pre>
     *
     * is printed as:
     *
     * <pre>
     *     -bm
     *     thrpt,avgt
     *     -jvmArgs
     *     -XX:Foo=foo -XX:-Bar
     *     -r
     *     2 s
     * </pre>
     *
     * As this example shows, printing on multiple lines serves to deal with the problem that some
     * values may contain spaces. Note that the parser groups the repeated "-bm" options together.
     * It also performs normalizations like reading "-r=2" as "-r='2 s'".
     */
    private static void printOptions(OptionSet options) {
        for (OptionSpec<?> spec : options.asMap().keySet()) {
            if (!options.has(spec)) {
                continue;
            }
            System.out.printf("-%s\n", spec.options().toArray()[0]);

            List<?> values = options.asMap().get(spec);
            if (values.size() == 1) {
                System.out.println(values.get(0));
            } else if (values.size() > 1) {
                String sep = "";
                for (Object value : values) {
                    System.out.printf("%s%s", sep, value);
                    sep = ",";
                }
                System.out.println();
            }
        }
    }

    /**
     * Print the benchmark filters. Filters are printed separated by newlines.
     */
    private static void printFilters(OptionSet options) {
        for (Object filter : options.nonOptionArguments()) {
            System.out.println(filter);
        }
    }
}
