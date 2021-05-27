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
#include <stdbool.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <time.h>
#include <limits.h>
#include <pthread.h>
#include <sys/errno.h>
#include <arpa/inet.h>

#include <jni.h>
#include <jvmti.h>
#include <jvmticmlr.h>


// This a simple JVMTI agent for the efficient capture of assembly into a binary file.  It captures
// all available assembly informmation into a simple format for later decoding.

// This utility macro quotes the passed string
#define QUOTE(x) #x
#define QUOTE2(x) QUOTE(x)
#ifndef JVMTI_ASM_ARCH
  #error Build must define JVMTI_ASM_ARCH
#endif
static char* arch = QUOTE2(JVMTI_ASM_ARCH);

// The file containing the captured assembly.  During JVM shutdown this could become NULL so it must
// be checked before use while holding the file lock.
static FILE* output_file = NULL;
// A global lock protecting access to output_file
static pthread_mutex_t file_lock = PTHREAD_MUTEX_INITIALIZER;
// The global handle to the JVMTI environment
static jvmtiEnv *jvmti = NULL;

// File header format
static char* filetag = "JVMTIASM";
static int MajorVersion = 1;
static int MinorVersion = 0;

#define TAG_VALUE(t, shift) (((int)(t) & 0xff) << shift)
#define BUILD_TAG(a, b, c, d) (TAG_VALUE(a, 24) | TAG_VALUE(b, 16) | TAG_VALUE(c, 8) | TAG_VALUE(d, 0))

// Marker values for various data sections in the output file
static int DynamicCodeTag          = BUILD_TAG('D', 'Y', 'N', 'C');
static int CompiledMethodLoadTag   = BUILD_TAG('C', 'M', 'L', 'T');
static int MethodsTag              = BUILD_TAG('M', 'T', 'H', 'T');
static int DebugInfoTag            = BUILD_TAG('D', 'E', 'B', 'I');
static int CompiledMethodUnloadTag = BUILD_TAG('C', 'M', 'U', 'T');

// Cache of JVMTI information for a jmethodID
typedef struct MethodData {
  int id;
  jmethodID method;
  char *source_file;
  char *method_name;
  char *method_signature;
  char *class_signature;
  jint line_number_table_count;
  jvmtiLineNumberEntry *line_number_table;
  struct MethodData* next;
} MethodData;


static void report_error(const char* format, ...) {
  va_list ap;
  va_start(ap, format);
  fprintf(stderr, "Error: ");
  vfprintf(stderr, format, ap);
  fprintf(stderr, "\n");
  abort();
}

static void jvmti_report_error(const char* message, jvmtiError result) {
  char* error_name;
  (*jvmti)->GetErrorName(jvmti, result, &error_name);
  report_error("%s: %s", message, error_name);
}


static void free_method(MethodData* method) {
  // The data elements are allocated by JVMTI but the record itself allocated by calloc
  if (method->source_file) {
    (*jvmti)->Deallocate(jvmti, (unsigned char *)method->source_file);
  }
  if (method->method_name) {
    (*jvmti)->Deallocate(jvmti, (unsigned char *)method->method_name);
  }
  if (method->method_signature) {
    (*jvmti)->Deallocate(jvmti, (unsigned char *)method->method_signature);
  }
  if (method->class_signature) {
    (*jvmti)->Deallocate(jvmti, (unsigned char *)method->class_signature);
  }
  if (method->line_number_table) {
    (*jvmti)->Deallocate(jvmti, (unsigned char *)method->line_number_table);
  }
  free(method);
}


// Certain JVMIT errors represent missing information so don't treat them as hard errors.  Almost
// everything else is a real hard error or at least can't be handled as anything else.
// JVMTI_ERROR_WRONG_PHASE occurs when JVMTI is in the process of shutting down which should be
// handled by simply unwinding the call without producing any data or reporting any errors.
static bool check_method_error(const char* message, jvmtiError result, MethodData* method) {
  if (result != JVMTI_ERROR_NONE && result != JVMTI_ERROR_NATIVE_METHOD && result != JVMTI_ERROR_ABSENT_INFORMATION) {
    if (result == JVMTI_ERROR_WRONG_PHASE) {
      // Cleanup the storage for this method.  This calls JVMTI Deallocate which doesn't seem to care about
      // being called during JVMTI_ERROR_WRONG_PHASE.  Alternatively the storage could just leak and it
      // probably wouldn't matter.
      free_method(method);
      return true;
    }
    jvmti_report_error(message, result);
    return true;
  }
  return false;
}


