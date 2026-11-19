"""Automatic placement and orthogonal routing.

Devices are put in columns by logic depth (sources left, sinks right).
Between columns are routing channels; every net gets one vertical track in
each channel it touches. Pins reach their track with a horizontal stub
(bottom/top pins first drop/rise below/above their device). Tracks of one
net in different channels are joined by horizontal trunks on rows that
cross no device and no other net's wire. Rows are reserved as devices are
placed, so two nets never share a row segment; Circuit.check() verifies
the result.
"""
from .model import SIDE, GRID, PIN_LEN

PITCH = 2 * GRID   # distance between tracks / drop rows
GAP = 2 * GRID     # vertical gap between devices of one column
MARGIN = GRID


def _snap(v):
    return int(round(v / GRID)) * GRID


class _Ctx:
    def __init__(self, c):
        self.c = c
        self.hres = []      # (y, x1, x2, net_index)
        self.bands = []     # (x0, y0, x1, y1) absolute device bands


def _pin_side(inst, pin):
    return SIDE[inst.dtype.pin(pin)[1]['side']]


def _is_out(inst, pin):
    return inst.dtype.pin(pin)[1]['type'] != 0


def _columns(c, nets):
    insts = c.insts
    has_in = {i: any(p['type'] == 0 for p in i.dtype.pins) for i in insts}
    has_out = {i: any(p['type'] != 0 for p in i.dtype.pins) for i in insts}
    succ = {i: [] for i in insts}
    for drv, pins in nets:
        for i, _ in pins:
            if i is not drv[0] and i not in succ[drv[0]]:
                succ[drv[0]].append(i)
    # drop back edges (DFS) so feedback loops do not push levels forever
    state, back = {}, set()

    def dfs(u):
        state[u] = 1
        for v in succ[u]:
            if state.get(v) == 1:
                back.add((u, v))
            elif v not in state:
                dfs(v)
        state[u] = 2
    for i in sorted(insts, key=lambda i: has_in[i]):
        if i not in state:
            dfs(i)
    level = {i: 0 for i in insts}
    for _ in range(len(insts)):
        changed = False
        for u in insts:
            for v in succ[u]:
                if (u, v) not in back and level[v] < level[u] + 1:
                    level[v] = level[u] + 1
                    changed = True
        if not changed:
            break
    inner = [level[i] for i in insts if has_in[i] and has_out[i]]
    last = (max(inner) + 1) if inner else (max(level.values()) if level else 0)
    for i in insts:
        if not has_in[i]:
            level[i] = 0
        elif not has_out[i]:
            level[i] = max(last, 1)
    ncol = max(level.values()) + 1 if level else 1
    cols = [[i for i in insts if level[i] == k] for k in range(ncol)]
    return cols, level


