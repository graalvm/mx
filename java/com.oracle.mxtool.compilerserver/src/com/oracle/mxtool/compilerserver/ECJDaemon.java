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

import java.io.PrintWriter;
import java.lang.reflect.Method;

public class ECJDaemon extends CompilerDaemon {

    private final class ECJCompiler implements Compiler {
        public int compile(String[] args) throws Exception {
            boolean result = (Boolean) compileMethod.invoke(null, args, new PrintWriter(System.out), new PrintWriter(System.err), null);
            return result ? 0 : -1;
        }
    }

    private Method compileMethod;

    ECJDaemon() throws Exception {
        Class<?> ecjMainClass = Class.forName("org.eclipse.jdt.core.compiler.batch.BatchCompiler");
        Class<?> progressClass = Class.forName("org.eclipse.jdt.core.compiler.CompilationProgress");
        this.compileMethod = ecjMainClass.getMethod("compile", String[].class, PrintWriter.class, PrintWriter.class, progressClass);
    }

    @Override
    Compiler createCompiler() {
        return new ECJCompiler();
    }

    public static void main(String[] args) throws Exception {
        ECJDaemon daemon = new ECJDaemon();
        daemon.run(args);
    }
}
