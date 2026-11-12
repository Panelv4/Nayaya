# Analysis — `in.bns.abetment-suicide`

**Abetment of suicide — BNS 2023 s.107**

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
| `AMB-107-MENTAL-ILLNESS` | s.107(2) | n/a (one reading recorded) | n/a |


## 3. Statutory illustrations reproduced

5 of 5 illustrations printed in the statute are reproduced by the encoding. This is the only correctness evidence a machine can produce on its own; it is not a substitute for a lawyer reading the pack.

| Illustration | Cites | Expected | Encoding | |
|---|---|---|---|---|
| `ILL-107-1` | s.107(1), text | abetment_suicide | abetment_suicide | pass |
| `ILL-107-2-CHILD` | s.107(2), text | abetment_suicide_vulnerable | abetment_suicide_vulnerable | pass |
| `ILL-107-NO-SUICIDE` | s.107, 'commission of suicide' | not an offence | not an offence | pass |
| `ILL-107-NO-ABETMENT` | s.107, 'abets the commission' | not an offence | not an offence | pass |
| `ILL-107-INTOXICATED` | s.107(2), text | abetment_suicide_vulnerable | abetment_suicide_vulnerable | pass |

## 4. Scope

**Encoded:** s.107(1) abetment of suicide (up to twelve years); s.107(2) abetment of suicide of a child, person with mental illness, delirious or intoxicated person (death, life, or ten years minimum)

**Deliberately not encoded:** ss.100-106 homicide and negligence (separate packs in.bns.homicide, in.bns.negligence); s.108 attempt to murder (separate pack in.bns.attempt-murder); abetment generally (BNS s.45: instigation, conspiracy, aiding); sentencing discretion within the maxima
