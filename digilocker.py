"""NYAYA-RAC — DigiLocker identity verification (calibrated flow model).

WHAT THIS IS
------------
A faithful *model* of how the real DigiLocker partner flow works, implemented
with the same states, artefacts and failure modes so the portal can be exercised
end-to-end without a partner account or network egress:

    1. authorize      — build the consent request (client id, redirect URI,
                        PKCE code challenge, scope, purpose, timestamp nonce)
    2. consent        — the user approves a scoped request on the (simulated)
                        DigiLocker consent screen
    3. callback       — the authorization code is exchanged for an access token
                        and an ID artefact is pulled from the user's locker
    4. verify         — the artefact is checked: issuer allow-list, schema,
                        consent still inside its validity window, name/DOB sanity,
                        code replay protection, one identity per account
    5. attest         — on success the portal issues a *verification artefact*
                        (sha256-sealed, expiring) that reports carry as evidence
                        of identity; on failure it records a machine-readable
                        rejection reason and nothing is attached

CALIBRATION
-----------
Constants below are deliberately explicit and it is honest about what is real:

  * REAL_WORLD: the public DigiLocker facts the model is calibrated against
    (issuer names, consent validity, artefact fields, request parameters).
  * Every simulated behaviour is labelled SIMULATION in the API payload
    (`mode: "SIMULATED"`), stamped on the artefact (`simulated: true`) and shown
    in the UI with a "simulated" tag. The portal never claims a government
    identity was verified.
  * Switching to a live integration means implementing `exchange_code()` and
    `fetch_artefact()` against the partner gateway; no other layer changes.
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
from typing import Any, Dict, List, Optional

from db import LOCK, db, now

VERSION = "digilocker-model-1.0.0"

# --------------------------------------------------------------------------
# REAL_WORLD — calibration constants (public facts about the actual system)
# --------------------------------------------------------------------------

REAL_WORLD = {
    "environment": "https://digilocker.gov.in (sandbox: partner gateway sandbox)",
    "flow": "OAuth-2 authorization-code with PKCE, consent screen, artefact pull",
    "consent_validity_minutes": 30,      # a consent token is short-lived
    "max_consent_requests_per_day": 5,   # anti-harassment / replay control
    "code_single_use": True,
    "state_parameter_required": True,
    "pkce_required": True,
    "artefact_fields": ["name", "dob", "gender", "photo_present", "issuer",
                        "issuer_ref", "issued_on", "address_present", "verified_by"],
    # DigiLocker draws most identity papers from these issuer families:
    "allowed_issuers": [
        "UIDAI", "Election Commission of India", "Ministry of Road Transport and Highways",
        "Income Tax Department", "CGHS", "Employees' Provident Fund Organisation",
    ],
}

# Simulation-only knobs (used by tests and the demo consent screen).
SIMULATION = {
    "mode": "SIMULATED",
    "simulated": True,
    "disclosure": "No data leaves this machine. Code exchange and artefact pull are "
                  "generated locally to exercise the real flow's state machine.",
}

MIN_AGE_YEARS = 0          # identity is age-agnostic; age checks live in the engine
CONSENT_TTL_MINUTES = REAL_WORLD["consent_validity_minutes"]

IDENTITY_SCHEMA_VERSION = "nyaya-identity-1"

STATUS_LABELS = {
    "NOT_LINKED": "Not linked",
    "PENDING": "Consent given — awaiting callback",
    "LINKED": "Identity verified",
    "EXPIRED": "Verification expired",
    "REVOKED": "Verification withdrawn",
    "FAILED": "Verification failed",
}

REJECTION_REASONS = {
    "UNKNOWN_ISSUER": "The document was not issued by a recognised issuer.",
    "MISSING_NAME": "The document carries no legible holder name.",
    "MISSING_DOB": "The document carries no date of birth.",
    "BAD_DOB": "The date of birth is not a valid calendar date.",
    "FUTURE_DOB": "The date of birth lies in the future.",
    "CONSENT_EXPIRED": "The consent window lapsed before the callback completed.",
    "CODE_REPLAYED": "The authorization code was already used once.",
    "CODE_INVALID": "The authorization code did not match the request.",
    "STATE_MISMATCH": "The callback state parameter did not match the consent request.",
    "ALREADY_LINKED": "This account already has a verified identity.",
    "IDENTITY_IN_USE": "That identity is already linked to another account.",
}


# --------------------------------------------------------------------------
# schema
# --------------------------------------------------------------------------

def init_dl() -> None:
    with db() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS dl_requests(
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              created_at TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              client_id TEXT NOT NULL,
              redirect_uri TEXT NOT NULL,
              scope TEXT NOT NULL,
              purpose TEXT NOT NULL,
              state TEXT NOT NULL UNIQUE,
              code_challenge TEXT NOT NULL,
              code_verifier TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'AWAITING_CONSENT',
              code TEXT,
              code_used INTEGER NOT NULL DEFAULT 0,
              completed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS dl_identities(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id TEXT NOT NULL UNIQUE,
              request_id TEXT NOT NULL,
              name TEXT NOT NULL,
              dob TEXT NOT NULL,
              gender TEXT NOT NULL DEFAULT '',
              issuer TEXT NOT NULL,
              issuer_ref TEXT NOT NULL,
              photo_present INTEGER NOT NULL DEFAULT 0,
              address_present INTEGER NOT NULL DEFAULT 0,
              verified_by TEXT NOT NULL,
              verified_at TEXT NOT NULL,
              expires_on TEXT NOT NULL,
              doc_json TEXT NOT NULL,
              doc_sha256 TEXT NOT NULL,
              artefact_id TEXT NOT NULL,
              simulated INTEGER NOT NULL DEFAULT 1,
              revoked_at TEXT,
              revoke_reason TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS dl_events(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              created_at TEXT NOT NULL,
              request_id TEXT NOT NULL DEFAULT '',
              user_id TEXT NOT NULL DEFAULT '',
              event TEXT NOT NULL,
              outcome TEXT NOT NULL DEFAULT '',
              reason_code TEXT NOT NULL DEFAULT '',
              detail TEXT NOT NULL DEFAULT ''
            );
            """
        )


