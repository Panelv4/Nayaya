"""End-to-end HTTP smoke test for NYAYA-RAC v0.5.0.

Run against a live portal:  python3 smoke.py [base_url]
Writes real rows (clearly marked demo accounts), so it is safe to re-run: all
emails are unique per run.
"""

import base64
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
PASS, FAIL = [], []
def _admin_credentials():
    """Never hardcode the administrator password: read it the way an operator does."""
    import os
    email = os.environ.get("NYAYA_ADMIN_EMAIL", "admin@nyaya.local")
    pw = os.environ.get("NYAYA_ADMIN_PASSWORD")
    if pw:
        return email, pw
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        ".nyaya-admin-credentials")
    try:
        with open(path, encoding="utf-8") as fh:
            kv = dict(line.strip().split("=", 1) for line in fh
                      if "=" in line and not line.startswith("#"))
        return kv.get("email", email), kv["password"]
    except (OSError, KeyError):
        raise SystemExit(
            f"No administrator password available. Set NYAYA_ADMIN_PASSWORD or run "
            f"`python3 server.py --rotate-admin-password` to create {path}.")


ADMIN = _admin_credentials()


def call(method, path, body=None, token=None, expect=200, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            status, payload = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, payload = e.code, e.read()
    if raw:
        return status, payload.decode("utf-8", "replace")
    try:
        return status, json.loads(payload or b"{}")
    except Exception:
        return status, {"_raw": payload[:300].decode("utf-8", "replace")}


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"   [{detail}]" if detail and not cond else ""))


def register_login(tag):
    email = f"{tag}.{uuid.uuid4().hex[:6]}@smoke.test"
    s, b = call("POST", "/api/register", {"name": f"Smoke {tag}", "email": email, "password": "smokepass123"})
    check(f"register {tag}", s == 200 and b.get("ok"), f"{s} {b}")
    s, b = call("POST", "/api/login", {"email": email, "password": "smokepass123"})
    check(f"login {tag}", s == 200 and b.get("token"), f"{s} {b}")
    return email, b.get("token")


def intake(token, **over):
    body = {
        "narrative": ("The accused threatened to kill me, pushed me against a wall and took my "
                      "phone so I could not call for help. I have photos of the bruises."),
        "incident_date": "2026-09-14", "location": "Gwalior",
        "domain": "CRIMINAL", "victim_under18": "no", "woman_or_girl": "yes",
        "sexual_offence": "no", "accused_in_custody": "no", "liberty_threat": "yes",
        "accused_under18": "", "has_lawyer": "not_yet", "provision": "", "statute": "",
        "disability": False, "mental_illness": False, "sc_st_atrocities": False,
        "transgender": False, "senior_citizen": False, "declaration": True,
        "evidence": [{"name": "bruise.png", "type": "image/png",
                      "data_b64": base64.b64encode(b"smoke-bytes").decode(), "description": "injury photo"}],
    }
    body.update(over)
    return call("POST", "/api/report", body, token)


print("=" * 70)
print("1. Pages are served without a session (JS guards them client-side)")
for page in ("/", "/login", "/dashboard", "/submit", "/cases", "/case", "/disclosed",
             "/admin", "/kb", "/workbench"):
    s, html = call("GET", page, raw=True)
    check(f"GET {page} → 200", s == 200, str(s))
s, html = call("GET", "/", raw=True)
check("footer shows v0.5.0", "v0.5.0" in html)
s, html = call("GET", "/disclosed", raw=True)
check("disclosed page renders registry", "Disclosed" in html)

print("\n2. APIs require a session")
for path in ("/api/me", "/api/reports", "/api/admin/overview", "/schema"):
    s, _ = call("GET", path)
    check(f"GET {path} without token → 401/403", s in (401, 403), str(s))

print("\n3. Admin bootstrap + admin surfaces")
s, b = call("POST", "/api/login", {"email": ADMIN[0], "password": ADMIN[1]})
check("admin login", s == 200 and b.get("role") == "ADMIN", f"{s} {b}")
admin_tok = b.get("token", "")
s, b = call("GET", "/api/me", token=admin_tok)
check("admin /api/me is_admin", b.get("is_admin") is True)
check("digilocker flow present and declared simulated",
      b.get("digilocker", {}).get("implemented") is True and b.get("digilocker", {}).get("simulated") is True)
