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
import java.lang.module.ModuleDescriptor;
import java.lang.module.ModuleReference;
import java.lang.module.ModuleFinder;
import java.io.PrintStream;
import java.lang.reflect.Method;
import java.util.stream.Collectors;
import java.util.Map;
import java.util.Map.Entry;
import java.util.Set;
import java.util.HashSet;
import jdk.internal.module.ModuleBootstrap;

/**
 * Utility for listing the info for all the modules in the Java runtime image.
 * This uses the same underlying module finding mechanism as {@code java --list-modules}.
 */
public class ListModules {

    /**
     * @returns {@code true} if {@code substrings} is empty or if {@code name} contains any of the
     *          entries in {@code substrings}.
     */
    private static boolean matches(String name, String[] substrings) {
        if (substrings.length == 0) {
            return true;
        }
        for (String s : substrings) {
            if (name.contains(s)) {
                return true;
            }
        }
        return false;
    }

    public static void main(String[] args) throws Throwable {
        PrintStream out = System.out;
        Set<ModuleDescriptor> bootModules = ModuleLayer.boot().modules().stream().map(m -> m.getDescriptor()).collect(Collectors.toSet());

        for (ModuleReference moduleRef : ModuleBootstrap.unlimitedFinder().findAll()) {
            ModuleDescriptor md = moduleRef.descriptor();
            if (!matches(md.name(), args)) {
                continue;
            }
            out.println(md.name());
            out.println("  boot " + bootModules.contains(md));
            for (ModuleDescriptor.Requires dependency : md.requires()) {
                String modifiers = dependency.modifiers().isEmpty() ? "" : dependency.modifiers().stream().map(e -> e.toString().toLowerCase()).collect(Collectors.joining(" ")) + " ";
                out.println("  requires " + modifiers + dependency.name());
            }
            for (String use : md.uses()) {
                out.println("  uses " + use);
            }
            for (ModuleDescriptor.Exports export : md.exports()) {
                String targets = export.targets().isEmpty() ? "" : " to " + export.targets().stream().map(Object::toString).collect(Collectors.joining(" "));
                out.println("  exports " + export.source() + targets);
            }
            for (String pkg : md.packages()) {
                out.println("  package " + pkg);
            }

            for (ModuleDescriptor.Provides provides : md.provides()) {
                for (String provider : provides.providers()) {
                    out.println("  provides " + provides.service() + " with " + provider);
                }
            }
        }
    }
}
