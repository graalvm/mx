# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2018, 2018, Oracle and/or its affiliates. All rights reserved.
# DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS FILE HEADER.
#
# This code is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 2 only, as
# published by the Free Software Foundation.
#
# This code is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
# version 2 for more details (a copy is included in the LICENSE file that
# accompanied this code).
#
# You should have received a copy of the GNU General Public License version
# 2 along with this work; if not, write to the Free Software Foundation,
# Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Please contact Oracle, 500 Oracle Parkway, Redwood Shores, CA 94065 USA
# or visit www.oracle.com if you need additional information or have any
# questions.
#
# ----------------------------------------------------------------------------------------------------

jdk_cache=$HOME/.mx/jdk_cache

# Usage: select_jdk <primary jdk dir> [<secondary jdk dirs>]
#            Sets the JAVA_HOME environment variable to <primary jdk dir>, prepends
#            $JAVA_HOME/bin to PATH and removes old $JAVA_HOME/bin if present. The
#            specified JDK directories are also saved to ~/.mx/jdk_cache.
#
#        select_jdk
#            Prompts for selection of one or more JDKs from ~/.mx/jdk_cache.
#            The selected JDKs are then processed as above.
#
# Assuming the directory containing mx.py is on your PATH, the select_jdk function can
# be sourced in your shell by adding this to $HOME/.bash_profile:
#
#   if [ -e $(dirname $(which mx))/select_jdk.bash ]; then
#     source $(dirname $(which mx))/select_jdk.bash
#   fi
#
function select_jdk {
  if [ "$#" -ne 0 ]; then
    __select_jdk_helper__ "$@"
  elif [ -e ${jdk_cache} ]; then
    index=1
    declare -a candidates
    tmp_cache=$HOME/.mx/jdk_cache.$$
    for jdk in $(cat ${jdk_cache} | sort | uniq); do
      if [ -d ${jdk} ]; then
        if [ ! -x ${jdk}/bin/java ]; then
          echo "Removing invalid JDK from cache: ${jdk}/bin/java not found or not executable"
        else
          echo "[$index] $jdk"
          candidates[$index]="$jdk"
          index=$(expr $index + 1)
          echo ${jdk} >>${tmp_cache}
        fi
      else
       echo "Removing invalid JDK from cache: ${jdk} not found or not a directory"
      fi
    done
    if [ $index != 1 ]; then
	  mv ${tmp_cache} ${jdk_cache}
      read -p 'Select JDK(s) (separate multiple choices by whitespace)> ' -a indexes
      declare -a jdks
      for index in "${indexes[@]}"; do
        if [ ${index} -ge 1 -a ${index} -le ${#candidates[@]} ]; then
          jdk=${candidates[${index}]}
          jdks+=(${jdk})
        else
          echo "Ignoring invalid selection: $index"
        fi
      done
      if [ ${#jdks[@]} -gt 0 ]; then
        __select_jdk_helper__ "${jdks[@]}"
      fi
    else
      echo "No valid JDKs in ${jdk_cache}. Provide one or more JDKs as arguments."
    fi
  fi
}


function __select_jdk_helper__ {
  if [ $# -eq 0 ]; then
    echo "error - expected 1 or more args to __select_jdk_helper__"
    return 1
  fi

  OLD_JH=$JAVA_HOME
  export JAVA_HOME=$1
  echo $JAVA_HOME >> ${jdk_cache}
  echo "JAVA_HOME=$JAVA_HOME"

  NEW_PATH=$JAVA_HOME/bin
  for i in ${PATH//:/ }; do
    if [ -z "$OLD_JH" -o "$i" != "$OLD_JH/bin" ]; then
      NEW_PATH=$NEW_PATH:$i
    fi
  done
  export PATH=$NEW_PATH

  if [ $# -gt 1 ]; then
    extra_jdks=("${@}")
    extra_jdks=(${extra_jdks[@]:1})
    for jdk in "${extra_jdks[@]}"; do
      echo ${jdk} >>${jdk_cache}
    done
    export EXTRA_JAVA_HOMES=${extra_jdks[@]}
    export EXTRA_JAVA_HOMES=${EXTRA_JAVA_HOMES// /:}
    echo "EXTRA_JAVA_HOMES=$EXTRA_JAVA_HOMES"
  fi
}
