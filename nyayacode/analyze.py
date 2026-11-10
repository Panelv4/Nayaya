"""nyayacode.analyze — the two questions a lawyer cannot answer by reading.

1. **Which rules disagree on the same facts?**  Enumerate the declared fact
   domain, decide every point, and look for points where a case is decided one
   way by one provision and the other way by another: gaps (no branch fires) and
   overlaps (two branches fire with different verdicts, one silently losing on
   ordering).

2. **What would a change to the law do?**  Rewrite the pack (an amendment) and
   re-run the enumeration, then report how many cases move between outcomes.

Both are exhaustive over the declared domain, so the output is a proof over that
domain, not a sample. The honesty of the result depends entirely on the domain
being right — which is why every pack must declare its facts, and why the report
always states how many points were checked.
"""

from __future__ import annotations

import copy
import hashlib
import itertools
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import eval as ev
from .pack import Pack, PackError, _validate, _validate_analysable


# --------------------------------------------------------------------- helpers

def enumerate_domain(pack: Pack) -> Iterable[Dict[str, Any]]:
    """Yield every fact assignment in the declared domain (exhaustive)."""
    domain = pack.domain()
    names = list(domain)
    for combo in itertools.product(*(domain[n] for n in names)):
        yield dict(zip(names, combo))


def _key(decision: Dict[str, Any]) -> str:
    return str(decision.get("offence") or decision.get("verdict"))


def label(pack: Pack, decision: Dict[str, Any]) -> str:
    """Human label for a decision, including the outcome if there is one."""
    if decision.get("verdict") == "not_offence":
        return "not an offence"
    if decision.get("verdict") == "indeterminate":
        return "no provision applies"
    return str(decision.get("offence") or decision["verdict"])


# --------------------------------------------------------------- gaps/overlaps

def find_gaps(pack: Pack) -> Dict[str, Any]:
    """Points in the domain where no provision applies at all."""
    points = []
    total = 0
    for facts in enumerate_domain(pack):
        total += 1
        d = pack.decide(facts)
        if d.get("unmatched"):
            points.append({"facts": facts, "why": "no branch and no defeater matched"})
    return {
        "pack": pack.id, "kind": "gap", "count": len(points), "checked": total,
        "points": points,
        "reading": ("No provision decides these cases. Either the statute is silent "
                    "(a real gap a legislature could close) or the encoding is "
                    "incomplete (a defect in this pack). The tool cannot tell which; "
                    "a human must read the provision."),
    }


def find_overlaps(pack: Pack) -> Dict[str, Any]:
    """Points where two decision points match with different outcomes.

    Three distinct things can happen when more than one node matches, and only
    two of them are defects:

    * **designed override** — a defeater explicitly lists the branch in
      `overrides`. That is how "except in the cases hereinafter excepted" works,
      and it is reported as structure, not as a problem.
    * **undeclared precedence** — a defeater beats a branch without saying so, or
      two branches disagree. The outcome then depends on the author's ordering,
      not on law. This is a finding.
    * **agreement** — several provisions match and concur. Harmless, counted only.
    """
    conflicts: List[Dict[str, Any]] = []
    designed = 0
    agree = 0
    total = 0
    for facts in enumerate_domain(pack):
        total += 1
        ctx = {**facts, "param": pack.parameters}
        matches = []
        for node in pack.targets():
            try:
                if ev.evaluate(node["when"], ctx):
                    matches.append(node)
            except ev.EvalError:
                continue
        if len(matches) < 2:
            continue
        for a, b in itertools.combinations(matches, 2):
            oa, ob = _outcome_key(pack, a), _outcome_key(pack, b)
            if oa == ob:
                agree += 1
                continue
            decl = _declared_override(pack, a, b)
            if decl:
                designed += 1
                continue
            chosen = pack.decide(facts)
            conflicts.append({
                "facts": facts,
                "node_a": {"id": a["id"], "kind": a["kind"], "provision": a["provision"], "outcome": oa},
                "node_b": {"id": b["id"], "kind": b["kind"], "provision": b["provision"], "outcome": ob},
                "decided_by": chosen.get("branch"),
                "resolved_by_ordering": chosen.get("branch") in (a["id"], b["id"]),
            })
    return {
        "pack": pack.id, "kind": "overlap", "count": len(conflicts),
        "checked": total, "points": conflicts,
        "designed_overrides": designed, "agreeing_matches": agree,
        "reading": ("Undeclared contentions: two provisions each match and disagree, "
                    "and nothing in the pack says which wins, so the result depends on "
                    "evaluation order. Designed overrides (exceptions) are counted "
                    "separately and are not defects."),
    }