def _event_conn(c, request_id: str, user_id: str, event: str, outcome: str = "",
                reason_code: str = "", detail: str = "") -> None:
    """Write an audit event on an open connection (never opens a second one:
    doing so inside an uncommitted write transaction self-deadlocks SQLite)."""
    c.execute(
        "INSERT INTO dl_events(created_at,request_id,user_id,event,outcome,reason_code,detail) "
        "VALUES(?,?,?,?,?,?,?)",
        (now(), request_id, user_id, event, outcome, reason_code, str(detail)[:600]),
    )


def _event(request_id: str, user_id: str, event: str, outcome: str = "",
           reason_code: str = "", detail: str = "") -> None:
    with LOCK, db() as c:
        _event_conn(c, request_id, user_id, event, outcome, reason_code, detail)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _iso(d: dt.datetime) -> str:
    return d.astimezone(dt.timezone.utc).isoformat()


def _parse(ts: Optional[str]) -> Optional[dt.datetime]:
    if not ts:
        return None
    try:
        return dt.datetime.fromisoformat(ts)
    except ValueError:
        return None


def _pkce_pair() -> tuple[str, str]:
    """RFC 7636 S256: verifier is 43-128 chars, challenge = BASE64URL(SHA256(v))."""
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


def normalise_name(name: str) -> str:
    return re.sub(r"[^a-z]", "", str(name or "").lower())