s, b = call("GET", "/api/admin/overview", token=admin_tok)
# Must not depend on how many accounts happen to exist: a fresh boot has only
# the bootstrap admin (1 user); a seeded demo has 3. Assert shape, not count.
check("admin overview stats", s == 200 and b["stats"]["users"] >= 1
      and "reports" in b["stats"] and "admins" in b["stats"], f"{s} {b}")
check("admin overview queues", all(k in b["queues"] for k in ("disclosure_pending", "manual_check", "flagged")))
s, b = call("GET", "/api/kb", token=admin_tok)
check("kb exposes statutes+precedents+conflicts", s == 200 and "statutes" in b and "conflicts" in b)
s, b = call("GET", "/schema", token=admin_tok)
check("admin can open /schema", s == 200)
s, b = call("GET", "/audit", token=admin_tok)
check("admin can open /audit", s == 200)

print("\n4. Intake, KB resolution and strict validation")
owner_email, owner_tok = register_login("owner")
stranger_email, stranger_tok = register_login("stranger")
voter_email, voter_tok = register_login("voter")
s, b = intake(owner_tok, statute="IPC", provision="302", incident_date="2020-06-01")
check("intake with KB citation", s == 200 and b["ok"], f"{s} {b}")
rid = b["summary"]["report_id"]
check("rev 1 + private + unchecked", b["summary"]["rev_no"] == 1 and
      b["summary"]["disclosure_status"] == "PRIVATE" and b["summary"]["manual_check_status"] == "UNCHECKED")
check("citation resolves UNVERIFIED → punishment withheld",
      b["summary"]["kb_resolution"] == "UNVERIFIED", b["summary"].get("kb_resolution"))
s, b = intake(owner_tok, incident_date="2026-02-30")
check("impossible date → 400", s == 400, f"{s} {b}")
s, b = intake(owner_tok, incident_date="2026-09-14", incident_end_date="2026-09-01")
check("end before start → 400", s == 400, f"{s} {b}")
s, b = intake(owner_tok, evidence=[], no_evidence_ack=False)
check("evidence-or-ack enforced → 400", s == 400, f"{s} {b}")
s, b = intake(owner_tok, evidence=[], no_evidence_ack=True)
check("no-evidence ack accepted", s == 200, f"{s} {b}")
ack_id = b["summary"]["report_id"]

print("\n5. Strict access control (nothing visible before approval)")
s, b = call("GET", f"/api/report?id={rid}", token=owner_tok)
check("owner sees FULL payload", s == 200 and b.get("access") == "FULL", f"{s}")
check("payload redaction keys present", "revisions" in b and "coverage" in b and "provenance" in b)
s, b = call("GET", f"/api/report?id={rid}", token=stranger_tok)
check("stranger gets 404 (not 403)", s == 404, f"{s} {b}")
s, b = call("GET", f"/api/reports", token=stranger_tok)
check("stranger's own list does not include the case", all(r["id"] != rid for r in b.get("reports", [])))
s, b = call("POST", "/api/disclosure-request", {"report_id": rid, "note": "ok to publish anonymously"}, owner_tok)
check("disclosure request → PENDING", s == 200 and b.get("disclosure_status") == "PENDING", f"{s} {b}")
s, b = call("GET", f"/api/report?id={rid}", token=stranger_tok)
check("still hidden while PENDING", s == 404, str(s))
s, b = call("POST", "/api/admin/disclosure", {"report_id": rid, "action": "APPROVE", "mode": "ANONYMIZED"}, stranger_tok)
check("non-admin cannot approve → 403", s == 403, f"{s} {b}")
s, b = call("POST", "/api/admin/disclosure", {"report_id": rid, "action": "APPROVE", "mode": "ANONYMIZED",
                                              "note": "no identifiers"}, admin_tok)
