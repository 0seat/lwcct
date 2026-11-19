---
name: logicworks-cct
description: Create LogicWorks 5 circuits (.cct) and part libraries (.clf) from a YAML spec with the lwcct tool — gates, switches/probes, subcircuit blocks with custom symbols (e.g. MUX, DEMUX, decoder, adder). Use whenever the user wants a LogicWorks circuit, a .cct/.clf file, or a digital-logic circuit built, instead of drawing in the LogicWorks GUI.
---

# LogicWorks circuits with lwcct

Never draw circuits by clicking in LogicWorks: write a YAML spec and build it.
Use the GUI only to look at the result.

## 1. Tool check

```bash
python -m lwcct parts and_    # works -> installed
```

If it fails, install lwcct from its repository:
`git clone https://github.com/0seat/lwcct` then `pip install --user -e lwcct`
(or set `PYTHONPATH` to its `src` folder). Always call the tool as
`python -m lwcct`; the `lwcct` script is usually not on PATH.
LogicWorks 5 must be installed; it is found automatically or via `LWCCT_LOGICWORKS`.

## 2. Pick parts

`python -m lwcct parts [filter]` lists library parts with pin names (`>` = output). Common:

| part | pins |
|---|---|
| `NOT` | INA, OUT> |
| `and_2` / `and_3` / `and_4` | INA INB [INC IND], Y> |
| `or_2` / `or_3` / `or_4`, `nand_*`, `nor_*`, `xor_2` | same pattern |
| `Binary Switch` | Q0> (top-level input) |
| `Binary Probe` | D0 (top-level output display) |
| `Clock` | Q0> (free-running clock, 10/10 time units) |
| `D Flip Flop`, `JK Flip Flop`, `T Flip Flop` | see `parts Flip` (library primitives) |

Check names with `python -m lwcct parts` before using anything else.

## 3. Write the spec

```yaml
blocks:                    # optional reusable subcircuits
  MUX2:
    left: [I0, I1]         # inputs on left and/or bottom
    bottom: [S]            # e.g. select lines on the bottom edge
    right: [Z]             # outputs on the right
    pitch: 20              # px between pins (default 10); 20 gives roomier wiring
    parts: {n: NOT, a0: and_2, a1: and_2, o: or_2}
    nets:                  # each list = one signal; bare name = block pin
      - [S, n.INA, a1.INB]
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
    - [m.Z, p.D0]
  labels:                  # remote connections (optional), see below
    SEL: [ss.Q0, m.S]
```

Rules:
- Derive the gate network from the truth table / Boolean equations first and
  state them to the user (e.g. `Z = S1'S0'I0 + S1'S0I1 + S1S0'I2 + S1S0I3`).
- One driver per net. Every gate input must be connected.
- Put a Binary Switch on every top-level input and a Binary Probe on every output
  so the circuit can be simulated.
- Block and part ids: letters/digits; block names may start with a digit (`4X1MUX`).
  Block names must be valid file names (no `/ \ : * ? " < > |`); put display text
  such as `D F/F` in the block's `title:`.
- If the user's earlier circuits build parts from gates (e.g. a D flip-flop block from
  NAND gates), follow that style instead of the library primitive.
- A block may be used many times; unconnected block pins (e.g. Q') are fine.

### Remote connections (`labels`) and junction dots

- `labels: {NAME: [pins]}` connects pins by a signal name instead of a wire: each
  pin gets only its short stub with `NAME` written next to it, and LogicWorks joins
  every piece of the same name into one signal (the same as naming signals by hand).
  Works in `top` and inside `blocks`.
- Use labels for signals that go far or fan out widely (clock, clear/reset, enable,
  select lines, bus bits between distant blocks); keep short local links in `nets`.
  This keeps big drawings readable and avoids long crossing wires.
- A pin belongs to either one `nets` entry or one `labels` name, not both. Use
  distinct names per signal (`CLK`, `CLRn`, `A0`..`A20`); the same name anywhere in
  the same circuit means the same signal. Inside a block, reach a block pin by
  listing its bare name, and do not give a label the same name as a block pin.
- Junction dots are automatic: wires are cut at every T-junction and the dot is drawn
  on the branch, as LogicWorks does. Nothing to specify; a branch without a dot in
  the drawing means the wires are not connected.
- Example: `examples/latch2_labels.yaml` in the lwcct repo (enable by label).

## 4. Build

```bash
python -m lwcct build spec.yaml -o out.cct --lib blocks.clf --open
```

`build` places and wires everything automatically and refuses to write files
with shorts or open nets. Use the output file name the user asks for.

## 5. Verify in LogicWorks (one screenshot, not a click marathon)

- `--open` (or `python -m lwcct open file.cct`) launches LogicWorks with the file.
- Take one screenshot: blocks, switches, probes and wires should be visible, probes show 0,
  label names sit at the stub ends and T-junctions show dots.
- If computer use is available, toggle a few switches (click the switch lever)
  and confirm probe values against the truth table; report which rows were tested.
- The parts palette and file dialogs of LogicWorks ignore synthetic input;
  for library checks ask the user to drag the part from *File > Libraries > Open Lib*.

## Notes

- `.cct` files are self-contained (blocks embedded); `.clf` is only for reuse.
- Limitations: no part rotation or buses; signal names appear only on `labels`.
- Format details: `docs/FORMAT.md` in the lwcct repository.
