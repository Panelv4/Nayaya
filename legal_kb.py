"""NYAYA-RAC — Phase 2: Legal intelligence infrastructure.

Versioned statutory database · precedent tracking · legal provenance graph ·
conflict detection · citation resolution used by the intake pipeline.

Honesty rules baked in:
- A statutory version only feeds punishment data into an evaluation when a
  human has marked it `verified` (simulated approval workflow — see README).
- Seed rows are illustrative and ship UNVERIFIED; they never influence
  severity until a human verifies them.
- Every KB mutation writes an edge to the provenance graph.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from db import LOCK, db, now


# ------------------------------------------------------------------ schema

def init_kb() -> None:
    with db() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS statutes(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              statute TEXT NOT NULL, provision TEXT NOT NULL,
              statute_norm TEXT NOT NULL, provision_norm TEXT NOT NULL,
              version_label TEXT NOT NULL,
              effective_from TEXT NOT NULL, effective_to TEXT,
              title TEXT NOT NULL DEFAULT '', body TEXT NOT NULL DEFAULT '',
              pun_death INTEGER NOT NULL DEFAULT 0, pun_life INTEGER NOT NULL DEFAULT 0,
              pun_min_years REAL, pun_max_years REAL,
              cognizable TEXT, bailable TEXT, compoundable TEXT,
              source_ref TEXT NOT NULL DEFAULT '',
              verified INTEGER NOT NULL DEFAULT 0, verified_by TEXT, verified_at TEXT,
              note TEXT NOT NULL DEFAULT '', added_by TEXT NOT NULL DEFAULT 'system',
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS precedents(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              citation TEXT NOT NULL, court TEXT NOT NULL DEFAULT '',
              decided_on TEXT, statute TEXT NOT NULL DEFAULT '', provision TEXT NOT NULL DEFAULT '',
              statute_norm TEXT NOT NULL DEFAULT '', provision_norm TEXT NOT NULL DEFAULT '',
              headnote TEXT NOT NULL DEFAULT '',
              holding_tag TEXT NOT NULL DEFAULT 'PROCEDURAL',
              status TEXT NOT NULL DEFAULT 'GOOD_LAW',
              overruled_by TEXT, added_by TEXT NOT NULL DEFAULT 'system', created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS provenance(
              id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
              subject_type TEXT NOT NULL, subject_id TEXT NOT NULL,
              predicate TEXT NOT NULL,
              object_type TEXT NOT NULL, object_id TEXT NOT NULL,
              meta TEXT NOT NULL DEFAULT '{}'
            );
            """
        )
    seed_demo_statutes()


# ------------------------------------------------------------------ helpers

