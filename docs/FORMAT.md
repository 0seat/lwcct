# LogicWorks 5 file format notes

Observed from LogicWorks 5.x files; everything here was verified by having
LogicWorks open files generated from these rules.

## Syntax

A file is a tree of nodes: `(` + one tag byte + body + `)`.

- Numbers are hexadecimal, separated by spaces, may be negative (`-1EA`).
- String: `<hexlen> "<raw bytes>` with no closing quote, e.g. `(gA "LogicWorks)`.
  Text is in the system code page (cp949 on Korean Windows).
- Tag `r`: binary blob `<hexlen> <raw bytes>` (symbol pictures).
- Tag `0x8B` (libraries): blob `<hexlen>"<raw bytes>` (embedded design).

Tags include ASCII letters and bytes `0x80..0xAF`.

## Circuit (.cct)

```
(F50000103 D
  (V ...) (3 ...)          version, misc
  (85 ...)*                attribute field definitions: (84 num) (g "Name")
  (8 ...)*                 device types used in the design
  (E ...))                 top-level circuit
```

Attribute numbers (e.g. CctName, CctPath, Timing.Save) are defined per file by
the `85` nodes; look them up by name.

### Device type `(8 ...)`

| node | meaning |
|---|---|
| `l` | id/hash (not validated) |
| `m 0` | present on blocks (has internal circuit) |
| `j "name"` | type name |
| `U code id` | primitive code (0 NOT, 1 AND, 3 OR, 9 switch, B probe, 3E port, 48 block) and per-design id |
| `c (r blob)` | symbol picture (QuickDraw PICT v1) |
| `9B x0 y0 x1 y1` | symbol bounding box |
| `83 ...` | attributes (`(85 (g "Field")) (G flags) (g "value")`) |
| `9 n nin nout (7 ...)*` | pins: `(W x y) (88 type) (I side) (95 len) (h "name")` |
| `E ...` | internal circuit (blocks) |

Pin type `88`: 0 input, 1 output, 3 switch output. Pin side `I`: 2 left,
1 bottom, 0 top, absent/3 right. Pin length is 0x8C.

### Circuit `(E ...)`

Header nodes (`G`, `}` next object id, `v` timestamps, `2`, `1` page/print
settings, `83` circuit attributes), then:

- Device instance `(< k [G 2] (W x y) [(I rot)] (X code id) (z objid) attrs...)`.
  Port connectors carry their name as
  `(83 (G 151106) (82 1 (^ (91 5) (W x-E y+4D))) (g "NAME"))`.
- Signal `(B k [(` v...)] (@ k (? (z objid) (Z bbox) segments... pins...)))`:
  - wire segment `(= x1 y1 x2 y2 [(G dots)])`, axis-aligned, `G` bit 1/2 = junction
    dot at first/second point;
  - pin `(> (Y inst pin) (= ...pin stub...) (G C|14) [(T value)])`: `C` when the
    device-side point is the first one, `14` when it is the second. Any other value
    still loads and simulates, but LogicWorks then no longer drags the wire along
    when the device is moved.
  - named signal: the name is an attribute inside each piece, after `Z`:
    `(83 (G 151106) (82 1 (^ (91 just) (W x y))) (g "NAME"))`, with `W` the text
    point (lwcct uses the stub's outer end) and `just` 5 = text left of the point,
    3 = right. A signal may have several pieces `(? ...)` under one `@`; pieces
    that share a name are one signal even though no wire joins them (this is how
    LogicWorks stores connections made by naming signals).

Geometry: units are 1/14 symbol pixel, grid 70. Pin connection point =
instance `W` + pin `W` + direction × 0x8C. Wires connect only at segment ends
(T-junctions allowed); crossing segments are not connected.

Optional and safe to omit: the top-level `b` blob, per-instance copies of
block internals, `T` values and `` ` `` values in subcircuits.

### Symbol pictures

PICT v1 (size word 0, frame rect, opcodes 0x11 version, 0x01 clip, 0x30 frame
rect, ...). LogicWorks stores pin labels and font settings in long comments
(0xA1): kind 998/999 bracket pin `n` (`KGOL\x99\x00 n \x00`), kind 3995 is a
label (`LOGK` v h align 0x20 len text), 3998 sets text rotation (`LOGK\x00Z` =
90 degrees), 3999 font name.

## Library (.clf)

```
(F1 (y <offset of index>)
  [(8E (8F name) (8B <embedded design>))]    blocks only: internal circuit
  (8 (8F name) (l) [(m 0)] (c (r pict)) (9B ...) (83 ...)* (9 n nin nout (88 x y type side (h name))*))
  ...
  (t (u (g "name") (x <offset of 8 node>) (~ <8-digit offset of 8E node or 0>))*))
```

Library names are written `(8F 20 <len> "name<spaces to 32 chars>)`. Primitive
library parts use `(w code)` instead of `(U ...)`. The embedded design is a
complete `(F50000103 D ...)` file with a pin list `(9 n (7 (88 type) (h name))*)`,
the Timing.Save attribute definition, the types it uses and its circuit.

## Notes from LogicWorks 5 behaviour (checked in the program)

- Wires: LogicWorks cuts a wire at every T-junction and puts the junction dot (`G` 1/2)
  on the branch segment. lwcct writes nets the same way; a wire left whole through a T
  still connects, but shows no dot until a part on it is moved.
- Page settings `1 > K > 0`: `{` marks an open window. A top-level drawing has it; a
  block circuit must not, or the block opens in a window of its own with the file.
- `Z` is the drawing's extent. With the sheet on "auto-expand", LogicWorks sizes the
  page from it, so it must cover the drawing.
- A library part placed in a design: circuit header `G 4400`, `(2 (9A 0))`.
- A Ground part inside a block taken from a library did not drive 0 in simulation
  (that net stayed X); make constants from gates instead.
- Editing inside one instance of a block makes LogicWorks split that instance off as
  `NAME_1` (a type with `(X code id)` pointing at the original). If the edited block is
  used several times inside a parent block that is used once, the saved file reports
  internal error 241d33 when it is opened again. This happens with circuits drawn in
  LogicWorks itself too (HalfAdder x2 in FullAdder), so it is LogicWorks behaviour, not
  something a generated file can avoid.
