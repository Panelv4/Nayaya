"""nyayacode.pack — load and validate a rule pack.

A pack is a single JSON document: the encoded statute *plus* the evidence
needed to judge whether the encoding is faithful. The schema is deliberately
small enough to read in one sitting:

    {
      "id": "in.bns.homicide",
      "title": "Culpable homicide and murder — BNS 2023 ss.100-105",
      "jurisdiction": "IN",
      "review": {"status": "...", "by": ..., "on": ..., "method": ...},
      "sources": [ {"id": "bns-2023", "citation": ..., "url": ..., "kind": "primary"} ],
      "citations": ["bns-2023#s100"],
      "facts": [ {"name": ..., "type": "bool|enum|int", "values": [...]} ],
      "terms": [ {"id": ..., "definition": ..., "citations": [...]} ],
      "branches": [ {"id", "provision", "offence", "verdict", "when", "citations",
                     "text", "notes"} ],
      "defeaters": [...],   # precedent-made exceptions that override a branch
      "ambiguities": [...], # known contested readings; first unresolved one wins
      "outcomes": {...},    # verdict -> {provision, label, punishment?}
      "parameters": {...}   # knobs an amendment can turn (used by impact analysis)
    }

`load` validates structure and *evaluation totality*: every branch and every
defeater must evaluate against every declared fact without raising. A pack that
fails that check cannot be analysed, so it is rejected at load time.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from . import eval as ev

PACK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "packs")
AMEND_DIR = os.path.join(PACK_DIR, "amendments")

REVIEW_STATUSES = ("reviewed", "encoded_unreviewed", "seed_unverified")

_REQUIRED_TOP = ("id", "title", "jurisdiction", "review", "sources", "facts",
                 "branches", "outcomes", "parameters")


class PackError(Exception):
    """Raised when a pack is structurally invalid or not analysable."""


class Pack:
    """A validated rule pack."""

    def __init__(self, doc: Dict[str, Any], path: Optional[str] = None):
        self.doc = doc
        self.path = path
        self.id: str = doc["id"]
        self.title: str = doc["title"]
        self.jurisdiction: str = doc["jurisdiction"]
        self.review: Dict[str, Any] = doc["review"]
        self.sources: List[Dict[str, Any]] = doc["sources"]
        self.citations: List[str] = doc.get("citations", [])
        self.facts: List[Dict[str, Any]] = doc["facts"]
        self.terms: List[Dict[str, Any]] = doc.get("terms", [])
        self.branches: List[Dict[str, Any]] = doc["branches"]
        self.defeaters: List[Dict[str, Any]] = doc.get("defeaters", [])
        self.ambiguities: List[Dict[str, Any]] = doc.get("ambiguities", [])
        self.outcomes: Dict[str, Any] = doc["outcomes"]
        self.parameters: Dict[str, Any] = doc["parameters"]

    # ------------------------------------------------------------------ facts
    @property
    def fact_names(self) -> List[str]:
        return [f["name"] for f in self.facts]

    def fact(self, name: str) -> Dict[str, Any]:
        for f in self.facts:
            if f["name"] == name:
                return f
        raise KeyError(name)

    def domain(self) -> Dict[str, List[Any]]:
        """The analysis universe: every fact's declared values."""
        out: Dict[str, List[Any]] = {}
        for f in self.facts:
            if f["type"] == "bool":
                out[f["name"]] = [True, False]
            elif f["type"] == "int":
                lo, hi = f.get("range", [0, 1])
                out[f["name"]] = list(range(int(lo), int(hi) + 1))
            elif f["type"] == "enum":
                if not f.get("values"):
                    raise PackError(f"enum fact {f['name']!r} has no values")
                out[f["name"]] = list(f["values"])
            else:
                raise PackError(f"fact {f['name']!r}: unknown type {f['type']!r}")
        return out

    # ------------------------------------------------------------- decisions
    def decide(self, facts: Dict[str, Any], parameters: Optional[Dict[str, Any]] = None
               ) -> Dict[str, Any]:
        """Apply defeaters, then branches in order; first match wins.

        Returns {"verdict", "branch", "chain", "ambiguity"} — `verdict` is one of
        eval.VERDICTS, `branch` is the id that fired (or None).
        """
        params = dict(self.parameters)
        if parameters:
            params.update(parameters)
        ctx = dict(facts)
        ctx["param"] = params

        for d in self.defeaters:
            if ev.evaluate(d["when"], ctx):
                return {"verdict": _verdict_of(d), "offence": d.get("offence"),
                        "branch": d["id"], "provision": d.get("provision"),
                        "chain": d.get("overrides", []), "ambiguity": None,
                        "defeater": True}
        for b in self.branches:
            if ev.evaluate(b["when"], ctx):
                return {"verdict": _verdict_of(b), "offence": b.get("offence"),
                        "branch": b["id"], "provision": b.get("provision"),
                        "chain": [], "ambiguity": None, "defeater": False}
        # No branch fired. That is itself a finding about the encoding, not a
        # silent default, so it is surfaced rather than guessed at.
        return {"verdict": "indeterminate", "offence": None, "branch": None,
                "provision": None, "chain": [], "ambiguity": None,
                "defeater": False, "unmatched": True}

    # ---------------------------------------------------------------- targets
    def targets(self) -> List[Dict[str, Any]]:
        """Every decision point the analyser can aim at: branches then defeaters."""
        out = []
        for b in self.branches:
            out.append({"id": b["id"], "kind": "branch", "verdict": _verdict_of(b),
                        "provision": b.get("provision"), "when": b["when"]})
        for d in self.defeaters:
            out.append({"id": d["id"], "kind": "defeater", "verdict": _verdict_of(d),
                        "provision": d.get("provision"), "when": d["when"]})
        return out

    def target(self, target_id: str) -> Dict[str, Any]:
        for t in self.targets():
            if t["id"] == target_id:
                return t
        raise KeyError(target_id)

    # ------------------------------------------------------------ disclosure
    def review_context(self) -> str:
        """One line stating how far this encoding can be trusted."""
        st = self.review.get("status", "seed_unverified")
        by = self.review.get("by") or "nobody"
        on = self.review.get("on") or "n/a"
        return f"{st} (reviewed by {by} on {on})" if st == "reviewed" \
            else f"{st} (NOT yet reviewed against the statute text)"


