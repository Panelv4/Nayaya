# Analysis — `in.bns.attempt-culpable-homicide`

**Attempt to commit culpable homicide — BNS 2023 s.110**

- Review status: **encoded_unreviewed (NOT yet reviewed against the statute text)**
- Facts: 3 · case space enumerated: **8** points
- Decision digest: `45e86e7c5450760d`

## 1. Gaps and contentions

| Check | Result | Reading |
|---|---|---|
| Cases where no provision applies | **0** of 8 | none: every case in the declared domain is decided by some provision |
| Undeclared contentions | **0** of 8 | none: no two provisions disagree without the pack saying which wins |
| Designed overrides (exceptions doing their job) | 0 | counted, not defects |
| Unreachable provisions | **0** | every provision can fire somewhere in the domain |

## 2. Recorded ambiguities, measured

Each ambiguity is a question the text does not settle. The pack records both readings; the analyser decides the whole case space under each and counts how many cases move. A reading that moves nothing is not a real dispute.

| Ambiguity | Provision | Decisions moved | Sentences moved |
|---|---|---|---|
| `AMB-110-MENS-REA-BOUNDARY` | s.110 | n/a (one reading recorded) | n/a |


## 3. Statutory illustrations reproduced

4 of 4 illustrations printed in the statute are reproduced by the encoding. This is the only correctness evidence a machine can produce on its own; it is not a substitute for a lawyer reading the pack.

| Illustration | Cites | Expected | Encoding | |
|---|---|---|---|---|
| `ILL-110-1` | s.110, illustration | attempt_culpable_homicide | attempt_culpable_homicide | pass |
| `ILL-110-HURT` | s.110, 'if hurt is caused' | attempt_culpable_homicide_hurt | attempt_culpable_homicide_hurt | pass |
| `ILL-110-DEATH` | s.110, 'if he by that act caused death' | not an offence | not an offence | pass |
| `ILL-110-NO-ATTEMPT` | s.110, 'does any act' | not an offence | not an offence | pass |

## 4. Scope

**Encoded:** s.110 attempt to commit culpable homicide (up to three years); s.110 attempt to commit culpable homicide with hurt caused (up to seven years)

**Deliberately not encoded:** ss.100-105 culpable homicide and murder (separate pack in.bns.homicide); s.106 causing death by negligence (separate pack in.bns.negligence); ss.107-108 abetment of suicide (separate pack in.bns.abetment-suicide); s.109 attempt to murder (separate pack in.bns.attempt-murder); sentencing discretion within the maxima
