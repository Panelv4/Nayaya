# Coverage roadmap — what "full Indian law" means here

Indian law is not one statute. The three 2024 codes alone are:

| Code | Sections | Replaces |
|---|---|---|
| Bharatiya Nyaya Sanhita (BNS) | 358 | Indian Penal Code (511 sections) |
| Bharatiya Nagarik Suraksha Sanhita (BNSS) | 531 | Code of Criminal Procedure (511 sections) |
| Bharatiya Sakshya Adhiniyam (BSA) | 170 | Indian Evidence Act (167 sections) |

Plus the Motor Vehicles Act, POCSO, IT Act, and hundreds of other statutes.
No single change can encode all of it — and a tool that claims to would be
lying. This document says what is encoded, what is next, and in what order.

## Encoded today (9 packs, 11,646 cases)

| Pack | Provisions | Case space | Status |
|---|---|---|---|
| `in.bns.homicide` | BNS ss.100–105 + Exceptions 1–5 | 10,752 | encoded_unreviewed |
| `in.bns.negligence` | BNS s.106 | 30 | encoded_unreviewed |
| `in.bns.abetment-suicide` | BNS ss.107–108 | 20 | encoded_unreviewed |
| `in.bns.attempt-murder` | BNS s.109 | 16 | encoded_unreviewed |
| `in.bns.attempt-culpable-homicide` | BNS s.110 | 8 | encoded_unreviewed |
| `in.bns.organised-crime` | BNS s.111 | 28 | encoded_unreviewed |
| `in.bns.petty-organised-crime` | BNS s.112 | 32 | encoded_unreviewed |
| `in.bns.terrorist-act` | BNS s.113 | 28 | encoded_unreviewed |
| `in.mv.drunken-driving` | MV Act s.185 | 732 | encoded_unreviewed |

Amendments shipped: 4 (2 real penalty changes, 1 interpretive, 1 hypothetical).

## Next, in order

Each step is one pack (or one chapter) with illustrations, ambiguities,
tests, and a generated `demo_out/` report — the same bar as the packs above.

1. **BNS ss.109–110** — attempt to murder and attempt to commit culpable
   homicide. ✓ Done (packs `in.bns.attempt-murder`, `in.bns.attempt-culpable-homicide`).
2. **BNS ss.111–113** — organised crime, petty organised crime, terrorist act.
   New in the BNS. ✓ Done (packs `in.bns.organised-crime`,
   `in.bns.petty-organised-crime`, `in.bns.terrorist-act`); each records a
   measured ambiguity about its contested definition.
3. **BNS ss.114–125** — hurt and grievous hurt (definitions + punishments).
   The hurt/grievous line is a list, so this pack is mostly a term table with
   a boundary test.
4. **BNS ss.126–141** — wrongful restraint, confinement, kidnapping, abduction.
   Fact-heavy (age, consent, lawful guardianship); the case space will be
   larger and will test the analyser's performance.
5. **BNS ss.142–158** — offences against women and children (sexual offences,
   dowry death, cruelty). High public importance; needs careful, honest
   ambiguity recording.
6. **BNS ss.159–170** — offences against property (theft, extortion, robbery,
   dacoity, cheating, misappropriation, criminal breach of trust). The
   theft/robbery/dacoity ladder is a natural defeater hierarchy.
7. **BNS remaining chapters** — offences against the state, public order,
   religion, documents, and the general exceptions (ss.1–44). The general
   exceptions (private defence, necessity, mistake of fact) cut across every
   offence pack and may belong in the library as shared defeaters.
8. **BNSS** — procedure is mostly not rules-as-code in the same sense
   (discretion, timelines, forms). Encode the *decidable* parts: limitation,
   bail conditions, compounding, and the new timelines. Expect many
   `indeterminate` outcomes — that is a finding, not a failure.
9. **BSA** — admissibility rules (hearsay, confessions, electronic records).
   Encode as defeaters over fact patterns rather than offences.
10. **MV Act beyond s.185** — ss.184 (dangerous driving), 196 (driving without
    licence), 201 (obstruction). Small packs, same format.

## What will never be encoded

- **Sentencing discretion** (rarest-of-rare, mitigating/aggravating factors).
  The packs record maxima; the choice within them is judicial, not rules.
- **Fact-finding.** The packs decide *given* facts. Whether the facts are
  proved is for a court, not the encoding.
- **Anything that needs a lawyer's reading first.** Every pack ships as
  `encoded_unreviewed`. One verified provision beats fifty seeded ones —
  the roadmap above is ordered so that each new pack is verified before the
  next is seeded.

## How to add a pack

```bash
# 1. Write nyayacode/packs/in.<area>.<topic>.json (see nyayacode/README.md)
# 2. python3 -m nyayacode check          # must pass: total, illustrations, no contention
# 3. python3 -m nyayacode analyze --pack <id> --out demo_out
# 4. Add statute tests in tests/test_nyayacode.py
# 5. Update this file, README.md and nyayacode/README.md pack tables
```
