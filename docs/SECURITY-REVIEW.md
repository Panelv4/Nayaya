# Security review — NYAYA-RAC portal

**Date:** 2026-11-10 · **Version:** 0.5.0 · **Scope:** `server.py`, `engine.py`,
`db.py`, `legal_kb.py`, `digilocker.py`, `uncertainty.py`, `pages/`, `assets/`

## How this was done

Not a code-reading exercise. A live instance was stood up with its own database
and evidence directory, and the attacks below were actually executed against it,
alongside a read of the handlers. Where a claim is made, the observed result is
given.

**Scope limits, stated plainly.** No TLS interception, no browser-driven XSS
execution, no fuzzing campaign, no dependency audit (there are no third-party
dependencies — see §2.1), and no review of `seed.py` demo data. Findings are
limited to what was read and what was run.

---

## 1. Verdict

| | Score | One line |
|---|---|---|
| **The idea** | **7.5 / 10** | The analyser that proves a rule set total, disjoint and honestly ambiguous is the real contribution; the law is open-textured and the packs are self-described as unreviewed, which caps it. |
| **The security** | **6.5 / 10** | Genuinely careful in the places that are easy to get wrong (injection, authorisation, password hashing, path handling). Undone by one unforced design decision in session handling, and not deployable on real personal data as shipped. |

Six-and-a-half is a *good* score for a single-file prototype that has never had a
penetration test. It is not a passing score for a system that holds the
narrative of a sexual-offence complainant. Those are different bars, and the gap
between them is where this document lives.

---

## 2. What is solid

These are the things that are usually broken in a prototype and are not broken
here. They are worth stating because they were verified, not assumed.

### 2.1 Supply chain: essentially zero

Every import in the application is from the standard library (`grep` over all
six modules returns only `http.server`, `sqlite3`, `hashlib`, `hmac`, `secrets`,
`json`, `re`, `os`, `base64`, `ipaddress`, `uuid`, `threading`, `datetime`,
`urllib.parse`). No `pip install`, no vendored blobs, no transitive tree. The
attack surface usually described as "supply chain" does not exist here.

### 2.2 SQL injection: none found

All queries are parameterised. The two dynamic `WHERE` clauses
(`server.py:1504`, `server.py:2314`) interpolate only a string built from
literal fragments and `?` placeholders — no request data reaches the SQL text.
`ORDER BY` is hard-coded, not caller-selected. `LIKE` wildcards in search are
escaped (`_like()`), so `%` and `_` behave literally.

### 2.3 Authorisation: consistent and correct

This is the strongest area. Every endpoint was probed as an anonymous visitor,
as a second ordinary user, and as an administrator.

| Attack | Result |
|---|---|
| Bob reads Alice's private case | `404 Case not found.` |
| Bob downloads Alice's evidence | `404 Evidence not found.` |
| Bob revises Alice's case | `403 Only the owner or an administrator…` |
| Bob votes on Alice's case | `404` |
| Bob maps evidence on Alice's case | `403` |
| Bob requests disclosure of Alice's case | `403` |
| Bob reads Alice's provenance graph | `200`, **zero edges** — the chain is filtered, not merely trimmed |
| New user registers with `"role":"ADMIN"` in the body | `role: USER`; admin endpoint returns `403` |
| Non-admin hits `/api/admin/*`, `/audit`, `/schema` | `401` / `403` |
| Carol inspects Alice's DigiLocker consent request | `404 Consent request not found.` |

Mass assignment was tried directly — submitting `review_level`, `disclosure_status`,
`manual_check_status`, `feedback_up` in the report body. All ignored; the stored
record kept `L2 / PRIVATE / UNCHECKED / 0`. Server-side derivation is not driven
by client input.

Non-existent case ids and real-but-private case ids return identical shapes, so
there is no existence oracle. Unauthorised access returns `404`, not `403`,
which correctly refuses to confirm that a record exists.

### 2.4 Path traversal and evidence handling

Filenames are reduced to a basename, then stripped to `[\w.\- ]`
(`sanitize_filename`), then stored under a fresh UUID-prefixed name. On read the
path is resolved and must sit inside `EVIDENCE_DIR`, and the SHA-256 must match
the register before a byte is served. Unauthenticated `GET` on `/api/evidence`
is refused before any of that.

Probes that all returned `404`: `/pages/admin.html`, `/../server.py`,
`/assets/../server.py`, `/%2e%2e/server.py`, `/pages/../../etc/passwd`.

### 2.5 Password and reset crypto

PBKDF2-HMAC-SHA256, 120,000 iterations, 16-byte per-user salt, compared with
`hmac.compare_digest`. Reset tokens are 32 bytes of `secrets.token_urlsafe`,
stored only as SHA-256, single-use, 30-minute expiry, and a successful reset
deletes every session for that user.

Account enumeration was tested and does not work: wrong-password and
unknown-address give the same `401 Invalid email or password.`; password reset
returns the same sentence for a known and an unknown address.

