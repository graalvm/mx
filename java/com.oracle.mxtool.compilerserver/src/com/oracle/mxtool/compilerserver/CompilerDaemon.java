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

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.io.PrintWriter;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.SocketException;
import java.time.Instant;
import java.util.Formatter;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

public abstract class CompilerDaemon {

    // These values are used in mx.py so keep in sync.
    public static final String REQUEST_HEADER_COMPILE = "MX DAEMON/COMPILE: ";
    public static final String REQUEST_HEADER_SHUTDOWN = "MX DAEMON/SHUTDOWN";
    public static final String RESPONSE_DONE = "MX DAEMON/DONE:";

    /**
     * The deamon will shut down after receiving this many requests with an unrecognized header.
     */
    static final int MAX_UNRECOGNIZED_REQUESTS = 10_000;

    protected void logf(String format, Object... args) {
        if (verbose) {
            System.err.printf(format, args);
        }
    }

    private boolean verbose = false;
    private volatile boolean running;
    private ThreadPoolExecutor threadPool;
    private ServerSocket serverSocket;
    private final AtomicInteger unrecognizedRequests = new AtomicInteger();

    public void run(String[] args) throws Exception {
        int jobsArg = -1;
        int i = 0;
        while (i < args.length) {
            String arg = args[i];
            if (arg.equals("-v")) {
                verbose = true;
            } else if (arg.equals("-j") && ++i < args.length) {
                try {
                    jobsArg = Integer.parseInt(args[i]);
                } catch (NumberFormatException e) {
                    usage();
                }
            } else {
                usage();
            }
            i++;
        }

        // create socket bound to localhost
        serverSocket = new ServerSocket(0, 0, InetAddress.getLoopbackAddress());
        int port = serverSocket.getLocalPort();

        // Need at least 2 threads since we dedicate one to the control
        // connection waiting for the shutdown message.
        int threadCount = Math.max(2, jobsArg > 0 ? jobsArg : Runtime.getRuntime().availableProcessors());
        threadPool = new ThreadPoolExecutor(threadCount, threadCount, 0L, TimeUnit.MILLISECONDS, new LinkedBlockingQueue<>(), new ThreadFactory() {
            public Thread newThread(Runnable runnable) {
                return new Thread(runnable);
            }
        });

        System.out.printf("Started server on port %d [%d threads]\n", port, threadCount);
        running = true;
        while (running) {
            try {
                threadPool.submit(new Connection(serverSocket.accept(), createCompiler()));
            } catch (SocketException e) {
                if (running) {
                    e.printStackTrace();
                } else {
                    // we're shutting down
                }
            }
        }
        threadPool.shutdown();
        while (!threadPool.isTerminated()) {
            threadPool.awaitTermination(50, TimeUnit.MILLISECONDS);
        }
    }

    private static void usage() {
        System.err.println("Usage: [ -v ] [ -j NUM ]");
        System.exit(1);
    }

    abstract Compiler createCompiler();

    interface Compiler {
        int compile(String[] args, PrintWriter out) throws Exception;
    }

    public class Connection implements Runnable {

        private final Socket connectionSocket;
        private final Compiler compiler;

        public Connection(Socket connectionSocket, Compiler compiler) {
            this.connectionSocket = connectionSocket;
            this.compiler = compiler;
        }

        private String printable(String s) {
            Formatter buf = new Formatter();
            s.chars().forEach(c -> {
                if (c < 0x20 || c >= 0x7F) {
                    buf.format("\\u%04x", c);
                } else {
                    buf.format("%c", c);
                }
            });
            return buf.toString();
        }

        @Override
        public void run() {
            try {
                BufferedReader input = new BufferedReader(new InputStreamReader(connectionSocket.getInputStream(), "UTF-8"));
                OutputStreamWriter output = new OutputStreamWriter(connectionSocket.getOutputStream(), "UTF-8");

                try {
                    String request = input.readLine();
                    String requestOrigin = connectionSocket.getInetAddress().getHostAddress();
                    String prefix = String.format("[%s:%s] ", Instant.now(), requestOrigin);
                    if (request == null || request.equals(REQUEST_HEADER_SHUTDOWN)) {
                        shutdown(prefix);
                    } else if (request.startsWith(REQUEST_HEADER_COMPILE)) {
                        String commandLine = request.substring(REQUEST_HEADER_COMPILE.length());
                        String[] args = commandLine.split("\u0000");
                        logf("%sCompiling %s%n", prefix, String.join(" ", args));

                        int result;
                        PrintWriter log = new PrintWriter(output);
                        try {
                            result = compiler.compile(args, log);
                            if (result != 0 && args.length != 0 && args[0].startsWith("GET / HTTP")) {
                                // GR-52712
                                System.err.printf("%sFailing compilation received on %s%n", prefix, connectionSocket);
                            }
                        } finally {
                            log.flush();
                        }
                        logf("%sResult = %d%n", prefix, result);

                        output.write(RESPONSE_DONE + result + "\n");
                    } else {
                        int unrecognizedRequestCount = unrecognizedRequests.incrementAndGet();
                        System.err.printf("%sUnrecognized request %d (len=%d): \"%s\"%n", prefix, unrecognizedRequestCount, request.length(), printable(request));
                        if (unrecognizedRequestCount > MAX_UNRECOGNIZED_REQUESTS) {
                            shutdown(String.format("%sReceived %d unrecognized requests: ", prefix, unrecognizedRequestCount));
                        }
                        output.write(RESPONSE_DONE + "-1\n");
                    }
                } finally {
                    // close IO streams, then socket
                    output.close();
                    input.close();
                    connectionSocket.close();
                }
            } catch (SocketException se) {
                // Lost connection to mx
                shutdown("");
            } catch (Exception ioe) {
                ioe.printStackTrace();
            }
        }
    }

    private void shutdown(String prefix) {
        logf("%sShutting down%n", prefix);
        running = false;
        try {
            serverSocket.close();
        } catch (IOException e) {
            e.printStackTrace();
        }
    }
}