def _verdict_of(node: Dict[str, Any]) -> str:
    v = node.get("verdict", "indeterminate")
    if v not in ev.VERDICTS:
        raise PackError(f"{node.get('id')}: verdict {v!r} not in {ev.VERDICTS}")
    return v


# --------------------------------------------------------------------- loading

def _validate(doc: Dict[str, Any], where: str) -> None:
    for key in _REQUIRED_TOP:
        if key not in doc:
            raise PackError(f"{where}: missing top-level key {key!r}")
    if doc["review"].get("status") not in REVIEW_STATUSES:
        raise PackError(f"{where}: review.status must be one of {REVIEW_STATUSES}")
    if not doc["facts"]:
        raise PackError(f"{where}: a pack needs at least one fact")
    if not doc["branches"]:
        raise PackError(f"{where}: a pack needs at least one branch")
    for f in doc["facts"]:
        if f.get("type") == "int":
            rng = f.get("range")
            if not (isinstance(rng, list) and len(rng) == 2 and rng[0] <= rng[1]):
                raise PackError(f"{where}: int fact {f.get('name')!r} needs a [lo, hi] range; "
                                f"without one the case space cannot be enumerated")
        if f.get("type") == "enum" and not f.get("values"):
            raise PackError(f"{where}: enum fact {f.get('name')!r} needs values")
    for o in doc["outcomes"]:
        if o not in ev.VERDICTS:
            raise PackError(f"{where}: outcome {o!r} is not a verdict")

    ids = [b["id"] for b in doc["branches"]] + [d["id"] for d in doc.get("defeaters", [])]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise PackError(f"{where}: duplicate node ids {sorted(dupes)}")

    src_ids = {s["id"] for s in doc["sources"]}
    if not src_ids:
        raise PackError(f"{where}: a pack must cite at least one source")

    def check_cites(node: Dict[str, Any]) -> None:
        for c in node.get("citations", []):
            base = c.split("#", 1)[0]
            if base not in src_ids:
                raise PackError(f"{where}: {node['id']} cites unknown source {base!r}")

    for node in list(doc["branches"]) + list(doc.get("defeaters", [])) \
            + list(doc.get("terms", [])) + list(doc.get("punishment_rules", [])):
        check_cites(node)

    # Every citation in the pack must resolve to a declared source, including the
    # top-level list: a citation nobody can follow is worse than no citation.
    for cite in doc.get("citations", []):
        if cite.split("#", 1)[0] not in src_ids:
            raise PackError(f"{where}: top-level citation {cite!r} has no matching source")

    for b in doc["branches"]:
        if "when" not in b:
            raise PackError(f"{where}: branch {b['id']} has no condition")
        _verdict_of(b)

    for d in doc.get("defeaters", []):
        if "when" not in d:
            raise PackError(f"{where}: defeater {d['id']} has no condition")
        _verdict_of(d)
        for target in d.get("overrides", []):
            if target not in {b["id"] for b in doc["branches"]}:
                raise PackError(f"{where}: defeater {d['id']} overrides unknown branch {target!r}")


