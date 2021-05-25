/*
 * Copyright (c) 2014, 2014, Oracle and/or its affiliates. All rights reserved.
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

import java.io.BufferedInputStream;
import java.io.DataInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Enumeration;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.jar.JarEntry;
import java.util.jar.JarFile;

/**
 * Finds classes in given jar files (or extracted jar directories) that contain methods annotated by
 * a given set of annotations.
 */
public class FindClassesByAnnotatedMethods {

    /**
     * Finds classes in a given set of jar files that contain at least one method with an annotation
     * from a given set of annotations. For each jar, a single line is written to {@link System#out}
     * containing the jar file and 0 or more entries separated by {@link File#pathSeparator}. If an
     * entry starts with {@code '!'} then it's the name of a class whose class file version is not
     * supported. Otherwise, the entry is the name of a class matched by one of the annotations. The
     * jar file is separated from the entries also by {@link File#pathSeparator}.
     *
     * Example of output:
     *
     * <pre>
     * /Users/graal/ws/sdk/mxbuild/dists/jdk11/graal-sdk.jar
     * /Users/graal/ws/graal/sdk/mxbuild/dists/jdk1.8/sdk-test.jar:!org.hamcrest.BaseDescription:org.graalvm.collections.test.EconomicMapImplTest
     * </pre>
     *
     * There are no test or unsupported classes in graal-sdk.jar. In sdk-test.jar there is one
     * unsupported class (i.e. org.hamcrest.BaseDescription) and one test class (i.e.,
     * org.graalvm.collections.test.EconomicMapImplTest).
     *
     * @param args jar file names, annotations and snippets patterns. Annotations are those starting
     *            with "@" and can be either qualified or unqualified annotation class names,
     *            snippets patterns are those starting with {@code "snippetsPattern:"} and the rest
     *            are jar file names
     */
    public static void main(String... args) throws Throwable {
        Set<String> qualifiedAnnotations = new HashSet<>();
        Set<String> unqualifiedAnnotations = new HashSet<>();
        for (String arg : args) {
            if (isAnnotationArg(arg)) {
                String annotation = arg.substring(1);
                int lastDot = annotation.lastIndexOf('.');
                if (lastDot != -1) {
                    qualifiedAnnotations.add(annotation);
                } else {
                    String unqualifed = annotation.substring(lastDot + 1);
                    unqualifiedAnnotations.add(unqualifed);
                }
            }
        }

        for (String jarFilePath : args) {
            if (isSnippetArg(jarFilePath) || isAnnotationArg(jarFilePath)) {
                continue;
            }

            List<ClassFile> classfiles = findClassfiles(jarFilePath);

            int unsupportedClasses = 0;
            System.out.print(jarFilePath);
            for (ClassFile cf : classfiles) {
                Set<String> methodAnnotationTypes = new HashSet<>();
                DataInputStream stream = new DataInputStream(new BufferedInputStream(cf.getInputStream(), cf.getSize()));
                boolean isSupported = true;
                try {
                    readClassfile(stream, methodAnnotationTypes);
                } catch (UnsupportedClassVersionError ucve) {
                    isSupported = false;
                    unsupportedClasses++;
                } catch (Throwable t) {
                    throw new InternalError("Error while parsing class from " + cf + " in " + jarFilePath, t);
                }
                String className = cf.getName().substring(0, cf.getName().length() - ".class".length()).replaceAll("/", ".");
                if (!isSupported) {
                    System.out.print(File.pathSeparator + "!" + className);
                }
                for (String annotationType : methodAnnotationTypes) {
                    if (!qualifiedAnnotations.isEmpty()) {
                        if (qualifiedAnnotations.contains(annotationType)) {
                            System.out.print(File.pathSeparator + className);
                        }
                    }
                    if (!unqualifiedAnnotations.isEmpty()) {
                        final int lastDot = annotationType.lastIndexOf('.');
                        if (lastDot != -1) {
                            String simpleName = annotationType.substring(lastDot + 1);
                            int lastDollar = simpleName.lastIndexOf('$');
                            if (lastDollar != -1) {
                                simpleName = simpleName.substring(lastDollar + 1);
                            }
                            if (unqualifiedAnnotations.contains(simpleName)) {
                                System.out.print(File.pathSeparator + className);
                            }
                        }
                    }
                }
            }
            if (unsupportedClasses != 0) {
                System.err.printf("Warning: %d classes in %s skipped as their class file version is not supported by %s%n", unsupportedClasses, jarFilePath,
                                FindClassesByAnnotatedMethods.class.getSimpleName());
            }
            System.out.println();
        }
    }

