/*
 * Copyright (c) 2014, 2014, Oracle and/or its affiliates. All rights reserved.
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
package com.oracle.mxtool.junit;

import java.lang.annotation.Annotation;
import java.lang.reflect.AnnotatedElement;
import java.net.URL;
import java.net.URLClassLoader;
import java.util.ArrayList;
import java.util.Enumeration;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.jar.JarEntry;
import java.util.jar.JarFile;
import java.util.regex.Pattern;
import java.util.stream.Stream;

/**
 * Finds classes in given jar files that contain {@code AnnotatedElement}s annotated by a given set of annotations.
 */
public class FindClassesByAnnotatedElements {

    private static boolean containsAnnotation(Class<?> javaClass, Set<String> qualifiedAnnotations, Set<String> unqualifiedAnnotations) {
        AnnotatedElement[] classAnnotatedElements = Stream.of(javaClass.getDeclaredMethods(), javaClass.getDeclaredFields()).
                flatMap(Stream::of).toArray(AnnotatedElement[]::new);
        for (AnnotatedElement element : classAnnotatedElements) {
            Annotation[] annos = element.getAnnotations();
            for (Annotation a : annos) {
                if (!qualifiedAnnotations.isEmpty()) {
                    String qualifiedName = a.annotationType().getName();
                    if (qualifiedAnnotations.contains(qualifiedName)) {
                        return true;
                    }
                }
                if (!unqualifiedAnnotations.isEmpty()) {
                    String simpleName = a.annotationType().getSimpleName();
                    if (unqualifiedAnnotations.contains(simpleName)) {
                        return true;
                    }
                }
            }
        }
        return false;
    }

    /**
     * Finds classes in a given set of jar files that contain at least one method with an annotation
     * from a given set of annotations. The qualified name and containing jar file (separated by a
     * space) is written to {@link System#out} for each matching class.
     *
     * @param args jar file names, annotations and snippets patterns. Annotations are those starting
     *            with "@" and can be either qualified or unqualified annotation class names,
     *            snippets patterns are those starting with {@code "snippetsPattern:"} and the rest
     *            are jar file names
     */
    public static void main(String... args) throws Throwable {
        Set<String> qualifiedAnnotations = new HashSet<>();
        Set<String> unqualifiedAnnotations = new HashSet<>();
        List<Pattern> snippetPatterns = new ArrayList<>();
        for (String arg : args) {
            if (isSnippetArg(arg)) {
                snippetPatterns.add(Pattern.compile(arg.substring("snippetsPattern:".length())));
            } else if (isAnnotationArg(arg)) {
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
            JarFile jarFile = new JarFile(jarFilePath);
            URL url = new URL("jar", "", "file:" + jarFilePath + "!/");
            ClassLoader loader = new URLClassLoader(new URL[]{url});

            List<String> classNames = new ArrayList<>(jarFile.size());
            Enumeration<JarEntry> e = jarFile.entries();
            while (e.hasMoreElements()) {
                JarEntry je = e.nextElement();
                if (je.isDirectory() || !je.getName().endsWith(".class")) {
                    continue;
                }
                String className = je.getName().substring(0, je.getName().length() - ".class".length());
                classNames.add(className.replace('/', '.'));
            }

            int unsupportedClasses = 0;
            for (String className : classNames) {
                try {
                    Class<?> tmpClass = Class.forName(className, false, loader);
                    if (containsAnnotation(tmpClass, qualifiedAnnotations, unqualifiedAnnotations)) {
                        while(tmpClass.getEnclosingClass() != null) {
                            tmpClass = tmpClass.getEnclosingClass();
                        }
                        System.out.println(tmpClass.getName() + " " + jarFilePath);
                    }
                } catch (UnsupportedClassVersionError ucve) {
                    unsupportedClasses++;
                } catch (NoClassDefFoundError ncdfe) {
                    if (!matches(ncdfe, snippetPatterns, className)) {
                        throw ncdfe;
                    }
                }
            }
            if (unsupportedClasses != 0) {
                System.err.printf("Warning: %s contained %d class files with an unsupported class file version%n",
                                jarFilePath, unsupportedClasses);
            }
        }
    }

    private static boolean isAnnotationArg(String arg) {
        return arg.charAt(0) == '@';
    }

    private static boolean isSnippetArg(String arg) {
        return arg.startsWith("snippetsPattern:");
    }

    private static boolean matches(NoClassDefFoundError ncdfe, List<Pattern> snippetPatterns, String className) {
        for (Pattern p : snippetPatterns) {
            if (p.matcher(ncdfe.getMessage()).matches()) {
                System.err.println("Warning: cannot resolve " + className + " due to " + ncdfe + " which is matched by snippetsPattern \"" + p + "\"");
                return true;
            }
        }
        return false;
    }
}
