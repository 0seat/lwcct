"""Circuit model and .cct / .clf writers.

Coordinates are LogicWorks internal units (14 units = 1 screen pixel at 100 %,
grid = 70 units, y grows downward). A pin's connection point is
device origin + pin offset + pin direction * pin length.
"""
import copy
import os
import zlib

from . import fmt
from .nodes import n_, set_nums, set_g, is_
from .symbol import auto_symbol, PX
from .template import Template, PIN_LEN, lib_to_design_type

BBOX_MARGIN = 0x5B
GRID = 70
BLOCK_CODE = 0x48
CLOCK_CODE = 0xC
IO_TYPES = {'Port In', 'Port Out', 'Binary Switch', 'Binary Probe'}

# pin "I" field -> unit direction of the pin stub
DIRS = {None: (1, 0), 3: (1, 0), 2: (-1, 0), 1: (0, 1), 0: (0, -1)}
SIDE = {None: 'R', 3: 'R', 2: 'L', 1: 'B', 0: 'T'}


class DevType:
    """A device type usable in circuits (library primitive or block)."""

    def __init__(self, name, node):
        self.name, self.node = name, node
        self.pins = []
        for p in node.kid('9').kids('7'):
            i = p.kid('I')
            self.pins.append({'name': p.kid('h').strings()[0].decode('cp949'),
                              'x': p.kid('W').nums()[0], 'y': p.kid('W').nums()[1],
                              'side': i.nums()[0] if i else None,
                              'type': p.kid(0x88).nums()[0]})
        self.block_size = None  # (w, h) in units for generated blocks

    def pin(self, name):
        for k, p in enumerate(self.pins, 1):
            if p['name'] == name:
                return k, p
        raise KeyError('%s has no pin %s (pins: %s)' % (self.name, name, ', '.join(q['name'] for q in self.pins)))

    def box(self):
        """Bounding box (x0, y0, x1, y1) relative to origin, including pin stubs."""
        xs, ys = [0], [0]
        if self.block_size:
            xs.append(self.block_size[0])
            ys.append(self.block_size[1])
        for p in self.pins:
            dx, dy = DIRS[p['side']]
            xs += [p['x'], p['x'] + dx * PIN_LEN]
            ys += [p['y'], p['y'] + dy * PIN_LEN]
        return min(xs), min(ys), max(xs), max(ys) + GRID


class Inst:
    def __init__(self, circuit, name, dtype, x=None, y=None, label=None):
        self.c, self.name, self.dtype, self.x, self.y, self.label = circuit, name, dtype, x, y, label
        self.num = None

    def pin_geom(self, name):
        """-> (index, P, outer) for a pin."""
        k, p = self.dtype.pin(name)
        px, py = self.x + p['x'], self.y + p['y']
        dx, dy = DIRS[p['side']]
        return k, (px, py), (px + dx * PIN_LEN, py + dy * PIN_LEN)

    def __getitem__(self, name):
        return self.pin_geom(name)[2]

    def __repr__(self):
        return '<%s %s>' % (self.dtype.name, self.name)


class Net:
    def __init__(self, name, pins, segs=None, label=None):
        self.name, self.pins, self.segs = name, list(pins), list(segs or [])
        self.label = label  # signal name shown in the drawing; joins same-named nets


def on_seg(p, s):
    (x1, y1), (x2, y2) = s
    if x1 == x2 == p[0]:
        return min(y1, y2) <= p[1] <= max(y1, y2)
    if y1 == y2 == p[1]:
        return min(x1, x2) <= p[0] <= max(x1, x2)
    return False


