# Demo outputs

Every file here is generated — nothing is hand-written. Regenerate with:

```bash
python3 -m nyayacode analyze --pack in.bns.homicide --out demo_out
python3 -m nyayacode analyze --pack in.bns.negligence --out demo_out
python3 -m nyayacode analyze --pack in.mv.drunken-driving --out demo_out
python3 -m nyayacode impact  --amendment amend.bns.exc4-abolished --out demo_out
python3 -m nyayacode impact  --amendment amend.bns.101b-generic-knowledge --out demo_out
python3 -m nyayacode impact  --amendment amend.bns.106-penalty --out demo_out
python3 -m nyayacode impact  --amendment amend.mv.2019-penalty --out demo_out
```

## The headline: one provision changes, 256 cases change side

`impact-amend.bns.exc4-abolished.md` — Exception 4 (sudden fight) is repealed and
everything else is left alone.

| | Cases | Of case space |
|---|---|---|
| Decisions that move | **256** | 2.38% of 10,752 |
| Sentences that move | 0 | — |
| Unaffected | 10,496 | 97.62% |

Every one of the 256 moves `culpable_homicide → murder`, because that is the only
thing Exception 4 does. The minimal witness is three facts:
`death_caused=true, mens_rea=intention_death, exception_state=sudden_fight`.
That prediction is written in the amendment file *before* the run, and the numbers
are the check on it.

## Three amendments, three different kinds of change

| Amendment | Kind | Decisions | Sentences |
|---|---|---|---|
| `amend.mv.2019-penalty` | **real** — the 2019 Act did this | 0 | **273** of 732 |
| `amend.bns.101b-generic-knowledge` | **interpretive** — a court could do this | **768** of 10,752 | 0 |
| `amend.bns.exc4-abolished` | **hypothetical** — nobody has proposed it | **256** of 10,752 | 0 |

The first is the one that shows why decisions and sentences are counted separately:
the 2019 amendment raised fines without touching what counts as an offence, so a tool
that only compared verdicts would report a famous amendment as a no-op.

## Analysis reports

`analysis-in.bns.homicide.md` — BNS ss.100-105 across 10,752 cases: 0 gaps, 0
undeclared contentions, 0 unreachable provisions, 9 of 9 statutory illustrations
reproduced, 1,664 designed overrides counted.

`analysis-in.mv.drunken-driving.md` — the same machinery on a non-penal statute,
732 cases, so the generality claim is not just an assertion.

## Measured ambiguities

Where the text is genuinely open the pack records both readings and the analyser
counts what the choice is worth:

| Dispute | What moves |
|---|---|
| s.101(b) — knowledge particularised to the victim, or generic? | 768 decisions (murder ↔ s.105) |
| s.103(2) — is there a seven-year floor? (secondary sources disagree) | 352 sentences |
| MV s.185 — is there a three-year window for the repeat offence? | 182 sentences |

`engine-page.png` — the same results rendered by `pages/engine.html`, which reads
`/api/engine/overview` and `/api/engine/impact`. The page is a viewer; the
analysis happens in the library and the CLI.
