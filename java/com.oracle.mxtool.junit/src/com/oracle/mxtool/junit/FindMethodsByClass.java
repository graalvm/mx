package com.oracle.mxtool.junit;

import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.util.ArrayList;
import java.util.List;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;


public class FindMethodsByClass{
    public static void main(String... args) throws Throwable{
        int testCount=0;
        for(String arg:args){
            Class<?> clazz = Class.forName(arg);
            Method[] methods = getAccessibleMethods(clazz);
            int i=0;
            for(i=0;i<methods.length;i++){
                Method method = methods[i];
                //Test annotation = method.getAnnotation(Test.class);
                String methodName = new String(method.getName());
                if(methodName.startsWith("test"))
                {
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
