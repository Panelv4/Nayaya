"""NYAYA-RAC v0.5.0 — citizen reporting portal + decision-support server.

Pure Python standard library.

Pages:
  /            homepage
  /login       login + registration
  /dashboard   post-login hub
  /submit      victim intake: narrative + key details + evidence + DigiLocker placeholder
  /cases       the logged-in user's own previous cases
  /case?id=..  full case record (strict access control, see below)
  /disclosed   public registry of cases an admin has manually approved for disclosure
  /admin       admin console: disclosure approvals, manual checks, re-evaluation, feedback
  /kb          legal knowledge base: versioned statutes, precedents, provenance, conflicts
  /engine      rules-as-code analysis (packs, gaps, amendment impact)
  /workbench   legacy technical engine workbench (ADMIN ONLY)
  /health      liveness probe (no auth): {"ok": true, ...}

Access model (strict):
  - A case is PRIVATE by default: only its owner and admins can view it.
  - The owner may request disclosure; an ADMIN must manually approve it
    (ANONYMIZED or FULL mode) before any other logged-in user can see it.
  - APIs enforce this server-side (404 for non-disclosed foreign cases).
  - /workbench, /audit, /schema, /evaluate and all /api/admin/* require ADMIN.

Feedback loop:
  - Every viewer with access can cast one thumbs-up / thumbs-down per case (stored per user and
    revision, changeable). Net-negative cases (down - up >= 2) are auto-flagged
    for admin review. Feedback is exported as a labeled JSONL dataset
    (/api/admin/feedback?export=jsonl) — the deterministic rule engine never
    self-modifies; the export is an audited record of how the routing was received.

DigiLocker: still a UI placeholder with intentionally empty backend stubs.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
import time
import uuid
from functools import partial
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import digilocker as dl_mod
import engine as engine_mod
import legal_kb
from db import ENGINE_LOCK, LOCK, DB_PATH, EVIDENCE_DIR, db, ensure_columns, now, now_dt, today

ROOT = os.path.dirname(os.path.abspath(__file__))
PAGES = os.path.join(ROOT, "pages")
ASSETS = os.path.join(ROOT, "assets")

ENGINE = engine_mod.Engine()

SESSION_COOKIE = "nyaya_session"
# Relay cookie: same value, but readable by JS so pages can bootstrap a session
# even when third-party cookies and web storage are both unavailable (preview
# iframes). SameSite=Lax means it still travels on top-level navigation.
RELAY_COOKIE = "nyaya_relay"
SESSION_DAYS = 7
PASSWORD_ITERATIONS = 120_000
MAX_EVIDENCE_FILES = 5
MAX_EVIDENCE_BYTES = 5 * 1024 * 1024
MAX_REPORT_BODY = 45 * 1024 * 1024
NARRATIVE_MIN, NARRATIVE_MAX = 30, 8000
FEEDBACK_FLAG_THRESHOLD = 2   # net negatives before a case is auto-flagged

ADMIN_EMAIL = os.environ.get("NYAYA_ADMIN_EMAIL", "admin@nyaya.local")
# Credentials: never a literal default. The password is either supplied by the
# operator or generated once per install and written to a file only the owner
# can read. See `nyaya_admin_credentials` in the README.
ADMIN_CREDENTIALS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      ".nyaya-admin-credentials")
ADMIN_PASSWORD = os.environ.get("NYAYA_ADMIN_PASSWORD", "")
_BANNED_PASSWORDS = {"NyayaAdmin@123", "password", "admin", "changeme"}

DOMAINS = ["CRIMINAL", "CIVIL", "FAMILY", "OTHER"]
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

ENUMS = {
    "victim_under18":     ["yes", "no", "prefer_not"],
    "woman_or_girl":      ["yes", "no", "prefer_not"],
    "sexual_offence":     ["yes", "no", "unsure"],
    "accused_in_custody": ["yes", "no", "dont_know"],
    "liberty_threat":     ["yes", "no"],
    "accused_under18":    ["yes", "no", "dont_know", ""],
    "has_lawyer":         ["yes", "no", "not_yet"],
}
CHECKBOXES = ["disability", "mental_illness", "sc_st_atrocities", "transgender", "senior_citizen"]
MAPPABLE_FACTS = list(ENUMS.keys()) + CHECKBOXES + ["incident_date", "incident_end_date", "location", "domain", "narrative", "provision"]

LEVEL_NAMES = {
    "L0": "Administrative automation",
    "L1": "Standard verification",
    "L2": "Mandatory enhanced manual review",
    "L3": "Mandatory judicial determination",
}
DISCLOSURE_STATUSES = ["PRIVATE", "PENDING", "DISCLOSED", "REJECTED"]
MANUAL_CHECK_STATUSES = ["UNCHECKED", "VERIFIED", "NEEDS_CORRECTION", "REJECTED"]

KEYWORD_CATEGORIES = {
    "sexual offence": ["rape", "sexual assault", "sexual harassment", "molest", "pocso", "outraging modesty"],
    "child/minor": ["child", "minor", "underage", "schoolgirl", "schoolboy", "kid"],
    "violence/injury": ["assault", "beat", "murder", "kill", "stab", "injur", "grievous hurt", "acid"],
    "liberty/custody": ["kidnap", "abduct", "hostage", "detain", "wrongful confinement", "traffick", "forced labour"],
    "threat/coercion": ["threat", "blackmail", "extort", "stalk", "intimidat", "dowry"],
    "weapon": ["weapon", "gun", "pistol", "knife", "lathi", "firearm", "bomb"],
    "caste/atrocity": ["caste", "sc/st", "atrocit", "untouchability"],
    "fraud/cyber": ["fraud", "cheat", "cyber", "morph", "fake photo", "online", "upi", "bank account"],
    "domestic": ["domestic violence", "husband", "in-laws", "marital"],
}


class AccessDenied(Exception):
    pass


class NotFound(Exception):
    pass


# ---------------------------------------------------------------- database

def init_db() -> None:
    with db() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users(
              id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
              pass_salt TEXT NOT NULL, pass_hash TEXT NOT NULL, created_at TEXT NOT NULL,
              digilocker_status TEXT NOT NULL DEFAULT 'NOT_LINKED', digilocker_ref TEXT
            );
            CREATE TABLE IF NOT EXISTS sessions(
              token TEXT PRIMARY KEY, user_id TEXT NOT NULL,
              created_at TEXT NOT NULL, expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reports(
              id TEXT PRIMARY KEY, ref TEXT NOT NULL, user_id TEXT NOT NULL,
              created_at TEXT NOT NULL, narrative TEXT NOT NULL,
              incident_date TEXT NOT NULL, incident_end_date TEXT, location TEXT,
              domain TEXT NOT NULL, answers TEXT NOT NULL, facts TEXT NOT NULL,
              derived_runtime TEXT NOT NULL, keywords TEXT NOT NULL, intake_notes TEXT NOT NULL,
              engine_output TEXT NOT NULL, validators TEXT NOT NULL, audit_id INTEGER,
              review_level TEXT NOT NULL, urgency TEXT NOT NULL, severity_tier TEXT NOT NULL,
              confidence REAL NOT NULL, digilocker_status TEXT NOT NULL DEFAULT 'NOT_LINKED',
              evidence_count INTEGER NOT NULL DEFAULT 0, no_evidence_ack INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS evidence(
              id INTEGER PRIMARY KEY AUTOINCREMENT, report_id TEXT NOT NULL,
              filename TEXT NOT NULL, content_type TEXT, size INTEGER NOT NULL,
              sha256 TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
              stored_path TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS revisions(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              report_id TEXT NOT NULL, rev_no INTEGER NOT NULL, created_at TEXT NOT NULL,
              actor TEXT NOT NULL, actor_name TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
              narrative TEXT NOT NULL, incident_date TEXT NOT NULL, incident_end_date TEXT,
              location TEXT, domain TEXT NOT NULL, answers TEXT NOT NULL, facts TEXT NOT NULL,
              derived_runtime TEXT NOT NULL, keywords TEXT NOT NULL, intake_notes TEXT NOT NULL,
              kb_context TEXT NOT NULL DEFAULT '{}',
              engine_output TEXT NOT NULL, validators TEXT NOT NULL, audit_id INTEGER,
              review_level TEXT NOT NULL, urgency TEXT NOT NULL, severity_tier TEXT NOT NULL,
              confidence REAL NOT NULL,
              UNIQUE(report_id, rev_no)
            );
            CREATE TABLE IF NOT EXISTS feedback(
              id INTEGER PRIMARY KEY AUTOINCREMENT, report_id TEXT NOT NULL, user_id TEXT NOT NULL,
              rev_no INTEGER NOT NULL, vote INTEGER NOT NULL, comment TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              UNIQUE(report_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS evidence_fact_map(
              id INTEGER PRIMARY KEY AUTOINCREMENT, report_id TEXT NOT NULL,
              evidence_id INTEGER NOT NULL, fact_key TEXT NOT NULL, relation TEXT NOT NULL,
              note TEXT NOT NULL DEFAULT '', mapped_by TEXT NOT NULL, mapped_role TEXT NOT NULL,
              created_at TEXT NOT NULL,
              UNIQUE(evidence_id, fact_key)
            );
            """
        )
        ensure_columns(c, "users", [("role", "TEXT NOT NULL DEFAULT 'USER'")])
        ensure_columns(c, "reports", [
            ("current_rev_no", "INTEGER NOT NULL DEFAULT 1"),
            ("disclosure_status", "TEXT NOT NULL DEFAULT 'PRIVATE'"),
            ("disclosure_mode", "TEXT NOT NULL DEFAULT 'ANONYMIZED'"),
            ("disclosed_at", "TEXT"),
            ("disclosure_note", "TEXT NOT NULL DEFAULT ''"),
            ("disclosure_request_note", "TEXT NOT NULL DEFAULT ''"),
            ("manual_check_status", "TEXT NOT NULL DEFAULT 'UNCHECKED'"),
            ("manual_check_note", "TEXT NOT NULL DEFAULT ''"),
            ("manual_check_by", "TEXT NOT NULL DEFAULT ''"),
            ("manual_check_at", "TEXT"),
            ("feedback_up", "INTEGER NOT NULL DEFAULT 0"),
            ("feedback_down", "INTEGER NOT NULL DEFAULT 0"),
            ("feedback_flagged", "INTEGER NOT NULL DEFAULT 0"),
            ("kb_context", "TEXT NOT NULL DEFAULT '{}'"),
        ])
    backfill_revisions()


def backfill_revisions() -> None:
    """Migration: give every pre-existing report its revision 1 snapshot."""
    with LOCK, db() as c:
        rows = c.execute("SELECT * FROM reports").fetchall()
        for r in rows:
            n = c.execute("SELECT COUNT(*) n FROM revisions WHERE report_id=?", (r["id"],)).fetchone()["n"]
            if not n:
                c.execute(
                    "INSERT INTO revisions(report_id,rev_no,created_at,actor,actor_name,reason,narrative,"
                    "incident_date,incident_end_date,location,domain,answers,facts,derived_runtime,keywords,"
                    "intake_notes,kb_context,engine_output,validators,audit_id,review_level,urgency,"
                    "severity_tier,confidence) VALUES(?,?,?,?,?,'Migrated from original submission',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (r["id"], 1, r["created_at"], "SYSTEM", "migration", r["narrative"], r["incident_date"],
                     r["incident_end_date"], r["location"], r["domain"], r["answers"], r["facts"],
                     r["derived_runtime"], r["keywords"], r["intake_notes"], r["kb_context"],
                     r["engine_output"], r["validators"], r["audit_id"], r["review_level"],
                     r["urgency"], r["severity_tier"], r["confidence"]),
                )
                c.execute("UPDATE reports SET current_rev_no=1 WHERE id=?", (r["id"],))


# ---------------------------------------------------------------- auth core

def hash_password(pw: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), PASSWORD_ITERATIONS)
    return salt, dk.hex()


def verify_password(pw: str, salt: str, expected_hex: str) -> bool:
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), PASSWORD_ITERATIONS)
    return hmac.compare_digest(dk.hex(), expected_hex)


def create_user(name: str, email: str, password: str, role: str = "USER") -> dict:
    if not 2 <= len(name) <= 80:
        raise ValueError("Please enter a full name (2–80 characters).")
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise ValueError("Please enter a valid email address.")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    salt, phash = hash_password(password)
    uid = uuid.uuid4().hex
    with LOCK, db() as c:
        if c.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise ValueError("An account with this email already exists. Please log in.")
        c.execute("INSERT INTO users(id,name,email,pass_salt,pass_hash,created_at,role) VALUES(?,?,?,?,?,?,?)",
                  (uid, name.strip(), email, salt, phash, now(), role))
        row = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return dict(row)