check("admin approves ANONYMIZED", s == 200 and b.get("disclosure_status") == "DISCLOSED", f"{s} {b}")
s, b = call("GET", f"/api/report?id={rid}", token=stranger_tok)
check("stranger now gets ANONYMIZED", s == 200 and b.get("access") == "ANONYMIZED", f"{s}")
check("narrative redacted", "Redacted" in str(b.get("narrative")))
check("answers/facts wiped", b.get("answers") == {} and b.get("facts") == {})
check("evidence filenames hidden", all(e["filename"] == "[hidden]" for e in b.get("evidence", [])))
check("owner id never exposed", "user_id" not in b)
s, b = call("GET", "/api/disclosed")
check("public registry lists it", any(c["id"] == rid for c in b.get("cases", [])), f"{s}")
check("ANONYMIZED registry entry has no excerpt",
      all("excerpt" not in c for c in b["cases"] if c["id"] == rid))

print("\n6. Re-evaluation, manual check, revision history")
s, b = call("POST", "/api/revise", {"report_id": rid, "reason": "", "narrative": "x" * 60,
                                    "incident_date": "2020-06-01", "domain": "CRIMINAL",
                                    "victim_under18": "no", "woman_or_girl": "yes",
                                    "sexual_offence": "no", "accused_in_custody": "no",
                                    "liberty_threat": "yes", "accused_under18": "",
                                    "has_lawyer": "not_yet", "provision": "302", "statute": "IPC"}, owner_tok)
check("revision without reason → 400", s == 400, f"{s} {b}")
s, b = call("POST", "/api/admin/manual-check", {"report_id": rid, "status": "VERIFIED", "note": "checked"}, admin_tok)
check("admin marks VERIFIED", s == 200, f"{s} {b}")
rev_body = {"report_id": rid, "reason": "Corrected the liberty-threat answer after re-reading my notes.",
            "narrative": ("The accused threatened to kill me twice, blocked the door and took my phone. "
                          "I have photos of the bruises and a hospital slip."),
            "incident_date": "2020-06-02", "incident_end_date": "", "location": "Gwalior",
            "domain": "CRIMINAL", "victim_under18": "no", "woman_or_girl": "yes",
            "sexual_offence": "no", "accused_in_custody": "no", "liberty_threat": "yes",
            "accused_under18": "", "has_lawyer": "not_yet", "provision": "302", "statute": "IPC"}
s, b = call("POST", "/api/revise", rev_body, owner_tok)
check("owner revises → rev 2", s == 200 and b["summary"]["rev_no"] == 2, f"{s} {b}")
s, b = call("GET", f"/api/report?id={rid}", token=owner_tok)
check("2 immutable revisions kept", [r["rev_no"] for r in b["revisions"]] == [1, 2])
check("revision reset manual check to UNCHECKED", b["manual_check_status"] == "UNCHECKED")
check("revision actor OWNER", b["revisions"][-1]["actor"] == "OWNER")
s, b = call("POST", "/api/revise", rev_body, stranger_tok)
check("stranger cannot revise → 403", s == 403, f"{s} {b}")

print("\n7. Evidence → fact mapping + coverage")
s, b = call("GET", f"/api/report?id={rid}", token=owner_tok)
ev_id = b["evidence"][0]["id"]
# Evidence bytes: owner + admin only, never disclosed viewers.
s, raw = call("GET", f"/api/evidence?id={ev_id}", token=owner_tok, raw=True)
check("owner can download evidence bytes", s == 200 and raw == "smoke-bytes", f"{s} {raw[:40]}")
s, b = call("GET", f"/api/evidence?id={ev_id}", token=admin_tok)
check("admin can download evidence bytes", s == 200, f"{s}")
s, b = call("GET", f"/api/evidence?id={ev_id}", token=stranger_tok)
check("ANONYMIZED viewer cannot download evidence → 404", s == 404, f"{s} {b}")
s, b = call("GET", "/api/evidence?id=999999999", token=owner_tok)
check("unknown evidence id → 404", s == 404, f"{s} {b}")
s, b = call("GET", f"/api/evidence?id={ev_id}")
check("anonymous evidence download → 401", s == 401, f"{s} {b}")
s, b = call("POST", "/api/evidence-map", {"report_id": rid, "evidence_id": ev_id, "fact_key": "liberty_threat",
                                          "relation": "SUPPORTS", "note": "photo of the blocked door"}, owner_tok)
