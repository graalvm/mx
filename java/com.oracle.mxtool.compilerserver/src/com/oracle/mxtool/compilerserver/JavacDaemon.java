/*
 * Copyright (c) 2016, Oracle and/or its affiliates. All rights reserved.
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
package com.oracle.mxtool.compilerserver;

import java.lang.reflect.Method;

public class JavacDaemon extends CompilerDaemon {

    private final class JavacCompiler implements Compiler {
        public int compile(String[] args) throws Exception {
            final Object receiver = javacMainClass.getDeclaredConstructor().newInstance();
            int result = (Integer) compileMethod.invoke(receiver, (Object) args);
            if (result != 0 && result != 1) {
                // @formatter:off
                /*
                 * com.sun.tools.javac.main.Main:
                 *
                 *     public enum Result {
                 *        OK(0),        // Compilation completed with no errors.
                 *        ERROR(1),     // Completed but reported errors.
                 *        CMDERR(2),    // Bad command-line arguments
                 *        SYSERR(3),    // System error or resource exhaustion.
                 *        ABNORMAL(4);  // Compiler terminated abnormally
                 */
                // @formatter:on
                System.err.printf("javac exited with exit code %d for args: '%s'%n", result, String.join("' '", args));
            }
            return result;
        }
    }

    private Class<?> javacMainClass;
    private Method compileMethod;

    JavacDaemon() throws Exception {
        this.javacMainClass = Class.forName("com.sun.tools.javac.Main");
        this.compileMethod = javacMainClass.getMethod("compile", String[].class);
    }

    @Override
    Compiler createCompiler() {
        return new JavacCompiler();
    }

    public static void main(String[] args) throws Exception {
        JavacDaemon daemon = new JavacDaemon();
        daemon.run(args);
    }
}
