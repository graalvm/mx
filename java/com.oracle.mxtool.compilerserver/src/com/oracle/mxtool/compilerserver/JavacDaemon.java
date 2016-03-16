/*
 * Copyright (c) 2016, Oracle and/or its affiliates. All rights reserved.
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
package com.oracle.mxtool.compilerserver;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.lang.reflect.Method;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

public class JavacDaemon implements Runnable {

    private static void logf(String commandLine, Object... args) {
        if (verbose) {
            System.err.printf(commandLine, args);
        }
    }

    private static boolean verbose = false;
    private static boolean running;
    private static ThreadPoolExecutor threadPool;

    private Socket connectionSocket;
    private Object compiler;
    private Method compile;

    public static void main(String[] args) throws Exception {
        if (args.length != 1) {
            System.err.println("Usage: port");
            System.exit(1);
        }

        // create socket
        int port = Integer.parseInt(args[0]);
        ServerSocket serverSocket = new ServerSocket();
        serverSocket.setReuseAddress(true);
        serverSocket.bind(new InetSocketAddress(port));
        logf("Started server on port %d\n", port);

        final Class<?> javacMainClass = Class.forName("com.sun.tools.javac.Main");
        final Method compileMethod = javacMainClass.getMethod("compile", new Class<?>[]{(new String[]{}).getClass()});

        int threadCount = Runtime.getRuntime().availableProcessors();
        threadPool = new ThreadPoolExecutor(threadCount, threadCount, 0L, TimeUnit.MILLISECONDS, new LinkedBlockingQueue<Runnable>(), new ThreadFactory() {
            public Thread newThread(Runnable runnable) {
                return new Thread(runnable);
            }
        });

        running = true;
        while (running) {
            Socket connectionSocket = serverSocket.accept();
            threadPool.submit(new JavacDaemon(connectionSocket, javacMainClass.newInstance(), compileMethod));
        }
        serverSocket.close();
    }

    public JavacDaemon(Socket connectionSocket, Object compiler, Method compile) {
        this.connectionSocket = connectionSocket;
        this.compiler = compiler;
        this.compile = compile;
    }

    public void run() {
        try {
            BufferedReader input = new BufferedReader(new InputStreamReader(connectionSocket.getInputStream(), "UTF-8"));
            OutputStreamWriter output = new OutputStreamWriter(connectionSocket.getOutputStream(), "UTF-8");

            try {
                String commandLine = input.readLine();
                if (commandLine.length() == 0) {
                    logf("Shutting down\n");
                    running = false;
                    while (threadPool.getActiveCount() > 1) {
                        threadPool.awaitTermination(50, TimeUnit.MILLISECONDS);
                    }
                    System.exit(0);
                } else {
                    logf("Compiling %s\n", commandLine);

                    Integer result = (Integer) compile.invoke(compiler, new Object[]{commandLine.split(" ")});
                    logf("Result = %d\n", result);

                    output.write(result + "\n");
                }
            } finally {
                // close IO streams, then socket
                logf("Closing connection with client\n");
                output.close();
                input.close();
                connectionSocket.close();
            }
        } catch (Exception ioe) {
            ioe.printStackTrace();
        }
    }
}