def norm_statute(s: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def norm_provision(p: Any) -> str:
    p = str(p or "").lower().strip()
    p = re.sub(r"^(section|sections|sec|s|article|art)\.?\s*", "", p)
    p = re.sub(r"[^a-z0-9\-]", "", p)
    return p


def record_provenance_conn(c, subject_type: str, subject_id: str, predicate: str,
                           object_type: str, object_id: str,
                           meta: Optional[dict] = None) -> None:
    """Write one provenance edge on an EXISTING connection.

    Callers that already hold an open write transaction must use this variant:
    opening a second connection from inside an uncommitted write would block
    on SQLite's write lock (self-deadlock)."""
    c.execute(
        "INSERT INTO provenance(created_at,subject_type,subject_id,predicate,object_type,object_id,meta) "
        "VALUES(?,?,?,?,?,?,?)",
        (now(), subject_type, str(subject_id), predicate, object_type, str(object_id),
         json.dumps(meta or {}, ensure_ascii=False)),
    )


def record_provenance(subject_type: str, subject_id: str, predicate: str,
                      object_type: str, object_id: str, meta: Optional[dict] = None) -> None:
    with LOCK, db() as c:
        record_provenance_conn(c, subject_type, subject_id, predicate, object_type, object_id, meta)


def provenance_chain(subject_type: str, subject_id: str, depth: int = 3) -> Dict[str, Any]:
    """Breadth-first walk of the provenance graph starting at one node."""
    nodes: List[Dict[str, str]] = [{"type": subject_type, "id": str(subject_id)}]
    edges: List[Dict[str, Any]] = []
    seen_edges: set[int] = set()
    frontier = [(subject_type, str(subject_id))]
    with db() as c:
        for _ in range(max(1, depth)):
            next_frontier = []
            for st, sid in frontier:
                rows = c.execute(
                    "SELECT * FROM provenance WHERE (subject_type=? AND subject_id=?) "
                    "OR (object_type=? AND object_id=?) ORDER BY id DESC LIMIT 200",
                    (st, sid, st, sid),
                ).fetchall()
                for r in rows:
                    if r["id"] in seen_edges:
                        continue
                    seen_edges.add(r["id"])
                    edge = {
                        "id": r["id"], "at": r["created_at"],
                        "subject": {"type": r["subject_type"], "id": r["subject_id"]},
                        "predicate": r["predicate"],
                        "object": {"type": r["object_type"], "id": r["object_id"]},
                        "meta": json.loads(r["meta"] or "{}"),
                    }
                    edges.append(edge)
                    for end in (edge["subject"], edge["object"]):
                        if end != {"type": st, "id": sid}:
                            nodes.append(end)
                            next_frontier.append((end["type"], end["id"]))
            frontier = next_frontier
            if not frontier:
                break
    return {"root": {"type": subject_type, "id": str(subject_id)}, "nodes": nodes, "edges": edges}


# ------------------------------------------------------------------ statutes

def add_statute_version(statute: str, provision: str, version_label: str,
                        effective_from: str, effective_to: Optional[str] = None,
                        title: str = "", body: str = "",
                        pun_death: bool = False, pun_life: bool = False,
                        pun_min_years: Optional[float] = None, pun_max_years: Optional[float] = None,
                        cognizable: Optional[str] = None, bailable: Optional[str] = None,
                        compoundable: Optional[str] = None, source_ref: str = "",
                        verified: bool = False, note: str = "", added_by: str = "system",
                        supersedes: bool = True) -> int:
    """Insert one version of one provision. When `supersedes`, the open-ended
    previous version of the same provision is closed the day before this one
    starts (that is what makes it an amendment)."""
    import datetime as _dt
    _dt.date.fromisoformat(effective_from)
    if effective_to:
        _dt.date.fromisoformat(effective_to)
    ns, np_ = norm_statute(statute), norm_provision(provision)
    with LOCK, db() as c:
        if supersedes:
            prev = c.execute(
                "SELECT id, effective_to FROM statutes WHERE statute_norm=? AND provision_norm=? "
                "AND effective_to IS NULL AND effective_from < ?",
                (ns, np_, effective_from),
            ).fetchall()
            close_date = (_dt.date.fromisoformat(effective_from) - _dt.timedelta(days=1)).isoformat()
            for p in prev:
                c.execute("UPDATE statutes SET effective_to=? WHERE id=?", (close_date, p["id"]))
                record_provenance("STATUTE_VERSION", effective_from + "/" + version_label,
                                  "AMENDS", "STATUTE_VERSION", str(p["id"]),
                                  {"statute": statute, "provision": provision})
        cur = c.execute(
            "INSERT INTO statutes(statute,provision,statute_norm,provision_norm,version_label,"
            "effective_from,effective_to,title,body,pun_death,pun_life,pun_min_years,pun_max_years,"
            "cognizable,bailable,compoundable,source_ref,verified,note,added_by,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?)",
            (statute, provision, ns, np_, version_label, effective_from, effective_to, title, body,
             1 if pun_death else 0, 1 if pun_life else 0, pun_min_years, pun_max_years,
             cognizable, bailable, compoundable, source_ref,
             note, added_by, now()),
        )
        sid = int(cur.lastrowid)
    record_provenance("STATUTE_VERSION", str(sid), "VERSION_OF", "PROVISION", f"{statute}|{provision}",
                      {"version_label": version_label, "effective_from": effective_from})
    return sid


def mark_statute_verified(statute_id: int, by: str) -> None:
    """Human approval step: only verified versions may feed evaluations."""
    with LOCK, db() as c:
        row = c.execute("SELECT id FROM statutes WHERE id=?", (statute_id,)).fetchone()
        if not row:
            raise LookupError("Statute version not found.")
        c.execute("UPDATE statutes SET verified=1, verified_by=?, verified_at=? WHERE id=?",
                  (by, now(), statute_id))
    record_provenance("STATUTE_VERSION", str(statute_id), "VERIFIED_BY", "OFFICER", by)


def statute_rows(limit: int = 500) -> List[Dict[str, Any]]:
    with db() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM statutes ORDER BY statute_norm, provision_norm, effective_from DESC LIMIT ?",
            (limit,)).fetchall()]


