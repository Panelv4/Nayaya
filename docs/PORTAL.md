# NYAYA-RAC v0.5.0 — Citizen Case Reporting & Decision-Support Portal

Rules-as-Code judicial decision-support engine (`embedded-demo-0.2.0`) wrapped in a
**victim-facing reporting portal** with a strict, human-approved disclosure model,
a versioned statutory knowledge base, evidence-to-fact mapping, and a re-evaluation /
feedback loop that produces a labelled dataset.

> **Advisory decision support only.** Not a judge, adjudicator, or sentencing
> authority. Not an FIR. Research prototype with demo-grade security — do not
> upload real sensitive case material.

---

## Read this first: what the project is for

The valuable part of this repository is **`nyayacode/`** — a library that encodes a
statute as data and then interrogates the encoding: does it decide every case, does
it contradict itself, and what happens to the whole case space if the law changes.

The portal in the rest of this README is **one application on top of it**, built to
show that the engine can drive a real workflow. It is not the argument. If you are
reading this to judge the idea, read `nyayacode/README.md` and run:

```
python3 -m nyayacode impact --amendment amend.bns.exc4-abolished
```

Two honest caveats, both of which the tool prints on every output:

* the statutes are **encoded but not yet reviewed by a lawyer**, and a passing
  analysis proves internal consistency, not legal correctness;
* the analysis is exhaustive over a **declared fact space**, so a fact nobody
  thought of is invisible to it.

### Two other things worth knowing

* **It is not an AI system.** The engine is deterministic rules-as-code: same input,
  same verdict, same digest, no model, no inference, no network call. (Two traces of
  machine-learning framing have been removed: the feedback export is now described
  as an audit record rather than a training feed, and the prompt-injection input
  flag is gone.)
* **It holds personal data.** See *Running it safely* below before binding it to
  anything but loopback.

## Run

```bash
python3 server.py                      # then open http://localhost:8000
python3 server.py --make-admin you@example.com   # promote an existing account
python3 tests.py                       # 125 automated tests (throwaway databases)
python3 smoke.py                       # 150 HTTP checks against a running server
curl http://localhost:8000/health      # liveness probe (no auth needed)
```

Python 3 standard library only — no dependencies to install.

First boot seeds an administrator and writes the generated password to
`.nyaya-admin-credentials` (mode `600`); the path is printed once:

```
[init] Seeded admin admin@nyaya.local; password from .nyaya-admin-credentials.
       Change it before exposing this server.
```

Override before first boot if you prefer:

```bash
NYAYA_ADMIN_EMAIL=registrar@court.local NYAYA_ADMIN_PASSWORD='...' python3 server.py
```

The admin is **only seeded when no administrator exists**, so custom credentials are
never silently overwritten on restart. For an existing account use `--make-admin`.

### Local data

| Path | Contents |
|---|---|
| `nyaya-rac.sqlite3` | users, sessions, reports, revisions, evidence register, evidence→fact map, disclosure + manual-check status, feedback, statutory KB, provenance graph |
| `nyaya-rac-audit.sqlite3` | engine audit trail (one row per evaluation, hash-linked input) |
| `evidence/` | uploaded proof files, grouped per report |

Override paths with `NYAYA_DB` / `NYAYA_EVIDENCE_DIR` / `NYAYA_AUDIT_DB`
(the test-suite does exactly this so it can never touch live data; the audit
DB defaults to alongside `NYAYA_DB`). The schema migrates in place on startup
(`ensure_columns` + `backfill_revisions`): existing v0.2.x databases keep every row.

---

## Access model — nothing is public until a human approves it

```
Visitor ──► Home / Login / Disclosed registry        (pages are served, APIs need a session)
User    ──► own dashboard, own cases, own feedback
Admin   ──► all cases, disclosure queue, manual-check queue, KB editor, workbench
```

* **Every report is `PRIVATE` on creation.** No other user can see it — the API
  answers `404 Case not found`, not `403`, so even the *existence* of someone
  else's case is not confirmed.
* **Disclosure is a two-step, human-gated flow.** The owner clicks *Request
  disclosure* (`PRIVATE|REJECTED → PENDING`); an administrator then reviews the
  case and either **APPROVE (ANONYMIZED)**, **APPROVE (FULL)** or **REJECT**.
  Admins may also `DISCLOSE` directly or `REVOKE` a published case back to
  `PRIVATE`. Nothing is auto-approved, on any timer, ever.