def authenticate(email: str, password: str) -> dict:
    with db() as c:
        row = c.execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
    if not row or not verify_password(password, row["pass_salt"], row["pass_hash"]):
        raise ValueError("Invalid email or password.")
    return dict(row)


def create_session(user_id: str) -> str:
    token = secrets.token_hex(32)
    expires = (now_dt() + dt.timedelta(days=SESSION_DAYS)).isoformat()
    with LOCK, db() as c:
        c.execute("INSERT INTO sessions VALUES(?,?,?,?)", (token, user_id, now(), expires))
    return token


def session_user(token: str | None):
    if not token:
        return None
    with db() as c:
        row = c.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id "
            "WHERE s.token=? AND s.expires_at > ?", (token, now_dt().isoformat())).fetchone()
    return dict(row) if row else None


def _admin_password() -> str:
    """Resolve the bootstrap administrator password.

    Order: NYAYA_ADMIN_PASSWORD, then the per-install generated secret. A weak or
    well-known password is refused rather than quietly used.
    """
    pw = ADMIN_PASSWORD
    if pw:
        if pw in _BANNED_PASSWORDS or len(pw) < 12:
            raise SystemExit(
                "Refusing to start: NYAYA_ADMIN_PASSWORD is too weak or is the old "
                "default. Use at least 12 characters.")
        return pw
    try:
        with open(ADMIN_CREDENTIALS_FILE, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("password="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    import secrets
    pw = secrets.token_urlsafe(18)
    fd = os.open(ADMIN_CREDENTIALS_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(f"# generated by NYAYA-RAC on first run; delete this file to rotate\n")
        fh.write(f"email={ADMIN_EMAIL}\npassword={pw}\n")
    return pw


def ensure_admin() -> None:
    """Seed the first administrator account with a generated password."""
    with db() as c:
        if c.execute("SELECT 1 FROM users WHERE role='ADMIN' LIMIT 1").fetchone():
            return
    pw = _admin_password()
    create_user("Administrator", ADMIN_EMAIL, pw, role="ADMIN")
    where = "NYAYA_ADMIN_PASSWORD" if ADMIN_PASSWORD else ADMIN_CREDENTIALS_FILE
    print(f"[init] Seeded admin {ADMIN_EMAIL}; password from {where}. "
          f"Change it before exposing this server.", flush=True)


def rotate_admin_password(email: str | None = None) -> str:
    """Replace the administrator password with a generated one.

    Writes the new secret to ADMIN_CREDENTIALS_FILE (mode 0600) and returns it.
    Use this after cloning an install, or whenever a password may have leaked.
    """
    email = (email or ADMIN_EMAIL).strip().lower()
    pw = secrets.token_urlsafe(18)
    salt, digest = hash_password(pw)
    with LOCK, db() as c:
        row = c.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if not row:
            raise SystemExit(f"no such user: {email}")
        c.execute("UPDATE users SET pass_salt=?, pass_hash=? WHERE id=?", (salt, digest, row["id"]))
        # every existing session belongs to the old credential
        c.execute("DELETE FROM sessions WHERE user_id=?", (row["id"],))
    fd = os.open(ADMIN_CREDENTIALS_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("# generated by NYAYA-RAC; delete to rotate on next start\n")
        fh.write(f"email={email}\npassword={pw}\n")
    return pw


def promote_admin(email: str) -> bool:
    with LOCK, db() as c:
        cur = c.execute("UPDATE users SET role='ADMIN' WHERE email=?", (email.strip().lower(),))
        return cur.rowcount > 0


def sanitize_filename(name: str) -> str:
    name = os.path.basename(str(name or "").replace("\\", "/")).strip()
    name = re.sub(r"[^\w.\- ]+", "_", name)[:120]
    return name or "evidence.bin"


# ---------------------------------------------------------------- intake core

def parse_incident_date(value: str, field_label: str) -> dt.date:
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise ValueError(f"{field_label} must be a valid date in YYYY-MM-DD format.")
    try:
        d = dt.date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{field_label} is not a real calendar date.")
    if d.year < 1900:
        raise ValueError(f"{field_label} must be 1900 or later.")
    if d > today():
        raise ValueError(f"{field_label} cannot be in the future.")
    return d


def scan_keywords(narrative: str) -> dict:
    low = narrative.lower()
    return {cat: [t for t in terms if t in low]
            for cat, terms in KEYWORD_CATEGORIES.items() if any(t in low for t in terms)}


def tri_state(answer: str) -> str:
    return {"yes": "TRUE", "no": "FALSE"}.get(answer, "UNKNOWN")


def validate_intake_body(body: dict) -> dict:
    """Shared validation for first submission and revisions. Returns a dict with
    narrative, dates, location and validated answers."""
    narrative = str(body.get("narrative", "")).strip()
    if not NARRATIVE_MIN <= len(narrative) <= NARRATIVE_MAX:
        raise ValueError(f"Please describe what happened in at least {NARRATIVE_MIN} characters (maximum {NARRATIVE_MAX}).")
    start = parse_incident_date(body.get("incident_date"), "Incident date")
    end_raw = (body.get("incident_end_date") or "").strip()
    end = None
    if end_raw:
        end = parse_incident_date(end_raw, "Incident end date")
        if end < start:
            raise ValueError("Incident end date cannot be before the start date.")
    location = str(body.get("location", "")).strip()[:200]
    answers: dict = {"domain": str(body.get("domain", "")).strip().upper()}
    if answers["domain"] not in DOMAINS:
        raise ValueError("Please choose a valid case type (domain).")
    for key, allowed in ENUMS.items():
        v = str(body.get(key, "")).strip().lower()
        if v not in allowed:
            if key == "accused_under18" and v == "":
                v = ""
            else:
                raise ValueError(f"Please answer the question mapped to '{key}'.")
        answers[key] = v
    for key in CHECKBOXES:
        answers[key] = bool(body.get(key))
    answers["provision"] = str(body.get("provision", "")).strip()[:80]
    answers["statute"] = str(body.get("statute", "")).strip()[:80]
    return {"narrative": narrative, "start": start, "end": end, "location": location, "answers": answers}


def build_engine_inputs(answers: dict, incident_date: dt.date, incident_end: dt.date | None):
    """Map plain-language answers onto the engine schema (nested facts with
    explicit tri-state strings) + derive the internal runtime values that
    replaced the removed user-facing 'Runtime variables' section."""
    sexual, woman = answers["sexual_offence"], answers["woman_or_girl"]
    if sexual == "yes" and woman == "yes":
        wvso = "TRUE"
    elif sexual == "no" or woman == "no":
        wvso = "FALSE"
    else:
        wvso = "UNKNOWN"
    victim_minor = {"yes": "CONFIRMED_MINOR", "no": "CONFIRMED_ADULT"}.get(answers["victim_under18"], "UNDETERMINED")

    facts: dict = {
        "task_class": "SUBSTANTIVE",
        "domain": answers["domain"],
        "offence": {
            "start_yyyymmdd": int(incident_date.strftime("%Y%m%d")),
            "end_yyyymmdd": int((incident_end or incident_date).strftime("%Y%m%d")),
        },
        "parties": {
            "victim_minor_status": victim_minor,
            "victim_age_basis": "Self-declared at intake (unverified)",
        },
        "flags": {
            "woman_victim_sexual_offence": wvso,
            "disability": "TRUE" if answers["disability"] else "FALSE",
            "mental_illness": "TRUE" if answers["mental_illness"] else "FALSE",
            "sc_st_atrocities_applicability": "TRUE" if answers["sc_st_atrocities"] else "FALSE",
            "transgender": "TRUE" if answers["transgender"] else "FALSE",
            "senior_citizen": "TRUE" if answers["senior_citizen"] else "FALSE",
            "unrepresented_party": {"yes": "FALSE", "no": "TRUE", "not_yet": "TRUE"}.get(answers["has_lawyer"], "UNKNOWN"),
            "in_custody": tri_state(answers["accused_in_custody"]),
        },
        "is_sexual_offence": sexual == "yes",
        "touches_personal_liberty": answers["liberty_threat"] == "yes" or answers["accused_in_custody"] == "yes",
        "offences": [],
    }
    if answers.get("accused_under18") == "yes":
        facts["parties"]["accused_minor_status"] = "CONFIRMED_MINOR"
    elif answers.get("accused_under18") == "no":
        facts["parties"]["accused_minor_status"] = "CONFIRMED_ADULT"
    provision = (answers.get("provision") or "").strip()
    if provision:
        facts["offences"].append({
            "provision": provision,
            "statute": (answers.get("statute") or "NOT SPECIFIED").strip() or "NOT SPECIFIED",
            "max_punishment": "Not specified",
            "verified_in_corpus": False,
        })

    runtime: dict = {}
    if answers["has_lawyer"] == "yes":
        runtime["legal_aid_check_status"] = "RESOLVED"
        runtime["victim_unrepresented"] = False
    elif answers["has_lawyer"] in ("no", "not_yet"):
        runtime["legal_aid_check_status"] = "UNRESOLVED"
        runtime["victim_unrepresented"] = True
    if answers["accused_in_custody"] == "yes":
        runtime["person_in_custody"] = True
    return facts, runtime


def apply_kb_context(facts: dict, kb: dict) -> None:
    """Phase 2 wiring: punishment data from a HUMAN-VERIFIED statutory version,
    KB-derived engine facts (rule_version_missing_for_date, precedent_conflict,
    provision_ambiguous)."""
    if kb.get("punishment") and facts.get("offences"):
        facts["offences"][0]["punishment"] = kb["punishment"]
        facts["offences"][0]["verified_in_corpus"] = True
        if kb["resolution"].get("title"):
            facts["offences"][0]["court_of_trial"] = "To be determined"
    for k, v in (kb.get("facts_extra") or {}).items():
        facts[k] = v


def kb_intake_note(kb: dict) -> str | None:
    res = (kb or {}).get("resolution")
    if not res:
        return None
    kind = res.get("kind")
    if kind == "VERIFIED":
        return (f"Citation resolved against VERIFIED statutory version '{res.get('version')}' "
                f"(in force {res.get('effective_from')}..{res.get('effective_to') or 'open'}); "
                "punishment data applied to severity routing.")
    if kind == "UNVERIFIED":
        return ("Citation found in the knowledge base but NOT yet human-verified; "
                "punishment data was NOT applied. An officer should verify the text against the official corpus.")
    if kind == "NO_VERSION_FOR_DATE":
        return "No statutory version covers the incident date; flagged for the registry (engine trigger T-16)."
    if kind == "NOT_IN_KB":
        return "Citation not present in the statutory knowledge base; marked NOT VERIFIED IN CORPUS."
    return None


def build_intake_notes(narrative: str, keywords: dict, evidence_count: int, no_evidence_ack: bool,
                       kb: dict | None = None, user_id: str | None = None) -> list[str]:
    notes: list[str] = []
    if keywords:
        notes.append("Mechanical keyword scan (not AI) detected narrative terms related to: "
                     + ", ".join(keywords.keys())
                     + ". Registry should reconcile the narrative with the structured answers and evidence.")
    if len(narrative.strip()) < 90:
        notes.append("Narrative is brief; registry may request further detail from the complainant.")
    if evidence_count:
        notes.append(f"{evidence_count} evidence file(s) attached and registered with SHA-256 hashes.")
    elif no_evidence_ack:
        notes.append("Complainant confirmed no evidence is available to attach at this time.")
    kb_note = kb_intake_note(kb or {})
    if kb_note:
        notes.append(kb_note)
    if (kb or {}).get("conflicts"):
        notes.append("Knowledge-base conflicts touch the cited provision: "
                     + ", ".join(sorted({c["kind"] for c in kb["conflicts"]})) + " — see the KB tab.")
    try:
        ident = dl_mod.identity_row(user_id) if user_id else None
    except Exception:
        ident = None
    if ident:
        notes.append(f"Complainant identity verified against a DigiLocker artefact issued by "
                     f"{ident['issuer']} (verified {ident['verified_at'][:10]}, valid to "
                     f"{ident['expires_on']}). The document itself is not attached to the case file.")
    else:
        notes.append("Complainant identity not verified through DigiLocker; the case proceeds "
                     "unverified and is marked accordingly for the registry.")
    return notes


def next_steps_for_level(level: str) -> list[str]:
    steps = {
        "L0": ["Report recorded automatically; queued for registry audit-log review."],
        "L1": ["Report recorded and queued for standard verification by an authorised registry officer."],
        "L2": ["Report escalated for mandatory enhanced manual review by a judicial officer.",
               "The advisory output must not be relied upon without that review."],
        "L3": ["Report escalated for mandatory determination by the presiding judge or bench.",
               "A second reviewer is required at this level."],
    }.get(level, ["Report recorded; awaiting registry verification."])
    return steps + ["This portal does not lodge an FIR. For cognizable offences the statutory route "
                    "remains the police (dial 112/100 or visit the nearest station); this record and its "
                    "reference ID can be presented there."]


def _enrich_triggers(triggers: list[dict]) -> list[dict]:
    levels = {t["id"]: t["level"] for t in ENGINE.rb.get("review", {}).get("triggers", [])}
    return [{**t, "level": t.get("level") or levels.get(t.get("id"), "")} for t in triggers]


def current_identity_status(user_id: str) -> str:
    """Read the identity state fresh from the DB (session dicts are snapshots)."""
    try:
        with db() as c:
            row = c.execute("SELECT digilocker_status FROM users WHERE id=?", (user_id,)).fetchone()
        return row["digilocker_status"] if row else "NOT_LINKED"
    except Exception:
        return "NOT_LINKED"


def _digilocker_summary(status_value: str, artefact_id: str | None = None) -> dict:
    """Honest identity signal attached to every report summary."""
    linked = status_value == "LINKED"
    return {
        "implemented": True,
        "mode": dl_mod.SIMULATION["mode"],
        "simulated": True,
        "linked": linked,
        "verified": linked,
        "status": status_value,
        "label": dl_mod.STATUS_LABELS.get(status_value, status_value),
        "artefact_id": artefact_id,
        "message": ("Identity artefact verified through the DigiLocker flow model "
                    "(simulated issuer response — not a government attestation)."
                    if linked else
                    "Identity not verified. The report is accepted and marked unverified."),
    }


def summary_from_output(ref: str, report_id: str, out: dict, res: dict, created_at: str,
                        intake_notes: list[str], evidence_rows: list[dict], no_evidence_ack: bool,
                        digilocker_status: str, rev_no: int = 1, extra: dict | None = None) -> dict:
    mr = out["manual_review"]
    s = {
        "report_id": report_id, "ref": ref, "created_at": created_at, "rev_no": rev_no,
        "level": mr["required_level"], "level_name": LEVEL_NAMES.get(mr["required_level"], ""),
        "escalate_to": mr["escalate_to"], "urgency": mr["urgency"],
        "urgency_reason": mr.get("urgency_reason", ""),
        "severity": out["severity"]["final_tier"], "severity_base": out["severity"]["base_tier"],
        "modifiers": out["severity"]["modifiers_applied"],
        "confidence": out["confidence"]["overall"],
        "second_reviewer_required": mr["second_reviewer_required"],
        "triggers_fired": _enrich_triggers(mr["triggers_fired"]),
        "open_questions": out["open_questions_for_judicial_officer"],
        "constitutional_flags": out["constitutional_flags"],
        "next_steps": next_steps_for_level(mr["required_level"]),
        "intake_notes": intake_notes,
        "evidence": [{"filename": e["filename"], "size": e["size"], "sha256": e["sha256"]} for e in evidence_rows],
        "no_evidence_ack": no_evidence_ack and not evidence_rows,
        "digilocker": _digilocker_summary(digilocker_status),
        "disclaimer": out["disclaimer"],
    }
    s.update(extra or {})
    return s


def process_evidence_items(report_id: str, evidence_in: list, created_at: str) -> list[dict]:
    """Decode, size-check, hash and store uploaded proof files; return register rows."""
    rows: list[dict] = []
    if not evidence_in:
        return rows
    folder = os.path.join(EVIDENCE_DIR, report_id)
    os.makedirs(folder, exist_ok=True)
    for i, item in enumerate(evidence_in):
        if not isinstance(item, dict):
            raise ValueError("Invalid evidence entry.")
        name = sanitize_filename(item.get("name"))
        data_b64 = str(item.get("data_b64", ""))
        if data_b64.startswith("data:"):
            data_b64 = data_b64.split(",", 1)[-1]
        try:
            blob = base64.b64decode(data_b64, validate=True)
        except Exception:
            raise ValueError(f"Evidence file '{name}' could not be decoded.")
        if not blob:
            raise ValueError(f"Evidence file '{name}' is empty.")
        if len(blob) > MAX_EVIDENCE_BYTES:
            raise ValueError(f"Evidence file '{name}' exceeds the {MAX_EVIDENCE_BYTES // (1024*1024)} MB limit.")
        digest = hashlib.sha256(blob).hexdigest()
        stored = os.path.join(folder, f"{i:02d}_{name}")
        with open(stored, "wb") as f:
            f.write(blob)
        rows.append({"filename": name, "content_type": str(item.get("type", ""))[:100], "size": len(blob),
                     "sha256": digest, "description": str(item.get("description", "")).strip()[:500],
                     "stored_path": os.path.relpath(stored, ROOT)})
    with LOCK, db() as c:
        for e in rows:
            cur = c.execute(
                "INSERT INTO evidence(report_id,filename,content_type,size,sha256,description,stored_path,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (report_id, e["filename"], e["content_type"], e["size"], e["sha256"], e["description"],
                 e["stored_path"], created_at))
            e["id"] = int(cur.lastrowid)
            legal_kb.record_provenance_conn(c, "EVIDENCE", e["sha256"][:16], "REGISTERED_IN", "REPORT",
                                            report_id, {"filename": e["filename"], "size": e["size"]})
    return rows


def intake_report(user: dict, body: dict) -> dict:
    v = validate_intake_body(body)
    answers, narrative = v["answers"], v["narrative"]
    if not body.get("declaration"):
        raise ValueError("Please accept the declaration before submitting.")
    evidence_in = body.get("evidence") or []
    if not isinstance(evidence_in, list):
        raise ValueError("Evidence must be a list.")
    if len(evidence_in) > MAX_EVIDENCE_FILES:
        raise ValueError(f"At most {MAX_EVIDENCE_FILES} evidence files can be attached.")
    no_evidence_ack = bool(body.get("no_evidence_ack"))
    if not evidence_in and not no_evidence_ack:
        raise ValueError("Please attach the proof you have (photos, documents, audio, screenshots), "
                         "or tick the confirmation that you have no evidence to attach at this time.")

    facts, runtime = build_engine_inputs(answers, v["start"], v["end"])
    kb = legal_kb.kb_context_for(answers["statute"], answers["provision"], v["start"].isoformat())
    apply_kb_context(facts, kb)
    keywords = scan_keywords(narrative)
    intake_notes = build_intake_notes(narrative, keywords, len(evidence_in), no_evidence_ack, kb,
                                      user_id=user["id"])

    report_id = uuid.uuid4().hex
    ref = "NYR-" + uuid.uuid4().hex[:10].upper()
    created_at = now()
    with ENGINE_LOCK:
        res = ENGINE.evaluate(facts=facts, runtime_variables=runtime,
                              retrieved_sources=kb.get("sources") or [], case_id=ref)
    out = res["output"]
    mr = out["manual_review"]
    evidence_rows = process_evidence_items(report_id, evidence_in, created_at)

    with LOCK, db() as c:
        c.execute(
            "INSERT INTO reports(id,ref,user_id,created_at,narrative,incident_date,incident_end_date,"
            "location,domain,answers,facts,derived_runtime,keywords,intake_notes,engine_output,validators,"
            "audit_id,review_level,urgency,severity_tier,confidence,digilocker_status,evidence_count,no_evidence_ack,"
            "current_rev_no,kb_context) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
            (report_id, ref, user["id"], created_at, narrative, v["start"].isoformat(),
             v["end"].isoformat() if v["end"] else None, v["location"], answers["domain"],
             json.dumps(answers, ensure_ascii=False), json.dumps(facts, ensure_ascii=False),
             json.dumps(runtime, ensure_ascii=False), json.dumps(keywords, ensure_ascii=False),
             json.dumps(intake_notes, ensure_ascii=False), json.dumps(out, ensure_ascii=False),
             json.dumps(res["validators"], ensure_ascii=False), res.get("audit_id"),
             mr["required_level"], mr["urgency"], out["severity"]["final_tier"],
             out["confidence"]["overall"], current_identity_status(user["id"]), len(evidence_rows),
             1 if no_evidence_ack else 0, json.dumps(kb, ensure_ascii=False)))
        c.execute(
            "INSERT INTO revisions(report_id,rev_no,created_at,actor,actor_name,reason,narrative,incident_date,"
            "incident_end_date,location,domain,answers,facts,derived_runtime,keywords,intake_notes,kb_context,"
            "engine_output,validators,audit_id,review_level,urgency,severity_tier,confidence) "
            "VALUES(?,1,?,'OWNER',?,'Original submission'," + ",".join(["?"] * 18) + ")",
            (report_id, created_at, user["name"], narrative, v["start"].isoformat(),
             v["end"].isoformat() if v["end"] else None, v["location"], answers["domain"],
             json.dumps(answers, ensure_ascii=False), json.dumps(facts, ensure_ascii=False),
             json.dumps(runtime, ensure_ascii=False), json.dumps(keywords, ensure_ascii=False),
             json.dumps(intake_notes, ensure_ascii=False), json.dumps(kb, ensure_ascii=False),
             json.dumps(out, ensure_ascii=False), json.dumps(res["validators"], ensure_ascii=False),
             res.get("audit_id"), mr["required_level"], mr["urgency"], out["severity"]["final_tier"],
             out["confidence"]["overall"]))

    with LOCK, db() as c:
        _prov = partial(legal_kb.record_provenance_conn, c)
        _prov("REPORT", ref, "EVALUATED_BY", "AUDIT_EVENT", str(res.get("audit_id")),
              {"rule_base_version": ENGINE.version, "rev": 1, "level": mr["required_level"]})
        if kb.get("resolution") and kb["resolution"].get("version"):
            _prov("REPORT", ref, "CITES", "STATUTE_VERSION",
                  str((kb.get("resolution") or {}).get("version")),
                  {"kind": kb["resolution"]["kind"],
                   "statute": answers["statute"], "provision": answers["provision"]})
        _prov("REVISION", f"{ref}#1", "CREATED_FROM", "INTAKE", ref, {"actor": "OWNER"})
        _prov("REPORT", ref, "HAS_REVISION", "REVISION", f"{ref}#1", {"rev": 1})

    return {"ok": True, "summary": summary_from_output(
        ref, report_id, out, res, created_at, intake_notes, evidence_rows, no_evidence_ack,
        current_identity_status(user["id"]), rev_no=1,
        extra={"kb_resolution": (kb.get("resolution") or {}).get("kind"),
               "disclosure_status": "PRIVATE", "manual_check_status": "UNCHECKED",
               "feedback": {"up": 0, "down": 0, "my_vote": 0, "flagged": False}})}


# ---------------------------------------------------------------- revisions / manual check

def revise_report(user: dict, report_id: str, body: dict, actor: str | None = None,
                  facts_override: dict | None = None) -> dict:
    """Re-evaluation with corrected inputs. Owner corrects their own mistake;
    ADMIN can correct any case; SYSTEM is used by amendment-impact application.
    Every revision is an immutable snapshot; nothing is overwritten silently."""
    with db() as c:
        row = c.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    if not row:
        raise NotFound("Case not found.")
    is_admin = user.get("role") == "ADMIN"
    if not (is_admin or row["user_id"] == user["id"]):
        raise AccessDenied("Only the owner or an administrator can revise this case.")
    reason = str(body.get("reason", "")).strip()
    if actor != "SYSTEM" and len(reason) < 5:
        raise ValueError("Please give a reason for the correction (at least 5 characters).")

    v = validate_intake_body(body)
    answers, narrative = v["answers"], v["narrative"]
    facts, runtime = build_engine_inputs(answers, v["start"], v["end"])
    kb = legal_kb.kb_context_for(answers["statute"], answers["provision"], v["start"].isoformat())
    if facts_override:
        facts = json.loads(json.dumps(facts_override))
    else:
        apply_kb_context(facts, kb)
    keywords = scan_keywords(narrative)
    evidence_count = row["evidence_count"]
    no_evidence_ack = bool(row["no_evidence_ack"])
    intake_notes = build_intake_notes(narrative, keywords, evidence_count, no_evidence_ack, kb,
                                      user_id=row["user_id"])
    intake_notes.append(f"Revision by {actor or ('ADMIN' if is_admin else 'OWNER')}: {reason}")

    with ENGINE_LOCK:
        res = ENGINE.evaluate(facts=facts, runtime_variables=runtime,
                              retrieved_sources=kb.get("sources") or [], case_id=row["ref"])
    out = res["output"]
    mr = out["manual_review"]
    created_at = now()
    rev_no = int(row["current_rev_no"]) + 1
    actor = actor or ("ADMIN" if is_admin else "OWNER")
    with LOCK, db() as c:
        c.execute(
            "INSERT INTO revisions(report_id,rev_no,created_at,actor,actor_name,reason,narrative,incident_date,"
            "incident_end_date,location,domain,answers,facts,derived_runtime,keywords,intake_notes,kb_context,"
            "engine_output,validators,audit_id,review_level,urgency,severity_tier,confidence) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (report_id, rev_no, created_at, actor, user.get("name", "system"), reason, narrative,
             v["start"].isoformat(), v["end"].isoformat() if v["end"] else None, v["location"],
             answers["domain"], json.dumps(answers, ensure_ascii=False), json.dumps(facts, ensure_ascii=False),
             json.dumps(runtime, ensure_ascii=False), json.dumps(keywords, ensure_ascii=False),
             json.dumps(intake_notes, ensure_ascii=False), json.dumps(kb, ensure_ascii=False),
             json.dumps(out, ensure_ascii=False), json.dumps(res["validators"], ensure_ascii=False),
             res.get("audit_id"), mr["required_level"], mr["urgency"], out["severity"]["final_tier"],
             out["confidence"]["overall"]))
        c.execute(
            "UPDATE reports SET narrative=?, incident_date=?, incident_end_date=?, location=?, domain=?, "
            "answers=?, facts=?, derived_runtime=?, keywords=?, intake_notes=?, kb_context=?, engine_output=?, "
            "validators=?, audit_id=?, review_level=?, urgency=?, severity_tier=?, confidence=?, current_rev_no=? "
            "WHERE id=?",
            (narrative, v["start"].isoformat(), v["end"].isoformat() if v["end"] else None, v["location"],
             answers["domain"], json.dumps(answers, ensure_ascii=False), json.dumps(facts, ensure_ascii=False),
             json.dumps(runtime, ensure_ascii=False), json.dumps(keywords, ensure_ascii=False),
             json.dumps(intake_notes, ensure_ascii=False), json.dumps(kb, ensure_ascii=False),
             json.dumps(out, ensure_ascii=False), json.dumps(res["validators"], ensure_ascii=False),
             res.get("audit_id"), mr["required_level"], mr["urgency"], out["severity"]["final_tier"],
             out["confidence"]["overall"], rev_no, report_id))
        # A revision resets the human sign-off: corrected facts must be re-checked.
        c.execute("UPDATE reports SET manual_check_status='UNCHECKED', manual_check_note='', "
                  "manual_check_by='', manual_check_at=NULL WHERE id=? AND manual_check_status='VERIFIED'",
                  (report_id,))
    mc = body.get("manual_check") if is_admin else None
    if isinstance(mc, dict) and mc.get("status"):
        apply_manual_check(user, report_id, str(mc.get("status")), str(mc.get("note", "")))

    with LOCK, db() as c:
        _prov = partial(legal_kb.record_provenance_conn, c)
        _prov("REVISION", f"{row['ref']}#{rev_no}", "SUPERSEDES",
              "REVISION", f"{row['ref']}#{rev_no-1}", {"actor": actor, "reason": reason[:300]})
        _prov("REPORT", row["ref"], "EVALUATED_BY", "AUDIT_EVENT", str(res.get("audit_id")),
              {"rule_base_version": ENGINE.version, "rev": rev_no, "level": mr["required_level"]})
        _prov("REPORT", row["ref"], "HAS_REVISION", "REVISION", f"{row['ref']}#{rev_no}", {"rev": rev_no})
    with db() as c:
        ev = [dict(r) for r in c.execute(
            "SELECT id,filename,content_type,size,sha256,description,created_at FROM evidence WHERE report_id=? ORDER BY id",
            (report_id,)).fetchall()]
    return {"ok": True, "rev_no": rev_no, "summary": summary_from_output(
        row["ref"], report_id, out, res, created_at, intake_notes, ev, no_evidence_ack,
        current_identity_status(row["user_id"]), rev_no=rev_no,
        extra={"reason": reason, "actor": actor, "kb_resolution": (kb.get("resolution") or {}).get("kind")})}


def apply_manual_check(user: dict, report_id: str, status: str, note: str = "") -> None:
    if user.get("role") != "ADMIN":
        raise AccessDenied("Manual checks are restricted to administrators.")
    status = status.upper()
    if status not in MANUAL_CHECK_STATUSES:
        raise ValueError("Invalid manual-check status.")
    if len(note) > 3000:
        raise ValueError("Manual-check note is too long (max 3000 characters).")
    with LOCK, db() as c:
        row = c.execute("SELECT ref FROM reports WHERE id=?", (report_id,)).fetchone()
        if not row:
            raise NotFound("Case not found.")
        c.execute("UPDATE reports SET manual_check_status=?, manual_check_note=?, manual_check_by=?, manual_check_at=? WHERE id=?",
                  (status, note.strip(), user["name"], now(), report_id))
        legal_kb.record_provenance_conn(c, "REPORT", row["ref"], "MANUAL_CHECK", "OFFICER", user["name"],
                                        {"status": status, "note": note[:300]})


# ---------------------------------------------------------------- disclosure

def request_disclosure(user: dict, report_id: str, note: str = "") -> dict:
    with db() as c:
        row = c.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    if not row:
        raise NotFound("Case not found.")
    if row["user_id"] != user["id"] and user.get("role") != "ADMIN":
        raise AccessDenied("Only the owner can request disclosure of this case.")
    if row["disclosure_status"] not in ("PRIVATE", "REJECTED"):
        raise ValueError(f"Disclosure cannot be requested while status is {row['disclosure_status']}.")
    with LOCK, db() as c:
        c.execute("UPDATE reports SET disclosure_status='PENDING', disclosure_request_note=? WHERE id=?",
                  (str(note)[:1000], report_id))
        legal_kb.record_provenance_conn(c, "REPORT", row["ref"], "DISCLOSURE_REQUESTED", "OWNER", user["name"])
    return {"ok": True, "disclosure_status": "PENDING"}


def admin_disclosure(user: dict, report_id: str, action: str, mode: str = "ANONYMIZED", note: str = "") -> dict:
    """Manual approval gate: no case becomes visible to others without an admin
    explicitly approving (or directly making) the disclosure."""
    if user.get("role") != "ADMIN":
        raise AccessDenied("Disclosure decisions are restricted to administrators.")
    action = str(action).upper()
    mode = str(mode).upper()
    if action not in ("APPROVE", "REJECT", "DISCLOSE", "REVOKE"):
        raise ValueError("Action must be APPROVE, REJECT, DISCLOSE or REVOKE.")
    if mode not in ("ANONYMIZED", "FULL"):
        raise ValueError("Disclosure mode must be ANONYMIZED or FULL.")
    with db() as c:
        row = c.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    if not row:
        raise NotFound("Case not found.")
    if action == "APPROVE" and row["disclosure_status"] != "PENDING":
        raise ValueError("Only PENDING requests can be approved (use DISCLOSE to publish directly).")
    new_status = {"APPROVE": "DISCLOSED", "DISCLOSE": "DISCLOSED", "REJECT": "REJECTED", "REVOKE": "PRIVATE"}[action]
    with LOCK, db() as c:
        c.execute("UPDATE reports SET disclosure_status=?, disclosure_mode=?, disclosed_at=?, disclosure_note=? WHERE id=?",
                  (new_status, mode if new_status == "DISCLOSED" else row["disclosure_mode"],
                   now() if new_status == "DISCLOSED" else row["disclosed_at"], str(note)[:1000], report_id))
        legal_kb.record_provenance_conn(c, "REPORT", row["ref"], "DISCLOSURE_" + action, "ADMIN", user["name"],
                                        {"mode": mode, "note": note[:300]})
    return {"ok": True, "disclosure_status": new_status, "disclosure_mode": mode}


# ---------------------------------------------------------------- access control & redaction

def case_access(user: dict, row) -> str | None:
    """FULL for owner/admin; FULL/ANONYMIZED for others only after manual
    disclosure approval; None (→ 404) otherwise."""
    if user.get("role") == "ADMIN" or row["user_id"] == user["id"]:
        return "FULL"
    if row["disclosure_status"] == "DISCLOSED":
        return "FULL" if row["disclosure_mode"] == "FULL" else "ANONYMIZED"
    return None


def evidence_download(user: dict, evidence_id: int) -> tuple[str, str, bytes]:
    """Return (filename, content_type, bytes) for one evidence file.

    Bytes are served ONLY to the case owner and admins — never to disclosed
    viewers (even FULL mode shows metadata, not file bytes). The stored path
    must resolve inside EVIDENCE_DIR and the SHA-256 must match the register;
    a tampered or moved file is refused rather than served.
    """
    with db() as c:
        ev = c.execute("SELECT * FROM evidence WHERE id=?", (evidence_id,)).fetchone()
        if not ev:
            raise NotFound("Evidence not found.")
        report = c.execute("SELECT * FROM reports WHERE id=?", (ev["report_id"],)).fetchone()
    if not report:
        raise NotFound("Evidence not found.")
    if not (user.get("role") == "ADMIN" or report["user_id"] == user["id"]):
        raise NotFound("Evidence not found.")
    base = os.path.abspath(EVIDENCE_DIR)
    full = os.path.abspath(os.path.join(ROOT, ev["stored_path"]))
    if full != base and not full.startswith(base + os.sep):
        raise NotFound("Evidence not found.")
    try:
        with open(full, "rb") as fh:
            blob = fh.read()
    except OSError:
        raise NotFound("Evidence not found.")
    if hashlib.sha256(blob).hexdigest() != ev["sha256"]:
        raise ValueError("Evidence file failed its integrity check and was not served.")
    ctype = (ev["content_type"] or "application/octet-stream").split(";")[0].strip()
    if "/" not in ctype or len(ctype) > 100:
        ctype = "application/octet-stream"
    return ev["filename"], ctype, blob


def build_case_payload(user: dict, report_id: str) -> dict:
    with db() as c:
        row = c.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
        if not row:
            raise NotFound("Case not found.")
        access = case_access(user, row)
        if access is None:
            # Do not even confirm existence of someone else's private case.
            raise NotFound("Case not found.")
        ev = [dict(r) for r in c.execute(
            "SELECT id,filename,content_type,size,sha256,description,created_at FROM evidence WHERE report_id=? ORDER BY id",
            (report_id,)).fetchall()]
        revs = [dict(r) for r in c.execute(
            "SELECT rev_no,created_at,actor,actor_name,reason,review_level,urgency,severity_tier,confidence,audit_id "
            "FROM revisions WHERE report_id=? ORDER BY rev_no", (report_id,)).fetchall()]
        emap = [dict(r) for r in c.execute(
            "SELECT * FROM evidence_fact_map WHERE report_id=? ORDER BY id", (report_id,)).fetchall()]
        fb = c.execute("SELECT vote, comment FROM feedback WHERE report_id=? AND user_id=?",
                       (report_id, user["id"])).fetchone()
        comments = [dict(r) for r in c.execute(
            "SELECT comment, vote, created_at FROM feedback WHERE report_id=? AND comment!='' ORDER BY id DESC LIMIT 20",
            (report_id,)).fetchall()]

    d = dict(row)
    for key in ("answers", "facts", "derived_runtime", "keywords", "intake_notes", "engine_output", "validators", "kb_context"):
        d[key] = json.loads(d[key] or ("{}" if key in ("answers", "facts", "derived_runtime", "keywords", "kb_context") else "[]"))
    d["engine_output"].setdefault("manual_review", {})
    d["engine_output"]["manual_review"]["triggers_fired"] = _enrich_triggers(d["engine_output"]["manual_review"].get("triggers_fired", []))
    d["level_name"] = LEVEL_NAMES.get(d["review_level"], "")
    d["access"] = access
    d["viewer"] = {"role": user.get("role", "USER"), "is_owner": row["user_id"] == user["id"], "name": user["name"]}
    d["evidence"] = ev
    d["revisions"] = revs
    d["evidence_map"] = emap
    d["coverage"] = evidence_coverage(d["answers"], emap)
    d["provenance"] = legal_kb.provenance_chain("REPORT", d["ref"], depth=2)
    d["feedback"] = {"up": d["feedback_up"], "down": d["feedback_down"], "flagged": bool(d["feedback_flagged"]),
                     "my_vote": fb["vote"] if fb else 0}
    d.pop("user_id", None)  # never expose the owner's id to other viewers

    if access == "ANONYMIZED":
        # Redact everything personally identifying or narrative-level; keep the
        # role-based engine response (it contains no identifiers by design, OV-02).
        d["narrative"] = "[Redacted — this case was disclosed in ANONYMIZED mode]"
        d["location"] = ""
        d["answers"] = {}
        d["facts"] = {}
        d["derived_runtime"] = {}
        d["keywords"] = {}
        d["intake_notes"] = []
        d["kb_context"] = {"resolution": d.get("kb_context", {}).get("resolution"), "precedents": d.get("kb_context", {}).get("precedents", []), "conflicts": d.get("kb_context", {}).get("conflicts", [])}
        for e in d["evidence"]:
            e["filename"] = "[hidden]"
            e["description"] = ""
        for r in d["revisions"]:
            r["reason"] = "[redacted]"
            r["actor_name"] = r["actor"]
        d["manual_check_note"] = ""
        d["manual_check_by"] = ""
        d["disclosure_note"] = ""
        d["disclosure_request_note"] = ""
        d["feedback"] = {k: v for k, v in d["feedback"].items() if k != "comments"}
        d["comments"] = []
    else:
        d["comments"] = comments if (d["viewer"]["is_owner"] or user.get("role") == "ADMIN") else [
            {**c, "comment": c["comment"]} for c in comments]
    return d


def evidence_coverage(answers: dict, maps: list[dict]) -> dict:
    """Phase 3: evidence-to-fact mapping coverage over the structured answers."""
    keys = [k for k in ENUMS if answers.get(k) not in (None, "")] + \
           [k for k in CHECKBOXES if answers.get(k)] + ["incident_date"]
    supported = {m["fact_key"] for m in maps if m["relation"] == "SUPPORTS"}
    contradicted = {m["fact_key"] for m in maps if m["relation"] == "CONTRADICTS"}
    covered = [k for k in keys if k in supported]
    return {"mappable_facts": keys, "supported": sorted(set(covered)),
            "contradicted": sorted(k for k in keys if k in contradicted),
            "coverage": round(len(covered) / len(keys), 2) if keys else 0.0}


def map_evidence_to_fact(user: dict, report_id: str, evidence_id: int, fact_key: str, relation: str, note: str = "") -> dict:
    with db() as c:
        row = c.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
        if not row:
            raise NotFound("Case not found.")
        if not (user.get("role") == "ADMIN" or row["user_id"] == user["id"]):
            raise AccessDenied("Only the owner or an administrator can map evidence on this case.")
        ev = c.execute("SELECT id, sha256 FROM evidence WHERE id=? AND report_id=?", (evidence_id, report_id)).fetchone()
        if not ev:
            raise NotFound("Evidence file not found on this case.")
    if fact_key not in MAPPABLE_FACTS:
        raise ValueError(f"fact_key must be one of: {', '.join(MAPPABLE_FACTS)}")
    relation = str(relation).upper()
    if relation not in ("SUPPORTS", "CONTRADICTS", "CONTEXT"):
        raise ValueError("relation must be SUPPORTS, CONTRADICTS or CONTEXT.")
    with LOCK, db() as c:
        c.execute(
            "INSERT INTO evidence_fact_map(report_id,evidence_id,fact_key,relation,note,mapped_by,mapped_role,created_at) "
            "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(evidence_id,fact_key) DO UPDATE SET "
            "relation=excluded.relation, note=excluded.note, mapped_by=excluded.mapped_by, "
            "mapped_role=excluded.mapped_role, created_at=excluded.created_at",
            (report_id, evidence_id, fact_key, relation, str(note)[:500], user["name"],
             user.get("role", "USER"), now()))
    with LOCK, db() as c:
        legal_kb.record_provenance_conn(c, "EVIDENCE", ev["sha256"][:16], relation, "FACT", fact_key,
                                        {"report": row["ref"], "by": user["name"]})
    with db() as c:
        maps = [dict(r) for r in c.execute("SELECT * FROM evidence_fact_map WHERE report_id=?", (report_id,)).fetchall()]
        answers = json.loads(row["answers"])
    return {"ok": True, "map": maps, "coverage": evidence_coverage(answers, maps)}


# ---------------------------------------------------------------- feedback

def add_feedback(user: dict, report_id: str, vote: int, comment: str = "") -> dict:
    if int(vote) not in (1, -1):
        raise ValueError("vote must be 1 (up) or -1 (down).")
    with db() as c:
        row = c.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
        if not row:
            raise NotFound("Case not found.")
        access = case_access(user, row)
    if access is None:
        raise NotFound("Case not found.")
    vote = int(vote)
    comment = str(comment)[:1000]
    with LOCK, db() as c:
        existing = c.execute("SELECT id FROM feedback WHERE report_id=? AND user_id=?", (report_id, user["id"])).fetchone()
        if existing:
            c.execute("UPDATE feedback SET vote=?, comment=?, rev_no=?, updated_at=? WHERE id=?",
                      (vote, comment, row["current_rev_no"], now(), existing["id"]))
        else:
            c.execute("INSERT INTO feedback(report_id,user_id,rev_no,vote,comment,created_at,updated_at) "
                      "VALUES(?,?,?,?,?,?,?)",
                      (report_id, user["id"], row["current_rev_no"], vote, comment, now(), now()))
            legal_kb.record_provenance_conn(c, "FEEDBACK", f"{row['ref']}:{user['name']}", "ABOUT", "REPORT",
                                            row["ref"], {"vote": vote})
        up = c.execute("SELECT COUNT(*) n FROM feedback WHERE report_id=? AND vote=1", (report_id,)).fetchone()["n"]
        down = c.execute("SELECT COUNT(*) n FROM feedback WHERE report_id=? AND vote=-1", (report_id,)).fetchone()["n"]
        flagged = 1 if (down - up) >= FEEDBACK_FLAG_THRESHOLD else 0
        c.execute("UPDATE reports SET feedback_up=?, feedback_down=?, feedback_flagged=? WHERE id=?",
                  (up, down, flagged, report_id))
    return {"ok": True, "up": up, "down": down, "my_vote": vote, "flagged": bool(flagged)}


def feedback_analytics() -> dict:
    with db() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT f.*, r.ref, r.domain, r.review_level, r.severity_tier, r.engine_output "
            "FROM feedback f JOIN reports r ON r.id=f.report_id ORDER BY f.updated_at DESC LIMIT 1000").fetchall()]
    by_level: dict = {}
    by_domain: dict = {}
    by_trigger: dict = {}
    for f in rows:
        by_level.setdefault(f["review_level"], {"up": 0, "down": 0})
        by_domain.setdefault(f["domain"], {"up": 0, "down": 0})
        by_level[f["review_level"]]["up" if f["vote"] == 1 else "down"] += 1
        by_domain[f["domain"]]["up" if f["vote"] == 1 else "down"] += 1
        try:
            out = json.loads(f["engine_output"])
            for t in out.get("manual_review", {}).get("triggers_fired", []):
                by_trigger.setdefault(t["id"], {"up": 0, "down": 0})
                by_trigger[t["id"]]["up" if f["vote"] == 1 else "down"] += 1
        except Exception:
            pass
    return {"total": len(rows), "up": sum(1 for f in rows if f["vote"] == 1),
            "down": sum(1 for f in rows if f["vote"] == -1),
            "by_level": by_level, "by_domain": by_domain, "by_trigger": by_trigger}


