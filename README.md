# lwcct

Generate **LogicWorks 5** circuit files (`.cct`) and part libraries (`.clf`)
from a short YAML description: no clicking, automatic placement and wiring,
blocks (subcircuits) with custom symbols, and a library you can drag parts from.

> Unofficial tool, not affiliated with Capilano Computing / DesignWorks.
> The file format was analyzed for interoperability. Nothing from LogicWorks
> is included: headers and primitive parts are read at run time from your own
> LogicWorks 5 installation.

## Requirements

- Windows with LogicWorks 5 installed (default `C:\Program Files (x86)\LogicWorks 5`,
  or set `LWCCT_LOGICWORKS` / pass `--logicworks`)
- Python 3.9+, `pyyaml`

```bash
pip install -e .
```

## Quick start

```yaml
# mux2.yaml
blocks:
  MUX2:
    left: [I0, I1]       # symbol pins per side
    bottom: [S]
    right: [Z]
    parts: {n: NOT, a0: and_2, a1: and_2, o: or_2}
    nets:
      - [S, n.INA, a1.INB]     # bare name = block pin
      - [n.OUT, a0.INB]
      - [I0, a0.INA]
      - [I1, a1.INA]
      - [a0.Y, o.INA]
      - [a1.Y, o.INB]
      - [o.Y, Z]
top:
  parts: {s0: Binary Switch, s1: Binary Switch, ss: Binary Switch, m: MUX2, p: Binary Probe}
  nets:
    - [s0.Q0, m.I0]
    - [s1.Q0, m.I1]
    - [ss.Q0, m.S]
    - [m.Z, p.D0]
```

```bash
lwcct build mux2.yaml -o mux2.cct --lib mux2.clf --open
```

- `mux2.cct` opens and simulates in LogicWorks; double-click the block to see its gates.
- `mux2.clf` can be opened with *File > Libraries > Open Lib*; drag `MUX2` into any circuit.

## Commands

| command | |
|---|---|
| `lwcct build spec.yaml -o out.cct [--lib out.clf] [--open]` | build circuit (and library) |
| `lwcct parts [filter]` | list library parts and pins (`>` marks outputs) |
| `lwcct info file.cct` | summarize a .cct/.clf, check it parses losslessly |
| `lwcct open file.cct` | open in LogicWorks |

## Spec reference

- `blocks.<NAME>`: `left`, `right`, `bottom` pin lists (inputs on left/bottom,
  outputs on right); optional `width` (px, default 80), `pitch` (px between pins,
  default 10), `left_y0`, `right_y0`, `bottom_x0`.
  Port connectors for the pins are created automatically.
- `parts`: `id: Type` or `id: {type: Type, label: text}`. Types are library parts
  (`lwcct parts`) or blocks defined above.
- `nets`: list of pin lists, or `{name: pin list}`. Pins are `id.PIN`; inside a
  block a bare `NAME` is that block pin.
- `labels`: `{NAME: pin list}`, remote connections. Each pin gets only its stub
  with `NAME` written next to it, and LogicWorks joins all pieces of the same name
  into one signal (as when you name signals by hand). Use it for signals that go far
  or to many places (clock, clear); keep short local links under `nets`.
- Junction dots: wires are cut at every T-junction and the dot is drawn on the
  branch, as LogicWorks draws them. Nothing to specify.
- Top-level switches start at 0; all signals are initialised to 0.

## Python API

```python
from lwcct import Design
d = Design()
inner = d.block('INV', left=['A'], right=['Y'])
n = inner.add('NOT', name='n')
inner.connect([(inner.ports['A'], 'PIN1'), (n, 'INA')])
inner.connect([(n, 'OUT'), (inner.ports['Y'], 'PIN1')])
s, b, p = d.top.add('Binary Switch'), d.top.add('INV'), d.top.add('Binary Probe')
d.top.connect([(s, 'Q0'), (b, 'A')])
d.top.connect([(b, 'Y'), (p, 'D0')])
d.save('inv.cct')
```

Manual placement is possible too: give `add()` coordinates and draw wires with
`wire()`, `track()` or `path()`. `Circuit.check()` rejects shorts and open nets.
`label(name, pins)` connects pins by a signal name instead of a wire.

## Limitations

- No part rotation or buses. Signal names appear only on `labels` connections.
- Auto layout aims for correctness, not beauty (one track per net per channel).

## Tests

```bash
python -m unittest discover -s tests
```

The symbol test checks byte equality with a symbol produced by LogicWorks itself;
round-trip tests re-encode every example and library shipped with LogicWorks.

Format notes: [docs/FORMAT.md](docs/FORMAT.md).
