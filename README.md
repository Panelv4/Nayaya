# nyayacode

**Encode a statute as data. Then make the encoding prove itself.**

`nyayacode` is a small, dependency-free Python library that turns a statute into
rules-as-code and then asks the two questions you cannot answer by reading the
text:

1. **Does the law, as encoded, actually decide every case — or does it fall
   through, contradict itself, or contain provisions that can never fire?**
2. **If this provision changed, exactly which cases would change with it?**

Deterministic rules-as-code. No model, no inference, no network call: same pack in,
same decision and same digest out, forever. Python standard library only.

```bash
git clone <this repo> && cd <repo>
python3 -m nyayacode check                        # no install, no dependencies
python3 -m nyayacode impact --amendment amend.bns.exc4-abolished
```

---

## The headline

Take the Bharatiya Nyaya Sanhita, 2023, ss.100–105 — culpable homicide, murder and
the five exceptions — and encode it. That is **10,752 distinct cases**: every
combination of mental element, exception, proviso and aggravating fact.

Now repeal Exception 4 (sudden fight in the heat of passion) and change nothing
else.

| | Cases | Share |
|---|---|---|
| Decisions that move | **256** | 2.38% |
| Sentences that move | 0 | — |
| Unaffected | 10,496 | 97.62% |

All 256 move `culpable_homicide → murder`, and the tool reduces the change to the
three facts that actually decide it:

```
death_caused=true, mens_rea=intention_death, exception_state=sudden_fight
```

That prediction is written into the amendment file *before* the run. The numbers
are the check on the prediction, not a restatement of it. Full output in
[`demo_out/impact-amend.bns.exc4-abolished.md`](demo_out/impact-amend.bns.exc4-abolished.md).

### Why sentences are counted separately

| Amendment | Kind | Decisions | Sentences |
|---|---|---|---|
| MV Act s.185 fines raised (2019) | **real** — a legislature did this | 0 | **273** of 732 |
| BNS s.101(b) read down to generic knowledge | **interpretive** — a court could | **768** of 10,752 | 0 |
| BNS Exception 4 repealed | **hypothetical** — nobody has proposed it | **256** of 10,752 | 0 |

The first is the argument. A tool that only compared verdicts would report a famous
amendment — the 2019 Motor Vehicles Act penalty hike — as a **no-op**. It changed
nothing about what counts as an offence, and everything about what it costs. The
kind of change (`real`, `interpretive`, `hypothetical`) is mandatory in every
amendment and printed on every output, because those are different claims.

---

## Ambiguity, measured

Pointing out that a provision is ambiguous is table stakes. This counts what the
ambiguity is worth.

Secondary sources genuinely reproduce BNS s.103(2) in two different forms, and MV
Act s.185 in two different forms. Rather than silently picking one, the pack records
both readings and the analyser decides the entire case space under each:

| Disputed reading | What moves |
|---|---|
| BNS s.101(b) — knowledge particularised to the victim, or generic? | **768 decisions** (murder ↔ s.105) |
| BNS s.103(2) — is there a seven-year floor for group murder? | **352 sentences** |
| MV Act s.185 — is there a three-year window for the repeat offence? | **182 sentences** |

---

## Graded answers, and why doubt never resolves itself

Intake rarely produces clean booleans. A caller may say a victim *might* have a
disability, or a form may carry a likelihood such as `0.7`. `uncertainty.py`
names five levels on a 0..1 scale:

| Likelihood | Label | Meaning |
|---|---|---|
| `p >= 0.90` | `TRUE` | definitely true |
| `0.65 – 0.90` | `MAYBE` | leans true |
| `0.50 – 0.65` | `MIGHT_BE` | possible, slight lean true |
| `0.35 – 0.50` | `MIGHT_NOT_BE` | possible, slight lean false |
| `0.10 – 0.35` | `MAYBE_NOT` | leans false |
| `p < 0.10` | `FALSE` | definitely false |

The rule is deliberately blunt: **every graded band collapses to `UNKNOWN`**,
never to `TRUE` or `FALSE`. In a triage tool, doubt must raise human review — a
`maybe` on a disability flag becomes an unknown flag, and on a serious matter
that fires T-17 ("material facts missing/contradictory") and escalates the case
to mandatory judicial review. The report names each graded fact in its open
questions, so a collapsed `UNKNOWN` is never indistinguishable from a question
nobody asked.

Two boundaries are enforced rather than assumed. A number outside `[0, 1]` is not
a likelihood — an age of `17` raises instead of silently becoming "definitely
true". And the collapse runs over intake only, before the engine injects its own
`config` (which legitimately contains `confidence_threshold = 0.85`), so the
engine can never blank out its own settings.

## What it reports on a pack

| Check | Question it answers |
|---|---|
| **Gaps** | Are there cases no provision decides? Either the statute is silent, or the encoding is incomplete — the tool refuses to guess which. |
| **Undeclared contentions** | Do two provisions disagree without the pack saying which wins? Then the answer depends on evaluation order — on the author, not on law. |
| **Designed overrides** | How often do the exceptions actually override a limb? Counted as structure, not flagged as a defect. |
| **Unreachable provisions** | Can any limb never fire? |
| **Ambiguity sensitivity** | What is each disputed reading worth, in cases? |
| **Illustrations** | Does the encoding reproduce the examples printed in the statute? |

