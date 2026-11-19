"""Rectangular block symbols in the format LogicWorks' auto-symbol tool writes.

Symbol graphics are QuickDraw PICT v1 pictures with LogicWorks-specific
long comments ('LOGK'/'KGOL') carrying pin labels, fonts and text rotation.
With pitch=10 and LogicWorks' own pin order the output is byte-identical to
what LogicWorks generates.
"""
import struct

PX = 14       # internal units per symbol pixel
ORIGIN = 15   # symbol rectangle top-left in symbol pixels


def auto_symbol(title, left=(), right=(), bottom=(), width=80, height=None,
                left_y0=15, right_y0=15, bottom_x0=35, pitch=10, order=None):
    """Build a rectangular block symbol.

    Pins are `pitch` px apart (LogicWorks uses 10): left/right columns start
    left_y0/right_y0 px below the top edge, bottom pins bottom_x0 px from the
    left edge. Pin order (= pin index) is left, bottom, right.
    Returns (pict_blob, pins, bbox) with pins = [[name, x_px, y_px, side]],
    side in 'L', 'R', 'B'.
    """
    pins = [[nm, 0, left_y0 + pitch * k, 'L'] for k, nm in enumerate(left)]
    rights = [[nm, width, right_y0 + pitch * k, 'R'] for k, nm in enumerate(right)]
    side_max = max([p[2] for p in pins + rights] or [15])
    h = height or side_max + 15
    pins += [[nm, bottom_x0 + pitch * k, h, 'B'] for k, nm in enumerate(bottom)]
    pins += rights
    blob = encode_symbol(title, pins, width, h, order)
    bbox = (ORIGIN * PX, ORIGIN * PX, (ORIGIN + width + 1) * PX, (ORIGIN + h + 1) * PX)
    return blob, pins, bbox


def encode_symbol(title, pins, width, height, order=None):
    """QuickDraw PICT v1 in the layout LogicWorks' auto-symbol tool writes."""
    o = ORIGIN
    t, l, b, r = o, o, o + height + 1, o + width + 1
    body = bytearray()

    def a1(kind, data):
        body.extend(b'\xa1' + struct.pack('>hH', kind, len(data)) + data)

    def label(v, h, align, text):
        tb = text.encode('cp949')
        a1(3995, b'LOGK' + struct.pack('>hhhhH', v, h, align, 0x20, len(tb)) + tb)

    body += b'\x11\x01'
    body += b'\x01' + struct.pack('>Hhhhh', 10, t, l, b, r)
    body += b'\x30' + struct.pack('>hhhh', t, l, b, r)
    idx = order or list(range(1, len(pins) + 1))
    rotated = False
    for n, i in enumerate(idx):
        nm, x, y, side = pins[i - 1]
        tag = b'KGOL\x99\x00' + bytes([i]) + b'\x00'
        a1(998, tag)
        if n == 0:
            body += b'\x2c' + struct.pack('>HH', 8, 0) + b'\x05Arial'
            a1(3999, b'LOGKArial\x00')
            body += b'\x04\x00' + b'\x0d\x00\x09'
            a1(3998, b'LOGK\x00\x00')
            body += b'\x0e\x00\x00\x00\x21'
            a1(3997, b'LOGK\xaa\x00\x00\x00')
        else:
            body += b'\x0f\x00\x00\x00\x1e'
            a1(3996, b'LOGK\xaa\x00\x00\x01')
            if (side == 'B') != rotated:
                rotated = side == 'B'
                a1(3998, b'LOGK\x00' + (b'Z' if rotated else b'\x00'))
        body += b'\x0f\x00\x00\x00\x21'
        a1(3996, b'LOGK\xaa\x00\x00\x02')
        if side == 'L':
            label(o + y, o + x + 2, 1, nm)
        elif side == 'R':
            label(o + y, o + x - 2, 3, nm)
        else:
            label(o + y - 2, o + x, 1, nm)
        a1(999, tag)
    body += b'\x0f\x00\x00\x00\x1e'
    a1(3996, b'LOGK\xaa\x00\x00\x01')
    body += b'\x0a' + b'\x00' * 8 + b'\x04\x01' + b'\x0d\x00\x0c'
    if rotated:
        a1(3998, b'LOGK\x00\x00')
    body += b'\x0f\x00\x00\x00\x21'
    a1(3996, b'LOGK\xaa\x00\x00\x02')
    label(o, o + width // 2, 2, title)
    body += b'\xff'
    head = struct.pack('>Hhhhh', 0, t, l, b, r)
    return bytes(head + body)