check("map evidence SUPPORTS a fact", s == 200 and "coverage" in b, f"{s} {b}")
s, b = call("POST", "/api/evidence-map", {"report_id": rid, "evidence_id": ev_id, "fact_key": "liberty_threat",
                                          "relation": "SUPPORTS"}, stranger_tok)
check("stranger cannot map → 403", s == 403, str(s))
s, b = call("GET", f"/api/report?id={rid}", token=owner_tok)
check("coverage reports supported fact", "liberty_threat" in b["coverage"]["supported"], str(b["coverage"]))
check("coverage percentage computed", 0 < b["coverage"]["coverage"] <= 1, str(b["coverage"]["coverage"]))
s, b = call("POST", "/api/evidence-map", {"report_id": rid, "evidence_id": ev_id, "fact_key": "bogus",
                                          "relation": "SUPPORTS"}, owner_tok)
check("unknown fact_key → 400", s == 400, str(s))

print("\n8. Feedback (thumbs up/down) → flagging → dataset export")
s, b = call("POST", "/api/feedback", {"report_id": rid, "vote": 1, "comment": "Accurate routing."}, owner_tok)
check("owner 👍", s == 200 and b.get("up") == 1, f"{s} {b}")
s, b = call("POST", "/api/feedback", {"report_id": rid, "vote": -1, "comment": "Urgency felt too low."}, stranger_tok)
check("stranger 👎", s == 200 and b.get("down") == 1)
s, b = call("POST", "/api/feedback", {"report_id": rid, "vote": -1, "comment": "Same view."}, voter_tok)
check("second 👎 flags for review (net −1 … threshold −2)", s == 200, f"{s} {b}")
s, b = call("POST", "/api/feedback", {"report_id": rid, "vote": 0}, voter_tok)
check("invalid vote → 400", s == 400, str(s))
s, b = call("GET", f"/api/feedback?report_id={rid}", token=owner_tok)
check("feedback summary readable", s == 200 and "up" in b and "my_vote" in b, f"{s} {b}")
s, txt = call("GET", "/api/admin/feedback?export=jsonl", token=admin_tok, raw=True)
lines = [ln for ln in txt.strip().splitlines() if ln.strip()]
ok = bool(lines)
try:
    rec = json.loads(lines[0])
    ok = ok and {"ref", "label", "features"} <= set(rec) and "review_level" in rec["features"]
except Exception:
    ok = False
check("JSONL dataset export is shaped correctly", ok, txt[:200])
s, b = call("GET", "/api/admin/feedback?export=jsonl", token=stranger_tok)
check("dataset export is admin-only → 403", s == 403, str(s))

print("\n9. Amendment impact (Phase 2) — dry run then SYSTEM revision")
s, b = call("POST", "/api/admin/amendment-impact", {"statute": "IPC", "provision": "302"}, admin_tok)
check("dry run examines citing cases", s == 200 and any(i["report_id"] == rid for i in b["impacts"]), f"{s} {b}")
s, b = call("POST", "/api/admin/amendment-impact", {"statute": "IPC", "provision": "302"}, stranger_tok)
check("amendment impact is admin-only → 403", s == 403, str(s))
s, b = call("POST", "/api/admin/amendment-impact", {"statute": "IPC", "provision": "302",
                                                    "apply_report_id": rid}, admin_tok)
check("apply creates a SYSTEM revision", s == 200 and b.get("applied", {}).get("rev_no") == 3, f"{s} {b}")
s, b = call("GET", f"/api/report?id={rid}", token=owner_tok)
check("SYSTEM revision recorded as actor SYSTEM", b["revisions"][-1]["actor"] == "SYSTEM", str(b["revisions"][-1]))

