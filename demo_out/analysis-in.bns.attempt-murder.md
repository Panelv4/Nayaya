# Analysis — `in.bns.attempt-murder`

**Attempt to murder — BNS 2023 s.109**

- Review status: **encoded_unreviewed (NOT yet reviewed against the statute text)**
- Facts: 4 · case space enumerated: **16** points
- Decision digest: `77f197fde9bcfc2f`

## 1. Gaps and contentions

| Check | Result | Reading |
|---|---|---|
| Cases where no provision applies | **0** of 16 | none: every case in the declared domain is decided by some provision |
| Undeclared contentions | **0** of 16 | none: no two provisions disagree without the pack saying which wins |
| Designed overrides (exceptions doing their job) | 0 | counted, not defects |
| Unreachable provisions | **0** | every provision can fire somewhere in the domain |

## 2. Recorded ambiguities, measured

Each ambiguity is a question the text does not settle. The pack records both readings; the analyser decides the whole case space under each and counts how many cases move. A reading that moves nothing is not a real dispute.

| Ambiguity | Provision | Decisions moved | Sentences moved |
|---|---|---|---|
| `AMB-109-ATTEMPT-LINE` | s.109 | n/a (one reading recorded) | n/a |


## 3. Statutory illustrations reproduced

7 of 7 illustrations printed in the statute are reproduced by the encoding. This is the only correctness evidence a machine can produce on its own; it is not a substitute for a lawyer reading the pack.

| Illustration | Cites | Expected | Encoding | |
|---|---|---|---|---|
| `ILL-109-A` | s.109, illustration (a) | attempt_murder | attempt_murder | pass |
| `ILL-109-B` | s.109, illustration (b) | attempt_murder | attempt_murder | pass |
| `ILL-109-C-PREP` | s.109, illustration (c), first limb | not an offence | not an offence | pass |
| `ILL-109-C-FIRE` | s.109, illustration (c), second limb | attempt_murder_hurt | attempt_murder_hurt | pass |
| `ILL-109-D-PREP` | s.109, illustration (d), first limb | not an offence | not an offence | pass |
| `ILL-109-D-PLACE` | s.109, illustration (d), second limb | attempt_murder | attempt_murder | pass |
| `ILL-109-LIFE-CONVICT` | s.109(2), text | attempt_murder_life_convict | attempt_murder_life_convict | pass |

## 4. Scope

**Encoded:** s.109(1) attempt to murder (up to ten years); s.109(1) attempt to murder with hurt caused (life); s.109(2) attempt to murder by a person under a life sentence with hurt caused (death or remainder of natural life)

**Deliberately not encoded:** ss.100-105 culpable homicide and murder (separate pack in.bns.homicide); s.106 causing death by negligence (separate pack in.bns.negligence); ss.107-108 abetment of suicide (separate pack in.bns.abetment-suicide); s.110 attempt to commit culpable homicide (separate pack in.bns.attempt-culpable-homicide); sentencing discretion within the maxima