* **ANONYMIZED** discloses the *routing answer* — review level, urgency, severity,
  triggers, confidence, resolution against the statutory KB — while redacting the
  narrative, location, structured answers, facts, keywords, intake notes, evidence
  filenames, revision reasons and check notes. **FULL** discloses the narrative
  excerpt as well.
* **Owner and admins always see the full case**; the payload marks
  `access: "FULL" | "ANONYMIZED"` and never exposes the owner's internal user id.
* **Admin-only endpoints** return `403` for everyone else:
  `/schema`, `/audit`, `/evaluate`, `/api/admin/*`. The Admin, Legal KB and
  Workbench links are injected into the nav only for admins, and those pages are
  client-guarded with `requireAdmin()` as defence in depth.

### Revision & manual check (fixing an honest mistake)

Applicants make mistakes; the record must still be trustworthy.

* `/api/revise` re-runs the engine on corrected answers. A **reason (≥5 chars) is
  mandatory**; revisions are **immutable snapshots** (`revisions` table, `UNIQUE(report_id, rev_no)`,
  actor `OWNER | ADMIN | SYSTEM`) and the revision graph records `SUPERSEDES` +
  `HAS_REVISION` + `EVALUATED_BY` provenance edges. Nothing is silently overwritten —
  revision 1 survives verbatim.
* A revision **resets a `VERIFIED` manual check back to `UNCHECKED`**, because
  corrected facts must be re-checked by a human.
* Manual-check states (admins only): `UNCHECKED → VERIFIED | NEEDS_CORRECTION | REJECTED`,
  each with an officer note and a `MANUAL_CHECK` provenance edge.

### Feedback — 👍 / 👎 on every verdict, fed to the data

Every report shows a small thumbs-up / thumbs-down control (one vote per user per
report, upsert-able, tied to the revision it was cast on).

* When **down − up ≥ 2** the report is automatically **flagged for admin review**
  (`/api/admin/overview → queues.flagged`).
* Admins see analytics by review level, case type and trigger, and can export the
  **labelled dataset** — `GET /api/admin/feedback?export=jsonl` (NDJSON):

```json
{"ref":"NYR-…","rev_no":2,"label":-1,"comment":"wrong urgency band","voted_at":"…",
 "features":{"domain":"CRIMINAL","answers":{…},"keyword_categories":["threat/coercion"],
             "review_level":"L2","urgency":"HIGH","severity_tier":"S2","confidence":0.72,
             "triggers_fired":["T-12","T-15"]}}
```

Features = intake answers + keyword categories + computed routing. Label = the
citizen's verdict on that routing. That is the audit record — **no rule mutates
itself from a vote**; a human reviews flagged cases and edits the rule base or the
statutory DB deliberately.

---

## Page flow

```
Homepage (/)  →  Login / Register (/login)  →  Dashboard (/dashboard)
                                                 ├── Submit Report (/submit)
                                                 ├── My Cases (/cases → /case?id=…)
                                                 └── Disclosed Registry (/disclosed)     [public, approved cases only]
Admin only: Admin console (/admin) · Legal KB (/kb) · Technical workbench (/workbench)
```

**Victim experience.** Step 1 is a free-text narrative ("what happened"), followed
by plain-language questions (dates, case type, age/minor status, sexual offence,
custody, liberty threat, legal aid, vulnerability checkboxes, optional legal
section). The runtime-variables box is gone — the values the engine still needs
(`legal_aid_check_status`, `victim_unrepresented`, `person_in_custody`) are derived
server-side in `build_engine_inputs`. Evidence is optional but attachable; if
nothing is attached the applicant must tick *"I have no evidence to attach at this
time"*.

