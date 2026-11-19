"""Generate LogicWorks 5 circuit (.cct) and library (.clf) files."""
from .model import Design, Circuit
from .spec import build, load_spec
from .template import Template

__version__ = '0.1.0'
__all__ = ['Design', 'Circuit', 'Template', 'build', 'load_spec']
