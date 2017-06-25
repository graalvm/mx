/*
 * Copyright (c) 2017, Oracle and/or its affiliates. All rights reserved.
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
package sun.misc;

import java.lang.reflect.*;
import java.security.*;

// Skeleton of Unsafe from JDK8 for the purpose of compiling
// against this version using javac from JDK9 along with
// the `--release 8` option.
public final class Unsafe {

	
    public static Unsafe getUnsafe() {
    	throw new UnsupportedOperationException();
    }

    public native int getInt(Object o, long offset);
    public native void putInt(Object o, long offset, int x);
    public native Object getObject(Object o, long offset);
    public native void putObject(Object o, long offset, Object x);
    public native boolean getBoolean(Object o, long offset);
    public native void    putBoolean(Object o, long offset, boolean x);
    public native byte    getByte(Object o, long offset);
    public native void    putByte(Object o, long offset, byte x);
    public native short   getShort(Object o, long offset);
    public native void    putShort(Object o, long offset, short x);
    public native char    getChar(Object o, long offset);
    public native void    putChar(Object o, long offset, char x);
    public native long    getLong(Object o, long offset);
    public native void    putLong(Object o, long offset, long x);
    public native float   getFloat(Object o, long offset);
    public native void    putFloat(Object o, long offset, float x);
    public native double  getDouble(Object o, long offset);
    public native void    putDouble(Object o, long offset, double x);
    public int getInt(Object o, int offset) {
    	throw new UnsupportedOperationException();
    }
    public void putInt(Object o, int offset, int x) {
    	throw new UnsupportedOperationException();
    }
    public Object getObject(Object o, int offset) {
    	throw new UnsupportedOperationException();
    }
    public void putObject(Object o, int offset, Object x) {
    	throw new UnsupportedOperationException();
    }
    public boolean getBoolean(Object o, int offset) {
    	throw new UnsupportedOperationException();
    }
    public void putBoolean(Object o, int offset, boolean x) {
    	throw new UnsupportedOperationException();
    }
    public byte getByte(Object o, int offset) {
    	throw new UnsupportedOperationException();
    }
    public void putByte(Object o, int offset, byte x) {
    	throw new UnsupportedOperationException();
    }
    public short getShort(Object o, int offset) {
    	throw new UnsupportedOperationException();
    }
    public void putShort(Object o, int offset, short x) {
    	throw new UnsupportedOperationException();
    }
    public char getChar(Object o, int offset) {
    	throw new UnsupportedOperationException();
    }
    public void putChar(Object o, int offset, char x) {
    	throw new UnsupportedOperationException();
    }
    public long getLong(Object o, int offset) {
    	throw new UnsupportedOperationException();
    }
    public void putLong(Object o, int offset, long x) {
    	throw new UnsupportedOperationException();
    }
    public float getFloat(Object o, int offset) {
    	throw new UnsupportedOperationException();
    }
    public void putFloat(Object o, int offset, float x) {
    	throw new UnsupportedOperationException();
    }
    public double getDouble(Object o, int offset) {
    	throw new UnsupportedOperationException();
    }
    public void putDouble(Object o, int offset, double x) {
    	throw new UnsupportedOperationException();
    }
    public native byte    getByte(long address);
    public native void    putByte(long address, byte x);
    public native short   getShort(long address);
    public native void    putShort(long address, short x);
    public native char    getChar(long address);
    public native void    putChar(long address, char x);
    public native int     getInt(long address);
    public native void    putInt(long address, int x);
    public native long    getLong(long address);
    public native void    putLong(long address, long x);
    public native float   getFloat(long address);
    public native void    putFloat(long address, float x);
    public native double  getDouble(long address);
    public native void    putDouble(long address, double x);
    public native long getAddress(long address);
    public native void putAddress(long address, long x);
    public native long allocateMemory(long bytes);
    public native long reallocateMemory(long address, long bytes);
    public native void setMemory(Object o, long offset, long bytes, byte value);
    public void setMemory(long address, long bytes, byte value) {
    	throw new UnsupportedOperationException();
    }
    public native void copyMemory(Object srcBase, long srcOffset,
                                  Object destBase, long destOffset,
                                  long bytes);
    public void copyMemory(long srcAddress, long destAddress, long bytes) {
    	throw new UnsupportedOperationException();
    }
    public native void freeMemory(long address);
    public static final int INVALID_FIELD_OFFSET   = -1;
    public int fieldOffset(Field f) {
    	throw new UnsupportedOperationException();
    }
    public Object staticFieldBase(Class<?> c) {
    	throw new UnsupportedOperationException();
    }
    public native long staticFieldOffset(Field f);
    public native long objectFieldOffset(Field f);
    public native Object staticFieldBase(Field f);
    public native boolean shouldBeInitialized(Class<?> c);
    public native void ensureClassInitialized(Class<?> c);
    public native int arrayBaseOffset(Class<?> arrayClass);
    public static final int ARRAY_BOOLEAN_BASE_OFFSET = badInit();
    public static final int ARRAY_BYTE_BASE_OFFSET = badInit();
    public static final int ARRAY_SHORT_BASE_OFFSET = badInit();
    public static final int ARRAY_CHAR_BASE_OFFSET = badInit();
    public static final int ARRAY_INT_BASE_OFFSET = badInit();
    public static final int ARRAY_LONG_BASE_OFFSET = badInit();
    public static final int ARRAY_FLOAT_BASE_OFFSET = badInit();
    public static final int ARRAY_DOUBLE_BASE_OFFSET = badInit();
    public static final int ARRAY_OBJECT_BASE_OFFSET = badInit();
    public native int arrayIndexScale(Class<?> arrayClass);
    public static final int ARRAY_BOOLEAN_INDEX_SCALE = badInit();
    public static final int ARRAY_BYTE_INDEX_SCALE = badInit();
    public static final int ARRAY_SHORT_INDEX_SCALE = badInit();
    public static final int ARRAY_CHAR_INDEX_SCALE = badInit();
    public static final int ARRAY_INT_INDEX_SCALE = badInit();
    public static final int ARRAY_LONG_INDEX_SCALE = badInit();
    public static final int ARRAY_FLOAT_INDEX_SCALE = badInit();
    public static final int ARRAY_DOUBLE_INDEX_SCALE = badInit();
    public static final int ARRAY_OBJECT_INDEX_SCALE = badInit();
    public native int addressSize();
    public static final int ADDRESS_SIZE = badInit();
    public native int pageSize();
    public native Class<?> defineClass(String name, byte[] b, int off, int len,
                                       ClassLoader loader,
                                       ProtectionDomain protectionDomain);
    public native Class<?> defineAnonymousClass(Class<?> hostClass, byte[] data, Object[] cpPatches);
    public native Object allocateInstance(Class<?> cls)
        throws InstantiationException;
    public native void monitorEnter(Object o);
    public native void monitorExit(Object o);
    public native boolean tryMonitorEnter(Object o);
    public native void throwException(Throwable ee);
    public final native boolean compareAndSwapObject(Object o, long offset,
                                                     Object expected,
                                                     Object x);
    public final native boolean compareAndSwapInt(Object o, long offset,
                                                  int expected,
                                                  int x);
    public final native boolean compareAndSwapLong(Object o, long offset,
                                                   long expected,
                                                   long x);
    public native Object getObjectVolatile(Object o, long offset);
    public native void    putObjectVolatile(Object o, long offset, Object x);
    public native int     getIntVolatile(Object o, long offset);
    public native void    putIntVolatile(Object o, long offset, int x);
    public native boolean getBooleanVolatile(Object o, long offset);
    public native void    putBooleanVolatile(Object o, long offset, boolean x);
    public native byte    getByteVolatile(Object o, long offset);
    public native void    putByteVolatile(Object o, long offset, byte x);
    public native short   getShortVolatile(Object o, long offset);
    public native void    putShortVolatile(Object o, long offset, short x);
    public native char    getCharVolatile(Object o, long offset);
    public native void    putCharVolatile(Object o, long offset, char x);
    public native long    getLongVolatile(Object o, long offset);
    public native void    putLongVolatile(Object o, long offset, long x);
    public native float   getFloatVolatile(Object o, long offset);
    public native void    putFloatVolatile(Object o, long offset, float x);
    public native double  getDoubleVolatile(Object o, long offset);
    public native void    putDoubleVolatile(Object o, long offset, double x);
    public native void    putOrderedObject(Object o, long offset, Object x);
    public native void    putOrderedInt(Object o, long offset, int x);
    public native void    putOrderedLong(Object o, long offset, long x);
    public native void unpark(Object thread);
    public native void park(boolean isAbsolute, long time);
    public native int getLoadAverage(double[] loadavg, int nelems);
    public final int getAndAddInt(Object o, long offset, int delta) {
    	throw new UnsupportedOperationException();
    }
    public final long getAndAddLong(Object o, long offset, long delta) {
    	throw new UnsupportedOperationException();
    }
    public final int getAndSetInt(Object o, long offset, int newValue) {
    	throw new UnsupportedOperationException();
    }
    public final long getAndSetLong(Object o, long offset, long newValue) {
    	throw new UnsupportedOperationException();
    }
    public final Object getAndSetObject(Object o, long offset, Object newValue) {
    	throw new UnsupportedOperationException();
    }
    public native void loadFence();
    public native void storeFence();
    public native void fullFence();
    
    private static int badInit() {
    	throw new UnsupportedOperationException();
    }
}
