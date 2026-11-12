# nyayacode — README

A small, dependency-free Python library that encodes a statute as data, and then
does two things a person cannot do by reading the text:

1. **Decides every case in a declared fact space**, and reports where the rules
   fall through, contradict each other, or contain provisions that can never fire.
2. **Measures an amendment.** Change the law, re-decide the whole case space, and
   count exactly which cases move — separately for the offence and the sentence.

It is deterministic rules-as-code library code. No model, no inference, no
network call: given the same pack it produces the same decision and the same
digest, forever.

```
python3 -m nyayacode list
python3 -m nyayacode check
python3 -m nyayacode analyze --pack in.bns.homicide --out demo_out
python3 -m nyayacode impact  --amendment amend.bns.exc4-abolished --out demo_out
python3 -m nyayacode explain --pack in.bns.homicide \
        --fact death_caused=true --fact mens_rea=intention_injury_sufficient \
        --fact exception_state=sudden_fight
```

Runs on the Python standard library alone (3.10+). There is no `pip install`.

---

## The headline result

Repeal Exception 4 of BNS s.101 (sudden fight) and change nothing else:

| | Cases | Share of the 10,752-case space |
|---|---|---|
| Decisions that move | **256** | 2.38% |
| Sentences that move | 0 | — |
| Unaffected | 10,496 | 97.62% |

All 256 move `culpable_homicide → murder`. The tool reduces the change to a
**minimal witness** of three facts —
`death_caused=true, mens_rea=intention_death, exception_state=sudden_fight` — so
the reader sees the case, not a row of an enumeration. That prediction is written
in the amendment file *before* the run; the numbers are the check on it.

Four amendments ship, because they are different claims and should not be mixed:

| Amendment | Kind | Decisions | Sentences |
|---|---|---|---|
| `amend.mv.2019-penalty` — MV Act s.185 fines raised | **real** (2019) | 0 | **273** of 732 |
| `amend.bns.101b-generic-knowledge` — s.101(b) read down | **interpretive** | **768** of 10,752 | 0 |
| `amend.bns.exc4-abolished` — Exception 4 repealed | **hypothetical** | **256** of 10,752 | 0 |
| `amend.bns.106-penalty` — BNS s.106(1) penalty raised from two to five years | **real** (2024) | 0 | **4** of 30 |

The first is why decisions and sentences are counted separately: a verdict-only
comparison would report a famous amendment as a no-op.

---

## The rule format

A pack is one JSON document. It contains the encoded provisions **and** the
evidence needed to judge whether the encoding is faithful.

```jsonc
{
  "id": "in.bns.homicide",
  "review": { "status": "encoded_unreviewed", "by": null, "on": null, "method": "…" },
  "sources": [ { "id": "bns-2023", "citation": "…", "url": "…", "kind": "primary" } ],
  "facts":   [ { "name": "mens_rea", "type": "enum", "values": [...] } ],
  "branches": [ { "id": "M-101a", "provision": "s.101(a)", "verdict": "offence",
                  "offence": "murder", "when": {…}, "text": "…", "citations": [...] } ],
  "defeaters": [ { "id": "D-EXC4-SUDDEN-FIGHT", "verdict": "offence",
                   "offence": "culpable_homicide", "when": {…},
                   "overrides": ["M-101a", "M-101b"], "text": "…" } ],
  "punishment_rules": [ { "when": {…}, "text": "…", "citations": [...] } ],
  "ambiguities": [ { "id": "AMB-…", "question": "…", "position_a": "…",
                     "position_b": "…", "variants": [ { "id": "…", "patch": {…} } ] } ],
  "illustrations": [ { "id": "ILL-100-a", "facts": {…}, "expect": {…}, "text": "…" } ]
}
```

Three design choices carry most of the weight:

**Defeaters are first class.** A statute that says *"except in the cases
hereinafter excepted"* is not a list of rules; it is a list of rules plus
overrides. Encoding exceptions as `overrides` lets the analyser tell a *designed*
override (an exception doing its job) from an *undeclared* contention (two
provisions disagreeing and nobody saying which wins). The first is structure; the
second is a defect.

**Totality is required.** Every condition must evaluate against every point of the
declared fact space. A typed `var` carries a default, so a missing fact yields the
declared default rather than a silent `false`. A pack that is not total cannot be
analysed and is rejected at load time.

**A verdict is a closed set:** `offence`, `not_offence`, `indeterminate`. Anything
else is a bug, not a nuance.

---

## What the analysis reports

| Check | Question | Why it matters |
|---|---|---|
| **Gaps** | Are there cases no provision decides? | Either the statute is silent (a gap a legislature could close) or the encoding is incomplete. The tool refuses to guess which. |
| **Undeclared contentions** | Do two provisions disagree without the pack saying which wins? | The outcome would then depend on evaluation order — on the author, not on law. |
| **Designed overrides** | How often does an exception override a limb? | Counted, not flagged. If this is zero, the exceptions are doing nothing. |
| **Unreachable provisions** | Can any limb never fire? | Dead law, or a mis-specified condition. |
| **Ambiguity sensitivity** | If the other reading of a disputed phrase were adopted, how many cases move? | Turns "this phrase is ambiguous" into "this phrase is worth N cases". |
| **Illustrations** | Does the encoding reproduce the examples printed in the statute? | The only correctness evidence a machine can produce unaided. |

Output is exhaustive over the declared domain, so the numbers are proofs about
that domain — not samples. They are only as good as the fact list, which is why
every pack declares its facts and prints the domain size beside every result.

### Measured ambiguities

Where the text is genuinely open, the pack records both readings and the analyser
counts what the choice is worth:

| Dispute | What moves |
|---|---|
| BNS s.101(b) — knowledge particularised to the victim, or generic? | 768 decisions (murder ↔ s.105) |
| BNS s.103(2) — is there a seven-year floor? (secondary sources disagree) | 352 sentences |
| MV Act s.185 — is there a three-year window for the repeat offence? | 182 sentences |

---

## Amendments

An amendment is a patch plus context:

```jsonc
{ "id": "amend.bns.exc4-abolished",
  "pack": "in.bns.homicide",
  "kind": "hypothetical",          // real | interpretive | hypothetical
  "enacted": false,
  "commencement": null,
  "before": {},
  "after":  { "remove_branches": ["D-EXC4-SUDDEN-FIGHT"] } }
```

`kind` is mandatory and appears in every output. Comparison runs over the **union**
of the two packs' fact domains, so an amendment that introduces a new fact is
still measurable. Changed points are reduced by delta-debugging to a minimal
witness.

---

## Packs shipped

| Pack | Provisions | Case space | Review status |
|---|---|---|---|
| `in.bns.homicide` | BNS 2023 ss.100-105 and Exceptions 1-5 | 10,752 | **unreviewed** |
| `in.bns.negligence` | BNS 2023 s.106 (negligence and dangerous driving) | 30 | **unreviewed** |
| `in.bns.abetment-suicide` | BNS 2023 ss.107-108 (abetment of suicide) | 20 | **unreviewed** |
| `in.bns.attempt-murder` | BNS 2023 s.109 (attempt to murder) | 16 | **unreviewed** |
| `in.bns.attempt-culpable-homicide` | BNS 2023 s.110 (attempt to commit culpable homicide) | 8 | **unreviewed** |
| `in.bns.organised-crime` | BNS 2023 s.111 (organised crime) | 28 | **unreviewed** |
| `in.bns.petty-organised-crime` | BNS 2023 s.112 (petty organised crime) | 32 | **unreviewed** |
| `in.bns.terrorist-act` | BNS 2023 s.113 (terrorist act) | 28 | **unreviewed** |
| `in.mv.drunken-driving` | MV Act 1988 s.185, pre and post 2019 | 732 | **unreviewed** |

The second pack exists to show the machinery is not specific to a penal code:
s.185 has a numeric threshold instead of a mental element, two limbs that are
alternatives rather than a hierarchy, and an amendment that moves no verdict at
all. The analyser, the amendment format and the report are unchanged.

The third pack (`in.bns.negligence`) exists to show the boundary between two
packs: s.106 applies only to a rash or negligent act "not amounting to
culpable homicide", so its encoding must say where that line falls. Its
recorded ambiguity — does knowledge of the *possibility* of death amount to
culpable homicide, or is it still rashness? — moves 3 of its 30 cases.

### Review status is the honest part

`encoded_unreviewed` means exactly that. All three packs reproduce every
illustration printed in the statute and the analyser finds no gaps or
undeclared contentions in them. **That is not the same as being right.** A
lawyer reading the provisions against the India Code text is the only thing
that moves a pack to `reviewed`, and no amount of passing tests substitutes
for it.

---

## What the analyser caught in this repository

Not hypothetical — these were found by running the tool on its own packs:

* **Murder without a death.** Every s.101 limb omitted `death_caused`; only the
  "no death" branch tested it. The overlap detector reported 6,272 contentions
  because murder was firing on deaths that had not occurred. Fixed by gating every
  provision on the s.100 actus reus.
* **A missing lawful outcome.** Below-threshold driving under MV s.185 fell through
  every branch, so the gap finder reported 93 "gaps" that were simply lawful
  conduct. Fixed by making the fall-through explicit.
* **An amendment that did nothing.** `remove_branches` filtered branches but not
  defeaters, so repealing Exception 4 reported zero movement. The comparison's own
  numbers were the evidence.
* **A citation checker that was never called**, and int facts that silently
  defaulted to a range instead of being required.

Each is now a regression test, including negative tests that break a pack on
purpose and assert the analyser catches it. A tool that reports "no problems" on a
deliberately broken pack is worse than no tool.

---

## Tests

```
python3 -m pytest tests/ -q        # or: python3 tests/test_nyayacode.py
python3 -m nyayacode check         # every pack still reproduces its statute
```

43 tests: evaluator semantics, pack validation, the statutory illustrations,
amendment arithmetic, and the negative tests above.

---

## Limits

* **The domain is the argument.** Analysis is exhaustive over the declared facts.
  A fact nobody thought of is invisible, and the report will look just as clean.
* **Packs decide, they do not interpret.** Where the text is genuinely open the
  pack records both readings and measures the difference. It does not choose.
* **Sentencing is coarse.** Punishment rules select a statutory range; they do not
  model discretion or aggravating circumstances.
* **Scope is stated, not implied.** Each pack lists what it deliberately does not
  encode (s.106 negligence, s.108 attempt, ss.34-44 private defence beyond the
  Exception 2 excess case, and so on).

---

## Sources

* Bharatiya Nyaya Sanhita, 2023 (Act 45 of 2023), ss.100-105 —
  [India Code](https://www.indiacode.nic.in/bitstream/123456789/20062/1/a202345.pdf)
* Motor Vehicles Act, 1988, s.185, as amended by the Motor Vehicles (Amendment)
  Act, 2019 — [India Code](https://www.indiacode.nic.in/handle/123456789/1798)

Secondary commentaries were used **only** as evidence that a text is reproduced
inconsistently; every dispute they revealed is recorded as an unresolved
ambiguity, not silently resolved.

---

## Licence

MIT. See `LICENSE`.

Not legal advice. An analysis of an encoding.

---

## About this repository

`nyayacode/` is the library. The `portal/` application in this repository (a
citizen case-reporting prototype) is one consumer of it, kept to show the engine
can drive a real workflow; it is not the argument. See the root `README.md`.