// Find or cache the information associated with a jmethodID.  The JVMTI data required to describe a
// method is cached in a simple linked list which is built during each notification.
static MethodData* lookup_method(jvmtiEnv* jvmti, jmethodID method, MethodData** methods, jint* methods_count) {
  // The number of unique methods is relatively short so just do a linear search
  jvmtiError result;
  MethodData* current = *methods;
  MethodData* last = NULL;
  while (current != NULL) {
    if (current->method == method) {
      return current;
    }
    last = current;
    current = current->next;
  }
  current = calloc(1, sizeof(MethodData));
  current->method = method;
  result = (*jvmti)->GetMethodName(jvmti, method, &current->method_name, &current->method_signature, NULL);
  if (check_method_error("GetMethodName", result, current)) {
    return NULL;
  }
  jclass class;
  result = (*jvmti)->GetMethodDeclaringClass(jvmti, method, &class);
  if (check_method_error("GetMethodDeclaringClass", result, current))  {
    return NULL;
  }
  result = (*jvmti)->GetClassSignature(jvmti, class, &current->class_signature, NULL);
  if (check_method_error("GetClassSignature", result, current))  {
    return NULL;
  }
  result = (*jvmti)->GetSourceFileName(jvmti, class, &current->source_file);
  if (check_method_error("GetSourceFileName", result, current))  {
    return NULL;
  }
  result = (*jvmti)->GetLineNumberTable(jvmti, method, &current->line_number_table_count, &current->line_number_table);
  if (check_method_error("GetLineNumberTable", result, current))  {
    return NULL;
  }
  if (*methods == NULL) {
    // Set the head of the list
    *methods = current;
  } else {
    // Add the current entry onto the end of the list
    current->id = last->id + 1;
    last->next = current;
  }
  (*methods_count)++;
  return current;
}


static void lock_output_file() {
  int err = pthread_mutex_lock(&file_lock);
  if (err != 0) {
    report_error("Error locking file: %s", strerror(err));
  }
}

static void unlock_output_file() {
  int err = pthread_mutex_unlock(&file_lock);
  if (err != 0) {
    report_error("Error unlocking file: %s", strerror(err));
  }
}

static const char* usage_message = \
"JVMTI assembly capture agent\n"
  "Usage: java -agentpath=libjvmtiasmagent.so=<filename>\n"
"    The filename argument is non-optional and may contain '%p'\n"
"    which will be replaced by the pid of the current process.";


static void usage(const char* message) {
  if (message != NULL) {
    printf("Error: %s\n", message);
  }
  printf("%s\n", usage_message);
  exit(1);
}

// Utilities for writing data to the output file.

// Any error is simply considered a hard error because it represents a loss of data
static void write_or_fail(const void* data, int bytes) {
  if (fwrite(data, bytes, 1, output_file) != 1) {
    report_error("failed to write bytes: %s", strerror(errno));
  }
}

static void write_jint(jint value) {
  value = htonl(value);
  write_or_fail(&value, sizeof(value));
}

static void write_unsigned_jlong(jlong value) {
  if (1 != htonl(1)) {
    // There's no platform independent htonll so swap it manually
    jint lo = (jint)value;
    jint hi = (jint)(value >> 32);
    write_jint(hi);
    write_jint(lo);
  } else {
    // native order is same as network order
    write_or_fail(&value, sizeof(value));
  }
}

static void write_string(const char* str, const char* message) {
  if (str == NULL) {
    report_error("Unexpected NULL string for \"%s\"", message);
  }
  size_t full_len = strlen(str);
  // We could support full 64 bit length strings but that seems kind of pointless.
  if (full_len > INT_MAX) {
    report_error("String length is longer than an int");
  }
  jint len = (jint) full_len;
  write_jint(len);
  if (len > 0) {
    write_or_fail(str, len);
  }
}

static void write_string_or_null(const char* str) {
  if (str == NULL) {
    // 0 length means the empty string so use -1 for an actual NULL
    write_jint(-1);
  } else {
    write_string(str, NULL);
  }
}


// Timestamps are used to match events between multiple data sources so it's important to choose a
// clock that can match with whatever clock the system profiler uses.

#if defined(__linux__)
// On linux, timestamps in the file use the CLOCK_MONOTONIC which is a non adjustable clock.
clockid_t timestamp_clock = CLOCK_MONOTONIC;
#elif defined(__APPLE__) && defined(__MACH__) // Apple OSX and iOS (Darwin)
// The mac isn't currently supported for profiling but Instruments seems to report times based on
// gettimeofday which is the same as CLOCK_REALTIME so use that for now.
clockid_t timestamp_clock = CLOCK_REALTIME;
#else
#error "Unsupported platform"
#endif