def feedback_dataset(limit: int = 5000) -> str:
    """Labeled JSONL export — the audit record. Features = intake answers +
    keywords + computed routing; label = the user's verdict feedback."""
    with db() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT f.vote, f.comment, f.rev_no, f.created_at, r.ref, r.domain, r.answers, r.keywords, "
            "r.review_level, r.urgency, r.severity_tier, r.confidence, r.engine_output "
            "FROM feedback f JOIN reports r ON r.id=f.report_id ORDER BY f.created_at DESC LIMIT ?",
            (limit,)).fetchall()]
    lines = []
    for r in rows:
        try:
            out = json.loads(r["engine_output"])
            triggers = [t["id"] for t in out.get("manual_review", {}).get("triggers_fired", [])]
        except Exception:
            triggers = []
        lines.append(json.dumps({
            "ref": r["ref"], "rev_no": r["rev_no"], "label": r["vote"], "comment": r["comment"],
            "voted_at": r["created_at"],
            "features": {"domain": r["domain"], "answers": json.loads(r["answers"]),
                         "keyword_categories": list(json.loads(r["keywords"]).keys()),
                         "review_level": r["review_level"], "urgency": r["urgency"],
                         "severity_tier": r["severity_tier"], "confidence": r["confidence"],
                         "triggers_fired": triggers},
        }, ensure_ascii=False))
    return "\n".join(lines) + ("\n" if lines else "")


