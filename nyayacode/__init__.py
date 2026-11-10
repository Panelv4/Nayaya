"""nyayacode — a rules-as-code library for statute analysis (stdlib only).

The point of this package is not to run a portal. It is to make three claims
about an encoded law checkable by anyone with a laptop:

1. the encoding can be *decided* — every case in a declared fact domain gets an
   answer, and the answer cites the provision and the statutory words;
2. the encoding can be *interrogated* — gaps, overlapping provisions and
   order-dependent outcomes are found by enumeration rather than by opinion;
3. the encoding can be *changed* — an amendment is a patch to the pack, and its
   effect on the whole case space is measured, not guessed.
"""

from .pack import Pack, PackError, load, available
from . import analyze, eval as evaluator

__version__ = "1.0.0"
__all__ = ["Pack", "PackError", "load", "available", "analyze", "evaluator"]