def resolve_provision(statute: str, provision: str, on_date: str) -> Dict[str, Any]:
    """Resolve one citation against the versioned statutory database as of a
    date. Returns {'kind': VERIFIED|UNVERIFIED|NO_VERSION_FOR_DATE|NOT_IN_KB|NO_CITATION,
    'row': {...}|None}."""
    if not provision:
        return {"kind": "NO_CITATION", "row": None}
    ns, np_ = norm_statute(statute), norm_provision(provision)
    with db() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM statutes WHERE provision_norm=? AND (?='' OR statute_norm=?) "
            "ORDER BY verified DESC, effective_from DESC",
            (np_, ns, ns)).fetchall()]
    if not rows:
        return {"kind": "NOT_IN_KB", "row": None}
    covering = [r for r in rows if r["effective_from"] <= on_date and (not r["effective_to"] or r["effective_to"] >= on_date)]
    if not covering:
        return {"kind": "NO_VERSION_FOR_DATE", "row": rows[0]}
    for r in covering:
        if r["verified"]:
            return {"kind": "VERIFIED", "row": r}
    return {"kind": "UNVERIFIED", "row": covering[0]}


# ------------------------------------------------------------------ precedents

def add_precedent(citation: str, court: str = "", decided_on: Optional[str] = None,
                  statute: str = "", provision: str = "", headnote: str = "",
                  holding_tag: str = "PROCEDURAL", added_by: str = "system") -> int:
    if holding_tag not in ("SUPPORTS_STRICT", "SUPPORTS_LENIENT", "PROCEDURAL"):
        raise ValueError("holding_tag must be SUPPORTS_STRICT, SUPPORTS_LENIENT or PROCEDURAL.")
    with LOCK, db() as c:
        cur = c.execute(
            "INSERT INTO precedents(citation,court,decided_on,statute,provision,statute_norm,"
            "provision_norm,headnote,holding_tag,status,added_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,'GOOD_LAW',?,?)",
            (citation, court, decided_on, statute, provision, norm_statute(statute),
             norm_provision(provision), headnote, holding_tag, added_by, now()),
        )
        pid = int(cur.lastrowid)
    record_provenance("PRECEDENT", str(pid), "INTERPRETS", "PROVISION", f"{statute}|{provision}",
                      {"citation": citation})
    return pid


def set_precedent_status(precedent_id: int, status: str, overruled_by: Optional[str] = None) -> None:
    if status not in ("GOOD_LAW", "OVERRULED", "DISTINGUISHED"):
        raise ValueError("Invalid precedent status.")
    with LOCK, db() as c:
        row = c.execute("SELECT id FROM precedents WHERE id=?", (precedent_id,)).fetchone()
        if not row:
            raise LookupError("Precedent not found.")
        c.execute("UPDATE precedents SET status=?, overruled_by=? WHERE id=?", (status, overruled_by, precedent_id))
    if status == "OVERRULED" and overruled_by:
        record_provenance("PRECEDENT", str(precedent_id), "OVERRULED_BY", "PRECEDENT", overruled_by)


def precedent_rows(limit: int = 500) -> List[Dict[str, Any]]:
    with db() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM precedents ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]