# ---------------------------------------------------------------- amendment impact (Phase 2)

def amendment_impact(user: dict, statute: str, provision: str, apply_report_id: str | None = None) -> dict:
    """Re-resolve every case citing this provision against the CURRENT statutory
    database (dry run, no audit rows) and report which evaluations would change."""
    if user.get("role") != "ADMIN":
        raise AccessDenied("Amendment impact analysis is restricted to administrators.")
    with db() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM reports ORDER BY created_at DESC LIMIT 1000").fetchall()]
    ns, np_ = legal_kb.norm_statute(statute), legal_kb.norm_provision(provision)
    impacts = []
    for r in rows:
        answers = json.loads(r["answers"])
        if legal_kb.norm_provision(answers.get("provision")) != np_:
            continue
        if ns and legal_kb.norm_statute(answers.get("statute")) != ns:
            continue
        kb = legal_kb.kb_context_for(answers.get("statute", ""), answers.get("provision", ""), r["incident_date"])
        start = dt.date.fromisoformat(r["incident_date"])
        end = dt.date.fromisoformat(r["incident_end_date"]) if r["incident_end_date"] else None
        facts, runtime = build_engine_inputs(answers, start, end)
        apply_kb_context(facts, kb)
        with ENGINE_LOCK:
            res = ENGINE.evaluate(facts=facts, runtime_variables=runtime,
                                  retrieved_sources=kb.get("sources") or [],
                                  case_id="IMPACT-" + r["ref"], record_audit=False)
        out = res["output"]
        changed = (out["manual_review"]["required_level"] != r["review_level"]
                   or out["severity"]["final_tier"] != r["severity_tier"])
        impacts.append({
            "report_id": r["id"], "ref": r["ref"], "incident_date": r["incident_date"],
            "changed": changed,
            "current": {"level": r["review_level"], "severity": r["severity_tier"],
                        "kb_resolution": (json.loads(r["kb_context"] or "{}").get("resolution") or {}).get("kind")},
            "reevaluated": {"level": out["manual_review"]["required_level"],
                            "severity": out["severity"]["final_tier"],
                            "kb_resolution": (kb.get("resolution") or {}).get("kind"),
                            "confidence": out["confidence"]["overall"]},
        })
    result = {"ok": True, "statute": statute, "provision": provision, "cases_examined": len(impacts),
              "impacts": impacts, "changed": sum(1 for i in impacts if i["changed"])}
    if apply_report_id:
        target = next((i for i in impacts if i["report_id"] == apply_report_id), None)
        if not target:
            raise NotFound("That case does not cite this provision.")
        row = next(r for r in rows if r["id"] == apply_report_id)
        answers = json.loads(row["answers"])
        body = {"reason": f"Amendment impact re-evaluation: {statute} {provision} resolved against current statutory database.",
                "narrative": row["narrative"], "incident_date": row["incident_date"],
                "incident_end_date": row["incident_end_date"] or "", "location": row["location"] or "",
                "domain": row["domain"], **{k: answers.get(k, "") for k in ENUMS},
                **{k: answers.get(k, False) for k in CHECKBOXES},
                "provision": answers.get("provision", ""), "statute": answers.get("statute", "")}
        rev = revise_report(user, apply_report_id, body, actor="SYSTEM")
        result["applied"] = {"report_id": apply_report_id, "rev_no": rev["rev_no"], "summary": rev["summary"]}
    return result