    private static List<ClassFile> findClassfiles(String jarFilePath) throws IOException {
        List<ClassFile> classfiles = new ArrayList<>();
        if (!new File(jarFilePath).isDirectory()) {
            JarFile jarFile = new JarFile(jarFilePath);
            Enumeration<JarEntry> e = jarFile.entries();
            while (e.hasMoreElements()) {
                JarEntry je = e.nextElement();
                if (je.isDirectory() || !je.getName().endsWith(".class") ||
                                je.getName().equals("module-info.class")) {
                    continue;
                }
                classfiles.add(new JarClassFile(jarFile, je));
            }
        } else {
            Path root = Paths.get(jarFilePath);
            Files.walk(root).forEach(p -> {
                String name = p.toString();
                if (name.endsWith(".class") && !name.equals("module-info.class")) {
                    classfiles.add(new DirClassFile(jarFilePath, root.relativize(p).toString()));
                }
            });
        }
        return classfiles;
    }

    interface ClassFile {

        InputStream getInputStream() throws IOException;

        String getName();

        int getSize();
    }

    static class JarClassFile implements ClassFile {

        private final JarFile jarFile;
        private final JarEntry je;

        JarClassFile(JarFile jarFile, JarEntry je) {
            this.jarFile = jarFile;
            this.je = je;
        }

        @Override
        public InputStream getInputStream() throws IOException {
            return jarFile.getInputStream(je);
        }

        @Override
        public String getName() {
            return je.getName();
        }

        @Override
        public int getSize() {
            return (int) je.getSize();
        }
    }

    static class DirClassFile implements ClassFile {

        private final String name;
        private final File file;

        DirClassFile(String directory, String name) {
            this.name = name;
            this.file = new File(directory, name);
        }

        @Override
        public InputStream getInputStream() throws IOException {
            return new FileInputStream(file);
        }

        @Override
        public String getName() {
            return name;
        }

        @Override
        public int getSize() {
            return (int) this.file.length();
        }
    }

    private static boolean isAnnotationArg(String arg) {
        return arg.charAt(0) == '@';
    }

    private static boolean isSnippetArg(String arg) {
        return arg.startsWith("snippetsPattern:");
    }

    /*
     * Small bytecode parser that extract annotations.
     */
    private static final int MAJOR_VERSION_JAVA6 = 50;
    private static final int MAJOR_VERSION_OFFSET = 44;
    private static final byte CONSTANT_Utf8 = 1;
    private static final byte CONSTANT_Integer = 3;
    private static final byte CONSTANT_Float = 4;
    private static final byte CONSTANT_Long = 5;
    private static final byte CONSTANT_Double = 6;
    private static final byte CONSTANT_Class = 7;
    private static final byte CONSTANT_Fieldref = 9;
    private static final byte CONSTANT_String = 8;
    private static final byte CONSTANT_Methodref = 10;
    private static final byte CONSTANT_InterfaceMethodref = 11;
    private static final byte CONSTANT_NameAndType = 12;
    private static final byte CONSTANT_MethodHandle = 15;
    private static final byte CONSTANT_MethodType = 16;
    private static final byte CONSTANT_Dynamic = 17;
    private static final byte CONSTANT_InvokeDynamic = 18;
    private static final byte CONSTANT_Module = 19;
    private static final byte CONSTANT_Package = 20;

    private static void readClassfile(DataInputStream stream, Collection<String> methodAnnotationTypes) throws IOException {
        // magic
        int magic = stream.readInt();
        assert magic == 0xCAFEBABE;

        int minor = stream.readUnsignedShort();
        int major = stream.readUnsignedShort();
        if (major < MAJOR_VERSION_JAVA6) {
            throw new UnsupportedClassVersionError("Unsupported class file version: " + major + "." + minor);
        }
        // Starting with JDK8, ignore a classfile that has a newer format than the current JDK.
        String javaVersion = System.getProperties().get("java.specification.version").toString();
        int majorJavaVersion;
        if (javaVersion.startsWith("1.")) {
            javaVersion = javaVersion.substring(2);
            majorJavaVersion = Integer.parseInt(javaVersion);
        } else {
            majorJavaVersion = Integer.parseInt(javaVersion);
        }
        if (major > MAJOR_VERSION_OFFSET + majorJavaVersion) {
            throw new UnsupportedClassVersionError("Unsupported class file version: " + major + "." + minor);
        }

        String[] cp = readConstantPool(stream, major, minor);

        // access_flags, this_class, super_class
        stream.skipBytes(6);

        // interfaces
        stream.skipBytes(stream.readUnsignedShort() * 2);

        // fields
        skipFields(stream);

        // methods
        readMethods(stream, cp, methodAnnotationTypes);
    }

    private static void skipFully(DataInputStream stream, int n) throws IOException {
        long skipped = 0;
        do {
            long s = stream.skip(n - skipped);
            skipped += s;
            if (s == 0 && skipped != n) {
                // Check for EOF (i.e., truncated class file)
                if (stream.read() == -1) {
                    throw new IOException("truncated stream");
                }
                skipped++;
            }
        } while (skipped != n);
    }

