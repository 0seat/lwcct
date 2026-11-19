"""Build a Design from a YAML/JSON circuit description.

    blocks:                       # optional subcircuit blocks
      MUX2:
        left: [I0, I1]            # pin names per symbol side
        bottom: [S]
        right: [Z]
        title: 2-to-1 MUX         # text on the symbol (optional, default: block name)
        width: 80                 # symbol width in px (optional)
        pitch: 10                 # pin spacing in px (optional, LogicWorks uses 10)
        parts:
          n: NOT                  # id: part type
          a0: and_2
          a1: and_2
          o: or_2
        nets:                     # list of pin lists, or {name: pin list}
          - [S, n.INA, a1.INB]    # bare name = block pin (its port connector)
          - [n.OUT, a0.INB]
          - [I0, a0.INA]
          - [I1, a1.INA]
          - [a0.Y, o.INA]
          - [a1.Y, o.INB]
          - [o.Y, Z]
    top:
      parts:
        m: MUX2
        s: Binary Switch
        p: {type: Binary Probe}
      nets:
        - [m.Z, p.D0]
      labels:                     # remote connections: joined by name, no wire drawn
        SEL: [s.Q0, m.S]

Every pin under `labels` gets a short stub with the name written next to it;
LogicWorks treats all pieces with the same name as one signal (as when you name
signals by hand). Wire short local connections under `nets` and use `labels` for
signals that go far or to many places (clock, clear, buses).

Parts are LogicWorks library parts (see `lwcct parts`), blocks defined above, or
parts of your own .clf libraries listed under `libraries` (paths relative to the
spec file; give `{path: ..., parts: [...]}` to take only some):

    libraries: [../parts.clf]
"""
import json
import os

from .model import Design

SYMBOL_KEYS = ('title', 'width', 'pitch', 'height', 'left_y0', 'right_y0', 'bottom_x0')


def load_spec(path):
    with open(path, encoding='utf-8') as f:
        text = f.read()
    if path.lower().endswith('.json'):
        return json.loads(text)
    import yaml
    return yaml.safe_load(text)


def _fill(circ, body, ports=None):
    insts = dict(ports or {})
    for pid, p in (body.get('parts') or {}).items():
        if isinstance(p, str):
            p = {'type': p}
        insts[pid] = circ.add(p['type'], label=p.get('label'), name=pid)
        if 'delay' in p:  # Clock: "high,low" time
            insts[pid].delay = p['delay']
    def pin(ref):
        if '.' in ref:
            pid, pin = ref.split('.', 1)
            if pid not in insts:
                raise KeyError('%s: unknown part %r in %r' % (circ.name, pid, ref))
            insts[pid].dtype.pin(pin)  # validate pin name early
            return insts[pid], pin
        if ports and ref in ports:
            return ports[ref], 'PIN1'
        raise KeyError('%s: %r is neither part.pin nor a block pin' % (circ.name, ref))

    nets = body.get('nets') or []
    items = nets.items() if isinstance(nets, dict) else ((None, n) for n in nets)
    for name, refs in items:
        circ.connect([pin(r) for r in refs], name or '_'.join(refs[:1]))
    for name, refs in (body.get('labels') or {}).items():
        circ.label(str(name), [pin(r) for r in refs])


def build(spec, template=None, base=None):
    d = Design(template)
    for lib in spec.get('libraries') or []:
        if isinstance(lib, str):
            lib = {'path': lib}
        path = lib['path']
        if base and not os.path.isabs(path):
            path = os.path.join(base, path)
        d.use_library(path, lib.get('parts'))
    for name, b in (spec.get('blocks') or {}).items():
        sym = {k: b[k] for k in SYMBOL_KEYS if k in b}
        inner = d.block(name, left=b.get('left', []), right=b.get('right', []),
                        bottom=b.get('bottom', []), **sym)
        _fill(inner, b, inner.ports)
    _fill(d.top, spec.get('top') or {})
    return d