# ---------------------------------------------------------------- admin overview

def admin_overview(user: dict) -> dict:
    if user.get("role") != "ADMIN":
        raise AccessDenied("Admin console is restricted to administrators.")
    with db() as c:
        q = lambda sql, *a: c.execute(sql, a).fetchone()[0]  # noqa: E731
        stats = {
            "users": q("SELECT COUNT(*) FROM users"),
            "admins": q("SELECT COUNT(*) FROM users WHERE role='ADMIN'"),
            "reports": q("SELECT COUNT(*) FROM reports"),
            "revisions": q("SELECT COUNT(*) FROM revisions"),
            "evidence_files": q("SELECT COUNT(*) FROM evidence"),
            "feedback_up": q("SELECT COUNT(*) FROM feedback WHERE vote=1"),
            "feedback_down": q("SELECT COUNT(*) FROM feedback WHERE vote=-1"),
            "flagged": q("SELECT COUNT(*) FROM reports WHERE feedback_flagged=1"),
            "disclosed": q("SELECT COUNT(*) FROM reports WHERE disclosure_status='DISCLOSED'"),
            "statute_versions": q("SELECT COUNT(*) FROM statutes"),
            "statutes_verified": q("SELECT COUNT(*) FROM statutes WHERE verified=1"),
            "precedents": q("SELECT COUNT(*) FROM precedents"),
            "identities_verified": q("SELECT COUNT(*) FROM dl_identities WHERE revoked_at IS NULL"),
            "identities_revoked": q("SELECT COUNT(*) FROM dl_identities WHERE revoked_at IS NOT NULL"),
            "identity_failures": q("SELECT COUNT(*) FROM dl_requests WHERE status IN ('FAILED','DENIED','EXPIRED')"),
            "reports_unverified_identity": q(
                "SELECT COUNT(*) FROM reports WHERE digilocker_status!='LINKED'"),
        }
        by_level = {r["review_level"]: r["n"] for r in c.execute(
            "SELECT review_level, COUNT(*) n FROM reports GROUP BY review_level")}
        pending = [dict(r) for r in c.execute(
            "SELECT id,ref,created_at,domain,review_level,disclosure_request_note FROM reports "
            "WHERE disclosure_status='PENDING' ORDER BY created_at")][:100]
        unchecked = [dict(r) for r in c.execute(
            "SELECT id,ref,created_at,domain,review_level,urgency,manual_check_status,feedback_flagged,"\
            "digilocker_status "
            "FROM reports WHERE manual_check_status IN ('UNCHECKED','NEEDS_CORRECTION') "
            "ORDER BY feedback_flagged DESC, created_at DESC")][:200]
        flagged = [dict(r) for r in c.execute(
            "SELECT id,ref,review_level,feedback_up,feedback_down FROM reports WHERE feedback_flagged=1")][:100]
        recent = [dict(r) for r in c.execute(
            "SELECT r.id,r.ref,r.created_at,r.domain,r.review_level,r.urgency,r.severity_tier,r.disclosure_status,"
            "r.manual_check_status,r.current_rev_no,r.feedback_up,r.feedback_down,r.feedback_flagged,"\
            "r.digilocker_status,u.email "
            "FROM reports r JOIN users u ON u.id=r.user_id ORDER BY r.created_at DESC LIMIT 200")]
    return {"ok": True, "stats": stats, "by_level": by_level,
            "queues": {"disclosure_pending": pending, "manual_check": unchecked, "flagged": flagged},
            "cases": recent, "feedback": feedback_analytics(),
            "identity": dl_mod.stats(),
            "conflicts": legal_kb.detect_conflicts()}


