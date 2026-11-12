"""Graded uncertainty for NYAYA-RAC (standard library only).

The engine's facts are tri-state: TRUE / FALSE / UNKNOWN. Real intake is
fuzzier ("she *might* have a disability"). This module gives that fuzziness
four named levels, placed on a 0..1 scale of how likely a fact is to be true:

    p >= 0.90          -> definitely true   (collapses to TRUE)
    0.65 <= p < 0.90   -> maybe             (leans true)
    0.50 <= p < 0.65   -> might_be          (possible, slight lean true)
    0.35 <= p < 0.50   -> might_not_be      (possible, slight lean false)
    0.10 <= p < 0.35   -> maybe_not         (leans false)
    p < 0.10           -> definitely false  (collapses to FALSE)

SAFETY RULE (fail closed): any value inside the four graded bands collapses
to "UNKNOWN" for rule evaluation, never to TRUE or FALSE. In a legal triage
tool, doubt must raise human review (e.g. trigger T-17), never quietly settle
a fact either way. The engine still never decides a case.

Bands are module-level constants so a reviewer can change them deliberately.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional, Tuple

DEFINITE_TRUE_AT = 0.90
DEFINITE_FALSE_BELOW = 0.10

# label -> (inclusive lower bound, exclusive upper bound), highest lean first.
BANDS: Dict[str, Tuple[float, float]] = {
    "MAYBE": (0.65, DEFINITE_TRUE_AT),
    "MIGHT_BE": (0.50, 0.65),
    "MIGHT_NOT_BE": (0.35, 0.50),
    "MAYBE_NOT": (DEFINITE_FALSE_BELOW, 0.35),
}

GRADED_LABELS = frozenset(BANDS)


def _check(p: Any) -> float:
    """Validate a likelihood: a real number in [0, 1]. Booleans are rejected
    here on purpose (they are definite answers, handled by the callers)."""
    if isinstance(p, bool) or not isinstance(p, (int, float)):
        raise TypeError("likelihood must be a number between 0 and 1")
    if math.isnan(p) or not 0.0 <= p <= 1.0:
        raise ValueError("likelihood must be between 0 and 1")
    return float(p)


def _in_band(label: str, p: Any) -> bool:
    lo, hi = BANDS[label]
    return lo <= _check(p) < hi


def maybe(p: float) -> bool:
    """Leans true: 0.65 <= p < 0.90."""
    return _in_band("MAYBE", p)


def might_be(p: float) -> bool:
    """Possible, slight lean true: 0.50 <= p < 0.65."""
    return _in_band("MIGHT_BE", p)


def might_not_be(p: float) -> bool:
    """Possible, slight lean false: 0.35 <= p < 0.50."""
    return _in_band("MIGHT_NOT_BE", p)


def maybe_not(p: float) -> bool:
    """Leans false: 0.10 <= p < 0.35."""
    return _in_band("MAYBE_NOT", p)


def classify(p: Any) -> str:
    """Return TRUE, MAYBE, MIGHT_BE, MIGHT_NOT_BE, MAYBE_NOT or FALSE.

    Raises TypeError/ValueError for anything that is not a likelihood in
    [0, 1] -- a plain number such as an age (17) is not a probability, and
    silently calling it "definitely true" would be the worst kind of default
    in a legal triage tool.
    """
    if p is True:
        return "TRUE"
    if p is False:
        return "FALSE"
    p = _check(p)
    if p >= DEFINITE_TRUE_AT:
        return "TRUE"
    if p < DEFINITE_FALSE_BELOW:
        return "FALSE"
    for label, (lo, hi) in BANDS.items():
        if lo <= p < hi:
            return label
    return "UNKNOWN"  # unreachable; kept so the function can never raise here


def to_tri_state(value: Any) -> Optional[str]:
    """Collapse a graded answer to the engine's TRUE / FALSE / UNKNOWN.

    Accepts a probability (0..1), a graded label ("maybe", "might_be", ...),
    or a bool. Returns None for anything it does not recognise so callers can
    leave other values untouched. Graded values ALWAYS become "UNKNOWN".
    """
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, str):
        key = value.strip().upper().replace(" ", "_").replace("-", "_")
        return "UNKNOWN" if key in GRADED_LABELS else None
    if isinstance(value, (int, float)):
        label = classify(value)
        return label if label in ("TRUE", "FALSE") else "UNKNOWN"
    return None
