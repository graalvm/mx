# A collections of commands that exercise some mx functions in the context of a particular set of suites.
# Incomplete

from argparse import ArgumentParser
import os
import mx

from html.parser import HTMLParser
from urllib.request import urlopen

_suite = mx.suite('mxtests')

def _build(args):
    mx.primary_suite().build(args)

def _cp(args):
    parser = ArgumentParser(prog='mx mxt-classpath')
    parser.add_argument('--project', action='store', help='name of entity')
    parser.add_argument('--noResolve', action='store_true', help='noResolve')
    parser.add_argument('--ignoreSelf', action='store_true', help='ignoreSelf')
    args = parser.parse_args(args)
    result = mx.classpath(args.project, resolve=not args.noResolve, includeSelf=not args.ignoreSelf)
    print('classpath for: ', args.project)
    comps = result.split(':')
    for comp in comps:
        print(comp)

def _ap(args):
    parser = ArgumentParser(prog='mx mxt-proj-ap-path')
    parser.add_argument('--project', action='store', help='name of entity')
    args = parser.parse_args(args)
    project = mx.project(args.project)
    result = project.annotation_processors_path()
    print('annotation_processors_path for: ', args.project)
    comps = result.split(':')
    for comp in comps:
        print(comp)

def _alldeps(args):
    parser = ArgumentParser(prog='mx mxt-alldeps')
    parser.add_argument('--kind', action='store', help='project, dist or library', default='project')
    parser.add_argument('--name', action='store', help='name of entity', required=True)
    parser.add_argument('--includeLibs', action='store_true', help='includeLibs')
    parser.add_argument('--ignoreSelf', action='store_true', help='ignoreSelf')
    args = parser.parse_args(args)
    entity = None
    if args.kind == 'project':
        entity = mx.project(args.name)
    elif args.kind == 'library':
        entity = mx.library(args.name)
    elif args.kind == 'dist':
        entity = mx.distribution(args.name)
    else:
        mx.abort('illegal kind: ' + args.kind)

    in_deps = []
    deps = entity.all_deps(in_deps, includeLibs=args.includeLibs, includeSelf=not args.ignoreSelf)
    print('alldeps:')
    for d in deps:
        print(d.__class__.__name__, ":", d.name)

class MyHTMLParser(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self)
    def handle_starttag(self, tag, attrs):
        print("Start tag:", tag)
        for attr in attrs:
            print("     attr:", attr)
    def handle_endtag(self, tag):
        print("End tag  :", tag)

class DirHTMLParser(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self)
        self.files = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            for attr in attrs:
                if attr[0] == 'href':
                    name = attr[1]
                    self.files.append(name)

def _readurl(args):
    parser = ArgumentParser(prog='mx mxt-readurl')
    parser.add_argument('--url', action='store', help='target url', required=True)
    parser.add_argument('--print-tags', action='store_true', help='print all tags')
    args = parser.parse_args(args)
    if 'file://' in args.url:
        for f in os.listdir(args.url.replace('file://', '')):
            print(f)
    else:
        f = urlopen(args.url)
        text = f.read()
        parser = MyHTMLParser() if args.print_tags else DirHTMLParser()
        parser.feed(text)
        if not args.print_tags:
            for f in parser.files:
                print(f)

def _vc_clone(args):
    parser = ArgumentParser(prog='mx mxt-vc-clone')
    parser.add_argument('--url', action='store', help='repo url', required=True)
    parser.add_argument('--target', action='store', help='target dir')
    parser.add_argument('--rev', action='store', help='revision')
    parser.add_argument('--kind', action='store', help='vc kind (hg, git)', default='hg')
    parser.add_argument('--log', action='store', help='log command output', default='True')
    args = parser.parse_args(args)
    vc = mx.vc_system(args.kind)
    rc = vc.clone(args.url, args.target, args.rev, args.log == 'True')
    print(rc)

def _vc_pull(args):
    parser = ArgumentParser(prog='mx mxt-vc-pull')
    parser.add_argument('--no-update', action='store_true', help='do not update')
    parser.add_argument('--dir', action='store', help='repo url', default=os.getcwd())
    parser.add_argument('--kind', action='store', help='vc kind (hg, git)', default='hg')
    args = parser.parse_args(args)
    vc = mx.vc_system(args.kind)
    vc.pull(args.dir, update=not args.no_update)

def _vc_tip(args):
    parser = ArgumentParser(prog='mx mxt-vc-tip')
    parser.add_argument('--dir', action='store', help='repo url', default=os.getcwd())
    parser.add_argument('--kind', action='store', help='vc kind (hg, git, binary)', default='hg')
    args = parser.parse_args(args)
    vc = mx.vc_system(args.kind)
    rc = vc.tip(args.dir)
    print(rc)

def _vc_locate(args):
    parser = ArgumentParser(prog='mx mxt-vc-locate')
    parser.add_argument('--dir', action='store', help='repo url', default=os.getcwd())
    parser.add_argument('--vind', action='store', help='vc kind (hg, git)', default='hg')
    parser.add_argument('--patterns', action='store', help='patterns)')
    args = parser.parse_args(args)
    vc = mx.vc_system(args.kind)
    lines = vc.locate(args.dir, patterns=args.patterns)
    for line in lines:
        print(line)

def _command_info(args):
    parser = ArgumentParser(prog='mx mxt-command_function')
    parser.add_argument('--command', action='store', help='command', required=True)
    args = parser.parse_args(args)
    mx.command_function(args.command)

mx.update_commands(_suite, {
    # overrides
    "build" : [_build, '[options]'],
    # new commands
    "mxt-alldeps" : [_alldeps, '[options]'],
    "mxt-classpath" : [_cp, '[options]'],
    "mxt-proj-ap-path" : [_ap, '[options]'],
    "mxt-readurl" : [_readurl, '[options]'],
    "mxt-vc-tip" : [_vc_tip, '[options]'],
    "mxt-vc-clone" : [_vc_clone, '[options]'],
    "mxt-vc-locate" : [_vc_locate, '[options]'],
    'mxt-command-info' : [_command_info, '[options]'],
})