def disclosed_list(user: dict) -> dict:
    with db() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT id,ref,created_at,incident_date,domain,review_level,urgency,severity_tier,disclosure_mode,"
            "feedback_up,feedback_down,narrative FROM reports WHERE disclosure_status='DISCLOSED' "
            "ORDER BY disclosed_at DESC LIMIT 200")]
    privileged = user.get("role") == "ADMIN"
    cases = []
    for r in rows:
        item = {k: r[k] for k in ("id", "ref", "created_at", "incident_date", "domain", "review_level",
                                  "urgency", "severity_tier", "disclosure_mode", "feedback_up", "feedback_down")}
        if r["disclosure_mode"] == "FULL" or privileged:
            n = r["narrative"] or ""
            item["excerpt"] = (n[:140] + "…") if len(n) > 140 else n
        cases.append(item)
    return {"cases": cases, "count": len(cases)}


# ---------------------------------------------------------------- engine analysis
# The portal is one application on top of nyayacode. These two read-only
# endpoints expose the library's output so the analysis can be looked at in a
# browser; nothing here decides anything, it only renders what the CLI renders.

def _engine_lib():
    import nyayacode
    from nyayacode import analyze as nc_analyze
    return nyayacode, nc_analyze


def engine_overview() -> dict:
    nypack, nc_analyze = None, None
    try:
        nyayacode, nc_analyze = _engine_lib()
    except ImportError as exc:
        return {"ok": False, "error": f"nyayacode library not available: {exc}"}
    from nyayacode import pack as nypack
    packs, analyses = [], []
    for pid in nypack.available():
        p = nypack.load(pid)
        packs.append({
            "id": p.id, "title": p.title, "facts": len(p.facts),
            "domain": nc_analyze._domain_size(p),
            "reviewed": p.review.get("status") == "reviewed",
            "review": p.review_context(),
        })
        r = nc_analyze.full_report(p)
        analyses.append({
            "pack": r["pack"], "review": r["review"], "digest": r["digest"],
            "domain_size": r["domain_size"],
            "gaps": {"count": r["gaps"]["count"], "checked": r["gaps"]["checked"]},
            "overlaps": {"count": r["overlaps"]["count"],
                         "designed_overrides": r["overlaps"]["designed_overrides"]},
            "unreachable": {"count": r["unreachable"]["count"]},
            "ambiguities": {"ambiguities": r["ambiguities"]["ambiguities"]},
        })
    ams = []
    for aid in nypack.amendments():
        a = nypack.load_amendment(aid)
        ams.append({"id": a.id, "title": a.title, "kind": a.kind,
                    "enacted": a.enacted, "commencement": a.commencement})
    return {"ok": True, "packs": packs, "analyses": analyses, "amendments": ams}


def engine_impact(amendment_id: str) -> dict:
    try:
        nyayacode, nc_analyze = _engine_lib()
    except ImportError as exc:
        return {"ok": False, "error": f"nyayacode library not available: {exc}"}
    from nyayacode import pack as nypack, cli as nc_cli
    try:
        am = nypack.load_amendment(amendment_id)
    except nypack.PackError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, **nc_cli.build_impact(am)}


# ---------------------------------------------------------------- rate limiting
# A local tool still faces a laptop that is left running. Login and register are
# the two endpoints where a guess costs an attacker nothing, so both are limited
# per (address, account) with an exponential backoff after repeated failures.
_RATE: dict[str, list[float]] = {}
_RATE_LOCK = __import__("threading").Lock()
RATE_WINDOW = 900          # seconds the failure history is remembered
RATE_LOCKOUT = 900         # how long a tripped key stays locked
# Per account is tight; per address is loose on purpose. Keying only on the
# address would let anyone lock every user out of a shared network with five
# bad guesses, which is a denial of service, not a defence.
RATE_MAX_ACCOUNT = 5
RATE_MAX_ADDRESS = 30
RATE_MAX_REGISTER = 10  # registrations per address per window (spam guard)


def _rate_key(kind: str, who: str) -> str:
    return f"{kind}:{who.lower()}"


def rate_check(kind: str, who: str, limit: int = RATE_MAX_ACCOUNT) -> int:
    """Return 0 if allowed, else seconds the caller must wait."""
    key = _rate_key(kind, who)
    now_ts = time.time()
    with _RATE_LOCK:
        hits = [t for t in _RATE.get(key, []) if now_ts - t < RATE_WINDOW]
        _RATE[key] = hits
        if len(hits) >= limit:
            wait = int(RATE_LOCKOUT - (now_ts - hits[-limit]))
            return max(wait, 1)
    return 0


def rate_fail(kind: str, who: str) -> None:
    with _RATE_LOCK:
        _RATE.setdefault(_rate_key(kind, who), []).append(time.time())


def rate_reset(kind: str, who: str) -> None:
    with _RATE_LOCK:
        _RATE.pop(_rate_key(kind, who), None)


# ---------------------------------------------------------------- HTTP handler

APP_VERSION = "0.5.0"

# Content-Security-Policy: the portal inlines all CSS/JS (no external resources
# are loaded — verified: no http(s) src/href in pages/ or assets/), so a tight
# policy is possible. 'unsafe-inline' is required for the inlined assets.
# frame-ancestors is deliberately permissive: the portal is designed to run
# inside cross-origin preview iframes (see assets/auth.js), so a framing ban
# would break its primary deployment. All other exfiltration vectors (external
# scripts, styles, images, connections, form targets) stay blocked.
CSP = ("default-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
       "connect-src 'self'; font-src 'self' data:; frame-ancestors *; "
       "base-uri 'self'; form-action 'self'")

ROBOTS_TXT = "User-agent: *\nDisallow: /\n# Holds personal data; do not index.\n"

FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<rect width="32" height="32" rx="6" fill="#0f2b46"/>'
    '<path d="M16 6v20M8 12h16M8 12l-3 6a4 4 0 0 0 6 0L8 12zm16 0l-3 6a4 4 0 0 0 6 0L24 12z" '
    'stroke="#fff" stroke-width="1.8" fill="none" stroke-linecap="round" '
    'stroke-linejoin="round"/></svg>'
)