def route(c):
    """Assign positions to unplaced devices and wires to unrouted nets of circuit c."""
    nets = []
    for net in c.nets:
        drv = next(((i, p) for i, p in net.pins if _is_out(i, p)), net.pins[0])
        nets.append((drv, net.pins))
    # pieces of a named (remote) signal still order the columns like one net
    named = {}
    for net in c.nets:
        if net.label:
            named.setdefault(net.label, []).extend(net.pins)
    groups = [(next(((i, p) for i, p in pins if _is_out(i, p)), pins[0]), pins) for pins in named.values()]
    cols, level = _columns(c, nets + groups)

    # which channel each pin attaches to (channel k lies right of column k)
    attach = []  # per net: list of (inst, pin, channel)
    for drv, pins in nets:
        lst = []
        for i, p in pins:
            side = _pin_side(i, p)
            lst.append((i, p, level[i] if side == 'R' else level[i] - 1))
        attach.append(lst)
    tracks = {}  # (net, channel) -> x ; filled after column x positions
    chan_nets = {}
    for k, lst in enumerate(attach):
        if len(c.nets[k].pins) < 2:
            continue
        for _, _, ch in lst:
            chan_nets.setdefault(ch, [])
            if k not in chan_nets[ch]:
                chan_nets[ch].append(k)

    # column x positions
    x = 0
    col_left = {}
    chans = range(-1, len(cols))
    for ch in chans:
        start = x
        n = len(chan_nets.get(ch, []))
        for t, k in enumerate(chan_nets.get(ch, [])):
            tracks[(k, ch)] = start + PITCH * (t + 1)
        x = start + PITCH * (n + 1)
        if ch + 1 < len(cols):
            col_left[ch + 1] = x
            width = max([i.dtype.box()[2] - i.dtype.box()[0] for i in cols[ch + 1]] or [0])
            x += _snap(width) + GRID

    ctx = _Ctx(c)
    net_of = {}
    for k, (_, pins) in enumerate(nets):
        for i, p in pins:
            net_of[(id(i), p)] = k

    def pin_wires(inst, px, py):
        """Stubs/drops for inst placed at (px, py): list of (net, ch, row, segs)."""
        out = []
        bottoms = sorted([p for p in inst.dtype.pins if SIDE[p['side']] == 'B'], key=lambda p: p['x'])
        tops = sorted([p for p in inst.dtype.pins if SIDE[p['side']] == 'T'], key=lambda p: p['x'])
        for p in inst.dtype.pins:
            k = net_of.get((id(inst), p['name']))
            if k is None or len(c.nets[k].pins) < 2:
                continue
            side = SIDE[p['side']]
            ch = level[inst] if side == 'R' else level[inst] - 1
            tx = tracks[(k, ch)]
            P = (px + p['x'], py + p['y'])
            if side in 'LR':
                o = (P[0] + (PIN_LEN if side == 'R' else -PIN_LEN), P[1])
                out.append((k, ch, o[1], [(o, (tx, o[1]))]))
            else:
                sgn = 1 if side == 'B' else -1
                depth = (bottoms if side == 'B' else tops).index(p)
                o = (P[0], P[1] + sgn * PIN_LEN)
                row = o[1] + sgn * PITCH * depth
                segs = [(o, (o[0], row))] if row != o[1] else []
                segs.append(((o[0], row), (tx, row)))
                out.append((k, ch, row, segs))
        return out

    def free(y, x1, x2, k):
        a, b = min(x1, x2), max(x1, x2)
        for ry, rx1, rx2, rk in ctx.hres:
            if ry == y and rk != k and not (b < rx1 or a > rx2):
                return False
        return True

    def reserve(y, x1, x2, k):
        ctx.hres.append((y, min(x1, x2), max(x1, x2), k))

    rows = {}  # (net, ch) -> set of rows attached to the track
    segs_of = {k: [] for k in range(len(nets))}
    for ci, col in enumerate(cols):
        def bary(inst):
            vals = []
            for p in inst.dtype.pins:
                k = net_of.get((id(inst), p['name']))
                if k is None or p['type'] != 0:
                    continue
                drv = nets[k][0][0]
                if drv.y is not None and drv is not inst:
                    vals.append(drv[nets[k][0][1]][1] - p['y'])
            return sum(vals) / len(vals) if vals else None
        if ci > 0:
            col = sorted(col, key=lambda i: (bary(i) is None, bary(i) or 0))
        y_cursor = 0
        for inst in col:
            bx0, by0, bx1, by1 = inst.dtype.box()
            n_top = sum(1 for p in inst.dtype.pins if SIDE[p['side']] == 'T')
            n_bot = sum(1 for p in inst.dtype.pins if SIDE[p['side']] == 'B')
            ext_top = PITCH * max(0, n_top - 1)
            ext_bot = PITCH * max(0, n_bot - 1)
            px = col_left[ci] - bx0
            b = bary(inst)
            y = _snap(max(y_cursor - by0 + ext_top, b if b is not None else -10 ** 9))
            for _ in range(2000):
                wires = pin_wires(inst, px, y)
                if all(free(row, s[-1][0][0], s[-1][1][0], k) for k, ch, row, s in wires):
                    break
                y += GRID
            else:
                raise RuntimeError('could not place %s' % inst)
            inst.x, inst.y = px, y
            for k, ch, row, s in wires:
                reserve(row, s[-1][0][0], s[-1][1][0], k)
                rows.setdefault((k, ch), set()).add(row)
                segs_of[k] += s
            band = (px + bx0 - MARGIN, y + by0 - ext_top - MARGIN, px + bx1 + MARGIN, y + by1 + ext_bot + MARGIN)
            ctx.bands.append(band)
            y_cursor = band[3] + GAP

    # trunks between the tracks of a net in different channels
    for k, lst in enumerate(attach):
        chs = sorted({ch for _, _, ch in lst})
        if len(c.nets[k].pins) < 2 or len(chs) < 2:
            continue
        drv_y = nets[k][0][0][nets[k][0][1]][1]
        for a, b in zip(chs, chs[1:]):
            xa, xb = tracks[(k, a)], tracks[(k, b)]
            for step in range(4000):
                y = drv_y + (step // 2 + 1) * GRID * (1 if step % 2 else -1) if step else drv_y
                if not free(y, xa, xb, k):
                    continue
                if any(y0 <= y <= y1 and not (xb < x0 or xa > x1) for x0, y0, x1, y1 in ctx.bands):
                    continue
                if any(y in r for (kk, ch), r in rows.items() if kk != k and xa <= tracks[(kk, ch)] <= xb):
                    continue
                break
            else:
                raise RuntimeError('no trunk row for net %s' % c.nets[k].name)
            reserve(y, xa, xb, k)
            rows.setdefault((k, a), set()).add(y)
            rows.setdefault((k, b), set()).add(y)
            segs_of[k].append(((xa, y), (xb, y)))

    # vertical track pieces
    for (k, ch), rs in rows.items():
        tx = tracks[(k, ch)]
        rs = sorted(rs)
        segs_of[k] += [((tx, a), (tx, b)) for a, b in zip(rs, rs[1:])]

    # center the drawing on the page origin, as LogicWorks does
    pts = [(b[0], b[1]) for b in ctx.bands] + [(b[2], b[3]) for b in ctx.bands]
    pts += [e for ss in segs_of.values() for s in ss for e in s]
    dx = -_snap((min(p[0] for p in pts) + max(p[0] for p in pts)) / 2) if pts else 0
    dy = -_snap((min(p[1] for p in pts) + max(p[1] for p in pts)) / 2) if pts else 0
    for inst in c.insts:
        inst.x += dx
        inst.y += dy
    for k, net in enumerate(c.nets):
        if not net.segs:
            net.segs = [((a[0] + dx, a[1] + dy), (b[0] + dx, b[1] + dy))
                        for a, b in segs_of[k] if a != b]