def normalise_dob(dob: str) -> str:
    """Accept DD-MM-YYYY, YYYY-MM-DD, DD/MM/YYYY → YYYY-MM-DD ('' if unparseable)."""
    s = str(dob or "").strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def validate_artefact(doc: Dict[str, Any], *, consent_expires_at: Optional[str] = None,
                      reference: Optional[dt.datetime] = None) -> List[tuple[str, str]]:
    """Return [(reason_code, message)] — empty list means the artefact is sound."""
    problems: List[tuple[str, str]] = []
    ref = reference or dt.datetime.now(dt.timezone.utc)
    issuer = str(doc.get("issuer", "")).strip()
    if issuer not in REAL_WORLD["allowed_issuers"]:
        problems.append(("UNKNOWN_ISSUER", REJECTION_REASONS["UNKNOWN_ISSUER"]))
    if not str(doc.get("name", "")).strip():
        problems.append(("MISSING_NAME", REJECTION_REASONS["MISSING_NAME"]))
    dob_raw = str(doc.get("dob", "")).strip()
    if not dob_raw:
        problems.append(("MISSING_DOB", REJECTION_REASONS["MISSING_DOB"]))
    else:
        dob = normalise_dob(dob_raw)
        if not dob:
            problems.append(("BAD_DOB", REJECTION_REASONS["BAD_DOB"]))
        elif dt.date.fromisoformat(dob) > ref.date():
            problems.append(("FUTURE_DOB", REJECTION_REASONS["FUTURE_DOB"]))
        else:
            age = (ref.date() - dt.date.fromisoformat(dob)).days / 365.25
            if age < MIN_AGE_YEARS:
                problems.append(("BAD_DOB", REJECTION_REASONS["BAD_DOB"]))
    exp = _parse(consent_expires_at)
    if exp and ref > exp:
        problems.append(("CONSENT_EXPIRED", REJECTION_REASONS["CONSENT_EXPIRED"]))
    return problems


# --------------------------------------------------------------------------
# step 1-2: consent request
# --------------------------------------------------------------------------

def consent_quota(user_id: str) -> Dict[str, Any]:
    with db() as c:
        n = c.execute(
            "SELECT COUNT(*) n FROM dl_requests WHERE user_id=? AND created_at>=?",
            (user_id, (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).isoformat()),
        ).fetchone()["n"]
    limit = REAL_WORLD["max_consent_requests_per_day"]
    return {"used": n, "limit": limit, "remaining": max(0, limit - n)}


def create_consent_request(user: dict, purpose: str = "", scope: str = "") -> Dict[str, Any]:
    """Step 1: authorise. Mirrors the partner request the portal would send."""
    with db() as c:
        row = c.execute("SELECT * FROM dl_identities WHERE user_id=? AND revoked_at IS NULL",
                        (user["id"],)).fetchone()
    if row:
        raise ValueError("ALREADY_LINKED: this account already has a verified identity.")
    quota = consent_quota(user["id"])
    if quota["remaining"] <= 0:
        raise ValueError("Consent request limit reached for today. Please try again after 24 hours.")

    verifier, challenge = _pkce_pair()
    req_id = "dlr_" + uuid_secret()
    state = "st_" + uuid_secret()
    created = dt.datetime.now(dt.timezone.utc)
    expires = created + dt.timedelta(minutes=CONSENT_TTL_MINUTES)
    scope = scope or "aadhaar:name aadhaar:dob aadhaar:gender aadhaar:photo"
    purpose = purpose or "Identity verification for a case report on NYAYA-RAC"
    with LOCK, db() as c:
        c.execute(
            "INSERT INTO dl_requests(id,user_id,created_at,expires_at,client_id,redirect_uri,scope,"
            "purpose,state,code_challenge,code_verifier,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,'AWAITING_CONSENT')",
            (req_id, user["id"], _iso(created), _iso(expires), DL_CLIENT_ID,
             DL_REDIRECT_URI, scope, purpose, state, challenge, verifier),
        )
    _event(req_id, user["id"], "CONSENT_REQUESTED", "AWAITING_CONSENT")
    return {
        "implementation": VERSION,
        "mode": SIMULATION["mode"], "simulated": True,
        "request_id": req_id, "state": state, "scope": scope, "purpose": purpose,
        "client_id": DL_CLIENT_ID, "redirect_uri": DL_REDIRECT_URI,
        "code_challenge": challenge, "code_challenge_method": "S256",
        "expires_at": _iso(expires), "validity_minutes": CONSENT_TTL_MINUTES,
        "quota": consent_quota(user["id"]),
        "disclosure": SIMULATION["disclosure"],
    }


