"""Minimal QuickDraw PICT v1 encode/decode (symbol graphics in .cct blobs)."""
import struct

# opcode -> fixed data length (None = variable, handled below)
_FIXED = {0x00: 0, 0x03: 2, 0x04: 1, 0x05: 2, 0x07: 4, 0x08: 2, 0x09: 8, 0x0A: 8,
          0x0B: 4, 0x0C: 4, 0x0D: 2, 0x0E: 4, 0x0F: 4, 0x10: 8, 0x11: 1, 0x1A: 6,
          0x1B: 6, 0x1E: 0, 0x1F: 6, 0x20: 8, 0x21: 4, 0x22: 6, 0x23: 2,
          0x30: 8, 0x31: 8, 0x32: 8, 0x33: 8, 0x34: 8, 0x38: 0, 0x39: 0, 0x3A: 0,
          0x3B: 0, 0x3C: 0, 0x40: 8, 0x41: 8, 0x48: 0, 0x50: 8, 0x51: 8, 0x58: 0,
          0x60: 12, 0x61: 12, 0x68: 4, 0x69: 4, 0x80: 0, 0x81: 0, 0xA0: 2, 0xFF: 0}


def decode(b):
    size, t, l, bo, r = struct.unpack('>Hhhhh', b[:10])
    ops = []
    i = 10
    while i < len(b):
        op = b[i]
        i += 1
        if op in (0x01,):  # region
            n = struct.unpack('>H', b[i:i + 2])[0]
            ops.append((op, b[i:i + n])); i += n
        elif op == 0x28:  # LongText pt + count + text
            n = b[i + 4]
            ops.append((op, b[i:i + 5 + n])); i += 5 + n
        elif op in (0x29, 0x2A):
            n = b[i + 1]
            ops.append((op, b[i:i + 2 + n])); i += 2 + n
        elif op == 0x2B:
            n = b[i + 2]
            ops.append((op, b[i:i + 3 + n])); i += 3 + n
        elif op == 0x2C:  # FontName
            n = struct.unpack('>H', b[i:i + 2])[0]
            ops.append((op, b[i:i + 2 + n])); i += 2 + n
        elif op == 0xA1:  # LongComment kind, size, data
            n = struct.unpack('>H', b[i + 2:i + 4])[0]
            ops.append((op, b[i:i + 4 + n])); i += 4 + n
        elif op in (0x70, 0x71, 0x72, 0x73, 0x74, 0x80, 0x81, 0x82, 0x83, 0x84):
            n = struct.unpack('>H', b[i:i + 2])[0]
            ops.append((op, b[i:i + n])); i += n
        elif op in _FIXED:
            n = _FIXED[op]
            ops.append((op, b[i:i + n])); i += n
            if op == 0xFF:
                break
        else:
            raise ValueError('opcode %02x at %d' % (op, i - 1))
    return (t, l, bo, r), ops, b[i:]


def describe(b):
    frame, ops, rest = decode(b)
    out = ['frame t,l,b,r=%s' % (frame,)]
    for op, d in ops:
        if op == 0x28:
            v, h = struct.unpack('>hh', d[:4]); out.append('  LongText (%d,%d) %r' % (h, v, d[5:]))
        elif op in (0x29, 0x2A):
            out.append('  %sText %+d %r' % ('DH' if op == 0x29 else 'DV', d[0], d[2:]))
        elif op == 0x20:
            v1, h1, v2, h2 = struct.unpack('>hhhh', d); out.append('  Line (%d,%d)-(%d,%d)' % (h1, v1, h2, v2))
        elif op == 0x22:
            v, h, dh, dv = struct.unpack('>hhbb', d); out.append('  ShortLine (%d,%d) d(%d,%d)' % (h, v, dh, dv))
        elif op == 0x21:
            v, h = struct.unpack('>hh', d); out.append('  LineFrom (%d,%d)' % (h, v))
        elif op == 0x23:
            dh, dv = struct.unpack('>bb', d); out.append('  ShortLineFrom d(%d,%d)' % (dh, dv))
        elif op in (0x30, 0x31, 0x50):
            t, l, bo, r = struct.unpack('>hhhh', d); out.append('  %02x Rect l%d t%d r%d b%d' % (op, l, t, r, bo))
        elif op == 0xA1:
            out.append('  Comment kind=%d %s' % (struct.unpack('>h', d[:2])[0], d[4:]))
        else:
            out.append('  op%02x %s' % (op, d.hex()))
    if rest:
        out.append('  trailing %s' % rest.hex())
    return '\n'.join(out)