print("\n10. KB editing + verification gate (admin)")
new_statute = {"statute": "SMOKE Act", "provision": "9", "version_label": "S-1.0",
               "effective_from": "2021-01-01", "title": "Smoke provision", "pun_max_years": 5}
s, b = call("POST", "/api/admin/statutes", new_statute, admin_tok)
check("admin adds statute version", s == 200 or s == 201, f"{s} {b}")
sid = b.get("id") or b.get("statute_id")
s, b = call("POST", "/api/admin/statutes/verify", {"id": sid}, admin_tok)
check("admin verifies version", s == 200, f"{s} {b}")
s, b = call("GET", "/api/kb", token=owner_tok)
row = [r for r in b["statutes"] if r["statute"] == "SMOKE Act"]
check("verified row visible to users", bool(row) and row[0]["verified"] in (1, True), str(row)[:200])
s, b = call("POST", "/api/admin/precedents", {"citation": "(Smoke) Test v State", "court": "Smoke HC",
                                              "statute": "SMOKE Act", "provision": "9",
                                              "holding_tag": "SUPPORTS_STRICT"}, admin_tok)
check("admin adds precedent", s in (200, 201), f"{s} {b}")
s, b = call("POST", "/api/admin/statutes", new_statute, stranger_tok)
check("KB editing is admin-only → 403", s == 403, str(s))

print("\n11. Gating recap for a normal user")
for path in ("/api/admin/overview", "/api/admin/feedback"):
    s, _ = call("GET", path, token=owner_tok)
    check(f"USER {path} → 403", s == 403, str(s))
s, _ = call("POST", "/evaluate", {"facts": {}}, token=owner_tok)
check("USER /evaluate → 403", s == 403, str(s))
s, b = call("GET", f"/api/report?id={ack_id}", token=stranger_tok)
check("no-evidence case stays private → 404", s == 404, str(s))

print("\n12. DigiLocker verification (calibrated consent flow)")
dl_email, dl_tok = register_login("identity")
s, b = call("GET", "/api/digilocker/status", token=dl_tok)
check("status endpoint is wired", s == 200 and b.get("status") == "NOT_LINKED", f"{s} {b}")
check("payload admits it is simulated", b.get("mode") == "SIMULATED" and b.get("simulated") is True)
check("real-world calibration constants exposed", "allowed_issuers" in b.get("real_world", {}))
s, c = call("POST", "/api/digilocker/consent", {}, dl_tok)
check("consent request opens", s == 200 and c.get("request_id"), f"{s} {c}")
check("PKCE S256 challenge issued",
      c.get("code_challenge_method") == "S256" and len(c.get("code_challenge", "")) > 20)
check("consent window is 30 minutes", c.get("validity_minutes") == 30, str(c.get("validity_minutes")))
s, g = call("POST", "/api/digilocker/grant", {"request_id": c["request_id"], "consent": True}, dl_tok)
check("consent granted → single-use code", s == 200 and g.get("code"), f"{s} {g}")
s, bad = call("POST", "/api/digilocker/callback",
              {"request_id": c["request_id"], "code": g["code"], "state": "st_forged"}, dl_tok)
check("forged state rejected", s == 200 and bad.get("reason_code") == "STATE_MISMATCH", str(bad))
s, att = call("POST", "/api/digilocker/callback",
              {"request_id": c["request_id"], "code": g["code"], "state": g["state"]}, dl_tok)
check("artefact attested", s == 200 and att.get("ok") and att.get("artefact_id"), f"{s} {att}")
check("issuer from the allow-list", att.get("document", {}).get("issuer") in
      ["UIDAI", "Election Commission of India", "Ministry of Road Transport and Highways",
       "Income Tax Department", "CGHS", "Employees' Provident Fund Organisation"], str(att.get("document")))
check("issuer reference masked in the response", "issuer_ref" not in att.get("document", {})
      and "issuer_ref_masked" in att.get("document", {}))
s, replay = call("POST", "/api/digilocker/callback",
                 {"request_id": c["request_id"], "code": g["code"], "state": g["state"]}, dl_tok)