class Circuit:
    def __init__(self, design, name='top'):
        self.d, self.name = design, name
        self.insts = []
        self.nets = []

    def add(self, type_name, x=None, y=None, label=None, name=None):
        inst = Inst(self, name or '%s%d' % (type_name, len(self.insts)), self.d.dtype(type_name), x, y, label)
        self.insts.append(inst)
        return inst

    def connect(self, pins, name=None):
        """Logical connection; geometry is filled in by layout.route()."""
        self.nets.append(Net(name or 'N%d' % len(self.nets), pins))

    # -- explicit wiring -------------------------------------------------
    def wire(self, pins, segs, name=None):
        self.nets.append(Net(name, pins, [tuple(map(tuple, s)) for s in segs]))

    def label(self, name, pins):
        """Connect pins by a signal name instead of a drawn wire (a remote connection):
        each pin gets only its stub, with `name` written at the stub's outer end, and
        LogicWorks joins all pieces of the same name into one signal."""
        for pin in pins:
            self.nets.append(Net(name, [pin], label=name))

    def track(self, pins, x, name=None):
        """Route all pins to a vertical track at x with horizontal stubs."""
        pts = [i[p] for i, p in pins]
        segs = [((px, py), (x, py)) for px, py in pts if px != x]
        ys = sorted({y for _, y in pts})
        segs += [((x, a), (x, b)) for a, b in zip(ys, ys[1:])]
        self.wire(pins, segs, name)

    def path(self, a, b, via=(), name=None):
        pts = [a[0][a[1]]] + list(via) + [b[0][b[1]]]
        self.wire([a, b], [(p, q) for p, q in zip(pts, pts[1:]) if p != q], name)

    # -- checks ------------------------------------------------------------
    def check(self):
        """Raise ValueError on diagonal wires, broken nets or shorts between nets."""
        allsegs = []
        for n in self.nets:
            segs = list(n.segs)
            for inst, p in n.pins:
                _, P, outer = inst.pin_geom(p)
                segs.append((P, outer))
            for s in n.segs:
                if not (s[0][0] == s[1][0] or s[0][1] == s[1][1]):
                    raise ValueError('net %s: diagonal segment %s' % (n.name, s))
            allsegs.append((n, segs))
            pts = sorted({e for s in n.segs for e in s} | {inst[p] for inst, p in n.pins})
            parent = {p: p for p in pts}

            def find(p):
                while parent[p] != p:
                    parent[p] = parent[parent[p]]
                    p = parent[p]
                return p
            for s in n.segs:
                for p in pts:
                    if on_seg(p, s):
                        parent[find(p)] = find(s[0])
            if len({find(inst[p]) for inst, p in n.pins}) != 1:
                raise ValueError('net %s is not connected' % n.name)
        for n1, s1 in allsegs:
            ends = {e for s in s1 for e in s}
            for n2, s2 in allsegs:
                if n1 is n2:
                    continue
                for p in ends:
                    for s in s2:
                        if on_seg(p, s):
                            raise ValueError('nets %s and %s touch at %s' % (n1.name, n2.name, p))


