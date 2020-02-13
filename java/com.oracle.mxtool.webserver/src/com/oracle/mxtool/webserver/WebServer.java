/*
 * Copyright (c) 2020, Oracle and/or its affiliates. All rights reserved.
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
package com.oracle.mxtool.webserver;

import java.awt.Desktop;
import java.io.BufferedOutputStream;
import java.io.BufferedReader;
import java.io.DataInputStream;
import java.io.FileNotFoundException;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.PrintWriter;
import java.net.BindException;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.URI;
import java.net.URISyntaxException;
import java.net.UnknownHostException;
import java.nio.file.Files;
import java.nio.file.NoSuchFileException;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Arrays;
import java.util.Date;
import java.util.Enumeration;
import java.util.Formatter;
import java.util.HashMap;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.util.jar.JarEntry;
import java.util.jar.JarFile;
import java.util.jar.JarOutputStream;
import java.util.jar.Manifest;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.IntStream;

/**
 * Simple web server that can serve a web site embedded in the same jar as the web server.
 */
public class WebServer implements Runnable {

    private static final int DEFAULT_PORT = 9090;
    private static final int MAX_PORT_PROBES = 10;

    public static void main(String[] args) throws IOException, URISyntaxException {
        String rootDir = null;
        String archive = null;
        Integer port = null;
        int i = 0;
        boolean openBrowser = true;
        while (i < args.length) {
            String arg = args[i];
            if (!arg.startsWith("--")) {
                rootDir = arg;
                if (i + 1 != args.length) {
                    System.out.printf("WARNING: Extra args after %s ignored%n", arg);
                }
                break;
            }
            if (arg.startsWith("--archive=")) {
                archive = arg.substring("--archive=".length());
            } else if (arg.equals("--no-browse")) {
                openBrowser = false;
            } else if (arg.startsWith("--port=")) {
                port = Integer.parseInt(arg.substring("--port=".length()));
            } else {
                System.out.printf("Unknown option: %s%n", arg);
                System.exit(1);
            }
            i++;
        }
        if (archive != null) {
            if (rootDir == null) {
                System.out.printf("--archive option requires root directory to be specified%n");
                System.exit(1);
            }
            createArchive(rootDir, archive);
        } else {
            if (port != null) {
                startServer(rootDir, port, openBrowser);
            } else {
                int[] ports = IntStream.range(DEFAULT_PORT, DEFAULT_PORT + MAX_PORT_PROBES).toArray();
                for (int p : ports) {
                    try {
                        startServer(rootDir, p, openBrowser);
                    } catch (BindException e) {
                    }
                }
                System.out.println("Ports already in use: " + Arrays.toString(ports));
            }
        }
    }

    private static void createArchive(String rootDir, String archive) throws IOException, FileNotFoundException {
        Manifest manifest = new Manifest();
        manifest.getMainAttributes().putValue("Manifest-Version", "1.0");
        manifest.getMainAttributes().putValue("Main-Class", WebServer.class.getName());
        try (JarOutputStream jos = new JarOutputStream(new FileOutputStream(archive), manifest)) {

            jos.putNextEntry(new JarEntry(WebServer.class.getName().replace('.', '/') + ".class"));
            jos.write(readResource(WebServer.class.getSimpleName() + ".class", WebServer.class, null));

            Path rootPath = Paths.get(rootDir);
            Files.walk(rootPath).forEach(p -> {
                if (!Files.isDirectory(p)) {
                    Path rel = rootPath.relativize(p);
                    JarEntry je = new JarEntry(rel.toString());
                    try {
                        jos.putNextEntry(je);
                        jos.write(Files.readAllBytes(p));
                    } catch (IOException e) {
                        throw new RuntimeException(e);
                    }
                }
            });
        }
        System.out.printf("Created %s.%nRun with: java -jar %s%n", archive, archive);
    }

    private static final Map<String, String> MIME_TYPES = new HashMap<>();

    static {
        MIME_TYPES.put(".gif", "image/gif");
        MIME_TYPES.put(".jpg", "image/jpeg");
        MIME_TYPES.put(".jpeg", "image/jpeg");
        MIME_TYPES.put(".png", "image/png");

        MIME_TYPES.put(".html", "text/html");
        MIME_TYPES.put(".htm", "text/html");
        MIME_TYPES.put(".txt", "text/plain");
        MIME_TYPES.put(".jtr", "text/plain");
    }

    private Socket socket;
    private String rootDir;

    public WebServer(Socket socket, String rootDir) {
        this.socket = socket;
        this.rootDir = rootDir;
    }

    private static void startServer(String rootDir, int port, boolean openBrowser) throws IOException, UnknownHostException, URISyntaxException {
        ServerSocket serverSocket = new ServerSocket(port, 50, InetAddress.getByName(null));
        String contentRoot;
        if (rootDir != null) {
            contentRoot = rootDir;
        } else {
            contentRoot = WebServer.class.getResource("WebServer.class").toString();
            contentRoot = contentRoot.substring(0, contentRoot.length() - (WebServer.class.getName() + ".class").length());
        }
        String localURL = "http://localhost:" + port;
        System.out.printf("Started server on %s to serve content at %s%n", localURL, contentRoot);
        System.out.printf("Kill server with CTRL-C when done.%n");

        if (openBrowser && Desktop.isDesktopSupported() && Desktop.getDesktop().isSupported(Desktop.Action.BROWSE)) {
            Desktop.getDesktop().browse(new URI(localURL));
        }
        while (true) {
            WebServer server = new WebServer(serverSocket.accept(), rootDir);
            Thread thread = new Thread(server);
            thread.start();
        }
    }

