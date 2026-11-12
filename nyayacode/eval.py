"""nyayacode.eval — a small, total, deterministic evaluator (stdlib only).

Design notes
------------
JSON Logic is pleasant to author but has three properties that make formal
analysis hard: operators are not total (missing data silently evaluates false),
errors are heterogeneous (union of a dict with an int, etc.), and `var` lookups
are untyped. This module therefore evaluates a *restricted* dialect:

* `var` may carry a `type` (one of the TYPE_KINDS) and an optional `default`.
  When both are present the lookup is **total**: an unassigned variable yields
  its declared default, so the expression always evaluates.
* Only a fixed operator set is accepted; anything else raises `EvalError`
  rather than quietly falling through.
* Values are JSON scalars. No exceptions escape for well-formed expressions.

The analyser in `analyze.py` relies on totality: it can only reason about
"which region of fact-space produces which verdict" if every point in the space
yields a verdict.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping

TYPE_KINDS = ("bool", "enum", "int", "str")

# Verdicts are a closed set. A decision that is not one of these is not a
# decision, and the analyser treats any other value as a defect.
VERDICTS = ("not_offence", "offence", "indeterminate")

OPS = frozenset({
    "var", "==", "!=", ">=", ">", "<=", "<", "in", "and", "or", "not",
})


class EvalError(Exception):
    """Raised for expressions outside the supported dialect."""


def _coerce(kind: str, raw: Any) -> Any:
    """Coerce a runtime fact to the declared type, or return None if it cannot be."""
    if kind == "bool":
        if isinstance(raw, bool):
            return raw
        if raw in (0, 1):
            return bool(raw)
        if isinstance(raw, str) and raw.lower() in ("true", "yes", "1"):
            return True
        if isinstance(raw, str) and raw.lower() in ("false", "no", "0"):
            return False
        return None
    if kind == "int":
        if isinstance(raw, bool):
            return None
        if isinstance(raw, int):
            return raw
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            return None
    if kind == "str":
        return None if raw is None else str(raw)
    if kind == "enum":
        return None if raw is None else str(raw)
    raise EvalError(f"unknown type {kind!r}")


def _get(facts: Mapping[str, Any], decl: Mapping[str, Any]) -> Any:
    name = decl.get("var")
    if not isinstance(name, str) or not name:
        raise EvalError("var needs a name")
    kind = decl.get("type")
    if kind is not None and kind not in TYPE_KINDS:
        raise EvalError(f"var {name!r}: bad type {kind!r}")
    raw = _lookup(facts, name)
    if raw is _MISSING:
        if "default" in decl:
            return decl["default"]
        # A typed var without an assigned fact and without a default is a
        # modelling error: the analyser must see totality break, not blend it away.
        raise EvalError(f"var {name!r}: no fact and no default")
    if kind is None:
        return raw
    val = _coerce(kind, raw)
    if val is None:
        if "default" in decl:
            return decl["default"]
        raise EvalError(f"var {name!r}: cannot coerce {raw!r} to {kind}")
    return val


def _lookup(facts: Mapping[str, Any], name: str) -> Any:
    """Resolve a dotted name (`param.threshold_mg`) against nested facts."""
    if name in facts:
        return facts[name]
    node: Any = facts
    for part in name.split("."):
        if isinstance(node, Mapping) and part in node:
            node = node[part]
        else:
            return _MISSING
    return node


class _Missing:
    def __repr__(self) -> str:            # pragma: no cover - debug aid
        return "<missing>"


_MISSING = _Missing()


def evaluate(expr: Any, facts: Mapping[str, Any]) -> Any:
    """Evaluate a restricted-dialect expression against `facts`."""
    # A bare literal is a value, not an operator (as in JSON Logic). It has no
    # type of its own; the surrounding operator decides what it means.
    if not isinstance(expr, dict):
        # Bare lists are literals too: `in` needs a haystack. Elements are not
        # evaluated, so a list can never smuggle in an operator.
        if isinstance(expr, list):
            return [evaluate(x, facts) if isinstance(x, dict) else x for x in expr]
        return expr

    # A var declaration is the one node allowed more than one key
    # ({"var": name, "type": ..., "default": ...}) because it carries its type.
    if "var" in expr:
        extra = set(expr) - {"var", "type", "default"}
        if extra:
            raise EvalError(f"var declaration has unknown keys {sorted(extra)}")
        return _get(facts, expr)

    if len(expr) != 1:
        raise EvalError(f"operator node must have exactly one key, got {expr!r}")
    (op, arg), = expr.items()
    if op not in OPS:
        raise EvalError(f"unsupported operator {op!r}")

    if op == "not":
        return not _truth(evaluate(arg, facts))

    if op == "and":
        if not isinstance(arg, list):
            raise EvalError("and expects a list")
        return all(_truth(evaluate(a, facts)) for a in arg)

    if op == "or":
        if not isinstance(arg, list):
            raise EvalError("or expects a list")
        return any(_truth(evaluate(a, facts)) for a in arg)

    if op == "in":
        if not isinstance(arg, list) or len(arg) != 2:
            raise EvalError("in expects [needle, haystack]")
        needle = evaluate(arg[0], facts)
        hay = evaluate(arg[1], facts)
        if not isinstance(hay, list):
            raise EvalError("in: haystack must be a list")
        return needle in hay

    if not isinstance(arg, list) or len(arg) != 2:
        raise EvalError(f"{op} expects two operands")
    left = evaluate(arg[0], facts)
    right = evaluate(arg[1], facts)

    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    return _compare(op, left, right)


def _compare(op: str, left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        raise EvalError(f"{op} is not defined on booleans")
    try:
        if op == ">=":
            return left >= right
        if op == ">":
            return left > right
        if op == "<=":
            return left <= right
        return left < right
    except TypeError as exc:
        raise EvalError(f"{op}: incomparable operands {left!r} / {right!r}") from exc


def _truth(value: Any) -> bool:
    """Strict truthiness: only real booleans are conditions."""
    if isinstance(value, bool):
        return value
    raise EvalError(f"condition must be boolean, got {value!r}")