static struct timespec get_timestamp() {
  struct timespec ts;
  int ret = clock_gettime(timestamp_clock, &ts);
  if (ret) {
    report_error("Error while writing timestamp: clock_gettime %s", strerror(errno));
  }
  return ts;
}

static void write_timestamp(struct timespec ts) {
  write_unsigned_jlong(ts.tv_sec);
  write_unsigned_jlong(ts.tv_nsec);
}

static void write_file_header() {
  write_or_fail(filetag, 8);
  write_jint(MajorVersion);
  write_jint(MinorVersion);
  write_string(arch, "architecture");
  jlong nanos;
  jvmtiError error = (*jvmti)->GetTime(jvmti, &nanos);
  if (error != JVMTI_ERROR_NONE) {
    jvmti_report_error("GetTime", error);
  }
  // Record the relationship between the Java times and our timestamp.
  write_timestamp(get_timestamp());
  write_unsigned_jlong(nanos);
}

static void JNICALL
compiledMethodUnload(jvmtiEnv *jvmti,
                     jmethodID method,
                     const void* code_addr) {
  struct timespec timestamp = get_timestamp();
  lock_output_file();
  if (output_file != NULL) {
    // Unlock events simply mark a previously reported code address as no longer being in use
    write_jint(CompiledMethodUnloadTag);
    write_timestamp(timestamp);
    write_unsigned_jlong((intptr_t)code_addr);
    fflush(output_file);
  }
  unlock_output_file();
}


// Write the captured assembly along with any Java metadata.
static void write_method_load_event(struct timespec timestamp, jint code_size,
                                    const void* code_addr,
                                    int methods_count,
                                    MethodData* methods,
                                    jvmtiCompiledMethodLoadInlineRecord *inline_records) {
  lock_output_file();
  if (output_file != NULL) {
    write_jint(CompiledMethodLoadTag);
    write_timestamp(timestamp);
    write_unsigned_jlong((intptr_t) code_addr);
    write_jint(code_size);
    write_or_fail(code_addr, code_size);

    // Emit all the methods seen
    write_jint(MethodsTag);
    write_jint(methods_count);
    for (MethodData* current = methods; current != NULL; current = current->next) {
      write_string(current->class_signature, "class_signature");
      write_string(current->method_name, "method_name");
      write_string(current->method_signature, "method_signature");
      write_string_or_null(current->source_file);
      write_jint(current->line_number_table_count);
      for (int i = 0; i < current->line_number_table_count; i++) {
        write_unsigned_jlong(current->line_number_table[i].start_location);
        write_jint(current->line_number_table[i].line_number);
      }
    }

    // Record the debug informmation with reference back to the previously recorded methods
    write_jint(DebugInfoTag);
    if (inline_records) {
      write_jint(inline_records->numpcs);
      for (int i = 0; i < inline_records->numpcs; i++) {
        PCStackInfo *info = &inline_records->pcinfo[i];
        write_unsigned_jlong((intptr_t) info->pc);
        write_jint(info->numstackframes);
        for (int j = 0; j < info->numstackframes; j++) {
          MethodData* method = lookup_method(jvmti, info->methods[j], &methods, &methods_count);
          write_jint(method->id);
          write_jint(info->bcis[j]);
        }
      }
    } else {
      write_jint(0);
    }
    fflush(output_file);
  }
  unlock_output_file();
}


static void JNICALL
compiledMethodLoad(jvmtiEnv *jvmti,
                   jmethodID method,
                   jint code_size,
                   const void* code_addr,
                   jint map_length,
                   const jvmtiAddrLocationMap* map,
                   const void* compile_info) {
  // Capture the timestamp early so that the timestamp is close to the actual time.
  struct timespec timestamp = get_timestamp();

  jvmtiCompiledMethodLoadInlineRecord *inline_records = NULL;
  MethodData* methods = NULL;
  jint methods_count = 0;
  if (lookup_method(jvmti, method, &methods, &methods_count) == NULL) {
    // A JVMTI_ERROR_WRONG_PHASE occurred during lookup so just skip this operation
    goto cleanup;
  }

  if (compile_info != NULL) {
    // Collect information on every method seen in the debug information
    const jvmtiCompiledMethodLoadRecordHeader *header = compile_info;
    while (header) {
      if (header->kind == JVMTI_CMLR_INLINE_INFO) {
        inline_records = (jvmtiCompiledMethodLoadInlineRecord *) header;
        for (int i = 0; i < inline_records->numpcs; i++) {
          PCStackInfo *info = &inline_records->pcinfo[i];
          for (int j = 0; j < info->numstackframes; j++) {
            if (lookup_method(jvmti, info->methods[j], &methods, &methods_count) == NULL) {
              // A JVMTI_ERROR_WRONG_PHASE occurred during lookup so just skip this operation
              goto cleanup;
            }
          }
        }
        break;
      }
      header = header->next;
    }
  }

  write_method_load_event(timestamp, code_size, code_addr, methods_count, methods, inline_records);

 cleanup:
  // Release the method information that was collected
  while (methods != NULL) {
    MethodData* next = methods->next;
    free_method(methods);
    methods = next;
  }
}