    private static String[] readConstantPool(DataInputStream stream, int major, int minor) throws IOException {
        int count = stream.readUnsignedShort();
        String[] cp = new String[count];

        int i = 1;
        while (i < count) {
            byte tag = stream.readByte();
            switch (tag) {
                case CONSTANT_Class:
                case CONSTANT_String:
                case CONSTANT_MethodType:
                case CONSTANT_Module:
                case CONSTANT_Package: {
                    skipFully(stream, 2);
                    break;
                }
                case CONSTANT_InterfaceMethodref:
                case CONSTANT_Methodref:
                case CONSTANT_Fieldref:
                case CONSTANT_NameAndType:
                case CONSTANT_Float:
                case CONSTANT_Integer:
                case CONSTANT_Dynamic:
                case CONSTANT_InvokeDynamic: {
                    skipFully(stream, 4);
                    break;
                }
                case CONSTANT_Long:
                case CONSTANT_Double: {
                    skipFully(stream, 8);
                    break;
                }
                case CONSTANT_Utf8: {
                    cp[i] = stream.readUTF();
                    break;
                }
                case CONSTANT_MethodHandle: {
                    skipFully(stream, 3);
                    break;
                }
                default: {
                    throw new InternalError(String.format("Invalid constant pool tag: " + tag + ". Maybe %s needs updating for changes introduced by class file version %d.%d?",
                                    FindClassesByAnnotatedMethods.class, major, minor));
                }
            }
            if ((tag == CONSTANT_Double) || (tag == CONSTANT_Long)) {
                i += 2;
            } else {
                i += 1;
            }
        }
        return cp;
    }

    private static void skipAttributes(DataInputStream stream) throws IOException {
        int attributesCount;
        attributesCount = stream.readUnsignedShort();
        for (int i = 0; i < attributesCount; i++) {
            stream.skipBytes(2); // name_index
            int attributeLength = stream.readInt();
            skipFully(stream, attributeLength);
        }
    }

    private static void readMethodAttributes(DataInputStream stream, String[] cp, Collection<String> methodAnnotationTypes) throws IOException {
        int attributesCount;
        attributesCount = stream.readUnsignedShort();
        for (int i = 0; i < attributesCount; i++) {
            String attributeName = cp[stream.readUnsignedShort()];
            int attributeLength = stream.readInt();

            if (attributeName.equals("RuntimeVisibleAnnotations")) {
                int numAnnotations = stream.readUnsignedShort();
                for (int a = 0; a != numAnnotations; a++) {
                    readAnnotation(stream, cp, methodAnnotationTypes);
                }
            } else {
                skipFully(stream, attributeLength);
            }
        }
    }

    private static void readAnnotation(DataInputStream stream, String[] cp, Collection<String> methodAnnotationTypes) throws IOException {
        int typeIndex = stream.readUnsignedShort();
        int pairs = stream.readUnsignedShort();
        String type = cp[typeIndex];
        String className = type.substring(1, type.length() - 1).replace('/', '.');
        methodAnnotationTypes.add(className);
        readAnnotationElements(stream, cp, pairs, true, methodAnnotationTypes);
    }

    private static void readAnnotationElements(DataInputStream stream, String[] cp, int pairs, boolean withElementName, Collection<String> methodAnnotationTypes) throws IOException {
        for (int p = 0; p < pairs; p++) {
            if (withElementName) {
                skipFully(stream, 2);
            }
            int tag = stream.readByte();
            switch (tag) {
                case 'B':
                case 'C':
                case 'D':
                case 'F':
                case 'I':
                case 'J':
                case 'S':
                case 'Z':
                case 's':
                case 'c':
                    skipFully(stream, 2);
                    break;
                case 'e':
                    skipFully(stream, 4);
                    break;
                case '@':
                    readAnnotation(stream, cp, methodAnnotationTypes);
                    break;
                case '[': {
                    int numValues = stream.readUnsignedShort();
                    readAnnotationElements(stream, cp, numValues, false, methodAnnotationTypes);
                    break;
                }
            }
        }
    }

    private static void skipFields(DataInputStream stream) throws IOException {
        int count = stream.readUnsignedShort();
        for (int i = 0; i < count; i++) {
            stream.skipBytes(6); // access_flags, name_index, descriptor_index
            skipAttributes(stream);
        }
    }

    private static void readMethods(DataInputStream stream, String[] cp, Collection<String> methodAnnotationTypes) throws IOException {
        int count = stream.readUnsignedShort();
        for (int i = 0; i < count; i++) {
            skipFully(stream, 6); // access_flags, name_index, descriptor_index
            readMethodAttributes(stream, cp, methodAnnotationTypes);
        }
    }
}
