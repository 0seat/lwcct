"""Structural pieces taken from the user's LogicWorks 5 installation.

Nothing from LogicWorks is shipped with this package: the file header
(attribute definitions), page/print settings and primitive part definitions
are read at run time from the installed Examples and Libs folders.
"""
import copy
import os

from . import fmt
from .nodes import n_, is_

DEFAULT_DIRS = [
    r'C:\Program Files (x86)\LogicWorks 5',
    r'C:\Program Files\LogicWorks 5',
]
DEFAULT_LIBS = ('VHDLPrims.clf', 'Simulation IO.clf', 'Pseudo Devices.CLF', 'Simulation Gates.clf',
                'Simulation Logic.clf')
HEADER_SOURCE = os.path.join('Examples', '5-Minute Example.CCT')
PIN_LEN = 0x8C


def find_logicworks(path=None):
    """Locate the LogicWorks 5 folder (argument, $LWCCT_LOGICWORKS, default install paths)."""
    for p in [path, os.environ.get('LWCCT_LOGICWORKS')] + DEFAULT_DIRS:
        if p and os.path.isfile(os.path.join(p, HEADER_SOURCE)):
            return p
    raise FileNotFoundError('LogicWorks 5 not found; pass its folder or set LWCCT_LOGICWORKS')


def lib_to_design_type(t, name):
    """Convert a library (.clf) part entry to the in-circuit type layout.

    Libraries store the symbol box as (y0 x0 y1 x1), circuits as (x0 y0 x1 y1);
    the optional (m ...) node (e.g. Clock's simulation parameters) is kept.
    """
    items = [copy.deepcopy(t.kid('l'))]
    if t.kid('m'):
        items.append(copy.deepcopy(t.kid('m')))
    bb = t.kid(0x9b).nums()
    code = t.kid('w').nums()[0] if t.kid('w') else 0x48  # user subcircuit parts carry no (w)
    items += [n_('j', fmt.Str(name)), n_('U', (code, 0)),
              copy.deepcopy(t.kid('c')), n_(0x9b, (bb[1], bb[0], bb[3], bb[2]))]
    items += [copy.deepcopy(a) for a in t.kids(0x83)]
    lib9 = t.kid('9')
    pins = []
    for p in lib9.kids(0x88):
        x, y, typ, side = p.nums()[:4]
        it = [n_('W', (x, y)), n_(0x88, typ)]
        if side != 3:
            it.append(n_('I', side))
        it += [n_(0x95, PIN_LEN), copy.deepcopy(p.kid('h'))]
        pins.append(n_('7', *it))
    items.append(n_('9', lib9.nums()[:3], *pins))
    return n_('8', *items)


class Template:
    def __init__(self, logicworks=None, libs=DEFAULT_LIBS):
        self.root = find_logicworks(logicworks)
        top = fmt.load(os.path.join(self.root, HEADER_SOURCE))[0]
        self.header = []
        for i in top.items:
            if is_(i, '8') or is_(i, 'E'):
                break
            self.header.append(i)
        self.attr_num = {}
        for a in self.header:
            if is_(a, 0x85) and a.kid(0x84) and a.kid('g'):
                self.attr_num[a.kid('g').strings()[0].decode('cp949')] = a.kid(0x84).nums()[0]
        top_e = top.kid('E')
        self.top_e_head = [i for i in top_e.items if not (is_(i, '<') or is_(i, 'B') or is_(i, 'b'))]
        sub = [t for t in top.kids('8') if t.kid('E')][0].kid('E')
        self.sub_e_head = [i for i in sub.items if not (is_(i, '<') or is_(i, 'B'))]
        self.types = {}
        for lib in libs:
            path = os.path.join(self.root, 'Libs', lib)
            if not os.path.isfile(path):
                continue
            for t in fmt.load(path)[0].kids('8'):
                if t.kid(0x8f) and t.kid('w') and t.kid('c'):
                    name = t.kid(0x8f).strings()[0].decode('cp949').strip()
                    self.types.setdefault(name, lib_to_design_type(t, name))
