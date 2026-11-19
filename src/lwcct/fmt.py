"""LogicWorks 5 .cct / .clf reader and writer.

The file is a tree of parenthesised nodes. Each node is '(' + one tag byte +
body + ')'. The body holds space-separated hex numbers, nested nodes,
length-prefixed strings ('<hexlen> "<raw bytes>') and, for tag 'r',
a length-prefixed binary blob ('<hexlen> <raw bytes>').
"""

BLOB_TAGS = {ord('r')}
QBLOB_TAGS = {0x8b}  # '<hexlen>"<raw>' with no space (library part payload)


class Node:
    __slots__ = ('tag', 'items')

    def __init__(self, tag, items=None):
        self.tag = tag if isinstance(tag, int) else ord(tag)
        self.items = items if items is not None else []

    # items: Node | Str | Blob | Raw(bytes)
    def kids(self, tag=None):
        t = None if tag is None else (tag if isinstance(tag, int) else ord(tag))
        return [i for i in self.items if isinstance(i, Node) and (t is None or i.tag == t)]

    def kid(self, tag):
        k = self.kids(tag)
        return k[0] if k else None

    def strings(self):
        return [i.value for i in self.items if isinstance(i, Str)]

    def nums(self):
        out = []
        for i in self.items:
            if isinstance(i, Raw):
                out += [t for t in i.data.split(b' ') if t]
        return [int(t, 16) if not t.startswith(b'-') else -int(t[1:], 16) for t in out if _ishex(t)]

    def __repr__(self):
        return 'Node(%r, %d items)' % (chr(self.tag) if self.tag < 128 else hex(self.tag), len(self.items))


class Str:
    __slots__ = ('value', 'lead')

    def __init__(self, value, lead=b''):
        self.value = value if isinstance(value, bytes) else value.encode('cp949')
        self.lead = lead  # bytes between previous token and length (normally b'' or b' ')


class Blob:
    __slots__ = ('data',)

    def __init__(self, data):
        self.data = data


class QBlob:
    __slots__ = ('data',)

    def __init__(self, data):
        self.data = data


class Raw:
    __slots__ = ('data',)

    def __init__(self, data):
        self.data = data


def _ishex(t):
    t = t[1:] if t.startswith(b'-') else t
    return bool(t) and all(c in b'0123456789ABCDEFabcdef' for c in t)


def parse(data):
    pos = 0
    roots = []

    def node():
        nonlocal pos
        assert data[pos] == 0x28, (pos, data[pos:pos + 20])
        tag = data[pos + 1]
        pos += 2
        n = Node(tag)
        if tag in QBLOB_TAGS:
            q = data.index(b'"', pos)
            ln = int(data[pos:q], 16)
            n.items.append(QBlob(data[q + 1:q + 1 + ln]))
            pos = q + 1 + ln
            assert data[pos] == 0x29, ('qblob end', pos)
            pos += 1
            return n
        if tag in BLOB_TAGS:
            sp = data.index(b' ', pos)
            ln = int(data[pos:sp], 16)
            n.items.append(Blob(data[sp + 1:sp + 1 + ln]))
            pos = sp + 1 + ln
            assert data[pos] == 0x29, ('blob end', pos)
            pos += 1
            return n
        buf = bytearray()
        while True:
            c = data[pos]
            if c == 0x29:
                if buf:
                    n.items.append(Raw(bytes(buf)))
                pos += 1
                return n
            if c == 0x28:
                if buf:
                    n.items.append(Raw(bytes(buf)))
                    buf = bytearray()
                n.items.append(node())
                continue
            if c == 0x22:  # string: preceding token in buf is its hex length
                j = len(buf) - 1
                assert buf[j] == 0x20, ('str', pos, bytes(buf))
                k = j
                while k > 0 and buf[k - 1] not in b' ':
                    k -= 1
                ln = int(bytes(buf[k:j]), 16)
                lead = bytes(buf[:k])
                if lead:
                    n.items.append(Raw(lead))
                buf = bytearray()
                n.items.append(Str(data[pos + 1:pos + 1 + ln]))
                pos += 1 + ln
                continue
            buf.append(c)
            pos += 1

    while pos < len(data):
        if data[pos] == 0x28:
            roots.append(node())
        else:
            roots.append(Raw(data[pos:pos + 1]))
            pos += 1
    return roots


def dump(items):
    out = bytearray()

    def w(i):
        if isinstance(i, Node):
            out.append(0x28)
            out.append(i.tag)
            for x in i.items:
                w(x)
            out.append(0x29)
        elif isinstance(i, Str):
            out.extend(b'%X "' % len(i.value) + i.value)
        elif isinstance(i, QBlob):
            out.extend(b'%X"' % len(i.data) + i.data)
        elif isinstance(i, Blob):
            out.extend(b'%X ' % len(i.data) + i.data)
        elif isinstance(i, Raw):
            out.extend(i.data)
        else:
            raise TypeError(i)

    for i in items:
        w(i)
    return bytes(out)


def load(path):
    with open(path, 'rb') as f:
        return parse(f.read())


def show(items, depth=0, maxdepth=99, out=None, blob=False):
    """Readable indented dump."""
    lines = out if out is not None else []
    for i in items:
        if isinstance(i, Node):
            t = chr(i.tag) if 32 < i.tag < 127 else '<%02x>' % i.tag
            simple = all(not isinstance(x, Node) for x in i.items)
            if simple:
                lines.append('  ' * depth + '(' + t + ' ' + ' '.join(_fmt(x, blob) for x in i.items) + ')')
            else:
                head = ' '.join(_fmt(x, blob) for x in i.items if not isinstance(x, Node))
                lines.append('  ' * depth + '(' + t + (' ' + head if head else ''))
                if depth < maxdepth:
                    show([x for x in i.items if isinstance(x, Node)], depth + 1, maxdepth, lines, blob)
                else:
                    lines.append('  ' * (depth + 1) + '...')
        else:
            lines.append('  ' * depth + _fmt(i, blob))
    return lines if out is not None else '\n'.join(lines)


def _fmt(x, blob=False):
    if isinstance(x, Str):
        return '"' + x.value.decode('cp949', 'replace') + '"'
    if isinstance(x, QBlob):
        return '<qblob %d>' % len(x.data)
    if isinstance(x, Blob):
        return '<blob %d%s>' % (len(x.data), (' ' + x.data.hex()) if blob else '')
    if isinstance(x, Raw):
        return x.data.decode('latin1').strip()
    return repr(x)