def uuid_secret() -> str:
    return secrets.token_hex(8)


def consent_status(user: dict, request_id: str) -> Dict[str, Any]:
    with db() as c:
        row = c.execute("SELECT * FROM dl_requests WHERE id=? AND user_id=?",
                        (request_id, user["id"])).fetchone()
    if not row:
        raise LookupError("Consent request not found.")
    expires = _parse(row["expires_at"])
    live = bool(expires and dt.datetime.now(dt.timezone.utc) <= expires)
    return {"request_id": row["id"], "status": row["status"], "scope": row["scope"],
            "purpose": row["purpose"], "expires_at": row["expires_at"], "live": live,
            "consent_given": row["status"] in ("CONSENT_GIVEN", "COMPLETED"),
            "seconds_remaining": max(0, int((expires - dt.datetime.now(dt.timezone.utc)).total_seconds()))
            if expires else 0}


# --------------------------------------------------------------------------
# step 3: simulated DigiLocker side (consent screen → code)
# --------------------------------------------------------------------------

def grant_consent(user: dict, request_id: str, *, consent: bool,
                  provided_name: str = "") -> Dict[str, Any]:
    """The user's decision on the DigiLocker consent screen.

    `consent=False` must terminate the flow with nothing stored, exactly like a
    denial on the real screen. `consent=True` issues a single-use code (the
    DigiLocker side then redirects back to our redirect_uri).
    """
    with db() as c:
        row = c.execute("SELECT * FROM dl_requests WHERE id=? AND user_id=?",
                        (request_id, user["id"])).fetchone()
    if not row:
        raise LookupError("Consent request not found.")
    if row["status"] != "AWAITING_CONSENT":
        raise ValueError("This consent request is no longer open.")
    expires = _parse(row["expires_at"])
    if not expires or dt.datetime.now(dt.timezone.utc) > expires:
        # Commit the EXPIRED transition *before* raising: an exception inside a
        # write transaction would roll the state change back.
        with LOCK, db() as c:
            c.execute("UPDATE dl_requests SET status='EXPIRED', completed_at=? WHERE id=?",
                      (now(), request_id))
            _event_conn(c, request_id, user["id"], "CONSENT", "EXPIRED", "CONSENT_EXPIRED")
        raise ValueError("CONSENT_EXPIRED: the consent window has lapsed. Start again.")
    with LOCK, db() as c:
        if not consent:
            c.execute("UPDATE dl_requests SET status='DENIED', completed_at=? WHERE id=?",
                      (now(), request_id))
            _event_conn(c, request_id, user["id"], "CONSENT", "DENIED", "USER_DENIED")
            return {"status": "DENIED", "stored": False,
                    "message": "Consent withheld. Nothing was fetched and nothing was stored."}
        code = "code_" + secrets.token_urlsafe(18)
        c.execute("UPDATE dl_requests SET status='CONSENT_GIVEN', code=? WHERE id=?",
                  (code, request_id))
    _event(request_id, user["id"], "CONSENT", "GRANTED")
    return {"status": "CONSENT_GIVEN", "code": code, "state": row["state"],
            "redirect_uri": row["redirect_uri"], "provided_name": provided_name.strip(),
            "message": "Consent granted. The authorization code is valid for one exchange only."}


