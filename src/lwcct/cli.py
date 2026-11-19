"""lwcct command line.

    lwcct build circuit.yaml -o out.cct [--lib blocks.clf] [--open]
    lwcct parts [filter]          list library parts and their pins
    lwcct info file.cct|file.clf  summarize a LogicWorks file
    lwcct open file.cct           open a file in LogicWorks
"""
import argparse
import os
import subprocess
import sys

from . import fmt
from .template import Template


def _open(path, lw=None):
    exe = os.path.join(Template(lw).root, 'LogicWorks.exe')
    # LogicWorks only accepts a quoted path when it contains non-ASCII characters
    subprocess.Popen('"%s" "%s"' % (exe, os.path.abspath(path)))


def cmd_build(a):
    from .spec import load_spec, build
    d = build(load_spec(a.spec), Template(a.logicworks), base=os.path.dirname(os.path.abspath(a.spec)))
    out = a.output or os.path.splitext(a.spec)[0] + '.cct'
    print('wrote %s (%d bytes)' % (out, d.save(out)))
    if a.lib:
        print('wrote %s (%d bytes)' % (a.lib, d.save_library(a.lib)))
    if a.open:
        _open(out, a.logicworks)


def cmd_parts(a):
    from .model import Design, DevType
    t = Template(a.logicworks)
    for name in sorted(t.types):
        if a.filter and a.filter.lower() not in name.lower():
            continue
        dt = DevType(name, t.types[name])
        pins = ' '.join('%s%s' % (p['name'], '>' if p['type'] else '') for p in dt.pins)
        print('%-24s %s' % (name, pins))


def cmd_info(a):
    data = open(a.file, 'rb').read()
    root = fmt.parse(data)[0]
    ok = fmt.dump([root]) == data
    print('%s: %d bytes, round-trip %s' % (a.file, len(data), 'ok' if ok else 'DIFFERS'))
    if root.kid('t'):  # library
        for u in root.kid('t').kids('u'):
            print('  part', u.kid('g').strings()[0].decode('cp949'))
        return
    for t in root.kids('8'):
        j = t.kid('j')
        if j:
            print('  type %-20s %s' % (j.strings()[0].decode('cp949'), 'block' if t.kid('E') else ''))
    e = root.kid('E')
    if e:
        print('  top: %d devices, %d signals' % (len(e.kids('<')), len(e.kids('B'))))


def cmd_open(a):
    _open(a.file, a.logicworks)


def main(argv=None):
    ap = argparse.ArgumentParser(prog='lwcct', description='LogicWorks 5 circuit generator')
    ap.add_argument('--logicworks', help='LogicWorks 5 folder (default: autodetect)')
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build', help='build .cct (and .clf) from a YAML/JSON spec')
    b.add_argument('spec')
    b.add_argument('-o', '--output')
    b.add_argument('--lib', help='also write blocks to this .clf library')
    b.add_argument('--open', action='store_true', help='open the result in LogicWorks')
    b.set_defaults(func=cmd_build)
    p = sub.add_parser('parts', help='list library parts')
    p.add_argument('filter', nargs='?')
    p.set_defaults(func=cmd_parts)
    i = sub.add_parser('info', help='summarize a .cct/.clf file')
    i.add_argument('file')
    i.set_defaults(func=cmd_info)
    o = sub.add_parser('open', help='open a file in LogicWorks')
    o.add_argument('file')
    o.set_defaults(func=cmd_open)
    a = ap.parse_args(argv)
    try:
        a.func(a)
    except (KeyError, ValueError, RuntimeError, FileNotFoundError) as e:
        print('error: %s' % (e.args[0] if e.args else e), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
