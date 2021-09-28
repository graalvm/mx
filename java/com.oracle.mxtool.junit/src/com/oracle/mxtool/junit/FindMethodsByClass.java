/*
 * Copyright (c) 2021, Oracle and/or its affiliates. All rights reserved.
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

import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.util.ArrayList;
import java.util.List;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;

public class FindMethodsByClass {
    public static void main(String... args) throws Throwable {
        int testCount = 0;
        for (String arg : args) {
            Class<?> clazz = Class.forName(arg);
            Method[] methods = getAccessibleMethods(clazz);
            int i = 0;
            for (i = 0; i < methods.length; i++) {
                Method method = methods[i];
                // Test annotation = method.getAnnotation(Test.class);
                String methodName = new String(method.getName());
                if (methodName.startsWith("test")) {
                    testCount++;
                    System.out.println(methodName);
                }

            }
        }
        System.out.println(testCount);
    }

    public static Method[] getAccessibleMethods(Class<?> clazz) {
        List<Method> result = new ArrayList<>();
        Class<?> myclass = clazz;
        while (myclass != null) {
            for (Method method : myclass.getDeclaredMethods()) {
                int modifiers = method.getModifiers();
                if (Modifier.isPublic(modifiers) || Modifier.isProtected(modifiers)) {
                    result.add(method);
                }
            }
            myclass = myclass.getSuperclass();
        }
        return result.toArray(new Method[result.size()]);
    }
}

@Retention(RetentionPolicy.RUNTIME)
@interface Test {

}