class Design:
    def __init__(self, template=None):
        self.t = template or Template()
        self.top = Circuit(self)
        self._types = {}
        self._order = []
        self._uid = {}
        self.subcircuits = []
        self._imported = []  # block types taken whole from a .clf library

    def _alloc_u(self, code):
        self._uid[code] = self._uid.get(code, 0) + 1
        return self._uid[code]

    def parts(self):
        return sorted(self.t.types)

    def dtype(self, name):
        if name not in self._types:
            if name not in self.t.types:
                raise KeyError('unknown part %r' % name)
            node = copy.deepcopy(self.t.types[name])
            code = node.kid('U').nums()[0]
            set_nums(node.kid('U'), code, self._alloc_u(code))
            self._types[name] = DevType(name, node)
            self._order.append(node)
        return self._types[name]

    def use_library(self, path, names=None):
        """Make parts of a .clf library (e.g. a shared parts library) usable by name.

        A library part is a symbol header plus a small design holding its
        internal circuit and every type that circuit uses, inner types first.
        Those types are adopted here (primitives map onto this design's own,
        nested blocks come along) with their type numbers rewritten; object ids
        are renumbered when the file is written. Returns the names added.
        """
        root = fmt.load(path)[0]
        headers = {t.kid(0x8f).strings()[0].decode('cp949').strip(): t
                   for t in root.kids('8') if t.kid(0x8f)}
        payloads = {p.kid(0x8f).strings()[0].decode('cp949').strip(): p.kid(0x8b).items[0].data
                    for p in root.kids(0x8e)}
        wanted = list(headers) if names is None else list(names)
        for name in wanted:
            if name not in headers:
                raise KeyError('part %r not in %s (has: %s)' % (name, path, ', '.join(headers)))
            if name in self._types:
                continue
            items = [n for n in fmt.parse(payloads[name])[0].items if isinstance(n, fmt.Node)]
            remap = {}  # payload type number -> this design's
            for t in (i for i in items if is_(i, '8')):
                old = tuple(t.kid('U').nums())
                remap[old] = tuple(self._adopt(t, remap).node.kid('U').nums())
            e = [i for i in items if is_(i, 'E')][0]
            self._add_imported(name, lib_to_design_type(headers[name], name), e, remap)
        return wanted

    def _adopt(self, t, remap):
        name = t.kid('j').strings()[0].decode('cp949').strip()
        if name in self._types or name in self.t.types:
            return self.dtype(name)
        node = copy.deepcopy(t)
        e = node.kid('E')
        if e is not None:  # a nested block carries its circuit inside the type
            node.items.remove(e)
            return self._add_imported(name, node, e, remap)
        code = node.kid('U').nums()[0]
        set_nums(node.kid('U'), code, self._alloc_u(code))
        self._types[name] = DevType(name, node)
        self._order.append(node)
        return self._types[name]

    def _add_imported(self, name, node, e, remap):
        e = copy.deepcopy(e)

        def fix(n):
            for k in n.kids():
                if is_(k, 'X') and tuple(k.nums()) in remap:
                    set_nums(k, *remap[tuple(k.nums())])
                fix(k)
        fix(e)
        # A library part's circuit is stored as a top-level drawing. Make it look like a
        # library part LogicWorks itself placed in a design: (2 (9A 0)), G 4400, and no
        # '{' in the page settings. The '{' marks an open window: with it, every block
        # taken from a library opened in a window of its own whenever the file was opened.
        if e.kid('2') is None:
            at = next(k for k, i in enumerate(e.items) if is_(i, 'v')) + 1
            e.items.insert(at, n_('2', n_(0x9a, 0)))
        set_nums(e.kid('G'), 0x4400)
        area = e.kid('1').kid('K').kid('0') if e.kid('1') is not None else None
        if area is not None:
            area.items = [i for i in area.items if not is_(i, '{')]
        set_nums(node.kid('U'), BLOCK_CODE, self._alloc_u(BLOCK_CODE))
        node.items.append(e)
        self._types[name] = DevType(name, node)
        self._order.append(node)
        self._imported.append(node)
        return self._types[name]

    def block(self, name, left=(), right=(), bottom=(), order=None, title=None, **sym):
        """Create a block (subcircuit) type; returns its internal Circuit.

        Port In / Port Out connectors named after the pins are added to the
        internal circuit automatically (inst.label == pin name). `title` is the
        text drawn on the symbol (default: name). LogicWorks treats block names
        like file names, so the name must not contain \\ / : * ? " < > |.
        """
        if any(ch in name for ch in '\\/:*?"<>|'):
            raise ValueError('block name %r contains a character not allowed in file names; '
                             'use title: for the symbol text' % name)
        blob, pins, bbox = auto_symbol(title or name, left, right, bottom, order=order, **sym)
        node = n_('8', n_('l', zlib.crc32(name.encode('cp949')) & 0xFFFFFFF), n_('m', 0),
                  n_('j', fmt.Str(name)), n_('U', (BLOCK_CODE, self._alloc_u(BLOCK_CODE))),
                  n_('c', fmt.Node('r', [fmt.Blob(blob)])), n_(0x9b, bbox))
        for fld, val in (('Restrict', '0'), ('AutoSym.Left', ' '.join(left)),
                         ('AutoSym.Right', ' '.join(right)), ('AutoSym.Top', ''),
                         ('AutoSym.Bottom', ' '.join(bottom))):
            a = n_(0x83, n_(0x85, n_('g', fmt.Str(fld))), n_('G', 0x8002))
            if val:
                a.items.append(n_('g', fmt.Str(val)))
            node.items.append(a)
        pnodes = []
        for nm, x, y, side in pins:
            it = [n_('W', (x * PX, y * PX))]
            it += {'R': [n_(0x88, 1)], 'L': [n_(0x88, 0), n_('I', 2)], 'B': [n_(0x88, 0), n_('I', 1)]}[side]
            it += [n_(0x95, PIN_LEN), n_('h', fmt.Str(nm))]
            pnodes.append(n_('7', *it))
        n_in = sum(1 for p in pins if p[3] != 'R')
        node.items.append(n_('9', (len(pins), n_in, len(pins) - n_in), *pnodes))
        dt = DevType(name, node)
        w = max(p[1] for p in pins) if pins else 80
        h = max([p[2] for p in pins] + [15])
        dt.block_size = (w * PX, (h if bottom else h + 15) * PX)
        self._types[name] = dt
        self._order.append(node)
        inner = Circuit(self, name)
        inner.ports = {}
        for nm, x, y, side in pins:
            inner.ports[nm] = inner.add('Port Out' if side == 'R' else 'Port In', label=nm, name=nm)
        self.subcircuits.append((node, inner))
        return inner

    # ------------------------------------------------------------ emission
    def _anum(self, field):
        return self.t.attr_num[field]

    def _inst_node(self, inst, k, ids):
        is_clock = inst.dtype.node.kid('U').nums()[0] == CLOCK_CODE
        is_io = inst.dtype.name in IO_TYPES or inst.dtype.name.startswith(('Hex ', '7-Seg'))
        it = [n_('G', 2)] if is_io else [n_('G', 0xA)] if is_clock else []
        it += [n_('W', (inst.x, inst.y)), n_('X', inst.dtype.node.kid('U').nums()), n_('z', next(ids))]
        # delay as LogicWorks stores it: blocks 0, primitives 1, Clock high/low time
        if is_clock:
            delay = getattr(inst, 'delay', None) or '10,10'
        else:
            delay = '0,0' if inst.dtype.node.kid('U').nums()[0] == BLOCK_CODE else '1,0'
        it.append(n_(0x83, n_(0x84, self._anum('Delay.Dev')), n_('G', 0x1041002), n_('g', fmt.Str(delay))))
        if is_clock:
            # the pending first edge: without a queued event the clock never starts
            it.append(n_('A', (0, 0x13A), n_('Y', (1, 0xFFFF))))
        if inst.label is not None:
            it.append(n_(0x83, n_('G', 0x151106),
                         n_(0x82, 1, n_('^', n_(0x91, 5), n_('W', (inst.x - 0xE, inst.y + 0x4D)))),
                         n_('g', fmt.Str(inst.label))))
        return n_('<', k, *it)

    @staticmethod
    def _split_at_junctions(net):
        """Segments of a net as LogicWorks draws them: a wire that another wire of the
        net (or one of its pins) meets in the middle is cut there, so every T-junction is
        a meeting of segment ends and gets its junction dot. A wire left whole through a
        T loads and simulates, but shows no dot; LogicWorks redraws a net its own way only
        when a part on it is moved, so a hand-edited file would otherwise mix the two."""
        segs = [tuple(sorted(s)) for s in net.segs]
        pts = {e for s in segs for e in s} | {inst[p] for inst, p in net.pins}
        out, seen = [], set()
        for a, b in segs:
            cuts = sorted([p for p in pts if p != a and p != b and on_seg(p, (a, b))])
            chain = [a] + cuts + [b]
            for s in zip(chain, chain[1:]):
                if s not in seen:
                    seen.add(s)
                    out.append(s)
        return out

    def _emit_circuit(self, circ, head, ids, sim=False):
        # LogicWorks fails to load a block instance whose pin belongs to no signal;
        # give each unconnected pin a signal of its own
        connected = {(id(i), p) for n in circ.nets for i, p in n.pins}
        for inst in circ.insts:
            for p in inst.dtype.pins:
                if (id(inst), p['name']) not in connected:
                    circ.nets.append(Net('%s.%s' % (inst.name, p['name']), [(inst, p['name'])]))
        if any(i.x is None for i in circ.insts) or any(not n.segs and len(n.pins) > 1 for n in circ.nets):
            from . import layout
            layout.route(circ)
        circ.check()
        items = copy.deepcopy(head)
        for k, inst in enumerate(circ.insts, 1):
            inst.num = k
            items.append(self._inst_node(inst, k, ids))
        signals = {}  # key -> [first net, pieces]; named pieces share one signal
        for net in circ.nets:
            geo, pin_nodes = [], []
            for inst, p in net.pins:
                idx, P, outer = inst.pin_geom(p)
                a, b = sorted([P, outer])
                pn = n_('>', n_('Y', (inst.num, idx)),
                        n_('=', (a[0], a[1], b[0], b[1]), n_('G', 0x14 if b == P else 0xC)))
                if sim and inst.dtype.pins[idx - 1]['type'] != 0:
                    pn.items.append(n_('T', 0))  # driven value; every input starts at 0
                pin_nodes.append(pn)
                geo += [P, outer]
            segs = self._split_at_junctions(net)
            count = {}
            for s in segs:
                for e in s:
                    count[e] = count.get(e, 0) + 1
            for inst, p in net.pins:
                count[inst[p]] = count.get(inst[p], 0) + 1
            # junction dot, on the branch rather than on the wire running through (as
            # LogicWorks draws it): the segment whose direction no other one there shares
            at_pt = {}
            for s in segs:
                for e in s:
                    at_pt.setdefault(e, []).append(s)
            dot_on = {}
            for e, here in at_pt.items():
                if count.get(e, 0) >= 3:
                    horiz = [s[0][1] == s[1][1] for s in here]
                    lone = [s for s, h in zip(here, horiz) if horiz.count(h) == 1]
                    dot_on[e] = (lone or here)[0]
            seg_nodes = []
            for s in segs:
                f = 0
                for bit, e in ((1, s[0]), (2, s[1])):
                    if dot_on.get(e) == s:
                        f |= bit
                geo += list(s)
                seg_nodes.append(n_('=', (s[0][0], s[0][1], s[1][0], s[1][1]), *([n_('G', f)] if f else [])))
            xs, ys = [p[0] for p in geo], [p[1] for p in geo]
            bbox = (min(xs) - BBOX_MARGIN, min(ys) - BBOX_MARGIN, max(xs) + BBOX_MARGIN, max(ys) + BBOX_MARGIN)
            piece = n_('?', n_('z', next(ids)), n_('Z', bbox), *seg_nodes, *pin_nodes)
            if net.label:
                piece.items.insert(2, self._label_node(net))
            key = ('label', net.label) if net.label else ('net', id(net))
            signals.setdefault(key, [net, []])[1].append(piece)
        for k, (net, pieces) in enumerate(signals.values(), 1):
            body = [n_('`', (0, 0, 0, 3, 0, 3))] if sim else []
            body.append(n_('@', k, *pieces))
            items.append(n_('B', k, *body))
        return items

    @staticmethod
    def _label_node(net):
        """A signal name as LogicWorks stores it: attribute 0x151106 with the text
        position (the stub's outer end) and justification (5 = text to the left of
        the point, 3 = to the right)."""
        inst, p = net.pins[0]
        _, pin, outer = inst.pin_geom(p)
        just = 5 if outer[0] < pin[0] else 3
        return n_(0x83, n_('G', 0x151106), n_(0x82, 1, n_('^', n_(0x91, just), n_('W', outer))),
                  n_('g', fmt.Str(net.label)))

    def _set_attr(self, items, field, value):
        num = self._anum(field)
        for a in items:
            if is_(a, 0x83) and a.kid(0x84) and a.kid(0x84).nums() == [num]:
                set_g(a, value)

    def _build(self):
        ids = iter(range(0x20, 0x100000))
        built = {}
        for node, inner in self.subcircuits:
            n = copy.deepcopy(node)
            n.items.append(fmt.Node('E', self._emit_circuit(inner, self.t.sub_e_head, ids)))
            built[id(node)] = (n, inner)
        top_e = fmt.Node('E', self._emit_circuit(self.top, self.t.top_e_head, ids, sim=True))
        # imported library blocks keep their circuits; only their object ids must
        # join this file's numbering
        imported = {}
        for node in self._imported:
            n = copy.deepcopy(node)

            def renum(x):
                for k in x.kids():
                    if is_(k, 'z'):
                        set_nums(k, next(ids))
                    renum(k)
            renum(n.kid('E'))
            imported[id(node)] = n
        nxt = next(ids)

        def set_next(x):
            for k in x.kids():
                if is_(k, '}'):
                    set_nums(k, nxt)
                set_next(k)
        for n, _ in built.values():
            set_nums(n.kid('E').kid('}'), nxt)
        for n in imported.values():
            set_next(n.kid('E'))
        set_nums(top_e.kid('}'), nxt)
        # parts first; blocks are created inner-first, so each follows what it uses
        subs = {id(n) for n, _ in self.subcircuits}
        types = [imported.get(id(n), n) for n in self._order if id(n) not in subs] + \
            [built[id(n)][0] for n, _ in self.subcircuits]
        return built, types, top_e

    def save(self, path):
        """Write a .cct circuit file; returns its size."""
        _, types, top_e = self._build()
        d, f = os.path.split(os.path.abspath(path))
        self._set_attr(top_e.items, 'CctName', f)
        self._set_attr(top_e.items, 'CctPath', d.rstrip('\\/') + '\\')
        data = fmt.dump([fmt.Node('F', copy.deepcopy(self.t.header) + types + [top_e])])
        with open(path, 'wb') as fh:
            fh.write(data)
        return len(data)

    # ------------------------------------------------------------ libraries
    def _lib_payload(self, node, inner, built):
        """Stand-alone design holding a block's internal circuit (library part body)."""
        pins = [n_('7', n_(0x88, p['type']), n_('h', fmt.Str(p['name'])))
                for p in DevType('', node).pins]
        items = [fmt.Raw(b'50000103 D'), n_('9', len(pins), *pins)]
        items += [copy.deepcopy(a) for a in self.t.header
                  if is_(a, 0x85) and a.kid(0x84) and a.kid(0x84).nums() == [self._anum('Timing.Save')]]
        # everything the circuit uses, nested blocks included, inner parts first
        by_u = {tuple(t.kid('U').nums()): t for t in self._order}
        inner_of = {id(n): c for n, c in self.subcircuits}
        used, order = set(), []

        def refs(n, out):
            for k in n.kids():
                if is_(k, 'X'):
                    out.append(tuple(k.nums()))
                refs(k, out)
            return out

        def use(u):
            if u in used or u not in by_u:
                return
            used.add(u)
            t = by_u[u]
            if id(t) in inner_of:
                visit(inner_of[id(t)])
            elif t.kid('E') is not None:  # block taken from a library: follow its circuit too
                for r in refs(t.kid('E'), []):
                    use(r)
            order.append(t)

        def visit(circ):
            for i in circ.insts:
                use(tuple(i.dtype.node.kid('U').nums()))
        visit(inner)
        for t in order:
            items.append(copy.deepcopy(built[id(t)][0]) if id(t) in built else copy.deepcopy(t))
        e = fmt.Node('E', [copy.deepcopy(i) for i in self.t.top_e_head if not is_(i, '2')] +
                     [copy.deepcopy(i) for i in node.kid('E').items if is_(i, '<') or is_(i, 'B')])
        set_nums(e.kid('}'), node.kid('E').kid('}').nums()[0])
        self._lib_pages(e.kid('1'), node.kid('E').kid('1'))
        self._set_attr(e.items, 'CctName', node.kid('j').strings()[0].decode('cp949') + '.cct')
        self._set_attr(e.items, 'CctPath', '')
        items.append(e)
        return fmt.dump([fmt.Node('F', items)])

    @staticmethod
    def _lib_pages(lib_one, block_one):
        """Give a library part's circuit (a top-level style drawing) as many pages as the
        block's own drawing has, so the circuit stays inside its page when opened.

        Page settings live in ('1' > 'K' > '0'): '[' the drawing area centred on the
        origin, the backslash node that area plus half a page each side, 'a' > '^' half a
        page, 'a' > 0xa0 the page count (0 0 in a block means LogicWorks' default 2 x 1).
        A top-level page is a little larger than a block page, so the same count covers it.
        'Z' is the drawing's extent, which LogicWorks uses to size an auto-expanding sheet.
        """
        if lib_one is None or block_one is None:
            return
        n = block_one.kid('K').kid('0').kid('a').kid(0xa0).nums()
        nx, ny = (2, 1) if n == [0, 0] else n
        area = lib_one.kid('K').kid('0')
        hx, hy = area.kid('a').kid('^').nums()[2:4]       # half a page
        set_nums(area.kid('['), -nx * hx, -ny * hy, nx * hx, ny * hy)
        set_nums(area.kid(chr(92)), -(nx + 1) * hx, -(ny + 1) * hy, (nx + 1) * hx, (ny + 1) * hy)
        set_nums(area.kid('a').kid(0xa0), nx, ny)
        set_nums(area.kid('Z'), *block_one.kid('K').kid('0').kid('Z').nums())  # drawing extent

    @staticmethod
    def _lib_name(name):
        b = name.encode('cp949')
        return n_(0x8f, fmt.Raw(b' '), fmt.Str(b), fmt.Raw(b' ' * max(0, 32 - len(b))))

    def _lib_header(self, node):
        name = node.kid('j').strings()[0].decode('cp949')
        bb = node.kid(0x9b).nums()
        items = [self._lib_name(name), copy.deepcopy(node.kid('l')), n_('m', 0),
                 copy.deepcopy(node.kid('c')), n_(0x9b, (bb[1], bb[0], bb[3], bb[2]))]
        items += [copy.deepcopy(a) for a in node.kids(0x83)]
        dt = DevType(name, node)
        pins = [n_(0x88, (p['x'], p['y'], p['type'], 3 if p['side'] is None else p['side']),
                   n_('h', fmt.Str(p['name']))) for p in dt.pins]
        n_out = sum(1 for p in dt.pins if p['type'] == 1)
        items.append(n_('9', (len(pins), len(pins) - n_out, n_out), *pins))
        return n_('8', *items)

    def save_library(self, path, names=None):
        """Write blocks (all, or those named) to a LogicWorks .clf library; returns its size.

        A library holds, per part, the internal circuit as an embedded design
        followed by the part header; an index at the end (offset in the
        leading (y ...) field) points at both.
        """
        built, _, _ = self._build()
        parts = []
        for node, inner in self.subcircuits:
            n = built[id(node)][0]
            name = n.kid('j').strings()[0].decode('cp949')
            if names is None or name in names:
                payload = n_(0x8e, self._lib_name(name), fmt.Node(0x8b, [fmt.QBlob(self._lib_payload(n, inner, built))]))
                parts.append((name, fmt.dump([payload]), fmt.dump([self._lib_header(n)])))
        ylen = 1
        while True:  # the index offset is written in front of everything it measures
            off = len(b'(F1(y%s)' % (b'0' * ylen))
            body, index = bytearray(), []
            for name, payload, header in parts:
                p_off = off + len(body)
                body += payload
                index.append((name, off + len(body), p_off))
                body += header
            y = off + len(body)
            if len(b'%X' % y) == ylen:
                break
            ylen = len(b'%X' % y)
        t = n_('t', *[n_('u', n_('g', fmt.Str(nm)), n_('x', x), fmt.Node(ord('~'), [fmt.Raw(b'%08X' % p)]))
                      for nm, x, p in index])
        data = b'(F1(y%X)' % y + bytes(body) + fmt.dump([t]) + b')'
        with open(path, 'wb') as fh:
            fh.write(data)
        return len(data)
