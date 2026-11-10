# Amendment impact — Reading s.101(b) down to generic knowledge — a proposed change to the homicide encoding

`amend.bns.101b-generic-knowledge` · **INTERPRETIVE** · not enacted

s.101(b) requires intention of bodily injury 'as the offender knows to be likely to cause the death of the person to whom the harm is caused'. One reading confines that knowledge to the particular victim; the other lets generic knowledge that the injury inflicted is likely to kill suffice. This amendment applies the generic reading — a bigger change to the law than most amendments, and it is the kind of change courts make silently.

Encoded by `in.bns.homicide` — encoded_unreviewed (NOT yet reviewed against the statute text)

## Result

Case space compared: **10,752** points (10,752 fact combinations).

| Measure | Count | Share of case space |
|---|---|---|
| Decisions that change | **768** | 7.14% |
| Sentences that change (offence unchanged) | **0** | 0.0% |
| Unaffected | 9,984 | 92.86% |

## Before / after, cell by cell

Rows are the outcome before the amendment, columns after. Every row sums to the number of points that had that outcome before.

| before \ after | culpable_homicide | murder | not_offence | total |
|---|---|---|---|---|
| **not_offence** |  |  | 6,144 | 6,144 |
| **murder** |  | 1,408 |  | 1,408 |
| **culpable_homicide** | 2,432 | 768 |  | 3,200 |

## Minimal cases that change

Each line is one case reduced to the facts that actually decide it — every other fact is at its neutral value, so the difference is visible. Counts show how many enumerated cases share that transition.

| Case | Before | After | Moved because | Cases |
|---|---|---|---|---|
| `death_caused=True`, `mens_rea=intention_injury_likely_death` | culpable_homicide | murder | `B-100-CULPABLE-ONLY` → `M-101b-GENERIC` (decision) | 768 |

## Did it do what it should?

Every case with intention of injury likely to cause death moves from culpable homicide under s.105 to murder under s.103. That is the set the two readings disagree about, and the number measures how much turns on the interpretation.

The measurement: **768** decisions and **0** sentences moved. Compare that against the sentence above — a mismatch is either a wrong encoding or a wrong prediction, and both are worth knowing.

## Integrity

- Decision digest before: `d02ad1751b088194`
- Decision digest after: `e4b40ff2e693b3f9`
- The digest is a hash of the decision for every point in the case space. Two packs with the same digest decide every case identically, which makes it usable as a regression test on the law itself.