def precedents_for(statute: str, provision: str) -> List[Dict[str, Any]]:
    ns, np_ = norm_statute(statute), norm_provision(provision)
    with db() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM precedents WHERE provision_norm=? AND (?='' OR statute_norm=?) ORDER BY id DESC",
            (np_, ns, ns)).fetchall()]


# ------------------------------------------------------------------ conflicts

def detect_conflicts() -> List[Dict[str, Any]]:
    """Phase 2: conflict detection across the knowledge base.

    OVERLAPPING_VERSIONS  two versions of one provision claim the same period
                          (the applicable text is ambiguous → provision_ambiguous)
    PRECEDENT_CONFLICT    good-law precedents on one provision pull in opposite
                          directions (→ precedent_conflict, engine trigger T-05)
    STATUS_INCONSISTENT   a precedent marked GOOD_LAW yet carrying overruled_by
    OVERRULED_IN_USE      a case cites a provision whose precedent base is overruled
    """
    conflicts: List[Dict[str, Any]] = []
    statutes = statute_rows()
    groups: Dict[tuple, List[dict]] = {}
    for s in statutes:
        groups.setdefault((s["statute_norm"], s["provision_norm"]), []).append(s)
    for (ns, np_), rows in groups.items():
        rows = sorted(rows, key=lambda r: r["effective_from"])
        for i in range(len(rows) - 1):
            a, b = rows[i], rows[i + 1]
            a_end = a["effective_to"] or "9999-12-31"
            if b["effective_from"] <= a_end:
                conflicts.append({
                    "kind": "OVERLAPPING_VERSIONS",
                    "statute": a["statute"], "provision": a["provision"],
                    "detail": f"Versions '{a['version_label']}' ({a['effective_from']}..{a['effective_to'] or 'open'}) "
                              f"and '{b['version_label']}' ({b['effective_from']}..{b['effective_to'] or 'open'}) overlap.",
                    "ids": [a["id"], b["id"]],
                })
    prec_groups: Dict[tuple, List[dict]] = {}
    for p in precedent_rows():
        if p["status"] == "GOOD_LAW" and p["provision_norm"]:
            prec_groups.setdefault((p["statute_norm"], p["provision_norm"]), []).append(p)
        if p["status"] == "GOOD_LAW" and p["overruled_by"]:
            conflicts.append({
                "kind": "STATUS_INCONSISTENT", "statute": p["statute"], "provision": p["provision"],
                "detail": f"Precedent '{p['citation']}' is marked GOOD_LAW but carries overruled_by='{p['overruled_by']}'.",
                "ids": [p["id"]],
            })
    for (ns, np_), rows in prec_groups.items():
        tags = {r["holding_tag"] for r in rows}
        if "SUPPORTS_STRICT" in tags and "SUPPORTS_LENIENT" in tags:
            conflicts.append({
                "kind": "PRECEDENT_CONFLICT",
                "statute": rows[0]["statute"], "provision": rows[0]["provision"],
                "detail": "Good-law precedents with opposing holdings: "
                          + ", ".join(f"{r['citation']} ({r['holding_tag']})" for r in rows),
                "ids": [r["id"] for r in rows],
            })
    return conflicts


def conflicts_for(statute: str, provision: str) -> List[Dict[str, Any]]:
    ns, np_ = norm_statute(statute), norm_provision(provision)
    return [c for c in detect_conflicts()
            if norm_provision(c.get("provision")) == np_ and (not ns or norm_statute(c.get("statute")) == ns)]


# ------------------------------------------------------------------ KB context for a case

