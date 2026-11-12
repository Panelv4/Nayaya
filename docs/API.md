# NYAYA-RAC v0.5.0 — API reference

All endpoints are JSON unless noted. Authentication is by `Authorization:
Bearer <token>` header or the session cookie (both issued by `/api/login` and
`/api/register`). Unauthenticated API calls return `401`; authenticated calls
that fail authorization return `403`; unknown or private resources return
`404` (existence is never confirmed for someone else's private case).

## Public (no auth)

| Method & path | Purpose |
|---|---|
| `GET /health`, `GET /api/health` | Liveness probe: `{"ok": true, "version", "engine", "mode", "db"}` |
| `GET /robots.txt` | `Disallow: /` (holds personal data) |
| `GET /favicon.svg` | Scales icon |
| `GET /api/disclosed` | Public registry of admin-approved disclosures |
| `GET /api/engine/overview`, `GET /api/engine/impact?amendment=…` | Rules-as-code analysis (read-only) |
| `GET /api/session` | Session bootstrap (never 401; returns `authenticated: false` when anonymous) |

## Session

| Method & path | Auth | Purpose |
|---|---|---|
| `POST /api/register` | — | Create account (rate limited: 10/address/15 min) |
| `POST /api/login` | — | Login (rate limited: 5/account, 30/address) |
| `POST /api/logout` | session | Invalidate token, clear cookies |
| `POST /api/renew` | session | Re-issue cookies from a Bearer token |
| `GET /api/me` | session | Profile, role, report count, DigiLocker status |

## Cases

| Method & path | Auth | Purpose |
|---|---|---|
| `POST /api/report` | session | File a report (narrative + answers + evidence or no-evidence ack) |
| `GET /api/reports` | session | Own cases (latest 200, with excerpts) |
| `GET /api/report?id=…` | owner / admin / disclosed | Full case payload (redacted when `ANONYMIZED`) |
| `POST /api/revise` | owner / admin | Corrected re-evaluation (immutable revision snapshot) |
| `POST /api/disclosure-request` | owner | Request disclosure (`PRIVATE\|REJECTED → PENDING`) |
| `GET /api/evidence?id=…` | owner / admin | Download evidence bytes (attachment; SHA-256 verified) |
| `POST /api/evidence-map` | owner / admin | Link evidence to a fact (`SUPPORTS\|CONTRADICTS\|CONTEXT`) |
| `POST /api/feedback` | session | Thumbs up/down per case (one vote per user) |
| `GET /api/feedback?report_id=…` | session | Feedback summary for a case |
| `GET /api/provenance?type=…&id=…` | session | Provenance chain around a subject; case/evidence nodes are filtered to the caller's own or disclosed cases |

| `POST /api/password-reset/request` | none | Start a reset; always answers identically |
| `POST /api/password-reset/confirm` | none | Consume a single-use reset token and set a new password |
## Admin only (`403` for everyone else)

| Method & path | Purpose |
|---|---|
| `GET /api/admin/overview` | Stats, queues (disclosure / manual-check / flagged), recent cases |
| `GET /api/admin/feedback` | Feedback analytics; `?export=jsonl` downloads the labelled dataset |
| `POST /api/admin/disclosure` | Approve / reject / disclose / revoke (`ANONYMIZED` or `FULL`) |
| `POST /api/admin/manual-check` | `VERIFIED \| NEEDS_CORRECTION \| REJECTED` with officer note |
| `POST /api/admin/statutes`, `POST /api/admin/statutes/verify` | Add / verify statutory versions (only verified feed evaluations) |
| `POST /api/admin/precedents`, `POST /api/admin/precedents/status` | Add / update precedents |
| `POST /api/admin/amendment-impact` | Dry-run re-evaluation of citing cases; `apply_report_id` writes a SYSTEM revision |
| `GET /schema`, `GET /audit`, `POST /evaluate` | Engine schema, audit trail, raw evaluation |

## DigiLocker (simulated)

| Method & path | Auth | Purpose |
|---|---|---|
| `GET /api/digilocker/status`, `GET /api/digilocker/events`, `GET /api/digilocker/verify?artefact=…` | session | Status, event log, artefact verification (full record for the owner/admin only) |
| `POST /api/digilocker/consent`, `/grant`, `/callback`, `/revoke` | session | Consent flow (all responses labelled `SIMULATED`) |

## Errors

`400` validation · `401` not logged in · `403` forbidden · `404` not found ·
`429` rate limited (with `retry_after`) · `500` internal error (generic message;
details are printed to the server log, never returned).
