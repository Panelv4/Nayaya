"""seed.py — create a demo database so a fresh clone has something to look at.

The repository does not ship a database: the development one contained real
people's statements, contact details and evidence, and publishing it would have
been indefensible. This script builds an equivalent-shaped database from
obviously fictional accounts.

    python3 seed.py            # creates nyaya-rac.sqlite3 if absent, then seeds
    python3 seed.py --force    # recreate the demo database from scratch

Every account is @example.invalid (a reserved domain that can never receive
mail), every password is printed on screen, and every case is invented.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("NYAYA_DB", os.path.join(HERE, "nyaya-rac.sqlite3"))

DEMO_PASSWORD = "demo-password-1234"
DEMO_ACCOUNTS = [
    ("Demonstration Administrator", "admin@example.invalid", "ADMIN"),
    ("Asha (demo filer)", "asha@example.invalid", "USER"),
    ("Ravi (demo filer)", "ravi@example.invalid", "USER"),
]

DEMO_CASES = [
    {
        "ref": "DEMO-CASE-0001",
        "user": "asha@example.invalid",
        "narrative": ("DEMO DATA. On an invented date a neighbour threatened me and took my "
                      "phone so I could not call for help. This statement is fictional and "
                      "exists to exercise the portal's screens."),
        "domain": "CRIMINAL",
        "location": "Demo City",
        "incident_date": "2026-09-14",
    },
    {
        "ref": "DEMO-CASE-0002",
        "user": "ravi@example.invalid",
        "narrative": ("DEMO DATA. A fictional landlord refused to return a deposit. Invented "
                      "for the demo database; it describes no real dispute."),
        "domain": "CIVIL",
        "location": "Demo City",
        "incident_date": "2026-08-02",
    },
]


def _schema_exists(c: sqlite3.Connection) -> bool:
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="delete and recreate the database")
    args = ap.parse_args(argv)

    if args.force and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"removed {DB_PATH}")

    # Importing the server would start nothing, but it does create the schema and
    # seed the administrator. That keeps one source of truth for the schema.
    sys.path.insert(0, HERE)
    # Override rather than setdefault: whatever is in the operator's environment,
    # this database is a throwaway demo and the password printed below must be the
    # password that actually works. Printing one value while setting another is
    # exactly the kind of lie this project is trying not to tell.
    os.environ["NYAYA_ADMIN_PASSWORD"] = DEMO_PASSWORD
    import server  # noqa: E402  (import for its side-effect-free helpers)

    server.init_all()

    created = []

    # The bootstrap administrator that init_all() creates is replaced here: a
    # demo database should have one administrator with a password you can read
    # off the screen, not a generated secret in a local file.
    with server.db() as c:
        boot = c.execute("SELECT id FROM users WHERE email=?", (server.ADMIN_EMAIL,)).fetchone()
        if boot:
            has_reports = c.execute("SELECT 1 FROM reports WHERE user_id=? LIMIT 1",
                                    (boot["id"],)).fetchone()
            if not has_reports:
                c.execute("DELETE FROM sessions WHERE user_id=?", (boot["id"],))
                c.execute("DELETE FROM users WHERE id=?", (boot["id"],))

    with server.db() as c:
        for name, email, role in DEMO_ACCOUNTS:
            row = c.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if row:
                continue
            try:
                server.create_user(name, email, DEMO_PASSWORD, role=role)
                created.append(email)
            except Exception as exc:                      # pragma: no cover
                print(f"  could not create {email}: {exc}")

        for case in DEMO_CASES:
            row = c.execute("SELECT id FROM users WHERE email=?", (case["user"],)).fetchone()
            if not row:
                continue
            exists = c.execute("SELECT 1 FROM reports WHERE narrative=?",
                              (case["narrative"],)).fetchone()
            if exists:
                continue
            # Built through the portal's own intake path rather than raw SQL, so
            # the demo rows have exactly the shape real rows have and every screen
            # renders against them.
            user = dict(c.execute("SELECT * FROM users WHERE id=?", (row["id"],)).fetchone())
            server.intake_report(user, {
                "narrative": case["narrative"],
                "incident_date": case["incident_date"],
                "location": case["location"],
                "domain": case["domain"],
                # every enum the intake validator requires, answered plainly
                "victim_under18": "no",
                "woman_or_girl": "yes" if case["domain"] == "CRIMINAL" else "no",
                "sexual_offence": "no",
                "accused_in_custody": "no",
                "liberty_threat": "no",
                "accused_under18": "no",
                "has_lawyer": "no",
                "no_evidence_ack": True,
                "declaration": True,
            })
            created.append(case["ref"])

    print(f"\ndatabase: {DB_PATH}")
    print(f"created:  {', '.join(created) if created else 'nothing new (already seeded)'}")
    print(f"\ndemo login (all accounts): password = {DEMO_PASSWORD}")
    for _name, email, role in DEMO_ACCOUNTS:
        print(f"  {email:28s} {role}")
    print("\nThese credentials are for a throwaway demo database. Before putting real "
          "\ninformation in it, delete the database and run "
          "`python3 server.py --rotate-admin-password`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
