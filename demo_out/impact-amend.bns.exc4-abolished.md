# Amendment impact — Repealing Exception 4 (sudden fight) — a hypothetical amendment

`amend.bns.exc4-abolished` · **HYPOTHETICAL** · not enacted

Exception 4 removes murder liability where death is caused in a sudden fight, in the heat of passion, without premeditation and without undue advantage. This hypothetical amendment repeals the exception and leaves everything else untouched. It is the cleanest possible demonstration: one statutory sentence disappears, and the tool reports exactly which cases change side.

Encoded by `in.bns.homicide` — encoded_unreviewed (NOT yet reviewed against the statute text)

## Result

Case space compared: **10,752** points (10,752 fact combinations).

| Measure | Count | Share of case space |
|---|---|---|
| Decisions that change | **256** | 2.38% |
| Sentences that change (offence unchanged) | **0** | 0.0% |
| Unaffected | 10,496 | 97.62% |

## Before / after, cell by cell

Rows are the outcome before the amendment, columns after. Every row sums to the number of points that had that outcome before.

| before \ after | culpable_homicide | murder | not_offence | total |
|---|---|---|---|---|
| **not_offence** |  |  | 6,144 | 6,144 |
| **murder** |  | 1,408 |  | 1,408 |
| **culpable_homicide** | 2,944 | 256 |  | 3,200 |

## Minimal cases that change

Each line is one case reduced to the facts that actually decide it — every other fact is at its neutral value, so the difference is visible. Counts show how many enumerated cases share that transition.

| Case | Before | After | Moved because | Cases |
|---|---|---|---|---|
| `death_caused=True`, `mens_rea=intention_death`, `exception_state=sudden_fight` | culpable_homicide | murder | `D-EXC4-SUDDEN-FIGHT` → `M-101a` (decision) | 256 |

## Did it do what it should?

Cases that relied on Exception 4 — sudden fight, no undue advantage, and a mental element that would otherwise be murder — become murder instead of culpable homicide not amounting to murder. Nothing else should move.

The measurement: **256** decisions and **0** sentences moved. Compare that against the sentence above — a mismatch is either a wrong encoding or a wrong prediction, and both are worth knowing.

## Integrity

- Decision digest before: `d02ad1751b088194`
- Decision digest after: `da48749cbae78243`
- The digest is a hash of the decision for every point in the case space. Two packs with the same digest decide every case identically, which makes it usable as a regression test on the law itself.