def _validate_analysable(pack: Pack, where: str) -> None:
    """Every decision point must evaluate against the whole declared domain."""
    domain = pack.domain()
    names = list(domain)
    # Evaluate each node over a coarse grid: full domain when small, else each
    # fact's values paired with the first value of the others. Totality is a
    # *type* property, so a coarse grid is sufficient to catch dialect errors.
    combos: List[Dict[str, Any]] = []
    size = 1
    for n in names:
        size *= len(domain[n])
    if size <= 4096:
        combos = _product(domain, names)
    else:
        for n in names:
            for v in domain[n]:
                base = {m: domain[m][0] for m in names}
                base[n] = v
                combos.append(base)
    for node in pack.targets():
        for facts in combos:
            try:
                ev.evaluate(node["when"], {**facts, "param": pack.parameters})
            except ev.EvalError as exc:
                raise PackError(
                    f"{where}: {node['id']} is not total — {exc} for {facts}") from exc


def _product(domain: Dict[str, List[Any]], names: List[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = [dict()]
    for n in names:
        grown = []
        for partial in out:
            for v in domain[n]:
                row = dict(partial)
                row[n] = v
                grown.append(row)
        out = grown
    return out


def load(name_or_path: str) -> Pack:
    """Load a pack by id (`in.bns.homicide`), file name, or path."""
    path = name_or_path
    if not os.path.exists(path):
        for cand in (os.path.join(PACK_DIR, name_or_path),
                     os.path.join(PACK_DIR, name_or_path + ".json")):
            if os.path.exists(cand):
                path = cand
                break
    if not os.path.exists(path):
        raise PackError(f"no such pack: {name_or_path!r}")
    with open(path, encoding="utf-8") as fh:
        try:
            doc = json.load(fh)
        except json.JSONDecodeError as exc:
            raise PackError(f"{path}: not valid JSON ({exc})") from exc
    _validate(doc, path)
    pack = Pack(doc, path)
    _validate_analysable(pack, path)
    return pack


def available() -> List[str]:
    """Ids of every pack shipped with the library."""
    out = []
    if not os.path.isdir(PACK_DIR):
        return out
    for fn in sorted(os.listdir(PACK_DIR)):
        if fn.endswith(".json"):
            try:
                out.append(load(fn).id)
            except PackError:
                out.append(fn[:-5] + "  [INVALID]")
    return out


# ----------------------------------------------------------------- amendments

AMEND_KINDS = ("real", "interpretive", "hypothetical")
_REQUIRED_AMENDMENT = ("id", "title", "pack", "kind", "summary", "before", "after")


class Amendment:
    """A documented change to a pack, plus the context needed to trust it.

    `kind` is load-bearing: `real` means a legislature did this, `interpretive`
    means a court could, `hypothetical` means nobody has. A report that mixes
    them without saying so would be misleading, so the field is required and is
    printed on every output.
    """

    def __init__(self, doc: Dict[str, Any], path: Optional[str] = None):
        self.doc = doc
        self.path = path
        self.id: str = doc["id"]
        self.title: str = doc["title"]
        self.pack_id: str = doc["pack"]
        self.kind: str = doc["kind"]
        self.enacted: bool = bool(doc.get("enacted", False))
        self.commencement = doc.get("commencement")
        self.summary: str = doc["summary"]
        self.source: Dict[str, Any] = doc.get("source", {})
        self.before_patch: Dict[str, Any] = doc["before"]
        self.after_patch: Dict[str, Any] = doc["after"]
        self.before_label: str = doc.get("before_label") or "before"
        self.after_label: str = doc.get("after_label") or "after"
        self.expected_reading: Optional[str] = doc.get("expected_reading")

    def label(self) -> str:
        badge = {"real": "ENACTED AMENDMENT", "interpretive": "INTERPRETIVE CHANGE",
                 "hypothetical": "HYPOTHETICAL"}[self.kind]
        return f"{badge} · {self.commencement or 'no commencement date'}"


def load_amendment(name_or_path: str) -> Amendment:
    path = name_or_path
    if not os.path.exists(path):
        for cand in (os.path.join(AMEND_DIR, name_or_path),
                     os.path.join(AMEND_DIR, name_or_path + ".json")):
            if os.path.exists(cand):
                path = cand
                break
    if not os.path.exists(path):
        raise PackError(f"no such amendment: {name_or_path!r}")
    with open(path, encoding="utf-8") as fh:
        try:
            doc = json.load(fh)
        except json.JSONDecodeError as exc:
            raise PackError(f"{path}: not valid JSON ({exc})") from exc
    for key in _REQUIRED_AMENDMENT:
        if key not in doc:
            raise PackError(f"{path}: amendment missing {key!r}")
    if doc["kind"] not in AMEND_KINDS:
        raise PackError(f"{path}: kind must be one of {AMEND_KINDS}")
    return Amendment(doc, path)


def amendments() -> List[str]:
    out = []
    if not os.path.isdir(AMEND_DIR):
        return out
    for fn in sorted(os.listdir(AMEND_DIR)):
        if fn.endswith(".json"):
            try:
                out.append(load_amendment(fn).id)
            except PackError:
                out.append(fn[:-5] + "  [INVALID]")
    return out
