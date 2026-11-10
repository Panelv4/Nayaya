"""nyayacode.cli — command line front end.

    python3 -m nyayacode list
    python3 -m nyayacode explain  --pack in.bns.homicide --fact death_caused=true \\
                                  --fact mens_rea=intention_death
    python3 -m nyayacode analyze  --pack in.bns.homicide [--out demo_out]
    python3 -m nyayacode amendments
    python3 -m nyayacode impact   --amendment amend.bns.exc4-abolished [--out demo_out]
    python3 -m nyayacode check

Every command prints a readable report and can emit machine-readable JSON, so
the same results can be checked by a person and asserted by a test.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

from . import analyze, pack as packmod
from .pack import PackError


# --------------------------------------------------------------------- helpers

def _json_out(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)


def _fact_value(raw: str) -> Any:
    """Parse `name=true` / `name=31` / `name=intention_death` into a typed value."""
    low = raw.strip().lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    try:
        return int(raw)
    except (TypeError, ValueError):
        return raw


def parse_facts(pairs: Optional[List[str]]) -> Dict[str, Any]:
    facts: Dict[str, Any] = {}
    for item in pairs or []:
        if "=" not in item:
            raise PackError(f"--fact expects name=value, got {item!r}")
        name, value = item.split("=", 1)
        facts[name.strip()] = _fact_value(value)
    return facts


def _header(title: str, sub: str = "") -> str:
    line = "=" * len(title)
    out = f"{title}\n{line}\n"
    return out + (sub + "\n" if sub else "")


def _trust_line(p: packmod.Pack) -> str:
    return (f"REVIEW STATUS: {p.review_context()}\n"
            f"SOURCES: {', '.join(s['id'] for s in p.sources)}\n"
            f"Advisory analysis of an encoding, not legal advice.")


# --------------------------------------------------------------------- explain

def cmd_explain(args: argparse.Namespace) -> int:
    p = packmod.load(args.pack)
    facts = parse_facts(args.fact)
    if args.json:
        d = p.decide(facts, parameters=parse_facts(args.param) or None)
        print(_json_out({"pack": p.id, "facts": facts, "decision": d,
                         "sentence": analyze.sentence_key(p, facts, d),
                         "review": p.review_context()}))
        return 0

    print(_header(f"{p.id} — {p.title}", _trust_line(p)))
    print("\nFACTS")
    for k in sorted(facts):
        print(f"  {k:32s} {facts[k]!r}")
    missing = [f for f in p.fact_names if f not in facts]
    if missing:
        print(f"  ({len(missing)} undeclared fact(s) take their defaults: {', '.join(missing)})")

    d = p.decide(facts)
    print("\nDECISION")
    if d.get("unmatched"):
        print("  No provision applies. Either the statute is silent on these facts, or")
        print("  the encoding is incomplete. The tool does not guess which.")
    else:
        node = p.target(d["branch"]) if d.get("branch") else None
        print(f"  Outcome:    {d.get('offence') or d['verdict']}")
        print(f"  Provision:  {d.get('provision')}")
        print(f"  Fired:      {d['branch']}" + ("  (an exception overriding a limb)" if d.get("defeater") else ""))
        if node and node.get("when"):
            print(f"  Condition:  {json.dumps(node['when'])[:160]}")
        for b in p.branches + p.defeaters:
            if b["id"] == d["branch"] and b.get("text"):
                print(f"  Statute:    {b['text']}")
        if d.get("chain"):
            print(f"  Overrides:  {', '.join(d['chain'])}")

    sent = analyze.sentence_key(p, facts, d)
    if sent:
        print(f"\nSENTENCE\n  {sent}")
    for amb in p.ambiguities:
        print(f"\nRECORDED AMBIGUITY ({amb['provision']}, {amb['status']})")
        print(f"  {amb['question']}")
    print("\nDigest of this pack:", analyze.digest(p))
    return 0


# --------------------------------------------------------------------- analyze

def build_analysis(p: packmod.Pack) -> Dict[str, Any]:
    r = analyze.full_report(p)
    r["illustrations"] = [
        {
            "id": i["id"], "cites": i.get("cites"), "text": i.get("text"),
            "facts": i["facts"],
            "expected": i["expect"].get("offence_kind"),
            "actual": p.decide(i["facts"]).get("offence"),
            "ok": p.decide(i["facts"]).get("offence") == i["expect"].get("offence_kind"),
        }
        for i in p.doc.get("illustrations", [])
    ]
    r["scope"] = p.doc.get("scope", {})
    return r


def render_analysis_md(r: Dict[str, Any]) -> str:
    L: List[str] = []
    L.append(f"# Analysis — `{r['pack']}`\n")
    L.append(f"**{r['title']}**\n")
    L.append(f"- Review status: **{r['review']}**")
    L.append(f"- Facts: {r['facts']} · case space enumerated: **{r['domain_size']:,}** points")
    L.append(f"- Decision digest: `{r['digest']}`\n")

    g, o, u = r["gaps"], r["overlaps"], r["unreachable"]
    L.append("## 1. Gaps and contentions\n")
    L.append("| Check | Result | Reading |")
    L.append("|---|---|---|")
    L.append(f"| Cases where no provision applies | **{g['count']}** of {g['checked']:,} | "
             + ("none: every case in the declared domain is decided by some provision"
                if g["count"] == 0 else "these cases fall through the statute") + " |")
    L.append(f"| Undeclared contentions | **{o['count']}** of {o['checked']:,} | "
             + ("none: no two provisions disagree without the pack saying which wins"
                if o["count"] == 0 else "outcome depends on evaluation order") + " |")
    L.append(f"| Designed overrides (exceptions doing their job) | {o['designed_overrides']:,} | "
             "counted, not defects |")
    L.append(f"| Unreachable provisions | **{u['count']}** | "
             + ("every provision can fire somewhere in the domain"
                if u["count"] == 0 else "dead law or a mis-specified condition") + " |")
    L.append("")

    L.append("## 2. Recorded ambiguities, measured\n")
    L.append("Each ambiguity is a question the text does not settle. The pack records both "
             "readings; the analyser decides the whole case space under each and counts how "
             "many cases move. A reading that moves nothing is not a real dispute.\n")
    L.append("| Ambiguity | Provision | Decisions moved | Sentences moved |")
    L.append("|---|---|---|---|")
    for a in r["ambiguities"]["ambiguities"]:
        dm = a.get("max_moved")
        sm = a.get("max_sentence_moved")
        L.append(f"| `{a['ambiguity']}` | {a.get('provision')} | "
                 f"{'n/a (one reading recorded)' if dm is None else f'{dm:,}'} | "
                 f"{'n/a' if sm is None else f'{sm:,}'} |")
    L.append("")
    for a in r["ambiguities"]["ambiguities"]:
        q = a.get("question")
        if q:
            L.append(f"- **{a['ambiguity']}** — {q}")
    L.append("")

    L.append("## 3. Statutory illustrations reproduced\n")
    ok = sum(1 for i in r["illustrations"] if i["ok"])
    L.append(f"{ok} of {len(r['illustrations'])} illustrations printed in the statute are "
             "reproduced by the encoding. This is the only correctness evidence a machine "
             "can produce on its own; it is not a substitute for a lawyer reading the pack.\n")
    L.append("| Illustration | Cites | Expected | Encoding | |")
    L.append("|---|---|---|---|---|")
    for i in r["illustrations"]:
        L.append(f"| `{i['id']}` | {i['cites']} | {i['expected'] or 'not an offence'} | "
                 f"{i['actual'] or 'not an offence'} | {'pass' if i['ok'] else '**FAIL**'} |")
    L.append("")
    sc = r.get("scope", {})
    if sc:
        L.append("## 4. Scope\n")
        L.append("**Encoded:** " + "; ".join(sc.get("in_scope", [])))
        L.append("")
        L.append("**Deliberately not encoded:** " + "; ".join(sc.get("out_of_scope", [])))
        L.append("")
    return "\n".join(L)


def cmd_analyze(args: argparse.Namespace) -> int:
    p = packmod.load(args.pack)
    r = build_analysis(p)
    if args.json:
        print(_json_out(r))
        return 0
    print(render_analysis_md(r))
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        stem = os.path.join(args.out, f"analysis-{p.id}")
        with open(stem + ".md", "w", encoding="utf-8") as fh:
            fh.write(render_analysis_md(r))
        with open(stem + ".json", "w", encoding="utf-8") as fh:
            fh.write(_json_out(r))
        print(f"\nWritten: {stem}.md, {stem}.json")
    return 0


# -------------------------------------------------------------------- impact

def build_impact(am: packmod.Amendment) -> Dict[str, Any]:
    base = packmod.load(am.pack_id)
    before = analyze.amended(base, am.before_patch, "before") if am.before_patch else base
    after = analyze.amended(base, am.after_patch, "after") if am.after_patch else base
    cmp_ = analyze.compare(before, after)
    outcomes = sorted(set(list(cmp_["matrix"]) + [k for v in cmp_["matrix"].values() for k in v]))
    return {
        "amendment": am.id, "title": am.title, "kind": am.kind,
        "enacted": am.enacted, "commencement": am.commencement,
        "summary": am.summary, "source": am.source,
        "before_label": am.before_label, "after_label": am.after_label,
        "expected_reading": am.expected_reading,
        "pack": base.id, "pack_review": base.review_context(),
        "outcomes": outcomes,
        "comparison": cmp_,
        "pack_before": analyze.build_digest_inputs(before) if hasattr(analyze, "build_digest_inputs") else {},
        "coverage": {
            "domain": cmp_["checked"],
            "facts_added": cmp_["facts_added"],
            "facts_removed": cmp_["facts_removed"],
        },
        "examples": _examples(cmp_, before, after, limit=8),
    }


def _examples(cmp_: Dict[str, Any], before: Any, after: Any,
              limit: int = 8) -> List[Dict[str, Any]]:
    """Minimal witnesses, one per distinct transition, not arbitrary points."""
    return analyze.minimal_witnesses(before, after, cmp_["moved"], limit=limit)


def render_impact_md(r: Dict[str, Any]) -> str:
    c = r["comparison"]
    L = [f"# Amendment impact — {r['title']}\n",
         f"`{r['amendment']}` · **{r['kind'].upper()}**"
         + (f" · commenced {r['commencement']}" if r["commencement"] else " · not enacted") + "\n",
         r["summary"] + "\n",
         f"Encoded by `{r['pack']}` — {r['pack_review']}\n"]

    L.append("## Result\n")
    L.append(f"Case space compared: **{c['checked']:,}** points "
             f"({r['coverage']['domain']:,} fact combinations).\n")
    L.append("| Measure | Count | Share of case space |")
    L.append("|---|---|---|")
    L.append(f"| Decisions that change | **{c['decisions_changed']:,}** | {c['pct_decisions']}% |")
    L.append(f"| Sentences that change (offence unchanged) | **{c['sentences_changed']:,}** | "
             f"{round(100.0 * c['sentences_changed'] / c['checked'], 2)}% |")
    L.append(f"| Unaffected | {c['unchanged']:,} | "
             f"{round(100.0 * c['unchanged'] / c['checked'], 2)}% |")
    L.append("")

    L.append("## Before / after, cell by cell\n")
    L.append("Rows are the outcome before the amendment, columns after. Every row sums to the "
             "number of points that had that outcome before.\n")
    cols = r["outcomes"]
    L.append("| before \\ after | " + " | ".join(cols) + " | total |")
    L.append("|---" * (len(cols) + 2) + "|")
    for run in [k for k in c["matrix"]]:
        row = c["matrix"][run]
        cells = [f"{row.get(col, 0):,}" if row.get(col) else "" for col in cols]
        L.append(f"| **{run}** | " + " | ".join(cells) + f" | {sum(row.values()):,} |")
    L.append("")

    if r["examples"]:
        L.append("## Minimal cases that change\n")
        L.append("Each line is one case reduced to the facts that actually decide it — every "
                 "other fact is at its neutral value, so the difference is visible. "
                 "Counts show how many enumerated cases share that transition.\n")
        L.append("| Case | Before | After | Moved because | Cases |")
        L.append("|---|---|---|---|---|")
        for e in r["examples"]:
            facts = ", ".join(f"`{k}={v}`" for k, v in e["facts"].items()) or "(no facts needed)"
            L.append(f"| {facts} | {e['before']} | {e['after']} | "
                     f"`{e['before_branch']}` → `{e['after_branch']}` ({e['kind']}) | {e['share']:,} |")
        L.append("")

    if r.get("expected_reading"):
        L.append("## Did it do what it should?\n")
        L.append(r["expected_reading"] + "\n")
        d, s = c["decisions_changed"], c["sentences_changed"]
        L.append(f"The measurement: **{d:,}** decisions and **{s:,}** sentences moved. "
                 "Compare that against the sentence above — a mismatch is either a wrong "
                 "encoding or a wrong prediction, and both are worth knowing.\n")

    L.append("## Integrity\n")
    L.append(f"- Decision digest before: `{c['digest_before']}`")
    L.append(f"- Decision digest after: `{c['digest_after']}`")
    L.append("- The digest is a hash of the decision for every point in the case space. Two "
             "packs with the same digest decide every case identically, which makes it usable as "
             "a regression test on the law itself.\n")
    return "\n".join(L)


def cmd_impact(args: argparse.Namespace) -> int:
    am = packmod.load_amendment(args.amendment)
    r = build_impact(am)
    if args.json:
        print(_json_out(r))
        return 0
    print(render_impact_md(r))
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        stem = os.path.join(args.out, f"impact-{am.id}")
        with open(stem + ".md", "w", encoding="utf-8") as fh:
            fh.write(render_impact_md(r))
        with open(stem + ".json", "w", encoding="utf-8") as fh:
            fh.write(_json_out(r))
        print(f"\nWritten: {stem}.md, {stem}.json")
    return 0


# ---------------------------------------------------------------------- misc

def cmd_list(args: argparse.Namespace) -> int:
    print("PACKS")
    for pid in packmod.available():
        try:
            p = packmod.load(pid)
            n = analyze._domain_size(p)
            print(f"  {p.id:28s} {n:>7,} points  {p.review_context()}")
        except PackError as exc:
            print(f"  {pid:28s} INVALID: {exc}")
    print("\nAMENDMENTS")
    for aid in packmod.amendments():
        try:
            a = packmod.load_amendment(aid)
            print(f"  {a.id:34s} {a.label()}")
        except PackError as exc:
            print(f"  {aid:34s} INVALID: {exc}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Fail loudly if any pack stops reproducing the statute it encodes."""
    failures = 0
    for pid in packmod.available():
        p = packmod.load(pid)
        r = build_analysis(p)
        bad = [i for i in r["illustrations"] if not i["ok"]]
        problems = []
        if bad:
            problems.append(f"{len(bad)} illustration(s) not reproduced")
        if r["gaps"]["count"]:
            problems.append(f"{r['gaps']['count']} undocumented gaps")
        if r["overlaps"]["count"]:
            problems.append(f"{r['overlaps']['count']} undeclared contentions")
        if r["unreachable"]["count"]:
            problems.append(f"{r['unreachable']['count']} unreachable provisions")
        status = "ok" if not problems else "; ".join(problems)
        if problems:
            failures += 1
        print(f"  {'PASS' if not problems else 'FAIL'}  {p.id:28s} {r['domain_size']:>7,} points  {status}")
    print()
    if failures:
        print(f"{failures} pack(s) failed")
        return 1
    print("All packs decide every case, reproduce every illustration, and have no undeclared contention.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="nyayacode", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("list", help="list packs and amendments")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("explain", help="decide one case and show why")
    s.add_argument("--pack", required=True)
    s.add_argument("--fact", action="append", metavar="NAME=VALUE")
    s.add_argument("--param", action="append", metavar="NAME=VALUE")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_explain)

    s = sub.add_parser("analyze", help="gaps, contentions, ambiguities, illustrations")
    s.add_argument("--pack", required=True)
    s.add_argument("--out")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_analyze)

    s = sub.add_parser("amendments", help="list amendments")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("impact", help="before/after comparison for an amendment")
    s.add_argument("--amendment", required=True)
    s.add_argument("--out")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_impact)

    s = sub.add_parser("check", help="verify every pack still reproduces its statute")
    s.set_defaults(func=cmd_check)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except packmod.PackError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":          # pragma: no cover
    raise SystemExit(main())