Everything is exhaustive over the declared fact space, so the numbers are proofs
about that space — not samples. They are only as good as the fact list, which is
why every pack declares its facts and prints the case-space size beside every
result.

---

## The rule format in thirty seconds

A pack is one JSON file containing the encoded provisions **and** the evidence
needed to judge whether the encoding is faithful: sources with URLs, the statutory
words for each branch, the illustrations as test vectors, and a review status.

```jsonc
"branches": [ { "id": "M-101a", "provision": "s.101(a)", "offence": "murder",
                "when": {"==": [{"var": "mens_rea", "type": "enum"}, "intention_death"]},
                "text": "if the act by which the death is caused is done with the
                         intention of causing death" } ],

"defeaters": [ { "id": "D-EXC4-SUDDEN-FIGHT", "offence": "culpable_homicide",
                 "overrides": ["M-101a", "M-101b", "M-101c", "M-101d"],
                 "text": "Culpable homicide is not murder if it is committed without
                          premeditation in a sudden fight …" } ]
```

Three choices do most of the work:

- **Exceptions are first-class `defeaters` with explicit `overrides`.** A statute
  that says *"except in the cases hereinafter excepted"* is a list of rules plus
  overrides. Encoding it that way lets the analyser tell a *designed* override from
  an *undeclared* contention.
- **Totality is required.** Every condition must evaluate at every point of the
  declared space; a typed variable carries a default, so a missing fact yields the
  declared default rather than a silent `false`. A non-total pack is refused at
  load.
- **A verdict is a closed set:** `offence`, `not_offence`, `indeterminate`.

Full format, CLI and design notes: [`nyayacode/README.md`](nyayacode/README.md).

---

## What the analyser caught here

Not hypothetical. These were found by running the tool on its own packs:

- **Murder without a death.** Every s.101 limb omitted `death_caused`; only the
  "no death" branch tested it. The overlap detector reported 6,272 contentions
  because murder was firing on deaths that had not occurred.
- **A missing lawful outcome.** Below-threshold driving under MV s.185 fell through
  every branch, and the gap finder reported 93 "gaps" that were simply lawful
  conduct.
- **An amendment that did nothing.** `remove_branches` filtered branches but not
  defeaters, so repealing Exception 4 reported zero movement.
- **A citation checker that was never called,** and int facts that silently
  defaulted to a range instead of being required.

Each is now a regression test — including negative tests that break a pack on
purpose and assert the analyser catches it. A tool that reports "no problems" on a
deliberately broken pack is worse than no tool.

---

## Honesty box

- **The packs are `encoded_unreviewed`.** No lawyer has read them against the
  statute text. They reproduce every illustration printed in the BNS and the
  analyser finds no gaps or undeclared contentions — but that proves internal
  consistency, not legal correctness. One carefully verified provision is worth
  more than fifty seeded ones.
- **The fact list is the argument.** Analysis is exhaustive over the declared
  facts; a fact nobody thought of is invisible, and the report will look just as
  clean.
- **It decides, it does not interpret.** Where the text is genuinely open, both
  readings are recorded and the difference measured. The tool does not choose.
- Two of the four recorded ambiguities still carry one reading each, so they report
  `n/a` instead of a number. That is a to-do, not a finding.

Not legal advice. An analysis of an encoding.

---

## Repository layout

```
nyayacode/            the library: pack format, evaluator, analyser, amendments, CLI
  packs/              encoded statutes (BNS ss.100-108; MV Act s.185)
  packs/amendments/   two real, one interpretive, one hypothetical amendment
server.py + pages/    a citizen case-reporting prototype built on the library
  (see docs/PORTAL.md — one application, not the argument)
tests/                library tests, incl. negative tests that break a pack on purpose
tests.py, smoke.py    portal tests (142) and end-to-end HTTP checks (153)
uncertainty.py        graded intake answers, collapsed fail-closed to UNKNOWN
demo_out/             generated analysis and impact reports (nothing hand-written)
seed.py               builds a demo database from obviously fictional accounts
```

`docs/PORTAL.md` documents the portal — one application on top of the library, kept
to show the engine can drive a real workflow. It is not the argument. It is a
deterministic rules engine, not an AI system, and it holds personal data, so it
binds to loopback by default and generates its own administrator credential on first
run rather than shipping one.

---

## Run the tests

```bash
python3 -m nyayacode check            # every pack reproduces its statute
python3 tests/test_nyayacode.py       # 79 library tests
python3 tests.py                      # 125 portal tests
python3 seed.py && python3 server.py  # then: python3 smoke.py
```

CI runs all of it on Python 3.10 and 3.12, and fails if a database, evidence file
or credential is ever committed.

---

## Sources

- Bharatiya Nyaya Sanhita, 2023 (Act 45 of 2023), ss.100–105 —
  [India Code](https://www.indiacode.nic.in/bitstream/123456789/20062/1/a202345.pdf)
- Motor Vehicles Act, 1988 s.185, as amended in 2019 —
  [India Code](https://www.indiacode.nic.in/handle/123456789/1798)

Secondary commentaries were used **only** as evidence that a text is reproduced
inconsistently; every dispute they revealed is recorded as an unresolved ambiguity,
not silently resolved.

## Licence

MIT — see [LICENSE](LICENSE).
