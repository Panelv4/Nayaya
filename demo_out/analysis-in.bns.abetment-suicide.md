# Analysis — `in.bns.abetment-suicide`

**Abetment of suicide — BNS 2023 ss.107-108**

- Review status: **encoded_unreviewed (NOT yet reviewed against the statute text)**
- Facts: 3 · case space enumerated: **20** points
- Decision digest: `58aed6d1ae85cb74`

## 1. Gaps and contentions

| Check | Result | Reading |
|---|---|---|
| Cases where no provision applies | **0** of 20 | none: every case in the declared domain is decided by some provision |
| Undeclared contentions | **0** of 20 | none: no two provisions disagree without the pack saying which wins |
| Designed overrides (exceptions doing their job) | 0 | counted, not defects |
| Unreachable provisions | **0** | every provision can fire somewhere in the domain |

## 2. Recorded ambiguities, measured

Each ambiguity is a question the text does not settle. The pack records both readings; the analyser decides the whole case space under each and counts how many cases move. A reading that moves nothing is not a real dispute.

| Ambiguity | Provision | Decisions moved | Sentences moved |
|---|---|---|---|
| `AMB-107-MENTAL-ILLNESS` | s.107 | n/a (one reading recorded) | n/a |


## 3. Statutory illustrations reproduced

5 of 5 illustrations printed in the statute are reproduced by the encoding. This is the only correctness evidence a machine can produce on its own; it is not a substitute for a lawyer reading the pack.

| Illustration | Cites | Expected | Encoding | |
|---|---|---|---|---|
| `ILL-108-1` | s.108, text | abetment_suicide | abetment_suicide | pass |
| `ILL-107-CHILD` | s.107, text | abetment_suicide_vulnerable | abetment_suicide_vulnerable | pass |
| `ILL-NO-SUICIDE` | ss.107-108, 'commits suicide' | not an offence | not an offence | pass |
| `ILL-NO-ABETMENT` | ss.107-108, 'abets the commission' | not an offence | not an offence | pass |
| `ILL-107-INTOXICATED` | s.107, text | abetment_suicide_vulnerable | abetment_suicide_vulnerable | pass |

## 4. Scope

**Encoded:** s.107 abetment of suicide of a child or person with mental illness, delirious or intoxicated (death, life, or up to ten years); s.108 abetment of suicide (up to ten years)

**Deliberately not encoded:** ss.100-106 homicide and negligence (separate packs in.bns.homicide, in.bns.negligence); s.109 attempt to murder (separate pack in.bns.attempt-murder); s.110 attempt to commit culpable homicide (separate pack in.bns.attempt-culpable-homicide); abetment generally (BNS s.45: instigation, conspiracy, aiding); sentencing discretion within the maxima
