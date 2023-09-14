#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2023, Oracle and/or its affiliates. All rights reserved.
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
#

from argparse import ArgumentParser

def parse_fd(fd, path="<fd>"):
    content = fd.read().decode('utf-8')
    return parse_string(content, path=path)

def parse_file(path):
  with open(path, "r") as f:
    return parse_fd(f, path)

def parse_string(content, path="<toml-string>"):
  parser = StomlParser()
  return parser.parse(path, content)

class Streamer:
  def __init__(self, path, content):
    self.path = path
    self.content = content
    self.lines = []
    self.line = ""
    self.row = 0
    self.column = 0
    self.pos = 0

  def terminate(self, message):
    row = self.row
    column = self.column
    self.slurp(len(self.content))
    raise RuntimeError(
        self.path + ":" + str(row + 1) + ":" + str(column) + ": " + message + "\n" +
        (self.lines[row] if row < len(self.lines) else ("<row " + str(row)) + ">") + "\n" +
        (" " * column) + "^" + "\n")

  def peek(self, ahead=0):
    if self.pos + ahead < len(self.content):
      return self.content[self.pos + ahead]
    return ""

  def pull(self, expected=None):
    if expected == None:
      self.slurp(1)
      return
    for i in range(0, len(expected)):
      if self.peek(i) != expected[i]:
        self.terminate("Unexpected string, expected '" + expected + "'")
    self.slurp(len(expected))

  def pullSpaces(self):
    while self.peek().isspace():
      self.pull()

  def slurp(self, count):
    for i in range(0, count):
      character = self.peek()
      if character == "\n" or character == "":
        self.lines.append(self.line)
        self.line = ""
        self.row = self.row + 1
        self.column = 0
      else:
        self.line = self.line + character
        self.column = self.column + 1
      self.pos = self.pos + 1

class StomlParser:
  def parse(self, path, content):
    rules = []
    streamer = Streamer(path, content);
    self.root(streamer, rules)
    return rules

  def root(self, streamer, rules):
    while True:
      while streamer.peek().isspace():
        streamer.pull()
      if streamer.peek() == "":
        return
      streamer.pull("[[rule]]")
      rule = self.rule(streamer)
      rules.append(rule)

  def rule(self, streamer):
    rule = {}
    while True:
      while streamer.peek().isspace():
        streamer.pull()
      if streamer.peek().isalpha():
        self.keyvalue(streamer, rule)
      else:
        return rule

  def keyvalue(self, streamer, rule):
    key = self.identifier(streamer)
    streamer.pullSpaces()
    streamer.pull("=")
    streamer.pullSpaces()
    if streamer.peek() == "\"":
      # string
      value = self.string(streamer)
    elif streamer.peek() == "[":
      # list of strings
      value = self.list(streamer)
    else:
      value = None
      streamer.terminate("Expected either a string or a list of strings.")
    rule[key] = value

  def identifier(self, streamer):
    ident = ""
    while streamer.peek().isalpha():
      ident = ident + streamer.peek()
      streamer.pull()
    return ident

  def string(self, streamer):
    streamer.pull("\"")
    content = ""
    while streamer.peek() != "\"":
      content = content + streamer.peek()
      streamer.pull()
    streamer.pull()
    return content

  def list(self, streamer):
    streamer.pull("[")
    values = []
    streamer.pullSpaces()
    while streamer.peek() != "]":
      streamer.pullSpaces()
      value = self.string(streamer)
      values.append(value)
      streamer.pullSpaces()
      if streamer.peek() == ",":
        streamer.pull()
        streamer.pullSpaces()
    streamer.pull()
    return values


if __name__ == "__main__":
  parser = ArgumentParser(
      prog="SimpleTOML parser.",
      description="Parses a simplified version of TOML.")
  parser.add_argument("filename")
  args = parser.parse_args()

  rules = parse_file(args.filename)
  print(rules)

