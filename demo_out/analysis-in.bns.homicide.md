# Analysis — `in.bns.homicide`

**Culpable homicide, murder and the five exceptions — BNS 2023 ss.100-105**

- Review status: **encoded_unreviewed (NOT yet reviewed against the statute text)**
- Facts: 10 · case space enumerated: **10,752** points
- Decision digest: `d02ad1751b088194`

## 1. Gaps and contentions

| Check | Result | Reading |
|---|---|---|
| Cases where no provision applies | **0** of 10,752 | none: every case in the declared domain is decided by some provision |
| Undeclared contentions | **0** of 10,752 | none: no two provisions disagree without the pack saying which wins |
| Designed overrides (exceptions doing their job) | 1,664 | counted, not defects |
| Unreachable provisions | **0** | every provision can fire somewhere in the domain |

## 2. Recorded ambiguities, measured

Each ambiguity is a question the text does not settle. The pack records both readings; the analyser decides the whole case space under each and counts how many cases move. A reading that moves nothing is not a real dispute.

| Ambiguity | Provision | Decisions moved | Sentences moved |
|---|---|---|---|
| `AMB-101b-PARTICULARISED` | s.101(b) | 768 | 0 |
| `AMB-103-2-MINIMUM` | s.103(2) | 0 | 352 |
| `AMB-101d-EXCUSE` | s.101(d) | n/a (one reading recorded) | n/a |
| `AMB-EXC4-MUTUALITY` | s.101 Exception 4 | n/a (one reading recorded) | n/a |

- **AMB-101b-PARTICULARISED** — Does s.101(b) require knowledge directed at the particular victim, or is it satisfied by knowledge that injury of that kind is likely to cause death in general?
- **AMB-103-2-MINIMUM** — Does s.103(2) carry a statutory floor of seven years for members of a group of five or more?

## 3. Statutory illustrations reproduced

9 of 9 illustrations printed in the statute are reproduced by the encoding. This is the only correctness evidence a machine can produce on its own; it is not a substitute for a lawyer reading the pack.

| Illustration | Cites | Expected | Encoding | |
|---|---|---|---|---|
| `ILL-100-a` | s.100 illustration (a) | culpable_homicide | culpable_homicide | pass |
| `ILL-100-b` | s.100 illustration (b) | murder | murder | pass |
| `ILL-100-c` | s.100 illustration (c) | not an offence | not an offence | pass |
| `ILL-101-c` | s.101 illustration to limb (c) | murder | murder | pass |
| `ILL-101-EXC1-WRONG-VICTIM` | s.101 Exception 1 illustration | culpable_homicide | culpable_homicide | pass |
| `ILL-101-EXC1-PROVOKED-AS-EXCUSE` | s.101 Exception 1 proviso (a) illustration | murder | murder | pass |
| `ILL-101-EXC2-HORSEWHIP` | s.101 Exception 2 illustration | culpable_homicide | culpable_homicide | pass |
| `ILL-101-EXC4-SUDDEN-FIGHT` | s.101 Exception 4 | culpable_homicide | culpable_homicide | pass |
| `NEG-DISEASED-VICTIM` | s.101 limb (b) illustration | murder | murder | pass |

## 4. Scope

**Encoded:** s.100 culpable homicide; s.101 murder; s.101 Exceptions 1-5; s.102 transferred malice; s.103 punishment for murder; s.104 murder by life-convict; s.105 culpable homicide not amounting to murder

**Deliberately not encoded:** s.106 death by negligence (separate pack in.bns.negligence); ss.107-108 abetment of suicide (separate pack in.bns.abetment-suicide); s.109 attempt to murder (separate pack in.bns.attempt-murder); s.299-304 IPC (repealed 1 July 2024); sentencing discretion (rarest-of-rare doctrine); private defence under ss.34-44 beyond the Exception 2 excess case