def _simulated_artefact(holder_name: str, *, seed_dob: Optional[str] = None,
                        seed: str = "") -> Dict[str, Any]:
    """Stand-in for the artefact DigiLocker returns after a token exchange.

    `seed` is the account id: a real issuer reference is unique per person, so
    two accounts that happen to share a name must not collide here either.
    """
    digest = hashlib.sha256((holder_name + (seed_dob or "") + seed).encode()).hexdigest()
    year = 1975 + int(digest[:2], 16) % 30
    month = 1 + int(digest[2:4], 16) % 12
    day = 1 + int(digest[4:6], 16) % 28
    issuer_rng = int(digest[6:8], 16) % 100
    issuer = ("UIDAI" if issuer_rng < 60 else
              "Election Commission of India" if issuer_rng < 78 else
              "Income Tax Department")
    return {
        "name": holder_name,
        "dob": seed_dob or f"{year:04d}-{month:02d}-{day:02d}",
        "gender": ["F", "M", "X"][int(digest[8:10], 16) % 3],
        "photo_present": int(digest[10:11], 16) % 4 != 0,
        "address_present": int(digest[11:12], 16) % 3 != 0,
        "issuer": issuer,
        "issuer_ref": "XXXX" + digest[:4].upper(),
        "issued_on": f"{year + 18:04d}-{month:02d}-{day:02d}",
        "verified_by": "DigiLocker (simulated issuer response)",
    }


def exchange_code(request_id: str, code: str, state: str,
                  user: Optional[dict] = None) -> Dict[str, Any]:
    """Step 3-4: callback handling — exchange, validate, attest.

    All the failure modes the real integration must handle are enforced here:
    state mismatch, single-use code, consent expiry, issuer allow-list, artefact
    schema, one identity per account and one account per identity.
    """
    with db() as c:
        row = c.execute("SELECT * FROM dl_requests WHERE id=?", (request_id,)).fetchone()
    if not row:
        raise LookupError("Consent request not found.")

    def fail(code_: str, message: str) -> Dict[str, Any]:
        with LOCK, db() as c:
            c.execute("UPDATE dl_requests SET status='FAILED', completed_at=? WHERE id=?",
                      (now(), request_id))
        _event(request_id, row["user_id"], "CALLBACK", "REJECTED", code_, message)
        return {"ok": False, "verified": False, "reason_code": code_, "message": message}

    if state != row["state"]:
        return fail("STATE_MISMATCH", REJECTION_REASONS["STATE_MISMATCH"])
    if row["code_used"]:
        return fail("CODE_REPLAYED", REJECTION_REASONS["CODE_REPLAYED"])
    if not row["code"] or code != row["code"]:
        return fail("CODE_INVALID", REJECTION_REASONS["CODE_INVALID"])
    expires = _parse(row["expires_at"])
    if not expires or dt.datetime.now(dt.timezone.utc) > expires:
        return fail("CONSENT_EXPIRED", REJECTION_REASONS["CONSENT_EXPIRED"])

    with LOCK, db() as c:
        c.execute("UPDATE dl_requests SET code_used=1, status='CODE_EXCHANGED' WHERE id=?",
                  (request_id,))
    _event(request_id, row["user_id"], "CODE_EXCHANGED", "OK")

    holder = (user or {}).get("name") or "Account Holder"
    doc = _simulated_artefact(holder, seed=row["user_id"])
    doc["artefact_source"] = "simulated-partner-gateway"
    problems = validate_artefact(doc, consent_expires_at=row["expires_at"])
    if problems:
        code_, msg = problems[0]
        return fail(code_, msg)

    if identity_row(row["user_id"]):
        return fail("ALREADY_LINKED", REJECTION_REASONS["ALREADY_LINKED"])
    with db() as c:
        clash = c.execute(
            "SELECT user_id FROM dl_identities WHERE issuer_ref=? AND revoked_at IS NULL AND user_id!=?",
            (doc["issuer_ref"], row["user_id"])).fetchone()
    if clash:
        return fail("IDENTITY_IN_USE", REJECTION_REASONS["IDENTITY_IN_USE"])

    doc_json = json.dumps(doc, sort_keys=True, separators=(",", ":"))
    doc_sha = hashlib.sha256(doc_json.encode()).hexdigest()
    verified_at = dt.datetime.now(dt.timezone.utc)
    expires_on = (verified_at + dt.timedelta(days=365)).date().isoformat()
    artefact_id = "dlv_" + doc_sha[:18]
    with LOCK, db() as c:
        c.execute(
            "INSERT INTO dl_identities(user_id,request_id,name,dob,gender,issuer,issuer_ref,"
            "photo_present,address_present,verified_by,verified_at,expires_on,doc_json,doc_sha256,"
            "artefact_id,simulated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
            (row["user_id"], request_id, doc["name"], normalise_dob(doc["dob"]), doc["gender"],
             doc["issuer"], doc["issuer_ref"], int(bool(doc["photo_present"])),
             int(bool(doc["address_present"])), doc["verified_by"], _iso(verified_at),
             expires_on, doc_json, doc_sha, artefact_id),
        )
        c.execute("UPDATE dl_requests SET status='COMPLETED', completed_at=? WHERE id=?",
                  (now(), request_id))
        c.execute("UPDATE users SET digilocker_status='LINKED', digilocker_ref=? WHERE id=?",
                  (artefact_id, row["user_id"]))
    _event(request_id, row["user_id"], "ATTESTED", "LINKED", detail=f"{doc['issuer']} {doc['issuer_ref']}")
    return {"ok": True, "verified": True, "artefact_id": artefact_id, "expires_on": expires_on,
            "document": public_document(doc), "doc_sha256": doc_sha,
            "mode": SIMULATION["mode"], "simulated": True,
            "message": "Identity artefact verified against the issuer allow-list and sealed by hash."}