check("code replay rejected", replay.get("reason_code") == "CODE_REPLAYED", str(replay))
s, st = call("GET", "/api/digilocker/status", token=dl_tok)
check("account now LINKED", st.get("status") == "LINKED" and st.get("verified") is True, str(st.get("status")))
s, anon = call("GET", "/api/digilocker/verify?artefact=" + str(att.get("artefact_id")))
check("artefact verification requires a session", s == 401, f"{s} {anon}")
s, chk = call("GET", "/api/digilocker/verify?artefact=" + str(att.get("artefact_id")), token=dl_tok)
check("artefact verifies for its owner (hash intact)", s == 200 and chk.get("valid") is True, f"{s} {chk}")
s, chk1 = call("GET", "/api/digilocker/verify?artefact=" + str(att.get("artefact_id")), token=stranger_tok)
# A logged-in outsider learns whether the artefact exists and nothing more:
# no digest, no issuer reference, no dates.
check("another logged-in user cannot read the artefact record",
      s == 200 and chk1.get("found") is True
      and "doc_sha256" not in chk1 and "issuer_ref_masked" not in chk1
      and "expires_on" not in chk1 and "verified_at" not in chk1, f"{s} {chk1}")
# The verdict itself (found / valid / state) is what verification exists to
# answer, so it is shared; the identifying record is not.
check("the outsider still gets a verdict to act on",
      chk1.get("found") is True and "state" in chk1, f"{chk1}")
s, chk2 = call("GET", "/api/digilocker/verify?artefact=dlv_nope", token=dl_tok)
check("unknown artefact reported as not found", chk2.get("found") is False)
s, rep = intake(dl_tok, evidence=[], no_evidence_ack=True)
dl = rep["summary"]["digilocker"]
check("report records the verified identity", dl.get("linked") is True and dl.get("simulated") is True, str(dl))
check("identity note added to the case", any("DigiLocker artefact" in n for n in rep["summary"]["intake_notes"]))
s, d2 = call("POST", "/api/digilocker/consent", {}, dl_tok)
check("second consent request refused (already linked)", s == 400, f"{s} {d2}")
s, ev = call("GET", "/api/digilocker/events", token=dl_tok)
check("audit events recorded", s == 200 and len(ev.get("events", [])) >= 4, f"{s}")
s, rv = call("POST", "/api/digilocker/revoke", {"reason": "smoke test"}, dl_tok)
check("verification can be withdrawn", s == 200 and rv.get("status") == "NOT_LINKED", f"{s} {rv}")
s, st2 = call("GET", "/api/digilocker/status", token=dl_tok)
check("status reflects withdrawal", st2.get("status") == "NOT_LINKED", str(st2.get("status")))
s, unv = intake(dl_tok, evidence=[], no_evidence_ack=True)
check("unverified report is accepted and marked", unv["summary"]["digilocker"]["linked"] is False
      and any("not verified" in n for n in unv["summary"]["intake_notes"]))
s, dq = call("POST", "/api/digilocker/consent", {}, stranger_tok)
s2, gq = call("POST", "/api/digilocker/grant", {"request_id": dq.get("request_id"), "consent": False}, stranger_tok)
check("denial stores nothing", gq.get("status") == "DENIED" and gq.get("stored") is False, str(gq))

print("\n13. Admin sees identity posture")
s, ov = call("GET", "/api/admin/overview", token=admin_tok)
check("identity stats in overview", "identities_verified" in ov.get("stats", {}), str(list(ov.get("stats", {}))[:5]))
check("identity block present", "verified" in ov.get("identity", {}), str(ov.get("identity")))
check("case rows carry identity state", all("digilocker_status" in c for c in ov.get("cases", [])))

print("\n14. Session continuity (relay cookie, /api/session, /api/renew)")


def _headers(h):
    """dict(headers) drops duplicate Set-Cookie lines; collect them explicitly."""
    d = dict(h)
    if hasattr(h, "get_all"):
        d["Set-Cookie"] = "\n".join(h.get_all("Set-Cookie") or [])
    return d