class Handler(BaseHTTPRequestHandler):
    server_version = f"NYAYA-RAC/{APP_VERSION}"
    timeout = 30  # seconds; a slow client must not hold a thread forever

    def _send_bytes(self, status: int, body: bytes, ctype: str, extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # The session relay token can appear in a URL (?st=). Never leak it to a
        # third party through the Referer header, and keep pages out of frames'
        # cross-origin parents from sniffing the document referrer.
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        for k, v in (extra_headers or []):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, obj, extra_headers=None):
        self._send_bytes(status, json.dumps(obj, ensure_ascii=False).encode(),
                         "application/json; charset=utf-8", extra_headers)

    def _text(self, status: int, text: str, ctype="text/plain; charset=utf-8"):
        self._send_bytes(status, text.encode(), ctype)

    # Shared assets are static: read once, reuse for every page view.
    # Restart the server to pick up edits to style.css / auth.js / icons.svg.
    _asset_cache: dict | None = None

    @classmethod
    def _assets(cls) -> dict:
        if cls._asset_cache is None:
            with open(os.path.join(ASSETS, "style.css"), encoding="utf-8") as f:
                css = f.read()
            with open(os.path.join(ASSETS, "auth.js"), encoding="utf-8") as f:
                auth_js = f.read()
            with open(os.path.join(ASSETS, "icons.svg"), encoding="utf-8") as f:
                sprite = f.read()
            auth_js = auth_js.replace("{{SPRITE}}", sprite.replace("`", "\\`").replace("\\", "\\\\"))
            cls._asset_cache = {"css": css, "auth": auth_js}
        return cls._asset_cache

    def _page(self, filename: str, status: int = 200):
        with open(os.path.join(PAGES, filename), encoding="utf-8") as f:
            text = f.read()
        assets = self._assets()
        text = (text.replace("{{STYLE}}", assets["css"]).replace("{{AUTH}}", assets["auth"])
                    .replace("{{YEAR}}", str(today().year)))
        self._send_bytes(status, text.encode(), "text/html; charset=utf-8")

    def _cookie_token(self) -> str | None:
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        try:
            jar = SimpleCookie()
            jar.load(raw)
            for name in (SESSION_COOKIE, RELAY_COOKIE):
                m = jar.get(name)
                if m and m.value:
                    return m.value
        except Exception:
            return None
        return None

    def _session_token(self) -> str | None:
        auth = self.headers.get("Authorization", "")
        if auth[:7].lower() == "bearer ":
            t = auth[7:].strip()
            if t:
                return t
        return self._cookie_token()

    def _user(self):
        return session_user(self._session_token())

    def _cookie_attrs(self) -> str:
        host = (self.headers.get("Host") or "").split(":")[0].strip().lower()
        xfp = (self.headers.get("X-Forwarded-Proto") or "").strip().lower()
        if xfp.startswith("https"):
            # Real HTTPS deployment: the cross-site preview iframe needs
            # SameSite=None + Secure or the browser drops the cookie outright.
            return "SameSite=None; Secure"
        # Everything else (localhost, 127.x, a sandboxed http preview host):
        # SameSite=None is *rejected* by browsers without Secure, so Lax is the
        # only cookie that can be stored at all.
        return "SameSite=Lax"

    def _session_cookie_headers(self, token: str) -> list:
        max_age = SESSION_DAYS * 86400
        return [
            ("Set-Cookie", f"{SESSION_COOKIE}={token}; Path=/; Max-Age={max_age}; HttpOnly; "
                           f"{self._cookie_attrs()}"),
            ("Set-Cookie", f"{RELAY_COOKIE}={token}; Path=/; Max-Age={max_age}; "
                           f"{self._cookie_attrs()}"),
        ]

    def _clear_cookie_headers(self) -> list:
        return [
            ("Set-Cookie", f"{SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; {self._cookie_attrs()}"),
            ("Set-Cookie", f"{RELAY_COOKIE}=; Path=/; Max-Age=0; {self._cookie_attrs()}"),
        ]

    # kept for callers that only need one header
    def _session_cookie_header(self, token: str):
        return self._session_cookie_headers(token)[0]

    def _clear_cookie_header(self):
        return self._clear_cookie_headers()[0]

    def _read_json(self, cap: int = 200_000) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        if length > cap:
            raise ValueError("Request too large.")
        data = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(data, dict):
            raise ValueError("Request body must be a JSON object.")
        return data

    # ---- routing ----

    PAGES = {"/dashboard": "dashboard.html", "/submit": "submit.html", "/cases": "cases.html",
             "/case": "case.html", "/disclosed": "disclosed.html", "/admin": "admin.html",
             "/kb": "kb.html", "/workbench": "workbench.html",
             "/engine": "engine.html"}

    def _not_found(self):
        """404: HTML for browser navigations, JSON for API callers."""
        accept = (self.headers.get("Accept") or "").lower()
        if "text/html" in accept and not self.path.startswith("/api/"):
            body = (
                "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
                "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
                "<title>Not found — NYAYA-RAC</title></head><body style=\"font-family:system-ui;"
                "max-width:560px;margin:60px auto;padding:0 20px;color:#101828\">"
                "<h1>Page not found</h1><p>The page you asked for does not exist. "
                "Check the address, or return to the "
                "<a href=\"/\">home page</a>.</p></body></html>"
            )
            self._send_bytes(404, body.encode(), "text/html; charset=utf-8")
        else:
            self._json(404, {"error": "Not found"})

    def _health(self):
        """Liveness probe (no auth): proves the process, DB and engine answer."""
        try:
            with db() as c:
                c.execute("SELECT 1 FROM users LIMIT 1").fetchone()
            db_ok = True
        except Exception:
            db_ok = False
        self._json(200 if db_ok else 503, {
            "ok": db_ok, "version": APP_VERSION,
            "engine": ENGINE.version, "mode": ENGINE._mode,
            "db": "ok" if db_ok else "unavailable",
        })

    def do_GET(self):
        u = urlparse(self.path)
        path, qs = u.path, parse_qs(u.query)
        try:
            if path == "/":
                self._page("home.html")
            elif path == "/login":
                self._page("login.html")
            elif path in self.PAGES:
                # Served unauthenticated; each page guards itself in JS (works
                # inside preview iframes where cookies are unavailable).
                self._page(self.PAGES[path])
            elif path in ("/health", "/api/health"):
                self._health()
            elif path == "/robots.txt":
                self._text(200, ROBOTS_TXT)
            elif path == "/assets/style.css":
                with open(os.path.join(ASSETS, "style.css"), "rb") as f:
                    self._send_bytes(200, f.read(), "text/css; charset=utf-8")
            elif path == "/favicon.svg":
                self._send_bytes(200, FAVICON_SVG.encode(), "image/svg+xml")
            elif path == "/favicon.ico":
                self._send_bytes(204, b"", "image/x-icon")
            elif path == "/api/engine/overview":
                self._json(200, engine_overview())
            elif path == "/api/engine/impact":
                q = parse_qs(urlparse(self.path).query)
                self._json(200, engine_impact((q.get("amendment") or [""])[0]))
            elif path == "/api/session":
                self._api_session()
            elif path == "/api/me":
                self._api_me()
            elif path == "/api/reports":
                self._api_reports_list()
            elif path == "/api/report":
                user = self._require_user()
                if user:
                    self._json(200, build_case_payload(user, (qs.get("id") or [""])[0]))
            elif path == "/api/evidence":
                user = self._require_user()
                if user:
                    try:
                        eid = int((qs.get("id") or ["0"])[0])
                    except ValueError:
                        raise ValueError("evidence id must be a number.")
                    fname, ctype, blob = evidence_download(user, eid)
                    safe = fname.replace('"', "").replace("\r", "").replace("\n", "")
                    self._send_bytes(200, blob, ctype, [
                        ("Content-Disposition", f'attachment; filename="{safe}"')])
            elif path == "/api/disclosed":
                # Public registry: approved disclosures only, safe for visitors.
                self._json(200, disclosed_list(self._user() or {"role": "GUEST", "name": "guest", "id": ""}))
            elif path == "/api/feedback":
                self._api_feedback_get((qs.get("report_id") or [""])[0])
            elif path == "/api/provenance":
                user = self._require_user()
                if user:
                    self._json(200, legal_kb.provenance_chain((qs.get("type") or ["REPORT"])[0],
                                                              (qs.get("id") or [""])[0]))
            elif path == "/api/kb":
                user = self._require_user()
                if user:
                    self._json(200, {"statutes": legal_kb.statute_rows(),
                                     "precedents": legal_kb.precedent_rows(),
                                     "conflicts": legal_kb.detect_conflicts()})
            elif path == "/api/admin/overview":
                user = self._require_user()
                if user:
                    self._json(200, admin_overview(user))
            elif path == "/api/admin/feedback":
                user = self._require_user()
                if not user:
                    return
                if user.get("role") != "ADMIN":
                    raise AccessDenied("Admin only.")
                if (qs.get("export") or [""])[0] == "jsonl":
                    self._text(200, feedback_dataset(), "application/x-ndjson; charset=utf-8")
                else:
                    self._json(200, {"ok": True, "analytics": feedback_analytics()})
            elif path == "/api/digilocker/status":
                self._api_digilocker_status()
            elif path == "/api/digilocker/events":
                self._api_digilocker_events()
            elif path == "/api/digilocker/verify":
                self._json(200, dl_mod.verify_artefact((qs.get("artefact") or [""])[0]))
            elif path == "/schema":
                self._admin_gate_then(self._api_schema)
            elif path == "/audit":
                self._admin_gate_then(self._api_audit)
            else:
                self._not_found()
        except AccessDenied as e:
            self._json(403, {"error": str(e)})
        except (NotFound, LookupError) as e:
            self._json(404, {"error": str(e)})
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            self._json(400, {"error": str(e)})
        except Exception as e:  # pragma: no cover
            print("Server error:", repr(e))
            self._json(500, {"error": "An internal error occurred."})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/register":
                self._api_register()
            elif path == "/api/login":
                self._api_login()
            elif path == "/api/logout":
                self._api_logout()
            elif path == "/api/renew":
                self._api_renew()
            elif path == "/api/report":
                user = self._require_user()
                if user:
                    body = self._read_json(MAX_REPORT_BODY)
                    self._json(200, intake_report(user, body))
            elif path == "/api/revise":
                user = self._require_user()
                if user:
                    body = self._read_json(MAX_REPORT_BODY)
                    rid = str(body.get("report_id", ""))
                    if not rid:
                        raise ValueError("report_id is required.")
                    self._json(200, revise_report(user, rid, body))
            elif path == "/api/disclosure-request":
                user = self._require_user()
                if user:
                    body = self._read_json()
                    self._json(200, request_disclosure(user, str(body.get("report_id", "")),
                                                       str(body.get("note", ""))))
            elif path == "/api/feedback":
                user = self._require_user()
                if user:
                    body = self._read_json()
                    self._json(200, add_feedback(user, str(body.get("report_id", "")),
                                                 body.get("vote", 0), str(body.get("comment", ""))))
            elif path == "/api/evidence-map":
                user = self._require_user()
                if user:
                    body = self._read_json()
                    self._json(200, map_evidence_to_fact(
                        user, str(body.get("report_id", "")), int(body.get("evidence_id", 0)),
                        str(body.get("fact_key", "")), str(body.get("relation", "")),
                        str(body.get("note", ""))))
            elif path == "/api/admin/disclosure":
                user = self._require_user()
                if user:
                    body = self._read_json()
                    self._json(200, admin_disclosure(user, str(body.get("report_id", "")),
                                                     str(body.get("action", "")),
                                                     str(body.get("mode", "ANONYMIZED")),
                                                     str(body.get("note", ""))))
            elif path == "/api/admin/manual-check":
                user = self._require_user()
                if user:
                    body = self._read_json()
                    apply_manual_check(user, str(body.get("report_id", "")),
                                       str(body.get("status", "")), str(body.get("note", "")))
                    self._json(200, {"ok": True})
            elif path == "/api/admin/statutes":
                user = self._require_admin()
                if user:
                    body = self._read_json()
                    sid = legal_kb.add_statute_version(
                        str(body.get("statute", "")), str(body.get("provision", "")),
                        str(body.get("version_label", "")), str(body.get("effective_from", "")),
                        body.get("effective_to") or None, str(body.get("title", "")),
                        str(body.get("body", "")), bool(body.get("pun_death")),
                        bool(body.get("pun_life")),
                        body.get("pun_min_years"), body.get("pun_max_years"),
                        body.get("cognizable"), body.get("bailable"), body.get("compoundable"),
                        str(body.get("source_ref", "")), False, str(body.get("note", "")),
                        user["name"])
                    self._json(200, {"ok": True, "id": sid,
                                     "reminder": "Version added UNVERIFIED. Mark it verified only after checking the official corpus; only verified versions feed evaluations."})
            elif path == "/api/admin/statutes/verify":
                user = self._require_admin()
                if user:
                    body = self._read_json()
                    legal_kb.mark_statute_verified(int(body.get("id", 0)), user["name"])
                    self._json(200, {"ok": True})
            elif path == "/api/admin/precedents":
                user = self._require_admin()
                if user:
                    body = self._read_json()
                    pid = legal_kb.add_precedent(
                        str(body.get("citation", "")), str(body.get("court", "")),
                        body.get("decided_on"), str(body.get("statute", "")),
                        str(body.get("provision", "")), str(body.get("headnote", "")),
                        str(body.get("holding_tag", "PROCEDURAL")), user["name"])
                    self._json(200, {"ok": True, "id": pid})
            elif path == "/api/admin/precedents/status":
                user = self._require_admin()
                if user:
                    body = self._read_json()
                    legal_kb.set_precedent_status(int(body.get("id", 0)),
                                                  str(body.get("status", "")),
                                                  body.get("overruled_by"))
                    self._json(200, {"ok": True})
            elif path == "/api/admin/amendment-impact":
                user = self._require_admin()
                if user:
                    body = self._read_json()
                    self._json(200, amendment_impact(
                        user, str(body.get("statute", "")), str(body.get("provision", "")),
                        body.get("apply_report_id") or None))
            elif path == "/api/digilocker/consent":
                self._api_digilocker_consent()
            elif path == "/api/digilocker/grant":
                self._api_digilocker_grant()
            elif path == "/api/digilocker/callback":
                self._api_digilocker_callback()
            elif path == "/api/digilocker/revoke":
                self._api_digilocker_revoke()
            elif path == "/evaluate":
                self._admin_gate_then(self._api_evaluate)
            else:
                self._not_found()
        except AccessDenied as e:
            self._json(403, {"error": str(e)})
        except (NotFound, LookupError) as e:
            self._json(404, {"error": str(e)})
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            self._json(400, {"error": str(e)})
        except engine_mod.JsonLogicError as e:
            self._json(400, {"error": f"Rule evaluation error: {e}"})
        except Exception as e:  # pragma: no cover
            print("Server error:", repr(e))
            self._json(500, {"error": "An internal error occurred."})

    def log_message(self, fmt, *args):
        print("%s %s" % (self.address_string(), fmt % args))

    # ---- auth gates ----

    def _require_user(self):
        user = self._user()
        if not user:
            self._json(401, {"error": "Not logged in.", "login_url": "/login"})
            return None
        return user

    def _require_admin(self):
        user = self._require_user()
        if not user:
            return None
        if user.get("role") != "ADMIN":
            self._json(403, {"error": "Administrator access required."})
            return None
        return user

    def _admin_gate_then(self, fn):
        user = self._require_admin()
        if user:
            fn()

    # ---- endpoints ----

    def _api_register(self):
        who = self._client()
        wait = rate_check("register", who, RATE_MAX_REGISTER)
        if wait:
            self._json(429, {"error": f"Too many registrations. Try again in {wait} seconds.",
                             "retry_after": wait})
            return
        body = self._read_json()
        try:
            user = create_user(str(body.get("name", "")), str(body.get("email", "")),
                               str(body.get("password", "")))
        except ValueError:
            rate_fail("register", who)
            raise
        rate_fail("register", who)  # count successful registrations too (spam guard)
        token = create_session(user["id"])
        self._json(200, {"ok": True, "name": user["name"], "token": token, "role": user["role"]},
                   self._session_cookie_headers(token))

    def _client(self) -> str:
        return (self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                or self.client_address[0])

    def _api_login(self):
        body = self._read_json()
        email = str(body.get("email", ""))
        for who, limit in ((email, RATE_MAX_ACCOUNT), (self._client(), RATE_MAX_ADDRESS)):
            wait = rate_check("login", who, limit)
            if wait:
                self._json(429, {"error": f"Too many failed attempts. Try again in {wait} seconds.",
                                 "retry_after": wait})
                return
        try:
            user = authenticate(email, str(body.get("password", "")))
        except ValueError:
            for who in (email, self._client()):
                rate_fail("login", who)
            raise
        for who in (email, self._client()):
            rate_reset("login", who)
        token = create_session(user["id"])
        self._json(200, {"ok": True, "name": user["name"], "token": token, "role": user["role"]},
                   self._session_cookie_headers(token))

    def _api_logout(self):
        token = self._session_token()
        if token:
            with LOCK, db() as c:
                c.execute("DELETE FROM sessions WHERE token=?", (token,))
        self._json(200, {"ok": True}, self._clear_cookie_headers())

    def _api_session(self):
        """Session bootstrap for pages: never 401, and repair the cookies.

        A page may arrive with no Authorization header, no readable web storage
        and blocked third-party cookies — the relay cookie is then the only
        surviving channel. Whenever a token is valid we also re-issue both
        cookies so the *next* navigation is authenticated too.
        """
        token = self._session_token()
        user = session_user(token) if token else None
        if not user:
            self._json(200, {"authenticated": False})
            return
        headers = self._session_cookie_headers(token) if self._cookie_token() != token else None
        self._json(200, {
            "authenticated": True,
            "token": token,                       # lets the page re-seed its storage
            "user": {"name": user["name"], "email": user["email"], "role": user.get("role", "USER"),
                     "is_admin": user.get("role") == "ADMIN", "created_at": user["created_at"],
                     "id": user["id"]},
        }, headers)

    def _api_renew(self):
        """Promote a Bearer token into cookies (used when storage was unavailable)."""
        user = self._require_user()
        if not user:
            return
        token = self._session_token()
        if not token:
            raise AccessDenied("No session to renew.")
        self._json(200, {"ok": True, "token": token}, self._session_cookie_headers(token))

    def _api_me(self):
        user = self._require_user()
        if not user:
            return
        with db() as c:
            n = c.execute("SELECT COUNT(*) n FROM reports WHERE user_id=?", (user["id"],)).fetchone()["n"]
        self._json(200, {
            "name": user["name"], "email": user["email"], "created_at": user["created_at"],
            "report_count": n, "role": user.get("role", "USER"), "is_admin": user.get("role") == "ADMIN",
            "digilocker": {**dl_mod.status(user), "short": True},
        })

    def _api_reports_list(self):
        user = self._require_user()
        if not user:
            return
        with db() as c:
            rows = c.execute(
                "SELECT id,ref,created_at,incident_date,domain,review_level,urgency,severity_tier,"
                "evidence_count,digilocker_status,narrative,disclosure_status,manual_check_status,"
                "current_rev_no,feedback_up,feedback_down,feedback_flagged FROM reports "
                "WHERE user_id=? ORDER BY created_at DESC LIMIT 200", (user["id"],)).fetchall()
        items = []
        for r in rows:
            n = r["narrative"] or ""
            items.append({**{k: r[k] for k in r.keys() if k != "narrative"},
                          "excerpt": (n[:140] + "…") if len(n) > 140 else n})
        self._json(200, {"reports": items, "count": len(items)})

    def _api_feedback_get(self, report_id: str):
        user = self._require_user()
        if not user:
            return
        with db() as c:
            row = c.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
            if not row:
                raise NotFound("Case not found.")
            if case_access(user, row) is None:
                raise NotFound("Case not found.")
            fb = c.execute("SELECT vote, comment FROM feedback WHERE report_id=? AND user_id=?",
                           (report_id, user["id"])).fetchone()
        self._json(200, {"up": row["feedback_up"], "down": row["feedback_down"],
                         "flagged": bool(row["feedback_flagged"]), "my_vote": fb["vote"] if fb else 0})

    def _api_digilocker_status(self):
        user = self._require_user()
        if not user:
            return
        self._json(200, dl_mod.status(user))

    def _api_digilocker_consent(self):
        """Step 1-2: open (or inspect) a scoped consent request."""
        user = self._require_user()
        if not user:
            return
        body = self._read_json()
        if body.get("request_id"):
            self._json(200, dl_mod.consent_status(user, str(body["request_id"])))
            return
        self._json(200, dl_mod.create_consent_request(
            user, str(body.get("purpose") or ""), str(body.get("scope") or "")))

    def _api_digilocker_grant(self):
        """The user's decision on the consent screen (deny stops the flow dead)."""
        user = self._require_user()
        if not user:
            return
        body = self._read_json()
        self._json(200, dl_mod.grant_consent(
            user, str(body.get("request_id", "")), consent=bool(body.get("consent")),
            provided_name=str(body.get("provided_name") or "")))

    def _api_digilocker_callback(self):
        """Step 3-4: identical handling for the simulated redirect and a real one."""
        user = self._require_user()
        if not user:
            return
        body = self._read_json()
        self._json(200, dl_mod.exchange_code(str(body.get("request_id", "")),
                                             str(body.get("code", "")),
                                             str(body.get("state", "")), user))

    def _api_digilocker_revoke(self):
        user = self._require_user()
        if not user:
            return
        body = self._read_json()
        self._json(200, dl_mod.revoke(user, str(body.get("reason") or "")))

    def _api_digilocker_events(self):
        user = self._require_user()
        if not user:
            return
        self._json(200, {"events": dl_mod.events(user["id"]), "status": dl_mod.status(user)["status"]})

    def _api_evaluate(self):
        body = self._read_json(2_000_000)
        facts = body.get("facts") or {}
        runtime = body.get("runtime_variables") or {}
        sources = body.get("retrieved_sources") or []
        case_id = body.get("case_id") or None
        rule_base_path = body.get("rule_base_path") or None
        if not isinstance(facts, dict) or not isinstance(runtime, dict) or not isinstance(sources, list):
            raise ValueError("facts/runtime_variables must be objects; retrieved_sources must be a list.")
        with ENGINE_LOCK:
            if rule_base_path:
                if not ENGINE.reload_rule_base(str(rule_base_path)):
                    raise ValueError("Could not load rule base from that path (missing or invalid JSON).")
            res = ENGINE.evaluate(facts=facts, runtime_variables=runtime,
                                  retrieved_sources=sources, case_id=case_id)
        self._json(200, res)

    def _api_schema(self):
        rb = ENGINE.rb
        self._json(200, {
            "mode": ENGINE._mode, "rule_base_version": ENGINE.version,
            "meta": rb.get("meta", {}), "config": rb.get("config", {}),
            "severity": {"tier_definitions": rb.get("severity", {}).get("tier_definitions", [])},
            "triggers": [{"id": t.get("id"), "level": t.get("level"), "name": t.get("name"),
                          "category": t.get("category")} for t in rb.get("review", {}).get("triggers", [])],
            "output_schema": rb.get("output_schema", {}),
        })

    def _api_audit(self):
        self._json(200, {"audit": ENGINE.audit_recent(200)})