def public_document(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Holder-facing view — the issuer reference is masked, the photo is not shipped."""
    out = dict(doc)
    ref = str(out.get("issuer_ref", ""))
    out["issuer_ref_masked"] = (ref[:4] + "••••" + ref[-2:]) if len(ref) > 6 else "••••"
    out.pop("issuer_ref", None)
    out["photo_present"] = bool(out.get("photo_present"))
    out.pop("artefact_source", None)
    return out


# --------------------------------------------------------------------------
# read / revoke
# --------------------------------------------------------------------------

def identity_row(user_id: str) -> Optional[Dict[str, Any]]:
    with db() as c:
        row = c.execute("SELECT * FROM dl_identities WHERE user_id=? AND revoked_at IS NULL",
                        (user_id,)).fetchone()
    return dict(row) if row else None


def status(user: dict) -> Dict[str, Any]:
    row = identity_row(user["id"])
    with db() as c:
        pending = c.execute(
            "SELECT * FROM dl_requests WHERE user_id=? AND status IN "
            "('AWAITING_CONSENT','CONSENT_GIVEN','CODE_EXCHANGED') ORDER BY created_at DESC LIMIT 1",
            (user["id"],)).fetchone()
        last_event = c.execute(
            "SELECT * FROM dl_events WHERE user_id=? ORDER BY id DESC LIMIT 1", (user["id"],)
        ).fetchone()
    base = {
        "implementation": VERSION, "implemented": True,
        "mode": SIMULATION["mode"], "simulated": True,
        "real_world": REAL_WORLD, "disclosure": SIMULATION["disclosure"],
        "status_labels": STATUS_LABELS, "quota": consent_quota(user["id"]),
    }
    if row:
        expires_on = row["expires_on"]
        expired = dt.date.fromisoformat(expires_on) < dt.date.today()
        return {**base, "status": "EXPIRED" if expired else "LINKED",
                "label": STATUS_LABELS["EXPIRED" if expired else "LINKED"],
                "linked": not expired, "verified": not expired,
                "artefact_id": row["artefact_id"], "verified_at": row["verified_at"],
                "expires_on": expires_on, "issuer": row["issuer"],
                "issuer_ref_masked": public_document({"issuer_ref": row["issuer_ref"]})["issuer_ref_masked"],
                "document": public_document(json.loads(row["doc_json"])),
                "doc_sha256": row["doc_sha256"], "simulated": bool(row["simulated"]),
                "pending": None,
                "last_event": dict(last_event) if last_event else None}
    return {**base, "status": "NOT_LINKED", "label": STATUS_LABELS["NOT_LINKED"],
            "linked": False, "verified": False, "document": None,
            "pending": ({"request_id": pending["id"], "status": pending["status"],
                         "expires_at": pending["expires_at"],
                         "scope": pending["scope"], "purpose": pending["purpose"]}
                        if pending else None),
            "last_event": dict(last_event) if last_event else None}


def revoke(user: dict, reason: str = "") -> Dict[str, Any]:
    with LOCK, db() as c:
        row = c.execute("SELECT * FROM dl_identities WHERE user_id=? AND revoked_at IS NULL",
                        (user["id"],)).fetchone()
        if not row:
            raise ValueError("There is no active DigiLocker verification to withdraw.")
        c.execute("UPDATE dl_identities SET revoked_at=?, revoke_reason=? WHERE id=?",
                  (now(), str(reason)[:300], row["id"]))
        c.execute("UPDATE users SET digilocker_status='NOT_LINKED', digilocker_ref=NULL WHERE id=?",
                  (user["id"],))
    _event(row["request_id"], user["id"], "REVOKED", "REVOKED", detail=str(reason)[:200])
    return {"ok": True, "status": "NOT_LINKED", "message": "Verification withdrawn and artefact revoked."}


def verify_artefact(artefact_id: str) -> Dict[str, Any]:
    """Public integrity check a court clerk can run against a quoted artefact id."""
    with db() as c:
        row = c.execute("SELECT * FROM dl_identities WHERE artefact_id=? ORDER BY id DESC LIMIT 1",
                        (artefact_id,)).fetchone()
    if not row:
        return {"found": False, "valid": False, "message": "No such artefact in this registry."}
    doc = json.loads(row["doc_json"])
    recomputed = hashlib.sha256(json.dumps(doc, sort_keys=True,
                                          separators=(",", ":")).encode()).hexdigest()
    intact = hmac.compare_digest(recomputed, row["doc_sha256"])
    revoked = bool(row["revoked_at"])
    expired = dt.date.fromisoformat(row["expires_on"]) < dt.date.today()
    return {
        "found": True, "valid": intact and not revoked and not expired,
        "artefact_id": row["artefact_id"], "integrity": "INTACT" if intact else "TAMPERED",
        "state": "REVOKED" if revoked else ("EXPIRED" if expired else "ACTIVE"),
        "issuer": row["issuer"], "issuer_ref_masked":
            public_document({"issuer_ref": row["issuer_ref"]})["issuer_ref_masked"],
        "verified_at": row["verified_at"], "expires_on": row["expires_on"],
        "doc_sha256": row["doc_sha256"], "simulated": bool(row["simulated"]),
        "mode": SIMULATION["mode"],
    }


def events(user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    with db() as c:
        rows = c.execute("SELECT * FROM dl_events WHERE user_id=? ORDER BY id DESC LIMIT ?",
                         (user_id, limit)).fetchall()
    return [dict(r) for r in rows]


def stats() -> Dict[str, Any]:
    with db() as c:
        q = lambda sql, *a: c.execute(sql, a).fetchone()[0]  # noqa: E731
        return {
            "consent_requests": q("SELECT COUNT(*) FROM dl_requests"),
            "verified": q("SELECT COUNT(*) FROM dl_identities WHERE revoked_at IS NULL"),
            "revoked": q("SELECT COUNT(*) FROM dl_identities WHERE revoked_at IS NOT NULL"),
            "failed": q("SELECT COUNT(*) FROM dl_requests WHERE status='FAILED'"),
            "denied": q("SELECT COUNT(*) FROM dl_requests WHERE status='DENIED'"),
            "expired": q("SELECT COUNT(*) FROM dl_requests WHERE status='EXPIRED'"),
        }


DL_CLIENT_ID = os.environ.get("NYAYA_DL_CLIENT_ID", "NYAYA-RAC-DEMO-CLIENT")
DL_REDIRECT_URI = os.environ.get("NYAYA_DL_REDIRECT_URI", "http://localhost:8000/api/digilocker/callback")
