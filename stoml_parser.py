
from argparse import ArgumentParser

def parse_file(path):
  with open(path, "r") as f:
    content = f.read()
    return parse_string(content, path=path)

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
        self.lines[row] + "\n" +
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
      if character == "\n":
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

