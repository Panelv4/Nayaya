# nyayacode — rules-as-code analysis

A small, dependency-free Python library that encodes a statute as data and then
answers two questions about the encoding:

1. **Does it decide every case, and does it ever contradict itself?**  
   Enumerate the declared fact space, decide every point, and report gaps
   (no provision applies), undeclared contentions (two provisions disagree and
   nothing says which wins) and dead provisions (a limb that can never fire).

2. **What does a change to the law actually do?**  
   An amendment is a patch to the pack. Apply it, re-decide the whole case space,
   and count every case that moves — separately for the offence and for the
   sentence.

It is deliberately not a web app and not a chatbot. There is no model, no
inference and no network call: given the same pack, it produces the same
decision and the same digest, forever.

```
python3 -m nyayacode list
python3 -m nyayacode check
python3 -m nyayacode analyze --pack in.bns.homicide --out demo_out
python3 -m nyayacode impact  --amendment amend.bns.exc4-abolished --out demo_out
python3 -m nyayacode explain --pack in.bns.homicide \
        --fact death_caused=true --fact mens_rea=intention_injury_sufficient \
        --fact exception_state=sudden_fight
```

---

## The rule format

A pack is one JSON document. It contains the encoded provisions **and** the
evidence needed to judge whether the encoding is faithful.

```jsonc
{
  "id": "in.bns.homicide",
  "title": "…",
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
provisions disagreeing with nobody saying which wins). The first is structure;
the second is a defect.

**Totality is required.** Every condition must evaluate against every point of
the declared fact space. A typed `var` carries a default, so a missing fact
yields the declared default rather than a silent `false`. A pack that is not
total cannot be analysed and is rejected at load time.

**A verdict is a closed set.** `offence`, `not_offence`, `indeterminate`. A
provision that produces anything else is a bug, not a nuance.

---

## What the analysis reports

| Check | Question | Why it matters |
|---|---|---|
| **Gaps** | Are there cases no provision decides? | Either the statute is silent (a gap the legislature could close) or the encoding is incomplete. The tool refuses to guess which. |
| **Undeclared contentions** | Do two provisions disagree without the pack saying which wins? | The outcome would then depend on evaluation order — i.e. on the author, not on law. |
| **Designed overrides** | How often does an exception override a limb? | Counted, not flagged. If this number is zero the exceptions are doing nothing. |
| **Unreachable provisions** | Is any limb impossible to fire? | Dead law, or a mis-specified condition. |
| **Ambiguity sensitivity** | If the other reading of a disputed phrase were adopted, how many cases move? | Turns "this phrase is ambiguous" into "this phrase is worth N cases at N months each". |
| **Illustrations** | Does the encoding reproduce the examples printed in the statute? | The only correctness evidence a machine can produce unaided. |

The output is exhaustive over the declared domain, so the numbers are proofs
about that domain — not samples. They are only as good as the fact list, which is
why every pack declares its facts and prints the domain size next to every result.

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

`kind` is mandatory and appears in every output. A real legislative change, a
change a court could make by interpretation, and an invented one are different
claims and must not be mixed silently. The shipped set has one of each:

| Amendment | Kind | Decisions moved | Sentences moved |
|---|---|---|---|
| `amend.mv.2019-penalty` — MV Act s.185 fines raised | real | 0 | 273 of 732 |
| `amend.bns.101b-generic-knowledge` — s.101(b) read down | interpretive | 768 of 10,752 | 0 |
| `amend.bns.exc4-abolished` — Exception 4 repealed | hypothetical | 256 of 10,752 | 0 |

Each result was predicted before it was run; the predictions are in the
`expected_reading` field of each amendment file.

Comparison runs over the **union** of the two packs' fact domains, so an
amendment that introduces a new fact is still measurable. Changed points are
reduced by delta-debugging to a **minimal witness** — the fewest facts that still
change the outcome — so a reader sees the case, not an arbitrary row of the
enumeration.

---

## Packs shipped

| Pack | Provisions | Case space | Review status |
|---|---|---|---|
| `in.bns.homicide` | BNS 2023 ss.100-105 and Exceptions 1-5 | 10,752 | **unreviewed** |
| `in.mv.drunken-driving` | MV Act 1988 s.185, pre and post 2019 | 732 | **unreviewed** |

The second pack exists to show the machinery is not specific to a penal code:
s.185 has a numeric threshold instead of a mental element, two limbs that are
alternatives rather than a hierarchy, and an amendment that moves no verdict at
all. Everything else — the analyser, the amendment format, the report — is
unchanged.

### Review status is the honest part

`encoded_unreviewed` means exactly that. The packs reproduce every illustration
printed in the statute, and the analyser finds no gaps or undeclared contentions
in them. **That is not the same as being right.** A lawyer reading ss.100-105
against the India Code text is the only thing that moves this to `reviewed`, and
no amount of passing tests substitutes for it. One carefully verified provision
is worth more than fifty seeded ones.

---

## What the analyser caught in this repository

Not hypothetical — these were found by running the tool on its own packs:

* **Murder without a death.** Every s.101 limb omitted `death_caused`; only the
  "no death" branch tested it. The overlap detector reported 6,272 contentions
  because murder was firing on corpses that did not exist. Fixed by gating every
  provision on the s.100 actus reus.
* **A missing lawful outcome.** Below-threshold driving under MV s.185 fell
  through every branch, and the gap finder reported 93 "gaps" that were simply
  lawful conduct. Fixed by making the fall-through explicit.
* **An amendment that did nothing.** `remove_branches` filtered branches but not
  defeaters, so repealing Exception 4 reported zero movement. The comparison's
  own numbers were the evidence.
* **A citation checker that was never called**, and int facts that silently
  defaulted to a range instead of being required.

Each of those is now a regression test in `tests/test_nyayacode.py`, including
negative tests that break a pack on purpose and assert that the analyser catches
it. A tool that reports "no problems" on a deliberately broken pack is worse than
no tool.

---

## Limits

* **The domain is the argument.** Analysis is exhaustive over the declared facts.
  A fact nobody thought of is invisible, and the report will look just as clean.
* **Packs decide, they do not interpret.** Where the text is genuinely open, the
  pack records both readings as an ambiguity and measures the difference. It does
  not choose.
* **Sentencing is coarse.** Punishment rules select a statutory range. They do
  not model discretion, aggravating circumstances, or the rarest-of-rare doctrine.
* **Scope is stated, not implied.** Each pack lists what it deliberately does not
  encode (s.106 negligence, s.108 attempt, ss.34-44 private defence beyond the
  Exception 2 excess case, and so on).

Not legal advice. An analysis of an encoding.