**DigiLocker identity verification** is a full, calibrated consent flow — see
[DigiLocker verification](#digilocker-identity-verification-calibrated-model) below.

---

## Phase 1 — Engine reliability

1. **Strict offence-date validation** (`engine._validate_offence_dates`): dates must
   be integers in `YYYYMMDD`, real calendar dates, inside 1861–2100, and ordered
   start ≤ end. Missing dates remain allowed (the regime resolves to `UNDETERMINED`,
   a protected state) but a *provided* bad date raises `ValueError` instead of
   silently producing `MIXED`/`UNDETERMINED` routing.
2. **Real JSON Schema validation** (`engine.validate_json_schema`, draft-07 subset:
   type/required/properties/items/enum/min/max) run against the engine's own
   `output_schema` — **fail closed**: violations raise before any output escapes,
   and validator `OV-01` reports `passed` on success.
3. **Nested tri-state normalization** — nested booleans become `"TRUE"/"FALSE"` so
   strict comparisons in derived facts actually fire (T-10, T-02, urgency rules).
4. **Trigger levels** are carried on every fired trigger (`T-xx → L0…L3`).
5. **Severity from punishment text** — "7 years", "3 to 7 years", "death", "life",
   "Not specified" all parse correctly; structured punishment dicts still win;
   child-specific statutes suppress double escalation.
6. `evaluate(..., record_audit=False)` for dry runs (amendment impact) that must not
   pollute the audit trail.

## Phase 2 — Legal intelligence infrastructure

* **Versioned statutory database** — one row per `(statute, provision, version)`
  with `effective_from` / `effective_to`, punishment fields, source reference and
  an explicit **`verified` flag**. A version **only feeds punishment into an
  evaluation after a human marks it verified** (`/api/admin/statutes/verify`);
  seed rows ship unverified on purpose, and the tests enforce that an unverified
  version can never influence severity. A new version auto-closes the previous open
  version.
* **Citation resolution** (`resolve_provision`) returns
  `VERIFIED | UNVERIFIED | NO_VERSION_FOR_DATE | NOT_IN_KB | NO_CITATION` for the
  incident date — the correct regime is picked per case (e.g. IPC 302 before
  2024-07-01, BNS 103 after).
* **Precedent tracking** — court, date, headnote, holding tagged
  `SUPPORTS_STRICT | SUPPORTS_LENIENT | PROCEDURAL`, status
  `GOOD_LAW | OVERRULED | DISTINGUISHED` with `overruled_by`.
* **Conflict detection** — `OVERLAPPING_VERSIONS`, `PRECEDENT_CONFLICT`,
  `STATUS_INCONSISTENT`; surfaced on `/kb` and in the admin banner.
* **KB → engine wiring** — `NO_VERSION_FOR_DATE` raises the `rule_version_missing_for_date`
  fact (trigger **T-16**), a precedent conflict raises `precedent_conflict`
  (trigger **T-05**), overlapping versions raise `provision_ambiguous`.
* **Provenance graph** — every KB/report/evidence/revision/disclosure/feedback event
  is an edge (`AMENDS`, `VERSION_OF`, `CITES`, `EVALUATED_BY`, `SUPERSEDES`,
  `HAS_REVISION`, `REGISTERED_IN`, `MANUAL_CHECK`, `DISCLOSURE_*`, `ABOUT`), browsable
  in `/kb` and via `/api/provenance`.
* **Amendment-impact analysis** — `POST /api/admin/amendment-impact
  {statute, provision, apply_report_id?}` re-resolves every case citing that
  provision against the *current* statutory DB, reports which evaluations would
  change (dry run, no audit rows), and can apply the result as a **SYSTEM
  revision** on one case.

## Phase 3 — Evidence and accountability

* **Evidence-to-fact mapping** — each uploaded file can be linked to a structured
  fact with `SUPPORTS | CONTRADICTS | CONTEXT` and a note (`UNIQUE(evidence_id, fact_key)`,
  owner/admin only, every link a provenance edge).
* **Coverage** — for each case, `coverage.mappable_facts` lists the facts that
  matter, `supported` / `contradicted` list which ones evidence actually addresses,
  and `coverage` is the fraction supported. Unsupported-but-contradicted facts are
  called out separately, so weak files cannot masquerade as proof.
* **Audit integrity** — immutable revision history, append-only engine audit trail,
  and the disclosure / manual-check / feedback trail above.

---

## API map

| Method & path | Who | Purpose |
|---|---|---|
| `POST /api/register`, `/api/login`, `/api/logout` | anyone | session (cookie **and** Bearer token) |
| `GET /api/me` | session | profile, role, `is_admin`, DigiLocker stub |
| `GET /api/reports` | session | own cases + disclosure/manual-check/revision/feedback columns |
| `GET /api/report?id=` | owner / admin / disclosed | full payload (redacted when ANONYMIZED) |
| `GET /api/evidence?id=` | owner / admin | download evidence bytes (SHA-256 verified; never for disclosed viewers) |
| `GET /api/disclosed` | anyone | public registry of approved cases |
| `POST /api/report` | session | intake (declaration + evidence *or* no-evidence ack) |
| `POST /api/revise` | owner / admin | re-evaluate with reason, immutable revision |
| `POST /api/disclosure-request` | owner | `PRIVATE|REJECTED → PENDING` |
| `POST /api/feedback` | anyone with access | 👍/👎 + comment, flags at net −2 |
| `POST /api/evidence-map` | owner / admin | link evidence → fact |
| `GET /api/kb`, `/api/provenance` | session | statutory rows, precedents, conflicts, graph |
| `POST /api/admin/disclosure` | admin | `APPROVE / REJECT / DISCLOSE / REVOKE` + mode |
| `POST /api/admin/manual-check` | admin | `UNCHECKED / VERIFIED / NEEDS_CORRECTION / REJECTED` |
| `POST /api/admin/statutes`, `/verify`, `/precedents`, `/status` | admin | KB editing + human verification |
| `GET /api/admin/overview` | admin | stats, queues, all cases, feedback analytics, conflicts |
| `GET /api/admin/feedback` (`?export=jsonl`) | admin | analytics / labelled dataset |
| `POST /api/admin/amendment-impact` | admin | dry run + optional SYSTEM revision |
| `GET /api/digilocker/status`, `/events` | session | identity state, consent quota, audit trail |
| `POST /api/digilocker/consent`, `/grant`, `/callback`, `/revoke` | session | consent → code → artefact → attest (or deny/withdraw) |
| `GET /api/digilocker/verify?artefact=` | anyone | independent integrity check of an artefact id |
| `POST /evaluate`, `GET /schema`, `GET /audit` | admin | technical workbench |

Errors: `AccessDenied → 403`, `NotFound → 404` (also used to hide foreign private
cases), `ValueError/TypeError → 400`.

Full endpoint reference: [`API.md`](API.md).

---

## DigiLocker identity verification (calibrated model)

A verified identity raises the evidential value of a report and deters duplicate or
malicious filings — it is **never a precondition** for filing. An unverified report is
accepted and permanently marked as unverified.

### The flow (implemented end to end)

```
POST /api/digilocker/consent    scope + purpose + state + PKCE-S256 challenge, 30-minute window
        ↓                       (max 5 request streams per account per day)
  consent screen                the user approves or denies, explicitly
        ↓ POST /grant
  single-use code               issued only against a live, approved consent request
        ↓ POST /callback
  issuer artefact               name, DOB, gender, photo flag, issuer + issuer reference
        ↓ validation
  hash-sealed artefact          sha256 over the canonical document, 12-month validity
        ↓
  LINKED                        recorded on the account and attached to every report
```

### What is calibrated against the real system

`digilocker.py` exposes its calibration constants (`REAL_WORLD`) through the API:

| Parameter | Value | Consequence modelled |
|---|---|---|
| consent validity | 30 minutes | a late callback is refused with `CONSENT_EXPIRED` |
| consent requests | 5 / account / day | `CONSENT_REQUESTED` throttling |
| authorisation code | single use | replay is refused with `CODE_REPLAYED` |
| `state` parameter | required | callback forgery refused with `STATE_MISMATCH` |
| PKCE | S256, 43–128-char verifier | challenge = BASE64URL(SHA256(verifier)), no padding |
| scope | `aadhaar:name aadhaar:dob aadhaar:gender aadhaar:photo` | user-visible, purpose-bound |
| issuer allow-list | UIDAI, ECI, MoRTH, Income Tax, CGHS, EPFO | unknown issuer refused with `UNKNOWN_ISSUER` |
| artefact checks | name, real DOB, not future-dated | `MISSING_NAME` / `MISSING_DOB` / `BAD_DOB` / `FUTURE_DOB` |
| one identity, one account | issuer reference unique | `IDENTITY_IN_USE` / `ALREADY_LINKED` |

Rejection reasons are machine-readable and enumerated in `digilocker.REJECTION_REASONS`;
every step is written to `dl_events` and surfaced as "last event".

### What is *not* real — stated in the UI, the API and the artefact

Nothing is sent to `digilocker.gov.in`. The consent screen, the issuer response and the
document are generated locally (`mode: "SIMULATED"`, `simulated: true`), the panel carries
a **SIMULATED** tag plus a plain-language honesty note, and `GET /api/digilocker/verify`
returns `simulated: true` for every artefact. Going live means implementing two functions
in `digilocker.py` (`exchange_code`, `_simulated_artefact` → partner gateway) — no other
layer changes.

### Artefact integrity

Each verification seals `json.dumps(doc, sort_keys=True)` with SHA-256 and stores the
sealed document, the digest, the issuer (masked in responses: `XXXX••••2A`) and an
expiry. `GET /api/digilocker/verify?artefact=dlv_…` re-computes the digest and reports
`INTEGRITY / TAMPERED`, `ACTIVE / EXPIRED / REVOKED`. Withdrawal (`/revoke`) keeps the
record for audit and flips the account back to `NOT_LINKED`; reports already filed keep
the state they were filed with, and the fingerprint is stable per account so two people
sharing a name never collide.

### Admin view

`/api/admin/overview` adds `stats.identities_verified`, `identities_revoked`,
`identity_failures`, `reports_unverified_identity` and an `identity` block; the console
shows a *Verified identities* tile and an **Identity** column (VERIFIED / UNVERIFIED) in
both the manual-check queue and the all-cases table.

---

## Interface & design system

The UI follows Indian government e-portal conventions rather than a consumer-app look:

* **tricolour rule** under a navy utility strip (Ministry line, public register,
  accessibility, हिन्दी / English), then the emblem + serif wordmark masthead;
* navy chrome, steel-grey rules, tabular figures, `Noto Serif`-style headings and
  restrained saffron/green accents for status only;
* **no emoji anywhere** — 50 hand-drawn 24×24 stroke icons in `assets/icons.svg`,
  injected once per page as an inline sprite. Icons support `currentColor`, so they
  inherit every badge and button palette;
* **CSS-only motion, honouring `prefers-reduced-motion`**: line-art draw-on for
  confirmation paths (`pathLength="100"`), swing on card hover, lift on tiles and
  file rows, spinner while a device is busy, pulse on live indicators;
* accessible by construction: `aria-hidden` on decorative SVGs, visible focus rings,
  ≥4.5:1 text contrast, no colour-only status (every badge pairs an icon with a label).

Because icons are injected inline and the CSS is server-inlined, the portal renders
identically inside a sandboxed preview iframe with no network access.

---

## Authentication notes (why it looks the way it does)

The portal is frequently opened inside a cross-site preview iframe, where the
browser gives a document **no usable session channel at all**: the session cookie
is third-party and dropped, `localStorage`/`sessionStorage` throw on access (the
*property read* throws, not just `getItem`), and a sandboxed document may have an
opaque origin. Server-side page redirects and cookie-only auth were tried and
reverted — do not reintroduce them.

The session therefore travels over **five complementary channels** and every page
re-attaches whichever one is alive:

| # | Channel | Survives |
|---|---|---|
| 1 | `Authorization: Bearer <token>` via `authFetch()` | every API call in the page's lifetime |
| 2 | `?st=<token>` relay, added to **every internal link** by a delegated click handler (`installLinkRelay`) plus `go(url)` | full page loads, cross-site iframes, opaque origins |
| 3 | `nyaya_relay` cookie (JS-readable, `SameSite=Lax`) | top-level navigation; bootstraps JS |
| 4 | `nyaya_session` cookie (HttpOnly, server-side truth) | normal same-site browsing |
| 5 | `window.name` (`nyaya:<token>`) | reload / back / forward even with an opaque origin |

Boot order on every page: `bootstrapSession()` → `GET /api/session`, which **never
returns 401** — anonymous gives `{authenticated:false}`, a valid token returns the
token plus the user and *re-issues both cookies* if the jar was emptied.
`POST /api/renew` promotes a Bearer token into the cookie jar right after login.
Logout clears all five channels. `?st=` is always **set, never appended**, so the
query cannot grow into the `?st=A&st=B&st=C` loop seen in the first implementation.

Because the token can sit in a URL, every response carries
`Referrer-Policy: no-referrer` (verified by a smoke check) and `nosniff`; the cookie
flags are `SameSite=None; Secure` only behind TLS, since browsers silently reject
`SameSite=None` without `Secure`.

Regression cover: `tests.py` (static guards on auth.js + server contract) and
`smoke.py` section 14 (`/api/session`, `/api/renew`, dual-cookie issue/clear).
The real-world case is exercised with Playwright: parent on `localhost`, portal
iframe on `127.0.0.1`, `localStorage`/`sessionStorage` throwing — login, every nav
link, reload, back/forward, DigiLocker consent and logout must all stay signed in.

---

## Running it safely

This is a laptop tool that stores real statements about real people. Three things
changed to make that less dangerous, and one thing is still your job.

| Concern | What it does now |
|---|---|
| **Administrator credential** | There is no password in the source. On first run a random one is generated and written to `.nyaya-admin-credentials` with mode `600` (owner-only). `NYAYA_ADMIN_PASSWORD` overrides it; a weak or well-known value is refused at startup. |
| **Rotation** | `python3 server.py --rotate-admin-password` generates a new secret, writes it to the same file and revokes every existing session for that account. Run it after cloning or if a secret may have leaked. |
| **Network exposure** | Binds `127.0.0.1` by default. Binding elsewhere requires `NYAYA_HOST` *and* `NYAYA_ALLOW_PUBLIC_BIND=1`, and prints a warning: there is no TLS and no record of who connects. |
| **Brute force** | Login is rate limited per account (5 failures / 15 min → 15 min lockout) and per address (30 failures). Two thresholds on purpose: keying only on the address would let one attacker lock out every user on a shared network. Registration is rate limited per address (10 / 15 min) as a spam guard. |
| **Evidence bytes** | Downloadable only by the case owner and admins (`GET /api/evidence`); disclosed viewers see metadata, never bytes. Paths are confined to `evidence/` and SHA-256 is re-verified on every download. |
| **Still your job** | Anyone who can read the database can read the cases. Full-disk encryption, and deleting the database when you are done, are outside what the code can do. |

Smoke tests read the generated credential file rather than hardcoding a password,
so no test in this repository contains a working login.


---

## Files

| File | Role |
|---|---|
| `engine.py` | Rules-as-Code decision engine (JSON-Logic rules, tri-state, severity, audit, schema validation) |
| `legal_kb.py` | Phase 2: statutory DB, precedents, conflicts, resolution, provenance graph |
| `digilocker.py` | Identity verification: calibrated consent/artefact flow, validation, sealing, revocation |
| `db.py` | Shared SQLite plumbing, paths, reentrant locks, lightweight migrations |
| `server.py` | v0.5.0 portal: intake, revisions, disclosure, manual check, feedback, evidence map, admin, HTTP handler, `/health`, security headers |
| `pages/*.html` | home, login, dashboard, submit, cases, case, workbench, **admin**, **kb**, **disclosed** |
| `assets/icons.svg` | 50-icon stroke sprite (no emoji), injected inline per page |
| `assets/auth.js`, `assets/style.css` | five-channel session relay + fetch helpers + DigiLocker panel renderer, government-portal design system |
| `nyayacode/` | **the library**: pack format, evaluator, gap/contention/ambiguity analysis, amendment impact, CLI. See `nyayacode/README.md` |
| `nyayacode/packs/` | encoded statutes (`in.bns.homicide`, `in.bns.negligence`, `in.bns.abetment-suicide`, `in.bns.attempt-murder`, `in.bns.attempt-culpable-homicide`, `in.bns.organised-crime`, `in.bns.petty-organised-crime`, `in.bns.terrorist-act`, `in.mv.drunken-driving`) and amendments. Coverage roadmap: `docs/COVERAGE.md` |
| `pages/engine.html` | reads `/api/engine/overview` and `/api/engine/impact` and renders the analysis |
| `tests.py` | 125 tests: engine, Phase-1 validation, KB, access control, disclosure, revisions, feedback, evidence mapping, admin, amendment impact, DigiLocker flow |
| `tests/test_nyayacode.py` | 52 tests: evaluator, analyser, amendments, statute encodings (homicide, negligence, MV), and negative tests that break a pack on purpose |
| `smoke.py` | 150 end-to-end HTTP checks against a running server (`python3 smoke.py`); creates throwaway `@smoke.test` accounts |

### Known limits (deliberate)

* DigiLocker — the flow, states, scopes and validation are real; the issuer response is
  simulated locally and labelled as such everywhere. No partner credentials, no egress.
* `verified` on statutes is a *simulated human approval* (an admin click), not a
  signature; there is no external corpus pinning yet.
* Demo-grade security: HTTP on localhost, no CSRF tokens (mitigated by
  `SameSite` cookies + Bearer tokens), login rate limiting per account and per
  address, no file virus scanning, password hashing is PBKDF2 with per-user salt.
  Responses carry `Content-Security-Policy`, `Permissions-Policy`,
  `X-Content-Type-Options` and `Referrer-Policy: no-referrer`.
* The engine is a decision-support *router*; it never decides a case.