    @Override
    public void run() {
        try {
            try (PrintWriter charOut = new PrintWriter(socket.getOutputStream());
                            BufferedOutputStream dataOut = new BufferedOutputStream(socket.getOutputStream())) {

                try (BufferedReader in = new BufferedReader(new InputStreamReader(socket.getInputStream()))) {

                    String input = in.readLine();
                    if (input == null) {
                        throw new IOException("Request truncated - could not find line terminator of first line");
                    }
                    String[] parts = input.split("\\s+");
                    if (parts.length < 2) {
                        throw new IOException("Malformed first line of request: " + input);
                    }
                    String method = parts[0].toUpperCase();
                    String requestURI = parts[1];

                    if (!method.equals("GET") && !method.equals("HEAD")) {
                        error(charOut, dataOut, 501, "501 Method Not Supported: " + method);
                    } else {
                        String[] contentType = {getContentType(requestURI)};

                        if (method.equals("GET")) {
                            try {
                                byte[] data = readURIData(requestURI, contentType);

                                charOut.printf("HTTP/1.1 200 OK\r\n");
                                charOut.printf("Date: %s\r\n", new Date());
                                charOut.printf("Content-type: %s\r\n", contentType[0]);
                                charOut.printf("Content-length: %d\r\n", data.length);
                                charOut.print("\r\n");
                                charOut.flush();

                                dataOut.write(data, 0, data.length);
                                dataOut.flush();
                            } catch (FileNotFoundException | NoSuchFileException e) {
                                try {
                                    error(charOut, dataOut, 501, "404 Resource Not Found: " + requestURI);
                                } catch (IOException ioe) {
                                    ioe.printStackTrace();
                                }
                            }
                        }
                    }

                } catch (IOException ioe) {
                    ioe.printStackTrace();
                } finally {
                    socket.close();
                }
            }
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    private byte[] readURIData(String name, String[] contentType) throws IOException {
        if (rootDir != null) {
            Path path = Paths.get(rootDir, name);
            if (Files.isDirectory(path)) {
                Path index = path.resolve("index.html");
                if (Files.exists(index)) {
                    contentType[0] = "text/html";
                    return Files.readAllBytes(index);
                } else {
                    Formatter buf = new Formatter();
                    buf.format("<html><head><title>%s</title></head>%n<body><h1>%s</h1>%n<ul>%n", name, name);
                    Files.list(path).sorted().forEach(e -> {
                        buf.format("  <li><a href=\"%s\">%s</li>%n", path.getFileName() + "/" + e.getFileName(), e.getFileName());
                    });
                    buf.format("</ul>%n</body></html>%n");
                    contentType[0] = "text/html";
                    return buf.toString().getBytes();
                }
            }
            return Files.readAllBytes(path);
        }
        return readResource(name, getClass(), contentType);
    }

    private static byte[] readResource(String name, Class<?> c, String[] contentType) throws IOException {
        InputStream s = c.getResourceAsStream(name);
        if (name.endsWith("/") && contentType != null) {
            s = c.getResourceAsStream(name + "index.html");
            if (s != null) {
                contentType[0] = "text/html";
            }
        }
        if (s == null) {
            if (contentType != null) {
                byte[] res = tryListJarDirectory(name, c, contentType);
                if (res != null) {
                    return res;
                }
            }
            throw new FileNotFoundException(name);
        }
        byte[] buf = new byte[s.available()];
        new DataInputStream(s).readFully(buf);
        return buf;
    }

    private static byte[] tryListJarDirectory(String name, Class<?> c, String[] contentType) throws IOException {
        String myClass = '/' + c.getName().replace('.', '/') + ".class";
        String myURL = String.valueOf(c.getResource(myClass));
        Matcher m = Pattern.compile("jar:file:(.+)!" + Pattern.quote(myClass)).matcher(myURL);
        if (m.matches()) {
            try (JarFile jar = new JarFile(m.group(1))) {
                Set<String> dirEntries = new TreeSet<>();
                for (Enumeration<JarEntry> e = jar.entries(); e.hasMoreElements();) {
                    JarEntry je = e.nextElement();
                    String absName = je.getName();
                    if (absName.charAt(0) != '/') {
                        absName = '/' + absName;
                    }
                    if (absName.startsWith(name + '/')) {
                        String relName = absName.substring(name.length() + 1);
                        if (relName.indexOf('/') == -1) {
                            dirEntries.add(relName);
                        } else {
                            dirEntries.add(relName.substring(0, relName.indexOf('/')));
                        }
                    }
                }
                Formatter buf = new Formatter();
                buf.format("<html><head><title>%s</title></head>%n<body><h1>%s</h1>%n<ul>%n", name, name);
                for (String e : dirEntries) {
                    buf.format("  <li><a href=\"%s\">%s</li>%n", name + "/" + e, e);
                }
                buf.format("</ul>%n</body></html>%n");
                contentType[0] = "text/html";
                return buf.toString().getBytes();
            }
        }
        return null;
    }

    private static String getContentType(String uri) {
        for (Map.Entry<String, String> e : MIME_TYPES.entrySet()) {
            if (uri.endsWith(e.getKey())) {
                return e.getValue();
            }
        }
        return "application/octet-stream";
    }

    private static void error(PrintWriter charOut, BufferedOutputStream dataOut, int errCode, String message) throws IOException {
        byte[] messageBytes = ("<html>" + message + "</html>").getBytes();
        String contentMimeType = "text/html";
        charOut.printf("HTTP/1.1 %d Error %d\r\n", errCode, errCode);
        charOut.printf("Date: %s\r\n", new Date());
        charOut.printf("Content-type: %s\r\n", contentMimeType);
        charOut.printf("Content-length: %d\r\n", messageBytes.length);
        charOut.print("\r\n");
        charOut.flush();
        dataOut.write(messageBytes, 0, messageBytes.length);
        dataOut.flush();
    }
}