### 2.6 Rate limiting

Per-account (5 failures) and per-address (30), with `X-Forwarded-For` honoured
only when the TCP peer is in `NYAYA_TRUSTED_PROXIES`. Verified: with a **fresh
forged IP on every attempt**, requests 1–5 returned `400` and 6–8 returned
`429`. The header is no longer a reset button.

### 2.7 Disclosure redaction

An `ANONYMIZED` disclosure served to an anonymous guest correctly emptied
everything that identifies the complainant: `narrative` replaced with a marker,
`location` blank, `answers: {}`, `facts: {}`, `keywords: {}`, `intake_notes: []`,
evidence filenames `[hidden]`. The role-based engine output is retained, which is
the documented intent. Evidence bytes are not downloadable even by a logged-in
non-owner.

### 2.8 Frontend escaping

Every `${…}` interpolation of request-derived data in `pages/*.html` is wrapped
in `esc()`. A script scanned all template literals for user-controlled fields
(`narrative`, `comment`, `filename`, `provision`, …) appearing unescaped and
found none. `onclick="…('${esc(id)}')"` is the pattern, and ids are
server-generated hex, so there is no quote-breaking vector.

### 2.9 Safe defaults

Binds `127.0.0.1` unless explicitly overridden; generates its own administrator
password on first run rather than shipping one; refuses weak or banned admin
passwords; sends `Content-Security-Policy`, `nosniff`, `no-referrer`,
`Permissions-Policy`, and `no-store` on every response. Deeply nested JSON and
oversized bodies do not crash the process.

---

## 3. Findings

Ordered by what I would fix first.

### F1 — Session token is accepted from the URL and written to the access log · **Medium-High**

`assets/auth.js:97` reads `?st=<token>` and, if present, **adopts it in
preference to every other channel**. `server.py:2124` logs the full request line
including the query string.

Confirmed:

```
GET /dashboard?st=SUPERSECRETTOKEN123 HTTP/1.1" 200 -
```

appears verbatim in the server log. Because the token is deliberately left in
the address bar (documented rationale at `auth.js:84`), it also lands in browser
history, in any screenshot or screen-share of a case page, and in the
`Referer`-suppressed but still-present URL bar.

Two consequences beyond leakage:

- **Log-as-credential.** Anyone with read access to a deployment log — which is
  a much lower bar than database access — holds live 7-day sessions.
- **Session fixation.** `getToken()` prefers the URL over storage, so a link to
  `/login?st=<attacker-token>` silently replaces the victim's session with the
  attacker's. The attacker then reads whatever the victim files while "logged
  in". No cookie trickery required, and `SameSite=Lax` does not help because the
  token arrives in the URL, not the cookie.

The engineering goal behind `?st=` is real — a sandboxed preview iframe with
third-party cookies blocked genuinely has no other channel. But the fix is to
make the relay **additive and short-lived**, not authoritative and permanent:
accept `?st=` only to *bootstrap* (store it, then `history.replaceState` it out
of the URL), never let it override an existing session, and mint the relay token
as a separate short-TTL credential that cannot be used as a session.

### F2 — Session tokens stored in cleartext, never rotated · **Medium**

`sessions.token` holds the raw bearer token. The DB is a single file next to the
application; a backup, a copied `.sqlite3`, or any future path-traversal bug
converts directly into account takeover, with no cracking step.

Also: `/api/renew` returns `200` but **does not change the token** (verified —
the returned token equals the presented one). There is no rotation on privilege
change, no idle timeout, and no re-authentication for administrative actions.
Sessions live 7 days absolutely.

Store a hash of the token as the lookup key (the same pattern the reset tokens
already use — the codebase knows how to do this), and rotate on `renew`.

### F3 — Any site may frame the portal · **Medium**

`CSP` sets `frame-ancestors *` (`server.py:1699`). The stated reason is the
cross-origin preview iframe. That reasoning is fine for a demo host and wrong
for a deployment: it makes **clickjacking** trivial. An attacker page frames
`/case?id=…` and positions an invisible overlay over *Approve disclosure*, *Mark
verified*, or *Revoke disclosure*. The admin's session cookie rides along —
`SameSite=Lax` permits it inside a same-site frame, and the `?st=` relay permits
it everywhere else.

Make `frame-ancestors` an explicit allowlist from an environment variable
(default `'none'`), and enable it for the preview host only.

### F4 — CSP permits inline script · **Low-Medium**

`script-src 'self' 'unsafe-inline'`. Combined with a single escaping slip this
turns a reflected bug into working XSS; the escaping is currently clean, so this
is defence-in-depth, not a live hole. The pages inline all their JS, so the
honest fix is a nonce or hash per inline block rather than removing the
directive.

### F5 — No transport security, and the guard is opt-in · **Medium (deployment)**