def purge_expired_sessions() -> int:
    """Delete expired session rows. Called on startup so the table cannot
    grow forever with dead tokens."""
    with db() as c:
        cur = c.execute("DELETE FROM sessions WHERE expires_at <= ?",
                        (now_dt().isoformat(),))
        return int(cur.rowcount)


def init_all() -> None:
    os.makedirs(EVIDENCE_DIR, exist_ok=True)
    init_db()
    legal_kb.init_kb()
    dl_mod.init_dl()
    purge_expired_sessions()
    ensure_admin()


# Binding: loopback by default. This is a laptop tool holding real personal data;
# publishing it to the network must be a deliberate act, not the default.
HOST = os.environ.get("NYAYA_HOST", "127.0.0.1")
PORT = int(os.environ.get("NYAYA_PORT", "8000"))
PUBLIC_BIND_ACK = os.environ.get("NYAYA_ALLOW_PUBLIC_BIND", "") == "1"

# A sandbox/preview container needs a non-loopback bind; without the explicit
# acknowledgement the server would be unreachable there and look broken.
if os.environ.get("NYAYA_PREVIEW") == "1":
    HOST, PUBLIC_BIND_ACK = "0.0.0.0", True


def main():
    init_all()
    if HOST not in ("127.0.0.1", "localhost", "::1") and not PUBLIC_BIND_ACK:
        raise SystemExit(
            f"Refusing to bind {HOST}: the portal has no transport security and holds "
            f"personal data. Set NYAYA_ALLOW_PUBLIC_BIND=1 only if you accept that.")
    shown = "localhost" if HOST in ("127.0.0.1", "0.0.0.0", "::1") else HOST
    print(f"NYAYA-RAC portal running on http://{shown}:{PORT} "
          f"(bind {HOST}, db: {DB_PATH})", flush=True)
    if HOST not in ("127.0.0.1", "localhost", "::1"):
        print("[warn] Reachable beyond this machine. No TLS, no audit of who connects.",
              flush=True)
    try:
        ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.", flush=True)


USAGE = """NYAYA-RAC v{ver} — citizen reporting portal + decision-support server

Usage:
  python3 server.py                          start the portal (http://localhost:8000)
  python3 server.py --make-admin EMAIL       promote an existing account to ADMIN
  python3 server.py --rotate-admin-password [EMAIL]
                                             generate a new admin password (revokes sessions)
  python3 server.py --version                print the version and exit
  python3 server.py --help                   show this help and exit

Environment:
  NYAYA_HOST / NYAYA_PORT                    bind address (default 127.0.0.1:8000)
  NYAYA_DB / NYAYA_AUDIT_DB / NYAYA_EVIDENCE_DIR
                                             data paths (defaults: ./nyaya-rac*.sqlite3, ./evidence)
  NYAYA_ADMIN_EMAIL / NYAYA_ADMIN_PASSWORD   bootstrap admin (password must be 12+ chars)
  NYAYA_ALLOW_PUBLIC_BIND=1                  required to bind beyond loopback (no TLS!)
  NYAYA_PREVIEW=1                            sandbox/preview mode: bind 0.0.0.0

Health: GET /health (no auth). Docs: docs/PORTAL.md, docs/API.md.
"""


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] in ("--help", "-h"):
        print(USAGE.format(ver=APP_VERSION))
        sys.exit(0)
    if len(sys.argv) >= 2 and sys.argv[1] == "--version":
        print(f"NYAYA-RAC {APP_VERSION}")
        sys.exit(0)
    if len(sys.argv) >= 2 and sys.argv[1] == "--rotate-admin-password":
        init_all()
        target = sys.argv[2] if len(sys.argv) >= 3 else None
        rotate_admin_password(target)
        print(f"Rotated. New credentials in {ADMIN_CREDENTIALS_FILE} (mode 600). "
              f"All sessions for that account were revoked.")
        sys.exit(0)
    if len(sys.argv) >= 3 and sys.argv[1] == "--make-admin":
        init_all()
        ok = promote_admin(sys.argv[2])
        print("Promoted" if ok else "No such user:", sys.argv[2])
        sys.exit(0 if ok else 1)
    if len(sys.argv) >= 2 and sys.argv[1].startswith("--"):
        print(f"Unknown option: {sys.argv[1]}\n\n" + USAGE.format(ver=APP_VERSION))
        sys.exit(2)
    main()