def _declared_override(pack: Pack, a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """True when the pack itself states which of the two beats the other."""
    for d in pack.defeaters:
        if d["id"] not in (a["id"], b["id"]):
            continue
        other = b["id"] if d["id"] == a["id"] else a["id"]
        if other in (d.get("overrides") or []):
            return True
    return False


def _outcome_key(pack: Pack, node: Dict[str, Any]) -> str:
    return _key({"verdict": node["verdict"], "offence": _offence_for(pack, node)})


def _offence_for(pack: Pack, node: Dict[str, Any]) -> Optional[str]:
    for b in pack.branches:
        if b["id"] == node["id"]:
            return b.get("offence")
    for d in pack.defeaters:
        if d["id"] == node["id"]:
            return d.get("offence")
    return None


def find_unreachable(pack: Pack) -> Dict[str, Any]:
    """Branches that never fire: dead law, or a mis-specified condition."""
    fired = {b["id"]: 0 for b in pack.branches}
    fired.update({d["id"]: 0 for d in pack.defeaters})
    total = 0
    for facts in enumerate_domain(pack):
        total += 1
        ctx = {**facts, "param": pack.parameters}
        for node in pack.targets():
            try:
                if ev.evaluate(node["when"], ctx):
                    fired[node["id"]] += 1
            except ev.EvalError:
                continue
    dead = [{"id": k, "why": "condition never true anywhere in the declared domain"}
            for k, v in fired.items() if v == 0]
    return {"pack": pack.id, "kind": "unreachable", "count": len(dead),
            "checked": total, "points": dead,
            "reading": ("These provisions are unreachable given the declared facts. "
                        "If the facts list is complete, the provision is either "
                        "redundant or the encoding is wrong.")}


def find_ambiguity_sensitivity(pack: Pack) -> Dict[str, Any]:
    """Re-decide the domain under each reading of each recorded ambiguity.

    A recorded ambiguity is only worth recording if the two readings actually
    decide cases differently. This measures that, so the claim 'this reading
    matters' comes with a number attached.
    """
    base = {json_key(f): pack.decide(f) for f in enumerate_domain(pack)}
    out = []
    for amb in pack.ambiguities:
        variants = amb.get("variants", [])
        if len(variants) < 2:
            out.append({"ambiguity": amb["id"], "provision": amb.get("provision"),
                        "status": amb.get("status"), "variant_count": len(variants),
                        "variants": [], "max_moved": None, "max_sentence_moved": None,
                        "note": "only one reading is recorded, so no measurement is possible yet"})
            continue
        counts = []
        for v in variants:
            d = copy.deepcopy(pack.doc)
            _apply_patch(d, v.get("patch", {}))
            try:
                _validate(d, f"{pack.id}:{amb['id']}:{v['id']}")
                alt = Pack(d)
                _validate_analysable(alt, f"{pack.id}:{amb['id']}:{v['id']}")
            except PackError as exc:
                counts.append({"variant": v["id"], "error": str(exc)})
                continue
            moved = 0
            sent_moved = 0
            for f in enumerate_domain(alt):
                d_alt, d_base = alt.decide(f), base[json_key(f)]
                if _key(d_alt) != _key(d_base):
                    moved += 1
                elif sentence_key(alt, f, d_alt) != sentence_key(pack, f, d_base):
                    sent_moved += 1
            counts.append({"variant": v["id"], "label": v.get("label"),
                           "moved": moved, "sentence_moved": sent_moved})
        moved_vals = [c.get("moved") for c in counts if c.get("moved") is not None]
        sent_vals = [c.get("sentence_moved") for c in counts if c.get("sentence_moved") is not None]
        out.append({
            "ambiguity": amb["id"], "provision": amb.get("provision"),
            "status": amb.get("status"), "question": amb.get("question"),
            "variants": counts,
            "max_moved": max(moved_vals) if moved_vals else None,
            "max_sentence_moved": max(sent_vals) if sent_vals else None,
        })
    return {"pack": pack.id, "kind": "ambiguity", "ambiguities": out}


def json_key(facts: Dict[str, Any]) -> str:
    return "|".join(f"{k}={facts[k]!r}" for k in sorted(facts))


# ----------------------------------------------------------------- amendments

def _apply_patch(doc: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """Apply an amendment to a pack document, in place, returning it."""
    for key in ("branches", "defeaters", "punishment_rules"):
        if key in patch:
            doc[key] = copy.deepcopy(patch[key])
    if "prepend_punishment_rules" in patch:
        doc["punishment_rules"] = (copy.deepcopy(patch["prepend_punishment_rules"])
                                   + doc.get("punishment_rules", []))
    if "append_punishment_rules" in patch:
        doc["punishment_rules"] = (doc.get("punishment_rules", [])
                                   + copy.deepcopy(patch["append_punishment_rules"]))
    if "parameters" in patch:
        doc["parameters"].update(patch["parameters"])
    if "facts" in patch:
        doc["facts"] = copy.deepcopy(patch["facts"])
    if "remove_branches" in patch:
        gone = set(patch["remove_branches"])
        known = {b["id"] for b in doc["branches"]} | {d["id"] for d in doc.get("defeaters", [])}
        unknown = gone - known
        if unknown:
            raise PackError(f"amendment removes unknown node(s) {sorted(unknown)}")
        doc["branches"] = [b for b in doc["branches"] if b["id"] not in gone]
        doc["defeaters"] = [d for d in doc.get("defeaters", []) if d["id"] not in gone]
    if "add_branches" in patch:
        # A patched node with an `overrides` key is a defeater; everything else
        # is a branch. This keeps amendments readable while preserving the
        # evaluation order the pack relies on.
        for node in copy.deepcopy(patch["add_branches"]):
            if "overrides" in node:
                doc.setdefault("defeaters", []).append(node)
            else:
                doc["branches"].append(node)
    if "edit_branches" in patch:
        by_id = {b["id"]: b for b in doc["branches"]}
        by_id.update({d["id"]: d for d in doc.get("defeaters", [])})
        for eid, changes in patch["edit_branches"].items():
            if eid not in by_id:
                raise PackError(f"amendment edits unknown node {eid!r}")
            by_id[eid].update(copy.deepcopy(changes))
    if "id" in patch:
        doc["id"] = patch["id"]
    if "version" in patch:
        doc["version"] = patch["version"]
    return doc


def amended(pack: Pack, patch: Dict[str, Any], tag: str = "amended") -> Pack:
    """Return a new Pack = this pack with `patch` applied, validated as a pack."""
    doc = _apply_patch(copy.deepcopy(pack.doc), patch)
    doc.setdefault("meta", {})
    doc["id"] = doc.get("id") or f"{pack.id}.{tag}"
    _validate(doc, f"{pack.id} -> {tag}")
    alt = Pack(doc, pack.path)
    _validate_analysable(alt, f"{pack.id} -> {tag}")
    return alt


def union_domain(before: Pack, after: Pack) -> Dict[str, List[Any]]:
    """The domain to compare over: every fact either pack declares.

    An amendment that introduces a new fact must still be measurable over the
    old fact set, so the comparison runs over the union. A pack that does not
    know a fact evaluates it at its declared default, which is exactly the
    behaviour a court would see on the day the amendment commences.
    """
    dom_b, dom_a = before.domain(), after.domain()
    names = list(dict.fromkeys(list(dom_b) + list(dom_a)))
    out: Dict[str, List[Any]] = {}
    for n in names:
        vals: List[Any] = []
        for src in (dom_b, dom_a):
            for v in src.get(n, []):
                if v not in vals:
                    vals.append(v)
        out[n] = vals
    return out


def compare(before: Pack, after: Pack) -> Dict[str, Any]:
    """Exhaustively compare two packs over the union of their fact domains.

    Returns per-outcome transition counts plus the individual points that moved,
    so every number in the report can be traced to a set of facts.
    """
    domain = union_domain(before, after)
    added = sorted(set(after.fact_names) - set(before.fact_names))
    removed = sorted(set(before.fact_names) - set(after.fact_names))
    matrix: Dict[str, Dict[str, int]] = {}
    moved: List[Dict[str, Any]] = []
    total = 0
    for facts in _iter_domain(domain):
        total += 1
        b = before.decide(facts)
        a = after.decide(facts)
        bk, ak = _key(b), _key(a)
        matrix.setdefault(bk, {}).setdefault(ak, 0)
        matrix[bk][ak] += 1
        sb, sa = sentence_key(before, facts, b), sentence_key(after, facts, a)
        if bk != ak:
            moved.append({"facts": facts, "before": bk, "after": ak, "kind": "decision",
                          "before_branch": b.get("branch"), "after_branch": a.get("branch")})
        elif sb != sa:
            moved.append({"facts": facts, "before": bk, "after": ak, "kind": "sentence",
                          "before_branch": b.get("branch"), "after_branch": a.get("branch"),
                          "before_sentence": sb, "after_sentence": sa})
    changed = len(moved)
    decisions = sum(1 for m in moved if m["kind"] == "decision")
    sentences = sum(1 for m in moved if m["kind"] == "sentence")
    return {
        "before": before.id, "after": after.id, "checked": total,
        "facts_added": added, "facts_removed": removed,
        "domain_facts": len(domain),
        "changed": changed,
        "decisions_changed": decisions,
        "sentences_changed": sentences,
        "unchanged": total - changed,
        "pct": round(100.0 * changed / total, 2) if total else 0.0,
        "pct_decisions": round(100.0 * decisions / total, 2) if total else 0.0,
        "matrix": matrix,
        "moved": moved,
        "digest_before": digest(before),
        "digest_after": digest(after),
    }


def _iter_domain(domain: Dict[str, List[Any]]) -> Iterable[Dict[str, Any]]:
    names = list(domain)
    for combo in itertools.product(*(domain[n] for n in names)):
        yield dict(zip(names, combo))


def sentence_key(pack: Pack, facts: Dict[str, Any], decision: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Which punishment rule applies to this point, if any.

    Decisions and sentences move independently: an amendment can leave the
    offence unchanged while changing every sentence, and the report must show
    that rather than calling such a change a no-op.
    """
    d = decision if decision is not None else pack.decide(facts)
    if not d.get("offence"):
        return None
    ctx = {**facts, "offence_kind": d["offence"], "param": pack.parameters}
    for rule in pack.doc.get("punishment_rules", []):
        try:
            if ev.evaluate(rule["when"], ctx):
                return rule.get("text")
        except ev.EvalError:
            continue
    return None


def neutral(pack: Pack, name: str) -> Any:
    """A 'nothing to see here' value for a fact, used to shrink witnesses."""
    f = pack.fact(name)
    if f["type"] == "bool":
        return False
    if f["type"] == "int":
        lo, _hi = f.get("range", [0, 1])
        return lo
    vals = list(f.get("values") or [])
    for candidate in ("none", "NOT_LINKED"):
        if candidate in vals:
            return candidate
    return vals[0] if vals else None


def minimal_witness(before: Pack, after: Pack, facts: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Shrink a changed point to the fewest facts that still change the outcome.

    This is delta-debugging over the fact set: reset one fact to its neutral
    value; if the case still moves between the two packs, keep the reset. What
    survives is a minimal explanation of the amendment's effect, which is far
    more useful to a reader than an arbitrary point from the enumeration.
    """
    want = (_key(before.decide(facts)), _key(after.decide(facts)))
    if want[0] == want[1]:
        return None
    current = dict(facts)
    for name in list(current):
        candidate = dict(current)
        candidate[name] = neutral(before, name)
        if candidate == current:
            continue
        try:
            got = (_key(before.decide(candidate)), _key(after.decide(candidate)))
        except ev.EvalError:
            continue
        if got == want:
            current = candidate
    return current


def minimal_witnesses(before: Pack, after: Pack, moved: List[Dict[str, Any]],
                      limit: int = 6) -> List[Dict[str, Any]]:
    """One minimal witness per distinct (before, after) transition."""
    seen: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for m in moved:
        key = (m["before"], m["after"])
        if key in seen:
            continue
        w = minimal_witness(before, after, m["facts"])
        if w is None:
            continue
        seen[key] = {
            "facts": {k: v for k, v in w.items() if v != neutral(before, k)},
            "before": m["before"], "after": m["after"],
            "before_branch": before.decide(w).get("branch"),
            "after_branch": after.decide(w).get("branch"),
            "kind": m["kind"],
            "share": sum(1 for x in moved if (x["before"], x["after"]) == key),
        }
        if len(seen) >= limit:
            break
    return list(seen.values())


def digest(pack: Pack) -> str:
    """Stable fingerprint of the decision function over the domain.

    Two packs with the same digest behave identically on every point of this
    pack's declared domain — useful as a regression test on law itself.
    """
    h = hashlib.sha256()
    for facts in enumerate_domain(pack):
        d = pack.decide(facts)
        h.update(f"{json_key(facts)}->{_key(d)};".encode())
    return h.hexdigest()[:16]


# ---------------------------------------------------------------------- report

def full_report(pack: Pack) -> Dict[str, Any]:
    """Everything the analyser has to say about one pack."""
    return {
        "pack": pack.id,
        "title": pack.title,
        "review": pack.review_context(),
        "facts": len(pack.facts),
        "domain_size": _domain_size(pack),
        "digest": digest(pack),
        "gaps": find_gaps(pack),
        "overlaps": find_overlaps(pack),
        "unreachable": find_unreachable(pack),
        "ambiguities": find_ambiguity_sensitivity(pack),
    }


def _domain_size(pack: Pack) -> int:
    n = 1
    for values in pack.domain().values():
        n *= len(values)
    return n