No TLS listener and no HSTS. The application correctly refuses to bind beyond
loopback without `NYAYA_ALLOW_PUBLIC_BIND=1`, but `NYAYA_PREVIEW=1` sets the bind
to `0.0.0.0`. In that mode — plaintext HTTP, personal data, cleartext session
tokens in a `SameSite=Lax` cookie — a passive network observer is game over. The
docs say "no TLS!" and that is honest, but the switch is one environment
variable away from an operator making a career-defining mistake. Require an
explicit acknowledgement *and* refuse cookie-based auth over plaintext
non-loopback, or terminate TLS in the process.

### F6 — Account lockout is a denial-of-service primitive · **Low-Medium**

Five failed logins lock an account for 15 minutes, keyed on the account. The
trade-off is documented and the reasoning is sound (keying on address would let
one attacker lock out a whole shared network). But it does mean anyone who knows
a complainant's email can keep them out of their own case indefinitely with five
requests every 15 minutes. A progressive delay, or unlocking on a successful
login from a previously-seen device, would blunt it.

### F7 — Smaller items

- **In-memory rate table is unbounded** (`_RATE`). One entry per distinct
  account/IP; a spray from many addresses grows it without limit. Cap it or use
  a TTL sweep.
- **Password-reset has no per-address cap** beyond the general one; register is
  capped at 10/window, reset is not clearly capped, so it is an email-bomb
  vector once real mail transport is added.
- **Evidence `content_type` is taken from the client** and echoed back on
  download. `Content-Disposition: attachment` plus `nosniff` currently
  neutralises it (verified: served as `text/html`, but forced to download). Two
  correct behaviours are load-bearing here; make it a strict allowlist
  (`application/pdf`, `image/*`, `audio/*`, `text/plain`) and default to
  `application/octet-stream`.
- **Truly malformed input returns `500`, not `400`** — 5,000-deep nested JSON
  produced `{"error": "An internal error occurred."}` with a traceback on stdout.
  Correct outcome (no crash, no detail leaked to the client), wrong status code,
  and tracebacks should go to a log rather than the console.
- **No security audit trail.** The `audit` table records engine decisions. Failed
  authorisation attempts, admin actions, disclosure approvals and revocations
  are not recorded as security events.
- **No MFA, no session-device binding** for the administrator role.
- **Evidence directory inherits `0755`** from the process umask; case files are
  readable by any local user. `0700` would cost nothing.

---

## 4. What I would fix, in order

1. **F1** — stop treating `?st=` as authoritative; bootstrap-only, scrub it from
   the URL, and give relay tokens a separate short TTL. This is the finding that
   moves the score the most.
2. **F3 + F5** — `frame-ancestors` allowlist and a TLS story. Both are
   configuration-shaped and both are the difference between "demo" and "held
   responsible after an incident".
3. **F2** — hash session tokens at rest and rotate on `/api/renew`.
4. **F4** — CSP nonce for the inline scripts.
5. **F6/F7** — the list above, in whatever order the deployment context makes
   urgent.

---

## 5. The idea, rated

**7.5 / 10.**

The valuable thing here is not the portal. It is the insistence that a rule set
be *proved* — total over its case space, disjoint, and explicit about the
ambiguity it cannot resolve — and the analyser that finds its own gaps. That is
an unusually honest piece of engineering. Most legal-tech encodes a statute and
declares victory; this one enumerates 480 points and reports which ones two
readings both claim.

Four things cap the score:

- **Law is open-textured.** "Grievous hurt" turns on facts the statute does not
  enumerate. A pack decides a *model* of the section, and the model's edges are
  where real cases live. The packs say `encoded_unreviewed` in their own
  metadata, which is the only responsible posture — but it also means the
  headline numbers describe the encoding, not the law.
- **Automation bias.** Output that looks authoritative gets trusted. The design
  pushes the other way (fail-closed, doubt escalates to human review, no verdict,
  severity for routing only), which is exactly right, and is why this is 7.5 and
  not 6.
- **A wrong encoding is worse than no tool**, because it launders a mistake into
  a confident-looking artifact. The analyser mitigates this for *internal*
  consistency; it cannot detect a misreading of the statute.
- **The citizen portal is largely a vehicle** for the library, and it is where
  all the security exposure is. The interesting work has the smaller attack
  surface.

What would move it to 9: validating a sample of encoded sections against
judgments by actual practitioners, and showing the analyser catching a
real-world amendment before the courts had to.

---

## 6. Closing note

The security posture is better than the category average and better than the
project's age. Injection, authorisation, path handling and password storage are
all handled correctly and were verified by attack. The score is held down by one
design choice (`?st=` as an authoritative session channel) that undoes a good
deal of that care, and by the ordinary prototype gaps around TLS, framing and
session lifecycle.

The single most useful sentence in this review: **the portal's security is good
enough to be honest with users about, and not good enough to put a complainant's
narrative in front of the open internet.** Run it on loopback, as its own
defaults insist.
