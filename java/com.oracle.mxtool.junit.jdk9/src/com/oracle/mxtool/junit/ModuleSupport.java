/*
 * Copyright (c) 2019, Oracle and/or its affiliates. All rights reserved.
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
import java.lang.annotation.Annotation;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import org.junit.runners.Suite;

import jdk.internal.module.Modules;

class ModuleSupport {

    private final PrintStream out;

    ModuleSupport(PrintStream out) {
        this.out = out;
    }

    void processAddExportsAnnotations(Set<Class<?>> requestClasses, Set<String> opened, Set<String> exported) {
        Set<Class<?>> classes = new HashSet<>();

        for (Class<?> cls : requestClasses) {
            gatherClasses(cls, classes);
        }

        Set<Class<?>> types = new HashSet<>();
        for (Class<?> cls : classes) {
            gatherSupertypes(cls, types);
        }
        for (Class<?> cls : types) {
            Annotation[] annos = cls.getAnnotations();
            for (Annotation a : annos) {
                Class<? extends Annotation> annotationType = a.annotationType();
                if (annotationType.getSimpleName().equals("AddExports")) {
                    Optional<String[]> value = getElement("value", String[].class, a);
                    if (value.isPresent()) {
                        for (String spec : value.get()) {
                            openPackages(spec, cls, opened, exported);
                        }
                    } else {
                        out.printf("%s: Ignoring \"AddExports\" annotation without `String value` element: %s%n", cls.getName(), a);
                    }
                }
            }
        }
    }

    /**
     * Recursively looks through the given base class for {@code Suite.SuiteClasses} annotations and
     * adds all classes to the set.
     */
    private void gatherClasses(Class<?> base, Set<Class<?>> classes) {
        if (!classes.contains(base)) {
            classes.add(base);
            Suite.SuiteClasses annot = base.getDeclaredAnnotation(Suite.SuiteClasses.class);
            if (annot != null) {
                for (Class<?> cls : annot.value()) {
                    gatherClasses(cls, classes);
                }
            }
        }
    }

    void processAddModulesAnnotations(Set<Class<?>> classes) {
        Set<Class<?>> types = new HashSet<>();
        for (Class<?> cls : classes) {
            gatherSupertypes(cls, types);
        }
        for (Class<?> cls : types) {
            Annotation[] annos = cls.getAnnotations();
            for (Annotation a : annos) {
                Class<? extends Annotation> annotationType = a.annotationType();
                if (annotationType.getSimpleName().equals("AddModules")) {
                    Optional<String[]> value = getElement("value", String[].class, a);
                    if (value.isPresent()) {
                        for (String spec : value.get()) {
                            Modules.loadModule(spec);
                        }
                    } else {
                        out.printf("%s: Ignoring \"AddModules\" annotation without `String value` element: %s%n", cls.getName(), a);
                    }
                }
            }
        }
    }

    public static List<Module> findModules(String spec) {
        ModuleLayer bootLayer = ModuleLayer.boot();
        Set<Module> modules = bootLayer.modules();
        List<Module> result = new ArrayList<>();
        StringSpec matcher = new StringSpec(spec);
        for (Module module : modules) {
            if (matcher.matches(module.getName())) {
                result.add(module);
            }
        }
        return result;
    }

    static class StringSpec {
        final String key;
        final boolean isPrefix;

        StringSpec(String spec) {
            this.isPrefix = spec.endsWith("*");
            this.key = isPrefix ? spec.substring(0, spec.length() - 1) : spec;
        }

        boolean matches(String s) {
            if (isPrefix) {
                return s.startsWith(key);
            } else {
                return s.equals(key);
            }
        }
    }

    private static final Pattern OPEN_PACKAGE_SPEC = Pattern.compile("([^/]+)/([^=]+)(?:=(.+))?");

    void openPackages(String spec, Object context, Set<String> opened, Set<String> exported) {
        Matcher m = OPEN_PACKAGE_SPEC.matcher(spec);
        if (m.matches()) {
            String moduleSpec = m.group(1);
            String packageSpec = m.group(2);
            String targetSpecs = m.group(3);
            List<Module> modules = findModules(moduleSpec);
            if (modules.isEmpty()) {
                out.printf("%s: Cannot find module(s) matching %s: %s%n", context, moduleSpec, spec);
            } else {
                List<Module> targets = new ArrayList<>();
                if (context instanceof Class) {
                    targets.add(((Class<?>) context).getModule());
                }
                boolean allUnnamedTarget = false;
                if (targetSpecs != null) {
                    for (String targetSpec : targetSpecs.split(",")) {
                        if (targetSpec.equals("ALL-UNNAMED")) {
                            allUnnamedTarget = true;
                        } else {
                            List<Module> list = findModules(targetSpec);
                            if (list.isEmpty()) {
                                out.printf("%s: Cannot find target module(s) matching %s: %s%n", context, targetSpec, spec);
                            } else {
                                targets.addAll(list);
                            }
                        }
                    }
                } else {
                    allUnnamedTarget = true;
                }
                StringSpec packageMatcher = new StringSpec(packageSpec);
                for (Module module : modules) {
                    for (String pn : module.getPackages()) {
                        if (packageMatcher.matches(pn)) {

                            List<String> openTargets = new ArrayList<>();
                            List<String> exportTargets = new ArrayList<>();
                            if (allUnnamedTarget) {
                                if (!module.isExported(pn)) {
                                    exportTargets.add("ALL-UNNAMED");
                                    Modules.addExportsToAllUnnamed(module, pn);
                                }
                                if (!module.isOpen(pn)) {
                                    openTargets.add("ALL-UNNAMED");
                                    Modules.addOpensToAllUnnamed(module, pn);
                                }
                            }
                            for (Module target : targets) {
                                if (!module.isExported(pn, target)) {
                                    if (target.isNamed()) {
                                        exportTargets.add(target.getName());
                                    }
                                    Modules.addExports(module, pn, target);
                                }
                                if (!module.isOpen(pn, target)) {
                                    if (target.isNamed()) {
                                        openTargets.add(target.getName());
                                    }
                                    Modules.addOpens(module, pn, target);
                                }
                            }
                            if (!exportTargets.isEmpty()) {
                                exported.add(String.format("%s/%s=%s", module.getName(), pn, String.join(",", exportTargets)));
                            }
                            if (!openTargets.isEmpty()) {
                                opened.add(String.format("%s/%s=%s", module.getName(), pn, String.join(",", openTargets)));
                            }
                        }
                    }
                }
            }
        } else {
            out.printf("%s: Ignoring specification not matching <module>/<package>[=<target-module>(,<target-module>)*] pattern: %s%n", context, spec);
        }
    }

    /**
     * Adds the super types of {@code cls} to {@code supertypes}.
     */
    private static void gatherSupertypes(Class<?> cls, Set<Class<?>> supertypes) {
        if (!supertypes.contains(cls)) {
            supertypes.add(cls);
            Class<?> superclass = cls.getSuperclass();
            if (superclass != null) {
                gatherSupertypes(superclass, supertypes);
            }
            for (Class<?> iface : cls.getInterfaces()) {
                gatherSupertypes(iface, supertypes);
            }
        }
    }

    /**
     * Gets the value of the element named {@code name} of type {@code type} from {@code annotation}
     * if present.
     *
     * @return the requested element value wrapped in an {@link Optional} or
     *         {@link Optional#empty()} if {@code annotation} has no element named {@code name}
     * @throws AssertionError if {@code annotation} has an element of the given name but whose type
     *             is not {@code type} or if there's some problem reading the value via reflection
     */
    private static <T> Optional<T> getElement(String name, Class<T> type, Annotation annotation) {
        Class<? extends Annotation> annotationType = annotation.annotationType();
        Method valueAccessor;
        try {
            valueAccessor = annotationType.getMethod(name);
            if (!valueAccessor.getReturnType().equals(type)) {
                throw new AssertionError(String.format("Element %s of %s is of type %s, not %s ", name, annotationType.getName(), valueAccessor.getReturnType().getName(), type.getName()));
            }
        } catch (NoSuchMethodException e) {
            return Optional.empty();
        }
        try {
            return Optional.of(type.cast(valueAccessor.invoke(annotation)));
        } catch (Exception e) {
            throw new AssertionError(String.format("Could not read %s element from %s", name, annotation), e);
        }
    }
}