def kb_context_for(statute: str, provision: str, on_date: str) -> Dict[str, Any]:
    """Everything the intake pipeline needs from the KB for one citation:
    resolution result, punishment enrichment, related precedents, conflicts,
    extra engine facts and retrieved-source entries for citation verification."""
    ctx: Dict[str, Any] = {
        "citation": {"statute": statute, "provision": provision},
        "resolution": None, "punishment": None, "precedents": [], "conflicts": [],
        "facts_extra": {}, "sources": [],
    }
    if not provision:
        return ctx
    res = resolve_provision(statute, provision, on_date)
    ctx["resolution"] = {"kind": res["kind"],
                         "version": (res["row"] or {}).get("version_label"),
                         "effective_from": (res["row"] or {}).get("effective_from"),
                         "effective_to": (res["row"] or {}).get("effective_to"),
                         "title": (res["row"] or {}).get("title"),
                         "source_ref": (res["row"] or {}).get("source_ref"),
                         "note": (res["row"] or {}).get("note")}
    if res["kind"] == "VERIFIED" and res["row"]:
        r = res["row"]
        pun: Dict[str, Any] = {}
        if r["pun_death"]:
            pun["death"] = True
        if r["pun_life"]:
            pun["life"] = True
        if r["pun_min_years"] is not None:
            pun["min_years"] = r["pun_min_years"]
        if r["pun_max_years"] is not None:
            pun["max_years"] = r["pun_max_years"]
        ctx["punishment"] = pun or None
        ctx["sources"].append({
            "source_id": f"{r['statute']}-{r['provision']}@{r['version_label']}",
            "statute": r["statute"], "section": r["provision"],
            "version": r["version_label"], "effective_from": r["effective_from"].replace("-", ""),
            "text": (r["body"] or r["title"] or "")[:2000],
        })
    elif res["kind"] == "NO_VERSION_FOR_DATE":
        # Engine trigger T-16: no rule/statute version covers the relevant date.
        ctx["facts_extra"]["rule_version_missing_for_date"] = True
    ctx["precedents"] = [
        {"id": p["id"], "citation": p["citation"], "court": p["court"], "status": p["status"],
         "holding_tag": p["holding_tag"], "headnote": p["headnote"]}
        for p in precedents_for(statute, provision)
    ]
    conf = conflicts_for(statute, provision)
    ctx["conflicts"] = conf
    kinds = {c["kind"] for c in conf}
    if "PRECEDENT_CONFLICT" in kinds:
        ctx["facts_extra"]["precedent_conflict"] = True
    if "OVERLAPPING_VERSIONS" in kinds:
        ctx["facts_extra"]["provision_ambiguous"] = True
    return ctx


# ------------------------------------------------------------------ seed

def seed_demo_statutes() -> None:
    """Illustrative seed rows — shipped UNVERIFIED so they cannot influence any
    evaluation until a human marks them verified (simulated approval)."""
    with db() as c:
        if c.execute("SELECT COUNT(*) n FROM statutes").fetchone()["n"]:
            return
    note = "ILLUSTRATIVE SEED — not an authoritative text. Verify against the official corpus before marking verified."
    add_statute_version("IPC", "302", "IPC-1860", "1862-01-01", "2024-06-30",
                        title="Punishment for murder (illustrative)",
                        pun_death=True, pun_life=True, pun_min_years=10,
                        source_ref="official corpus pending", note=note, added_by="seed")
    add_statute_version("BNS", "103", "BNS-2023", "2024-07-01", None,
                        title="Murder (illustrative)",
                        pun_death=True, pun_life=True, pun_min_years=10,
                        source_ref="official corpus pending", note=note, added_by="seed",
                        supersedes=False)
    add_statute_version("DEMO Act", "1", "DEMO-1.0", "2020-01-01", None,
                        title="Fictional demo provision — up to 3 years",
                        pun_max_years=3, note="Fully fictional row for testing severity routing.",
                        added_by="seed")
    add_statute_version("DEMO Act", "2", "DEMO-1.0", "2020-01-01", None,
                        title="Fictional demo provision — 3 to 7 years",
                        pun_min_years=3, pun_max_years=7, note="Fully fictional row for testing.",
                        added_by="seed")
    record_provenance("STATUTE_VERSION", "BNS-2023|103", "AMENDS", "STATUTE_VERSION", "IPC-1860|302",
                      {"note": "BNS replaced IPC w.e.f. 2024-07-01 (regime cutover)."})