void JNICALL
dynamicCodeGenerated(jvmtiEnv *jvmti,
                     const char* name,
                     const void* code_addr,
                     jint code_size) {
  struct timespec timestamp = get_timestamp();
  lock_output_file();
  if (output_file != NULL) {
    write_jint(DynamicCodeTag);
    write_timestamp(timestamp);
    write_string(name, "dynamic code name");
    write_unsigned_jlong((intptr_t) code_addr);
    write_jint(code_size);
    write_or_fail(code_addr, code_size);
    fflush(output_file);
  }
  unlock_output_file();
}

JNIEXPORT jint JNICALL
Agent_OnLoad(JavaVM *jvm, char *options, void *reserved) {
  if (options == NULL) {
    usage("Must specify an output file name");
  }

  if (strcmp(options, "-h") == 0 ||
      strcmp(options, "--help") == 0) {
    usage(NULL);
  }


  (*jvm)->GetEnv(jvm, (void **)&jvmti, JVMTI_VERSION_1);

  jvmtiError error;
  jvmtiCapabilities capabilities;
  memset(&capabilities, 0, sizeof(capabilities));
  capabilities.can_get_source_file_name            = 1;
  capabilities.can_get_line_numbers                = 1;
  capabilities.can_generate_compiled_method_load_events = 1;

  // Configure the required capabilities
  error = (*jvmti)->AddCapabilities(jvmti, &capabilities);
  if (error != JVMTI_ERROR_NONE) {
    jvmti_report_error("AddCapabilities", error);
  }

  jvmtiEventCallbacks callbacks;
  memset(&callbacks, 0, sizeof(callbacks));
  callbacks.CompiledMethodLoad   = &compiledMethodLoad;
  callbacks.CompiledMethodUnload = &compiledMethodUnload;
  callbacks.DynamicCodeGenerated = &dynamicCodeGenerated;

  // Acquire the file lock early
  lock_output_file();

  error = (*jvmti)->SetEventCallbacks(jvmti, &callbacks, (jint)sizeof(callbacks));
  if (error != JVMTI_ERROR_NONE) {
    jvmti_report_error("SetEventCallbacks", error);
  }
  error = (*jvmti)->SetEventNotificationMode(jvmti, JVMTI_ENABLE, JVMTI_EVENT_COMPILED_METHOD_UNLOAD, (jthread)NULL);
  if (error != JVMTI_ERROR_NONE) {
    jvmti_report_error("SetEventNotificationMode JVMTI_EVENT_COMPILED_METHOD_UNLOAD", error);
  }
  error = (*jvmti)->SetEventNotificationMode(jvmti, JVMTI_ENABLE, JVMTI_EVENT_COMPILED_METHOD_LOAD, (jthread)NULL);
  if (error != JVMTI_ERROR_NONE) {
    jvmti_report_error("SetEventNotificationMode JVMTI_EVENT_COMPILED_METHOD_LOAD", error);
  }
  error = (*jvmti)->SetEventNotificationMode(jvmti, JVMTI_ENABLE, JVMTI_EVENT_DYNAMIC_CODE_GENERATED, (jthread)NULL);
  if (error != JVMTI_ERROR_NONE) {
    jvmti_report_error("SetEventNotificationMode JVMTI_EVENT_DYNAMIC_CODE_GENERATED", error);
  }

  const char* filename = options;
  const char* pid_location = strstr(options, "%p");
  if (pid_location != NULL) {
    int pid = getpid();
    char buffer[32];
    snprintf(buffer, 32, "%d", pid);
    char * name = malloc(strlen(options) + strlen(buffer) + 1);
    *name = '\0';
    strncat(name, options, pid_location - options);
    strcat(name, buffer);
    strcat(name, pid_location + 2);
    filename = name;
  }

  output_file = fopen(filename, "w");
  if (output_file == NULL) {
    report_error("Error opening output file: %s", strerror(errno));
  }
  if (filename != options) {
    free((void*) filename);
  }
  write_file_header();

  fflush(output_file);

  // Everything is setup so release the lock
  unlock_output_file();

  return 0;
}

JNIEXPORT void JNICALL
Agent_OnUnload(JavaVM *jvm) {
  lock_output_file();
  fclose(output_file);
  output_file = NULL;
  unlock_output_file();
}
