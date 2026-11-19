"""Run with:  python -m unittest discover -s tests   (needs LogicWorks 5 installed)."""
import glob
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from lwcct import fmt, spec  # noqa: E402
from lwcct.symbol import auto_symbol  # noqa: E402
from lwcct.template import Template, find_logicworks  # noqa: E402

HERE = os.path.dirname(__file__)


def read(path):
    with open(path, 'rb') as f:
        return f.read()


EXAMPLES = os.path.join(HERE, '..', 'examples')

try:
    LW = find_logicworks()
except FileNotFoundError:
    LW = None
needs_lw = unittest.skipIf(LW is None, 'LogicWorks 5 not installed')

# Symbols written by LogicWorks' own auto-symbol tool (pins, pitch 10).
GOLDEN = {
    # 4x1 mux: I0..I3 left, S0 S1 bottom, Z right
    'mux': dict(args=('4X1MUX', ['I0', 'I1', 'I2', 'I3'], ['Z'], ['S0', 'S1']),
                kw=dict(width=80, right_y0=30, order=[4, 3, 2, 1, 7, 5, 6]),
                crc=0xA5412507, size=752),
}


class TestFormat(unittest.TestCase):
    @needs_lw
    def test_round_trip_installed_files(self):
        files = glob.glob(os.path.join(LW, 'Examples', '**', '*.[cC][cC][tT]'), recursive=True)
        files += glob.glob(os.path.join(LW, 'Libs', '*.[cC][lL][fF]'))
        self.assertTrue(files)
        for f in files:
            data = read(f)
            self.assertEqual(fmt.dump(fmt.parse(data)), data, f)


class TestSymbol(unittest.TestCase):
    def test_matches_logicworks_auto_symbol(self):
        import zlib
        for name, g in GOLDEN.items():
            blob, _, _ = auto_symbol(*g['args'], **g['kw'])
            self.assertEqual(len(blob), g['size'], name)
            self.assertEqual(zlib.crc32(blob), g['crc'], name)


@needs_lw
class TestBuild(unittest.TestCase):
    def test_examples_build_and_reparse(self):
        t = Template()
        for path in glob.glob(os.path.join(EXAMPLES, '*.yaml')):
            d = spec.build(spec.load_spec(path), t)
            with tempfile.TemporaryDirectory() as tmp:
                out = os.path.join(tmp, 'x.cct')
                lib = os.path.join(tmp, 'x.clf')
                d.save(out)
                d.save_library(lib)
                for f in (out, lib):
                    data = read(f)
                    self.assertEqual(fmt.dump(fmt.parse(data)), data, path)

    def test_repeated_block_and_clock(self):
        # instances of a block share one type; unconnected pins get a signal
        sp = {'blocks': {'DFF': {'title': 'D F/F', 'left': ['D', 'CLK'], 'right': ['Q', "Q'"],
                                 'parts': {'i': 'NOT', 'a': 'nand_2', 'b': 'nand_2', 'q': 'nand_2', 'r': 'nand_2'},
                                 'nets': [['D', 'i.INA', 'a.INA'], ['i.OUT', 'b.INA'], ['CLK', 'a.INB', 'b.INB'],
                                          ['a.Y', 'q.INA'], ['b.Y', 'r.INB'], ['q.Y', 'r.INA', 'Q'],
                                          ['r.Y', 'q.INB', "Q'"]]}},
              'top': {'parts': {'s': 'Binary Switch', 'c': 'Clock', 'f0': 'DFF', 'f1': 'DFF',
                                'p0': 'Binary Probe', 'p1': 'Binary Probe'},
                      'nets': [['s.Q0', 'f0.D', 'f1.D'], ['c.Q0', 'f0.CLK', 'f1.CLK'],
                               ['f0.Q', 'p0.D0'], ['f1.Q', 'p1.D0']]}}
        d = spec.build(sp, Template())
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'x.cct')
            d.save(out)
            top = fmt.load(out)[0]
        names = {t.kid('j').strings()[0]: t for t in top.kids('8')}
        self.assertNotIn(b'DFF_1', names)
        block_u = names[b'DFF'].kid('U').nums()
        used = [i for i in top.kid('E').kids('<') if i.kid('X').nums() == block_u]
        self.assertEqual(len(used), 2)
        flags = {p.kid('=').kid('G').nums()[0] for b in top.kid('E').kids('B')
                 for p in b.kid('@').kid('?').kids('>')}
        self.assertLessEqual(flags, {0xC, 0x14})  # pin stub flags LogicWorks understands
        with self.assertRaises(ValueError):
            spec.build({'blocks': {'D F/F': {'left': ['A'], 'right': ['Y']}}}, Template())

    @needs_lw
    def test_labels_join_pieces_into_one_signal(self):
        # remote connection: three pin stubs named CLK become one signal of three pieces
        sp = {'top': {'parts': {'c': 'Clock', 'a': 'NOT', 'b': 'NOT', 'pa': 'Binary Probe', 'pb': 'Binary Probe'},
                      'nets': [['a.OUT', 'pa.D0'], ['b.OUT', 'pb.D0']],
                      'labels': {'CLK': ['c.Q0', 'a.INA', 'b.INA']}}}
        d = spec.build(sp, Template())
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'x.cct')
            d.save(out)
            top = fmt.load(out)[0]
        sigs = top.kid('E').kids('B')
        self.assertEqual([b.nums()[0] for b in sigs], list(range(1, len(sigs) + 1)))
        named = [b for b in sigs if len(b.kid('@').kids('?')) > 1]
        self.assertEqual(len(named), 1)
        pieces = named[0].kid('@').kids('?')
        self.assertEqual(len(pieces), 3)
        for q in pieces:
            attr = q.kid(0x83)
            self.assertEqual(attr.kid('G').nums(), [0x151106])
            self.assertEqual(attr.kid('g').strings()[0], b'CLK')
            self.assertEqual(len(q.kids('>')), 1)   # one pin stub, no wire
            self.assertEqual(q.kids('='), [])

    def test_short_is_detected(self):
        from lwcct.model import Design
        d = Design(Template())
        a = d.top.add('Binary Switch', 0, 0)
        b = d.top.add('Binary Switch', 0, 700)
        p = d.top.add('Binary Probe', 2100, 0)
        x, y = a['Q0']
        d.top.wire([(a, 'Q0'), (p, 'D0')], [((x, y), (p['D0'][0], y)), ((p['D0'][0], y), p['D0'])])
        x2, y2 = b['Q0']
        d.top.wire([(b, 'Q0')], [((x2, y2), (x2, y))])  # ends on the other net's wire
        with self.assertRaises(ValueError):
            d.top.check()


if __name__ == '__main__':
    unittest.main()
