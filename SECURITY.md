# Security policy

NYAYA-RAC is a **research prototype** that holds personal data (case
narratives, contact details, evidence files). It is not production software
and must not be deployed publicly without the hardening described in
`docs/PORTAL.md` ("Running it safely").

## Security model

| Layer | What it does |
|---|---|
| Authentication | PBKDF2-HMAC-SHA256 (120k iterations, per-user salt); sessions are 256-bit random tokens, 7-day expiry |
| Admin bootstrap | No password in source. First run generates a random secret to `.nyaya-admin-credentials` (mode `600`); `NYAYA_ADMIN_PASSWORD` overrides; weak/well-known values are refused at startup |
| Brute force | Login rate limited per account (5 failures / 15 min → 15 min lockout) and per address (30 failures) |
| Access control | Every report is `PRIVATE` by default; only owner + admins see it. Disclosure needs manual admin approval (`ANONYMIZED` or `FULL`). APIs return `404` (not `403`) for foreign private cases so existence is not confirmed |
| Transport | Binds `127.0.0.1` by default. Non-loopback bind requires `NYAYA_ALLOW_PUBLIC_BIND=1` and prints a warning — there is no TLS |
| Response headers | `Content-Security-Policy`, `Permissions-Policy`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` (the session relay token can appear in a URL) |
| Data at rest | SQLite + `evidence/` on disk. Full-disk encryption and deletion are the operator's job |
| Audit | Append-only engine audit trail (`nyaya-rac-audit.sqlite3`); immutable revision snapshots; provenance graph |

## Reporting a vulnerability

Open a private report via GitHub's **Report a vulnerability** button on this
repository (Security → Report a vulnerability). Do not open a public issue
for a suspected vulnerability, and do not include real personal data in any
report.

Please include: affected version/commit, steps to reproduce, and impact.
We will acknowledge within a few days and fix before any public disclosure.

## What is out of scope

- The `nyayacode` packs are `encoded_unreviewed` — encoding errors are
  correctness issues, not security vulnerabilities. File them as ordinary
  issues with the statutory text and the pack id.
- DigiLocker integration is a **simulated** flow (labelled `SIMULATED`
  everywhere). There is no partner gateway to attack.
- Denial of service against a localhost prototype is not a vulnerability.

## Supported versions

Only the latest `main` is supported. There are no backported security fixes
for older commits.
