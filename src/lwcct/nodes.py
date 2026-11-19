"""Small helpers for building .cct tree nodes."""
from . import fmt


def hex_(v):
    return ('-%X' % -v) if v < 0 else ('%X' % v)


def n_(tag, *items):
    """Node with numbers (int or tuple of ints), strings-as-Str and child nodes."""
    out = []
    for i in items:
        if isinstance(i, (fmt.Node, fmt.Str, fmt.Blob, fmt.QBlob, fmt.Raw)):
            out.append(i)
        elif isinstance(i, (list, tuple)):
            out.append(fmt.Raw(' '.join(hex_(v) for v in i).encode()))
        else:
            out.append(fmt.Raw(hex_(i).encode()))
    return fmt.Node(tag, out)


def set_nums(node, *vals):
    node.items = [fmt.Raw(' '.join(hex_(v) for v in vals).encode())] + \
        [i for i in node.items if not isinstance(i, fmt.Raw)]


def set_g(attr, value):
    """Set the (g "value") child of an attribute node."""
    attr.items = [i for i in attr.items if not is_(i, 'g')] + [n_('g', fmt.Str(value))]


def is_(node, tag):
    return isinstance(node, fmt.Node) and node.tag == (tag if isinstance(tag, int) else ord(tag))
