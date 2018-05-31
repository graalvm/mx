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

set jdk_cache $HOME/.mx/jdk_cache

# Usage: select_jdk <primary jdk dir> [<secondary jdk dirs>]
#            Sets the JAVA_HOME environment variable to <primary jdk dir>, prepends
#            $JAVA_HOME/bin to PATH and removes old $JAVA_HOME/bin if present. The
#            specified JDK directories are also saved to ~/.mx/jdks_cache.
#
#        select_jdk
#            Prompts for selection of one or more JDKs from ~/.mx/jdk_cache.
#            The selected JDKs are then processed as above.
#
# Assuming the directory containing mx.py is on your PATH, the select_jdk function can
# be sourced in your shell by adding this to $HOME/.config/fish/config.fish:
#
#   if test -e (dirname (which mx))/select_jdk.fish
#     source (dirname (which mx))/select_jdk.fish
#   end
#
function select_jdk
  if test (count $argv) -ne 0
    __select_jdk_helper__ $argv
  else if test -e $jdk_cache
    set index 1
    set candidates
    set pid %self
    set tmp_cache (echo $jdk_cache.$pid)
    for jdk in (cat $jdk_cache | sort | uniq)
      if test -d $jdk
        echo "[$index] $jdk"
        set candidates $candidates "$jdk"
        set index (expr $index + 1)
        echo $jdk >> $tmp_cache
      end
    end
    if test -e $tmp_cache
      mv $tmp_cache $jdk_cache
    end
    if test $index != 1
      read -p 'echo "Select JDK(s) (separate multiple choices by whitespace)> "' indexes_raw
      eval set indexes $indexes_raw
      set jdks
      for index in $indexes
        if test $index -ge 1 -a $index -le (count $candidates)
          set jdks $jdks $candidates[$index]
        else
          echo "Ignoring invalid selection: $index"
        end
      end
      if test (count $jdks) -gt 0
        __select_jdk_helper__ $jdks
      end
    end
  end
end

function __select_jdk_helper__
  set OLD_JH $JAVA_HOME
  set -x JAVA_HOME $argv[1]
  echo $JAVA_HOME >>$jdk_cache
  echo "JAVA_HOME=$JAVA_HOME"

  set NEW_PATH $JAVA_HOME/bin
  for i in $PATH
    if test -z "$OLD_JH" -o $i != $OLD_JH/bin
      set NEW_PATH $NEW_PATH $i
    end
  end
  set -x PATH $NEW_PATH

  if test (count $argv) -gt 1
    for jdk in $argv[2..(count $argv)]
      echo $jdk >>$jdk_cache
    end
    set -x EXTRA_JAVA_HOMES (echo $argv[2..(count $argv)] | tr ' ' ':')
    echo "EXTRA_JAVA_HOMES=$EXTRA_JAVA_HOMES"
  end
end