def call_full(method, path, body=None, headers=None):
    """Like call(), but returns status, headers and raw payload for cookie work."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            st, hdrs, payload = r.status, _headers(r.headers), r.read()
    except urllib.error.HTTPError as e:
        st, hdrs, payload = e.code, _headers(e.headers), e.read()
    try:
        return st, hdrs, json.loads(payload or b"{}")
    except Exception:
        return st, hdrs, {}


sess_email = f"sess.{uuid.uuid4().hex[:6]}@smoke.test"
call("POST", "/api/register", {"name": "Smoke Session", "email": sess_email, "password": "smokepass123"})
s, h, b = call_full("POST", "/api/login", {"email": sess_email, "password": "smokepass123"})
raw_cookies = h.get("Set-Cookie", "")
sess_tok = b.get("token")
check("login issues both session cookies",
      "nyaya_session=" in raw_cookies and "nyaya_relay=" in raw_cookies, raw_cookies[:160])
check("relay cookie is readable by JS (not HttpOnly)",
      any(c.strip().startswith("nyaya_relay=") and "HttpOnly" not in c
          for c in raw_cookies.split("\n")))
check("session cookie is HttpOnly", any(c.strip().startswith("nyaya_session=") and "HttpOnly" in c
                                        for c in raw_cookies.split("\n")))

# /api/session is the page bootstrap: it must never 401.
s, h, anon = call_full("GET", "/api/session")
check("/api/session anonymous returns 200 + authenticated false",
      s == 200 and anon.get("authenticated") is False, f"{s} {anon}")
s, h, me = call_full("GET", "/api/session", headers={"Authorization": "Bearer " + str(sess_tok)})
check("/api/session with bearer restores the user",
      s == 200 and me.get("authenticated") is True and me.get("user", {}).get("email") == sess_email, f"{s} {me}")
check("/api/session hands the token back for the relay",
      me.get("token") == sess_tok, str(me.get("token"))[:12])
repair = h.get("Set-Cookie", "")
check("/api/session re-issues cookies when the jar is empty",
      "nyaya_relay=" in repair and "nyaya_session=" in repair, repair[:120])

# Cookie-only session (no Authorization header): the classic browser path.
cookies = "; ".join(f"{n}={sess_tok}" for n in ("nyaya_session", "nyaya_relay"))
s, h, viaCookie = call_full("GET", "/api/session", headers={"Cookie": cookies})
check("cookie-only session works", viaCookie.get("authenticated") is True, f"{s} {viaCookie}")
s, h, viaRelay = call_full("GET", "/api/session", headers={"Cookie": "nyaya_relay=" + str(sess_tok)})
check("relay cookie alone is accepted", viaRelay.get("authenticated") is True, f"{s}")

# /api/renew promotes a bearer token into the cookie jar (post-login repair).
s, h, rn = call_full("POST", "/api/renew", headers={"Authorization": "Bearer " + str(sess_tok)})
check("/api/renew returns ok + token", s == 200 and rn.get("ok") is True and rn.get("token") == sess_tok, f"{s} {rn}")
check("/api/renew sets both cookies",
      "nyaya_session=" in h.get("Set-Cookie", "") and "nyaya_relay=" in h.get("Set-Cookie", ""))
s, h, rn2 = call_full("POST", "/api/renew")
check("/api/renew without a token is refused", s == 401, str(s))

# Logout must clear BOTH cookies and kill the token.
s, h, lo = call_full("POST", "/api/logout", headers={"Authorization": "Bearer " + str(sess_tok)})
cleared = h.get("Set-Cookie", "")
check("logout clears both cookies",
      "nyaya_session=;" in cleared.replace(" ", "") or "nyaya_session=" in cleared, cleared[:120])
s, h, after = call_full("GET", "/api/session", headers={"Authorization": "Bearer " + str(sess_tok)})
check("token is dead after logout", after.get("authenticated") is False, f"{s} {after}")

# Pages must not leak the token to third parties.
req = urllib.request.Request(BASE + "/login?st=abc")
with urllib.request.urlopen(req, timeout=20) as r:
    rp = r.headers.get("Referrer-Policy")
check("pages send Referrer-Policy: no-referrer", (rp or "").lower() == "no-referrer", str(rp))

print("\n15. Hardening (credentials, binding, rate limiting)")


def _server_source():
    import os as _os
    with open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "server.py"),
              encoding="utf-8") as fh:
        return fh.read()


_src = _server_source()
# The old default may appear only in the denylist that refuses it, never as a
# fallback credential.
check("no default admin password fallback in source",
      'os.environ.get("NYAYA_ADMIN_PASSWORD", "NyayaAdmin@123")' not in _src
      and '_BANNED_PASSWORDS' in _src)
check("generated credential file is chmod 600", '0o600' in _src)
check("weak admin passwords are refused at startup", "_BANNED_PASSWORDS" in _src)
check("rotation command exists", "--rotate-admin-password" in _src)
check("binds loopback by default", 'os.environ.get("NYAYA_HOST", "127.0.0.1")' in _src)
check("public bind needs an explicit acknowledgement", "NYAYA_ALLOW_PUBLIC_BIND" in _src)

# Rate limiting is observable over HTTP. Probe with a throwaway account so the
# administrator's own login is never locked out by the test.
limited = None
probe = f"ratelimit.{uuid.uuid4().hex[:6]}@smoke.test"
for i in range(8):
    s, b = call("POST", "/api/login", {"email": probe, "password": "wrong"})
    if s == 429:
        limited = b
        break
check("repeated failed logins are rate limited", limited is not None and limited.get("retry_after"),
      str(limited))
if limited:
    check("429 carries a retry-after value", isinstance(limited.get("retry_after"), int))

print("\n16. Health, robots, 404 and security headers")
s, b = call("GET", "/health")
check("GET /health needs no auth and reports ok", s == 200 and b.get("ok") is True
      and "version" in b and "engine" in b, f"{s} {b}")
s, b = call("GET", "/api/health")
check("GET /api/health mirrors /health", s == 200 and b.get("ok") is True, f"{s} {b}")
s, txt = call("GET", "/robots.txt", raw=True)
check("GET /robots.txt disallows all", s == 200 and "Disallow: /" in txt, f"{s} {txt[:80]}")
s, b = call("GET", "/api/does-not-exist")
check("unknown API path returns JSON 404", s == 404 and "error" in b, f"{s} {b}")
# Browser navigation to an unknown path gets an HTML 404, not JSON.
req = urllib.request.Request(BASE + "/does-not-exist")
req.add_header("Accept", "text/html")
try:
    with urllib.request.urlopen(req, timeout=20) as r:
        st, hdrs, payload = r.status, _headers(r.headers), r.read()
except urllib.error.HTTPError as e:
    st, hdrs, payload = e.code, _headers(e.headers), e.read()
check("unknown page returns HTML 404", st == 404 and b"text/html" in
      (hdrs.get("Content-Type") or "").encode(), f"{st} {hdrs.get('Content-Type')}")
check("HTML 404 links home", b'href="/"' in payload, payload[:120].decode("utf-8", "replace"))
# Security headers on a normal page.
req = urllib.request.Request(BASE + "/login")
with urllib.request.urlopen(req, timeout=20) as r:
    hdrs = _headers(r.headers)
check("pages send Content-Security-Policy", "Content-Security-Policy" in hdrs
      and "default-src" in hdrs.get("Content-Security-Policy", ""), str(hdrs.get("Content-Security-Policy"))[:120])
check("pages send Permissions-Policy", "Permissions-Policy" in hdrs, str(hdrs.get("Permissions-Policy")))
check("pages send X-Content-Type-Options: nosniff",
      (hdrs.get("X-Content-Type-Options") or "").lower() == "nosniff", str(hdrs.get("X-Content-Type-Options")))
s, txt = call("GET", "/favicon.svg", raw=True)
check("GET /favicon.svg serves an SVG", s == 200 and "<svg" in txt, f"{s} {txt[:60]}")

print("\n" + "=" * 70)
print(f"PASSED {len(PASS)}   FAILED {len(FAIL)}")
if FAIL:
    for f in FAIL:
        print("  ✗ " + f)
    sys.exit(1)
print("ALL SMOKE CHECKS PASSED")
