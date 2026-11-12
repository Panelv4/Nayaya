"""Generate the BNS Chapter VI (hurt / grievous hurt) packs, ss.114-125.

Kept as a script rather than hand-written JSON so the four packs share exactly
the same source block, fact vocabulary and wording conventions, and so the
enum values can be cross-checked in one place. Run from the repo root:

    python3 scripts/gen_hurt_packs.py

The output is plain JSON committed under nyayacode/packs/; this script is a
build tool, not a runtime dependency.
"""
from __future__ import annotations

import json
import os

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "nyayacode", "packs")

SOURCES = [
    {
        "id": "bns-2023",
        "citation": "Bharatiya Nyaya Sanhita, 2023 (Act 45 of 2023), Chapter VI, ss.114-125",
        "url": "https://www.mha.gov.in/sites/default/files/250883_english_01042024.pdf",
        "kind": "primary",
        "note": "Assented 25 Dec 2023, in force 1 Jul 2024. MHA published English text.",
    },
    {
        "id": "ipc-1860",
        "citation": "Indian Penal Code, 1860, ss.319-338 (repealed 1 July 2024)",
        "url": "https://www.indiacode.nic.in/handle/123456789/2263",
        "kind": "repealed",
        "note": "Predecessor of Chapter VI. Two substantive changes: the residual "
                "grievous-hurt period fell from 20 days to 15, and ss.117(3)-(4) are new.",
    },
    {
        "id": "bnss-2023",
        "citation": "Bharatiya Nagarik Suraksha Sanhita, 2023, First Schedule",
        "url": "https://www.mha.gov.in/sites/default/files/2024-04/250884_2_english_01042024.pdf",
        "kind": "primary",
        "note": "Source of the cognizable / bailable / triable-by / compoundable labels.",
    },
]


def src_note(extra: str) -> dict:
    return {"id": "bns-2023", "citation": "Bharatiya Nyaya Sanhita, 2023, s." + extra}


# --------------------------------------------------------------------- facts
# Shared across the four packs so a case can be reasoned about consistently.
F_HURT_KIND = {
    "name": "hurt_kind",
    "type": "enum",
    "values": ["NONE", "HURT", "GRIEVOUS"],
    "label": "Bodily result: no hurt, hurt (s.114) or grievous hurt (s.116)",
}
F_VOLUNTARY = {
    "name": "voluntary",
    "type": "bool",
    "label": "The hurt was caused voluntarily: with intention to cause it, or "
             "knowledge that it was likely (s.115(1) / s.117(1))",
}
F_GRIEVOUS_KIND = {
    "name": "grievous_kind",
    "type": "enum",
    "values": [
        "NONE",
        "EMASCULATION",
        "SIGHT",
        "HEARING",
        "MEMBER_LOSS",
        "MEMBER_IMPAIRED",
        "DISFIGUREMENT",
        "BONE_TOOTH",
        "LIFE_ENDANGERED",
        "FIFTEEN_DAYS",
    ],
    "label": "Which s.116 clause the injury falls under (NONE when it is only hurt)",
}
F_MEANS = {
    "name": "means",
    "type": "enum",
    "values": ["ORDINARY", "DANGEROUS"],
    "label": "Means used: ordinary, or a dangerous weapon/means listed in s.118(1) "
             "(shooting/stabbing/cutting instrument, fire, poison, corrosive, explosive, animal)",
}
F_PURPOSE = {
    "name": "purpose",
    "type": "enum",
    "values": ["NONE", "EXTORT_PROPERTY", "EXTORT_CONFESSION", "DETER_PUBLIC_SERVANT",
               "ILLEGAL_ACT"],
    "label": "Ulterior purpose behind the hurt",
}
F_PROVOKED = {
    "name": "grave_sudden_provocation",
    "type": "bool",
    "label": "The hurt was caused on grave and sudden provocation, and the offender "
             "neither intended nor knew it likely to hurt anyone other than the provoker (s.122)",
}
F_ACID = {
    "name": "acid_used",
    "type": "bool",
    "label": "Acid (or a like corrosive substance) was thrown or administered",
}
F_DISABILITY = {
    "name": "permanent_disability",
    "type": "bool",
    "label": "The grievous hurt left the victim in permanent disability or a "
             "persistent vegetative state (s.117(3))",
}
F_GROUP_IDENTITY = {
    "name": "group_five_or_more_identity",
    "type": "bool",
    "label": "Five or more persons acting together caused the grievous hurt on a "
             "ground of race, caste, community, sex, place of birth, language or belief (s.117(4))",
}
F_POISON = {
    "name": "poison_or_stupefying",
    "type": "bool",
    "label": "Poison, or a stupefying/intoxicating/unwholesome substance, was "
             "administered with intent to cause hurt or to commit an offence (s.123)",
}
F_DANGER_ONLY = {
    "name": "rash_negligent_act",
    "type": "bool",
    "label": "The act was rash or negligent (not voluntary) and endangered human life "
             "or the personal safety of others (s.125)",
}

TERMS = [
    {
        "id": "T-hurt",
        "term": "hurt",
        "definition": "Bodily pain, disease or infirmity caused to any person (s.114). "
                      "No visible wound is required; mental distress alone is not hurt.",
        "citations": ["bns-2023#s114"],
    },
    {
        "id": "T-grievous",
        "term": "grievous hurt",
        "definition": "A closed list of eight kinds of hurt (s.116): emasculation; "
                      "permanent loss of sight of either eye; permanent loss of hearing of "
                      "either ear; loss of any member or joint; destruction or permanent "
                      "impairment of any member or joint; permanent disfigurement of the "
                      "head or face; fracture or dislocation of a bone or tooth; and any "
                      "hurt that endangers life or keeps the sufferer in severe pain or "
                      "unable to follow ordinary pursuits for fifteen days. The last limb "
                      "was twenty days under s.320 IPC.",
        "citations": ["bns-2023#s116", "ipc-1860#s320"],
    },
    {
        "id": "T-voluntary",
        "term": "voluntarily",
        "definition": "Done with the intention of causing the hurt, or with knowledge "
                      "that it was likely to be caused (s.115(1)). Intention or knowledge "
                      "is enough; both are not needed.",
        "citations": ["bns-2023#s115"],
    },
    {
        "id": "T-mens-rea-ladder",
        "term": "the intention ladder",
        "definition": "The gravity of the injury does not by itself fix the offence. "
                      "Injury caused without the intention or knowledge required to kill "
                      "stays in this chapter (s.117), however grave; injury caused WITH "
                      "that intention or knowledge leaves it for attempt to murder (s.109) "
                      "or culpable homicide (ss.100-105).",
        "citations": ["bns-2023#s117", "bns-2023#s109"],
    },
]


# ------------------------------------------------------------------ branches
def b(bid, provision, verdict, offence, when, text, notes, cites="bns-2023#s115"):
    return {
        "id": bid,
        "provision": provision,
        "verdict": verdict,
        "offence": offence,
        "when": when,
        "text": text,
        "notes": notes,
        "citations": [cites],
    }


VAR = lambda name, typ, default: {"var": name, "type": typ, "default": default}  # noqa: E731


def eq(name, typ, default, value):
    return {"==": [VAR(name, typ, default), value]}


def and_(*clauses):
    return {"and": list(clauses)}


# ======================================================================
# Pack 1 — ss.114, 115, 116: definitions + voluntarily causing hurt
# ======================================================================
HURT = {
    "id": "in.bns.hurt",
    "title": "Hurt, grievous hurt and voluntarily causing hurt - BNS 2023 ss.114-116",
    "jurisdiction": "IN",
    "version": "1.0.0",
    "review": {
        "status": "encoded_unreviewed",
        "by": None,
        "on": None,
        "method": "Encoded from the bare text of ss.114-116. Two of the three sections "
                  "are pure definitions (s.114 hurt, s.116 the eight kinds of grievous "
                  "hurt) and carry no sentence of their own; the only punishing branch "
                  "here is s.115(2), one year or ten thousand rupees. The aggravated "
                  "sentences live in the sibling packs, which take the same hurt/grievous "
                  "classification as their input.",
    },
    "scope": {
        "in_scope": [
            "s.114 hurt: bodily pain, disease or infirmity",
            "s.115(1)-(2) voluntarily causing hurt (up to one year / Rs 10,000)",
            "s.116 the eight kinds of grievous hurt, as a classification",
        ],
        "out_of_scope": [
            "the sentence for grievous hurt - s.117, pack in.bns.grievous-hurt",
            "dangerous weapons and means - s.118, pack in.bns.hurt-dangerous-means",
            "extortion, public servants, provocation, poison - ss.119-123, pack in.bns.hurt-aggravated",
            "acid - s.124, rash or negligent conduct - s.125, pack in.bns.hurt-aggravated",
            "assault and criminal force (ss.129-131), which need no resulting injury",
            "attempt to murder (s.109) and culpable homicide (ss.100-105)",
        ],
    },
    "sources": SOURCES,
    "citations": ["bns-2023#s114", "bns-2023#s115", "bns-2023#s116", "ipc-1860#s319",
                  "ipc-1860#s320", "ipc-1860#s323"],
    "facts": [F_HURT_KIND, F_VOLUNTARY, F_GRIEVOUS_KIND],
    "terms": TERMS,
    "parameters": {
        "max_years_simple_hurt": 1,
        "max_fine_simple_hurt": 10000,
        "grievous_residual_days": 15,
        "grievous_residual_days_ipc": 20,
    },
    "branches": [
        b("H-NO-HURT", "s.114", "not_offence", None,
          eq("hurt_kind", "str", "NONE", "NONE"),
          "Whoever causes bodily pain, disease or infirmity to any person is said to cause hurt.",
          "No bodily pain, disease or infirmity means there is no hurt to punish. Assault or "
          "criminal force without a resulting injury is dealt with by ss.129-131, not here."),
        b("H-INVOLUNTARY", "s.115", "not_offence", None,
          and_(eq("hurt_kind", "str", "NONE", "HURT"), {"==": [VAR("voluntary", "bool", False), False]}),
          "Whoever does any act with the intention of thereby causing hurt ... or with the "
          "knowledge that he is likely thereby to cause hurt ...",
          "Hurt that was not caused voluntarily is outside s.115. If the act was rash or "
          "negligent, s.125 is the provision - not this one.", "bns-2023#s115"),
        b("H-115", "s.115(2)", "offence", "voluntarily_causing_hurt",
          and_(eq("hurt_kind", "str", "NONE", "HURT"), {"==": [VAR("voluntary", "bool", False), True]}),
          "Whoever, except in the case provided for by sub-section (1) of section 122, "
          "voluntarily causes hurt, shall be punished with imprisonment of either "
          "description for a term which may extend to one year, or with fine which may "
          "extend to ten thousand rupees, or with both.",
          "Simple hurt. Non-cognizable, bailable, compoundable, triable by any Magistrate. "
          "The s.122(1) provocation exception, which reduces this to one month, is applied "
          "as a defeater in the aggravated pack."),
        b("H-GRIEVOUS", "s.116", "offence", "grievous_hurt_classification",
          and_(eq("hurt_kind", "str", "NONE", "GRIEVOUS"),
               {"!=": [VAR("grievous_kind", "str", "NONE"), "NONE"]}),
          "The following kinds of hurt only are designated as \"grievous\":- (a) Emasculation; "
          "(b) Permanent privation of the sight of either eye; (c) Permanent privation of the "
          "hearing of either ear; (d) Privation of any member or joint; (e) Destruction or "
          "permanent impairing of the powers of any member or joint; (f) Permanent "
          "disfiguration of the head or face; (g) Fracture or dislocation of a bone or tooth; "
          "(h) Any hurt which endangers life or which causes the sufferer to be during the "
          "space of fifteen days in severe bodily pain, or unable to follow his ordinary pursuits.",
          "A classification branch: s.116 fixes that the injury is grievous, which is what "
          "triggers the seven-year tariff in s.117(2). It carries no sentence itself.",
          "bns-2023#s116"),
        b("H-GRIEVOUS-UNSPECIFIED", "s.116", "indeterminate", None,
          and_(eq("hurt_kind", "str", "NONE", "GRIEVOUS"), eq("grievous_kind", "str", "NONE", "NONE")),
          "The following kinds of hurt only are designated as \"grievous\" ...",
          "The case asserts grievous hurt but names none of the eight s.116 clauses. That is "
          "a contradiction the encoding will not resolve silently, so it reports a gap: an "
          "injury outside the eight clauses is legally only hurt, whatever it felt like.",
          "bns-2023#s116"),
    ],
    "defeaters": [],
    "outcomes": {
        "not_offence": {"label": "Not hurt under s.114 / not voluntarily caused under s.115",
                        "provision": None},
        "offence": {"label": "Offence under Chapter VI", "provision": "bns-2023#s115"},
        "indeterminate": {"label": "No provision applies - encoding gap", "provision": None},
    },
    "punishment_rules": [
        {
            "when": eq("offence_kind", "str", "", "voluntarily_causing_hurt"),
            "text": "Imprisonment up to one year, or fine up to Rs 10,000, or both [s.115(2)]",
            "citations": ["bns-2023#s115"],
        },
        {
            "when": eq("offence_kind", "str", "", "grievous_hurt_classification"),
            "text": "No sentence in s.116 - grievous hurt is punished under s.117(2) with up "
                    "to seven years and fine [s.116, s.117(2)]",
            "citations": ["bns-2023#s116", "bns-2023#s117"],
        },
    ],
    "ambiguities": [
        {
            "id": "AMB-116-FIFTEEN-DAYS",
            "provision": "s.116(h)",
            "status": "resolved_by_amendment",
            "question": "How long must severe pain or incapacity last for the residual "
                        "clause of grievous hurt to apply?",
            "why_it_matters": "The period decides whether an injury that fits none of the "
                              "specific clauses is grievous (seven years under s.117) or "
                              "merely hurt (one year under s.115).",
            "position_a": "Fifteen days, as s.116(h) reads under the BNS (current encoding).",
            "position_b": "Twenty days, as s.320 IPC read before 1 July 2024.",
            "resolution": "The BNS shortened the period from twenty days to fifteen. The "
                          "encoding uses fifteen; the twenty-day reading is retained only "
                          "for pre-cutover IPC cases.",
            "citations": ["bns-2023#s116", "ipc-1860#s320"],
            "variants": [
                {"id": "bns-fifteen", "label": "15 days (BNS, current)", "patch": {}},
                {"id": "ipc-twenty", "label": "20 days (IPC, pre-cutover)",
                 "patch": {"parameters": {"grievous_residual_days": 20}}},
            ],
        }
    ],
    "illustrations": [
        {
            "id": "ILL-114-SLAP",
            "cites": "s.114, s.115(2)",
            "facts": {"hurt_kind": "HURT", "voluntary": True, "grievous_kind": "NONE"},
            "expect": {"offence_kind": "voluntarily_causing_hurt"},
            "text": "A slaps B in a heated argument. B feels pain but there is no visible "
                    "injury. Bodily pain is enough for hurt, and the slap was intended to "
                    "hurt: s.115(2), up to one year or Rs 10,000.",
        },
        {
            "id": "ILL-116-FRACTURE",
            "cites": "s.116(g), s.117",
            "facts": {"hurt_kind": "GRIEVOUS", "voluntary": True, "grievous_kind": "BONE_TOOTH"},
            "expect": {"offence_kind": "grievous_hurt_classification"},
            "text": "A single blow fractures B's wrist. A fracture of a bone is grievous "
                    "hurt under s.116(g) even though it may heal, and the sentence follows "
                    "under s.117(2).",
        },
        {
            "id": "ILL-116-FIFTEEN",
            "cites": "s.116(h)",
            "facts": {"hurt_kind": "GRIEVOUS", "voluntary": True, "grievous_kind": "FIFTEEN_DAYS"},
            "expect": {"offence_kind": "grievous_hurt_classification"},
            "text": "No bone is broken and no listed organ is lost, but the sufferer cannot "
                    "follow ordinary pursuits for fifteen days. The residual clause makes the "
                    "hurt grievous - fifteen days under the BNS, twenty under the IPC.",
        },
        {
            "id": "ILL-115-ACCIDENT",
            "cites": "s.115(1), s.125",
            "facts": {"hurt_kind": "HURT", "voluntary": False, "grievous_kind": "NONE"},
            "expect": {"offence_kind": None},
            "text": "A careless handling of a machine injures a co-worker. There was no "
                    "intention or knowledge that hurt was likely, so s.115 is not engaged; "
                    "the negligence track is s.125.",
        },
        {
            "id": "ILL-116-NO-CLAUSE",
            "cites": "s.116",
            "facts": {"hurt_kind": "GRIEVOUS", "voluntary": True, "grievous_kind": "NONE"},
            "expect": {"offence_kind": None},
            "text": "A claim of grievous hurt that names none of the eight clauses is a "
                    "contradiction; the encoding reports a gap rather than choosing.",
        },
    ],
}


# ======================================================================
# Pack 2 — s.117: voluntarily causing grievous hurt
# ======================================================================
GREVIOUS = {
    "id": "in.bns.grievous-hurt",
    "title": "Voluntarily causing grievous hurt - BNS 2023 s.117",
    "jurisdiction": "IN",
    "version": "1.0.0",
    "review": {
        "status": "encoded_unreviewed",
        "by": None,
        "on": None,
        "method": "Encoded from the bare text of s.117. The basic sentence (seven years and "
                  "fine) is unchanged from s.325 IPC. Two tiers are new in the BNS: s.117(3) "
                  "imposes a ten-year minimum where the grievous hurt leaves permanent "
                  "disability or a persistent vegetative state, and s.117(4) imports group "
                  "liability for five or more persons acting on an identity ground.",
    },
    "scope": {
        "in_scope": [
            "s.117(2) voluntarily causing grievous hurt (up to seven years and fine)",
            "s.117(3) permanent disability or persistent vegetative state "
            "(rigorous imprisonment, minimum ten years, up to life)",
            "s.117(4) five or more persons, identity ground (up to seven years and fine)",
        ],
        "out_of_scope": [
            "the definition of hurt and the eight kinds of grievous hurt - ss.114, 116, "
            "pack in.bns.hurt",
            "dangerous weapons or means - s.118, which raises the tariff to life, "
            "pack in.bns.hurt-dangerous-means",
            "acid - s.124, pack in.bns.hurt-aggravated",
            "provocation mitigation - s.122, pack in.bns.hurt-aggravated",
            "attempt to murder (s.109): injury gravity alone never moves a case there",
        ],
    },
    "sources": SOURCES,
    "citations": ["bns-2023#s117", "ipc-1860#s325", "bns-2023#s116"],
    "facts": [F_HURT_KIND, F_VOLUNTARY, F_GRIEVOUS_KIND, F_DISABILITY, F_GROUP_IDENTITY],
    "terms": TERMS,
    "parameters": {
        "max_years_grievous": 7,
        "min_years_disability": 10,
        "min_years_group": 0,
        "max_years_group": 7,
    },
    "branches": [
        b("G-NOT-GRIEVOUS", "s.117", "not_offence", None,
          {"!=": [VAR("hurt_kind", "str", "NONE"), "GRIEVOUS"]},
          "Whoever ... voluntarily causes grievous hurt ...",
          "Only grievous hurt is punished here. Simple hurt is s.115 (one year) and no hurt "
          "at all is outside this chapter.", "bns-2023#s117"),
        b("G-INVOLUNTARY", "s.117(1)", "not_offence", None,
          and_(eq("hurt_kind", "str", "NONE", "GRIEVOUS"),
               {"==": [VAR("voluntary", "bool", False), False]}),
          "A person is not said voluntarily to cause grievous hurt except when he both "
          "causes grievous hurt and intends or knows himself to be likely to cause grievous hurt.",
          "s.117(1) requires BOTH grievous hurt and the intention or knowledge that grievous "
          "hurt was likely. An unintended grave injury is either s.115 hurt or, where the "
          "conduct was rash or negligent, s.125.", "bns-2023#s117"),
        # The three positive tiers below are mutually exclusive by construction.
        # They are parallel aggravations of the same sentence, not cumulative
        # ones, so a case that satisfies two of them is not a legal conflict —
        # but leaving them overlapping would make the OUTCOME depend on the
        # author's ordering, which is exactly what the analyser must not allow.
        # Precedence: s.117(3) (ten-year floor) > s.117(4) (group) > s.117(2).
        b("G-117-3", "s.117(3)", "offence", "grievous_hurt_permanent_disability",
          and_(eq("hurt_kind", "str", "NONE", "GRIEVOUS"),
               {"==": [VAR("voluntary", "bool", False), True]},
               {"==": [VAR("permanent_disability", "bool", False), True]},
               {"!=": [VAR("grievous_kind", "str", "NONE"), "NONE"]}),
          "Whoever causes grievous hurt and in the course of such commission causes any hurt "
          "to a person which causes that person to be in permanent disability or in "
          "persistent vegetative state, shall be punished with rigorous imprisonment for a "
          "term which shall not be less than ten years but which may extend to imprisonment "
          "for life, which shall mean imprisonment for the remainder of that person's natural life.",
          "New in the BNS. Cognizable, non-bailable, triable by a Court of Session. The ten "
          "years is a floor, not a maximum: the court cannot go below it.", "bns-2023#s117"),
        b("G-117-4", "s.117(4)", "offence", "grievous_hurt_group_identity",
          and_(eq("hurt_kind", "str", "NONE", "GRIEVOUS"),
               {"==": [VAR("voluntary", "bool", False), True]},
               {"==": [VAR("group_five_or_more_identity", "bool", False), True]},
               {"==": [VAR("permanent_disability", "bool", False), False]},
               {"!=": [VAR("grievous_kind", "str", "NONE"), "NONE"]}),
          "Whoever commits an offence under sub-section (1) and thereby causes grievous hurt "
          "to any person on the ground of his race, caste, community, sex, place of birth, "
          "language, personal belief or any other ground and such offence is committed by "
          "five or more persons acting in concert, shall be punished with imprisonment of "
          "either description for a term which may extend to seven years, and shall also be "
          "liable to fine.",
          "New in the BNS. Each member of the group is liable without proof of the specific "
          "blow. Cognizable, non-bailable, triable by a Court of Session.", "bns-2023#s117"),
        b("G-117-2", "s.117(2)", "offence", "voluntarily_causing_grievous_hurt",
          and_(eq("hurt_kind", "str", "NONE", "GRIEVOUS"),
               {"==": [VAR("voluntary", "bool", False), True]},
               {"!=": [VAR("grievous_kind", "str", "NONE"), "NONE"]},
               {"==": [VAR("permanent_disability", "bool", False), False]},
               {"==": [VAR("group_five_or_more_identity", "bool", False), False]}),
          "Whoever, except in the case provided for by sub-section (2) of section 122, "
          "voluntarily causes grievous hurt, shall be punished with imprisonment of either "
          "description for a term which may extend to seven years, and shall also be liable "
          "to fine.",
          "The ordinary case: up to seven years and fine. Cognizable and bailable under the "
          "BNSS First Schedule, triable by any Magistrate. The s.122(2) provocation exception "
          "is applied as a defeater in the aggravated pack.", "bns-2023#s117"),
        b("G-GRIEVOUS-UNSPECIFIED", "s.116", "indeterminate", None,
          and_(eq("hurt_kind", "str", "NONE", "GRIEVOUS"),
               {"==": [VAR("voluntary", "bool", False), True]},
               eq("grievous_kind", "str", "NONE", "NONE")),
          "The following kinds of hurt only are designated as \"grievous\" ... [s.116]",
          "Grievous hurt is asserted but no s.116 clause is named, so the classification the "
          "sentence depends on is missing. Reported as a gap rather than assumed.",
          "bns-2023#s116"),
    ],
    "defeaters": [],
    "outcomes": {
        "not_offence": {"label": "Not s.117 (no voluntary grievous hurt)", "provision": None},
        "offence": {"label": "Offence under s.117", "provision": "bns-2023#s117"},
        "indeterminate": {"label": "No provision applies - encoding gap", "provision": None},
    },
    "punishment_rules": [
        {
            "when": eq("offence_kind", "str", "", "grievous_hurt_permanent_disability"),
            "text": "Rigorous imprisonment not less than ten years, up to imprisonment for "
                    "life (remainder of natural life) [s.117(3)]",
            "citations": ["bns-2023#s117"],
        },
        {
            "when": eq("offence_kind", "str", "", "grievous_hurt_group_identity"),
            "text": "Imprisonment up to seven years, and fine [s.117(4)]",
            "citations": ["bns-2023#s117"],
        },
        {
            "when": eq("offence_kind", "str", "", "voluntarily_causing_grievous_hurt"),
            "text": "Imprisonment up to seven years, and fine [s.117(2)]",
            "citations": ["bns-2023#s117"],
        },
    ],
    "ambiguities": [
        {
            "id": "AMB-117-GRAVITY-VS-INTENTION",
            "provision": "s.117",
            "status": "unresolved",
            "question": "Can the gravity of the injury alone establish the intention or "
                        "knowledge required to leave s.117 for s.109?",
            "why_it_matters": "The same skull-fracturing assault can be charged as s.117 "
                              "(seven years) or s.109 (ten years to life). If gravity decided "
                              "it, nearly every serious-injury case would be attempt to murder.",
            "position_a": "Gravity is evidence of intention but can never substitute for it: "
                          "the prosecution must prove intention or knowledge separately "
                          "(current encoding, following Roshan Lal v. State of Haryana, 2026 INSC 524).",
            "position_b": "The nature of the weapon and the body part struck may be treated "
                          "as conclusive of the intention to kill without further proof.",
            "resolution": None,
            "citations": ["bns-2023#s117", "bns-2023#s109"],
            "variants": [
                {"id": "intention-required",
                 "label": "intention must be proved (current encoding)", "patch": {}},
            ],
        },
        {
            "id": "AMB-117-3-MINIMUM",
            "provision": "s.117(3)",
            "status": "resolved_by_amendment",
            "question": "Is the ten years in s.117(3) a minimum or a maximum?",
            "why_it_matters": "Reading it as a maximum would make the new tier lighter than "
                              "s.117(2)'s seven-year ceiling only for a narrower band, which "
                              "cannot be what the legislature intended.",
            "position_a": "A floor of ten years, extendable to life (current encoding).",
            "position_b": "A ceiling of ten years.",
            "resolution": "The words are 'shall not be less than ten years but which may "
                          "extend to imprisonment for life'. It is a floor.",
            "citations": ["bns-2023#s117"],
            "variants": [{"id": "floor", "label": "floor of ten years (current encoding)", "patch": {}}],
        },
    ],
    "illustrations": [
        {
            "id": "ILL-117-BASIC",
            "cites": "s.117(2)",
            "facts": {"hurt_kind": "GRIEVOUS", "voluntary": True, "grievous_kind": "BONE_TOOTH",
                      "permanent_disability": False, "group_five_or_more_identity": False},
            "expect": {"offence_kind": "voluntarily_causing_grievous_hurt"},
            "text": "A single blow fractures B's arm. Grievous hurt under s.116(g), voluntarily "
                    "caused: up to seven years and fine under s.117(2).",
        },
        {
            "id": "ILL-117-3",
            "cites": "s.117(3)",
            "facts": {"hurt_kind": "GRIEVOUS", "voluntary": True, "grievous_kind": "MEMBER_IMPAIRED",
                      "permanent_disability": True, "group_five_or_more_identity": False},
            "expect": {"offence_kind": "grievous_hurt_permanent_disability"},
            "text": "The injury leaves B permanently unable to use the limb. New tier under "
                    "s.117(3): rigorous imprisonment of not less than ten years, up to life.",
        },
        {
            "id": "ILL-117-4",
            "cites": "s.117(4)",
            "facts": {"hurt_kind": "GRIEVOUS", "voluntary": True, "grievous_kind": "BONE_TOOTH",
                      "permanent_disability": False, "group_five_or_more_identity": True},
            "expect": {"offence_kind": "grievous_hurt_group_identity"},
            "text": "Five men beat B because of his caste and fracture his ribs. New group "
                    "provision under s.117(4): up to seven years and fine for each participant.",
        },
        {
            "id": "ILL-117-1-KNOWLEDGE",
            "cites": "s.117(1), illustration",
            "facts": {"hurt_kind": "GRIEVOUS", "voluntary": True, "grievous_kind": "FIFTEEN_DAYS",
                      "permanent_disability": False, "group_five_or_more_identity": False},
            "expect": {"offence_kind": "voluntarily_causing_grievous_hurt"},
            "text": "A strikes a blow intending to disfigure B's face. The face is not disfigured "
                    "but B is in severe pain for twenty days. s.117(1)'s illustration: this is "
                    "still voluntarily causing grievous hurt.",
        },
        {
            "id": "ILL-117-NO-INTENT",
            "cites": "s.117(1)",
            "facts": {"hurt_kind": "GRIEVOUS", "voluntary": False, "grievous_kind": "BONE_TOOTH",
                      "permanent_disability": False, "group_five_or_more_identity": False},
            "expect": {"offence_kind": None},
            "text": "A negligently drops a beam that fractures B's foot. Without the intention "
                    "or knowledge required by s.117(1) this is not s.117 at all.",
        },
    ],
}


# ======================================================================
# Pack 3 — s.118: dangerous weapons or means
# ======================================================================
DANGEROUS = {
    "id": "in.bns.hurt-dangerous-means",
    "title": "Hurt or grievous hurt by dangerous weapons or means - BNS 2023 s.118",
    "jurisdiction": "IN",
    "version": "1.0.0",
    "review": {
        "status": "encoded_unreviewed",
        "by": None,
        "on": None,
        "method": "Encoded from the bare text of s.118. Two changes from ss.324/326 IPC are "
                  "worth flagging: s.118(1) now caps the fine at Rs 20,000 (the IPC left it "
                  "unlimited), and hurt by a dangerous weapon is now non-bailable and "
                  "non-compoundable, which is a substantive shift, not a renumbering.",
    },
    "scope": {
        "in_scope": [
            "s.118(1) hurt by a dangerous weapon or means (up to three years / Rs 20,000)",
            "s.118(2) grievous hurt by such means (life, or one to ten years, and fine)",
        ],
        "out_of_scope": [
            "ordinary-means hurt - ss.115, 117, packs in.bns.hurt and in.bns.grievous-hurt",
            "acid - s.124, which is the specific and graver provision, pack in.bns.hurt-aggravated",
            "poison administered with intent to cause hurt or commit an offence - s.123",
            "hurt in furtherance of extortion or to deter a public servant - ss.119-121",
        ],
    },
    "sources": SOURCES,
    "citations": ["bns-2023#s118", "ipc-1860#s324", "ipc-1860#s326"],
    "facts": [F_HURT_KIND, F_VOLUNTARY, F_MEANS],
    "terms": TERMS,
    "parameters": {
        "max_years_hurt_dangerous": 3,
        "max_fine_hurt_dangerous": 20000,
        "min_years_grievous_dangerous": 1,
        "max_years_grievous_dangerous": 10,
    },
    "branches": [
        b("D-NO-HURT", "s.118", "not_offence", None,
          eq("hurt_kind", "str", "NONE", "NONE"),
          "Whoever ... voluntarily causes hurt ... by means of any instrument for shooting, "
          "stabbing or cutting ...",
          "No hurt means s.118 is not engaged, however dangerous the weapon.",
          "bns-2023#s118"),
        b("D-ORDINARY-MEANS", "s.118", "not_offence", None,
          and_({"!=": [VAR("hurt_kind", "str", "NONE"), "NONE"]},
               eq("means", "str", "ORDINARY", "ORDINARY")),
          "Whoever ... by means of any instrument for shooting, stabbing or cutting ...",
          "The section is defined by the means. With ordinary means the case belongs to "
          "s.115 (hurt) or s.117 (grievous hurt) instead. This branch routes the case out "
          "rather than duplicating those tariffs.",
          "bns-2023#s118"),
        b("D-INVOLUNTARY", "s.118", "not_offence", None,
          and_({"!=": [VAR("hurt_kind", "str", "NONE"), "NONE"]},
               eq("means", "str", "ORDINARY", "DANGEROUS"),
               {"==": [VAR("voluntary", "bool", False), False]}),
          "Whoever ... voluntarily causes hurt or grievous hurt ...",
          "s.118 requires the hurt to be caused voluntarily. An accidental injury from a "
          "dangerous object is a s.125 negligence case, not this one.",
          "bns-2023#s118"),
        b("D-118-2", "s.118(2)", "offence", "grievous_hurt_dangerous_means",
          and_(eq("hurt_kind", "str", "NONE", "GRIEVOUS"),
               eq("means", "str", "ORDINARY", "DANGEROUS"),
               {"==": [VAR("voluntary", "bool", False), True]}),
          "Whoever, except in the case provided for by sub-section (2) of section 120, "
          "voluntarily causes grievous hurt by any means referred to in sub-section (1), "
          "shall be punished with imprisonment for life, or with imprisonment of either "
          "description for a term which shall not be less than one year but which may extend "
          "to ten years, and shall also be liable to fine.",
          "The knife-and-firearm assault provision. Where life is not imposed there is a "
          "one-year floor. Cognizable, non-bailable, triable by a Magistrate of the first class.",
          "bns-2023#s118"),
        b("D-118-1", "s.118(1)", "offence", "hurt_dangerous_means",
          and_(eq("hurt_kind", "str", "NONE", "HURT"),
               eq("means", "str", "ORDINARY", "DANGEROUS"),
               {"==": [VAR("voluntary", "bool", False), True]}),
          "Whoever, except in the case provided for by sub-section (2) of section 122, "
          "voluntarily causes hurt to any person by means of any instrument for shooting, "
          "stabbing or cutting, or any instrument which, used as a weapon of offence, is "
          "likely to cause death, or by means of fire or any heated substance, or by means "
          "of any poison or any corrosive substance, or by means of any explosive substance, "
          "or by means of any substance which it is deleterious to the human body to inhale, "
          "to swallow, or to receive into the blood, or by means of any animal, shall be "
          "punished with imprisonment of either description for a term which may extend to "
          "three years, or with fine which may extend to twenty thousand rupees, or with both.",
          "Simple hurt with a dangerous weapon. The BNS made this non-bailable and "
          "non-compoundable, unlike s.324 IPC, and capped the fine at Rs 20,000.",
          "bns-2023#s118"),
    ],
    "defeaters": [],
    "outcomes": {
        "not_offence": {"label": "Not s.118 (no hurt, ordinary means, or not voluntary)",
                        "provision": None},
        "offence": {"label": "Offence under s.118", "provision": "bns-2023#s118"},
        "indeterminate": {"label": "No provision applies - encoding gap", "provision": None},
    },
    "punishment_rules": [
        {
            "when": eq("offence_kind", "str", "", "grievous_hurt_dangerous_means"),
            "text": "Imprisonment for life, or imprisonment of either description not less "
                    "than one year and up to ten years, and fine [s.118(2)]",
            "citations": ["bns-2023#s118"],
        },
        {
            "when": eq("offence_kind", "str", "", "hurt_dangerous_means"),
            "text": "Imprisonment up to three years, or fine up to Rs 20,000, or both [s.118(1)]",
            "citations": ["bns-2023#s118"],
        },
    ],
    "ambiguities": [
        {
            "id": "AMB-118-1-BAILABILITY",
            "provision": "s.118(1)",
            "status": "unresolved",
            "question": "Is hurt by a dangerous weapon bailable?",
            "why_it_matters": "s.324 IPC was bailable and compoundable. The BNSS First "
                              "Schedule makes s.118(1) non-bailable and non-compoundable, "
                              "which changes what an accused can expect at the first hearing.",
            "position_a": "Non-bailable and non-compoundable under the BNSS First Schedule "
                          "(current encoding; this is the substantive change commentators flag).",
            "position_b": "Bailable, carrying the IPC position forward by analogy.",
            "resolution": None,
            "citations": ["bns-2023#s118", "bnss-2023#sch1"],
            "variants": [
                {"id": "non-bailable", "label": "non-bailable (BNSS First Schedule, current)",
                 "patch": {}},
            ],
        }
    ],
    "illustrations": [
        {
            "id": "ILL-118-1-KNIFE",
            "cites": "s.118(1)",
            "facts": {"hurt_kind": "HURT", "voluntary": True, "means": "DANGEROUS"},
            "expect": {"offence_kind": "hurt_dangerous_means"},
            "text": "A slashes B with a knife but the injury is a shallow cut only. Hurt by "
                    "a stabbing instrument: up to three years or Rs 20,000 under s.118(1) - "
                    "and non-bailable.",
        },
        {
            "id": "ILL-118-2",
            "cites": "s.118(2)",
            "facts": {"hurt_kind": "GRIEVOUS", "voluntary": True, "means": "DANGEROUS"},
            "expect": {"offence_kind": "grievous_hurt_dangerous_means"},
            "text": "A stabs B with a knife, causing grievous hurt. s.118(2): imprisonment "
                    "for life, or one to ten years, and fine.",
        },
        {
            "id": "ILL-118-ORDINARY",
            "cites": "s.118(1), s.115",
            "facts": {"hurt_kind": "HURT", "voluntary": True, "means": "ORDINARY"},
            "expect": {"offence_kind": None},
            "text": "A punch is not a dangerous means; the case belongs to s.115.",
        },
        {
            "id": "ILL-118-ACCIDENT",
            "cites": "s.125",
            "facts": {"hurt_kind": "HURT", "voluntary": False, "means": "DANGEROUS"},
            "expect": {"offence_kind": None},
            "text": "A hunter's shot accidentally hits B. Not voluntary, so s.118 is not "
                    "engaged; the negligence track is s.125.",
        },
    ],
}


# ======================================================================
# Pack 4 — ss.119-125: purpose- and means-based aggravated hurt
# ======================================================================
# The offence conditions of ss.119-124, written once. The branches below and the
# generated residual both consume these, so totality and disjointness follow from
# construction rather than from two hand-maintained copies drifting apart.
_AGG_NOT_ACID = {"==": [VAR("acid_used", "bool", False), False]}
_AGG_NOT_POISON = {"==": [VAR("poison_or_stupefying", "bool", False), False]}
_AGG_VOL = {"==": [VAR("voluntary", "bool", False), True]}
_AGG_HURT = eq("hurt_kind", "str", "NONE", "HURT")
_AGG_GRIEVOUS = eq("hurt_kind", "str", "NONE", "GRIEVOUS")
_AGG_PURPOSE = lambda *vals: {"in": [VAR("purpose", "str", "NONE"), list(vals)]}  # noqa: E731

AGG_119_2_WHEN = and_(_AGG_GRIEVOUS, _AGG_VOL, _AGG_NOT_ACID,
                      _AGG_PURPOSE("EXTORT_PROPERTY", "ILLEGAL_ACT"))
AGG_119_1_WHEN = and_(_AGG_HURT, _AGG_VOL, _AGG_NOT_POISON, _AGG_NOT_ACID,
                      _AGG_PURPOSE("EXTORT_PROPERTY", "ILLEGAL_ACT"))
AGG_120_2_WHEN = and_(_AGG_GRIEVOUS, _AGG_VOL, _AGG_NOT_ACID,
                      _AGG_PURPOSE("EXTORT_CONFESSION"))
AGG_120_1_WHEN = and_(_AGG_HURT, _AGG_VOL, _AGG_NOT_POISON, _AGG_NOT_ACID,
                      _AGG_PURPOSE("EXTORT_CONFESSION"))
AGG_121_2_WHEN = and_(_AGG_GRIEVOUS, _AGG_VOL, _AGG_NOT_ACID,
                      _AGG_PURPOSE("DETER_PUBLIC_SERVANT"))
AGG_121_1_WHEN = and_(_AGG_HURT, _AGG_VOL, _AGG_NOT_POISON, _AGG_NOT_ACID,
                      _AGG_PURPOSE("DETER_PUBLIC_SERVANT"))
AGG_123_WHEN = and_({"!=": [VAR("hurt_kind", "str", "NONE"), "NONE"]}, _AGG_VOL,
                    {"==": [VAR("poison_or_stupefying", "bool", False), True]},
                    _AGG_NOT_ACID, {"==": [VAR("purpose", "str", "NONE"), "NONE"]})
AGG_124_1_WHEN = and_({"==": [VAR("acid_used", "bool", False), True]}, _AGG_VOL,
                      {"!=": [VAR("hurt_kind", "str", "NONE"), "NONE"]})
AGG_FALLTHROUGH_WHEN = and_(
    {"!=": [VAR("hurt_kind", "str", "NONE"), "NONE"]}, _AGG_VOL,
    {"==": [VAR("purpose", "str", "NONE"), "NONE"]}, _AGG_NOT_POISON, _AGG_NOT_ACID,
    {"==": [VAR("grave_sudden_provocation", "bool", False), False]})

# s.125 acts are a defect-specific kind: rash or negligent, so not voluntary at
# all. They are defeaters because they must beat the voluntary branches rather
# than compete with them.
NEG_NOT_VOL = {"==": [VAR("voluntary", "bool", False), False]}

_AGG_OFFENCE_CONDITIONS = [
    AGG_119_2_WHEN, AGG_119_1_WHEN, AGG_120_2_WHEN, AGG_120_1_WHEN,
    AGG_121_2_WHEN, AGG_121_1_WHEN, AGG_123_WHEN, AGG_124_1_WHEN,
    AGG_FALLTHROUGH_WHEN,
]

AGGRAVATED = {
    "id": "in.bns.hurt-aggravated",
    "title": "Aggravated hurt: extortion, public servants, provocation, poison, acid, "
             "negligence - BNS 2023 ss.119-125",
    "jurisdiction": "IN",
    "version": "1.0.0",
    "review": {
        "status": "encoded_unreviewed",
        "by": None,
        "on": None,
        "method": "Encoded from the bare text of ss.119-125. These are the purpose-based and "
                  "means-based aggravations that sit on top of the hurt/grievous-hurt "
                  "distinction. s.122 is the one mitigating provision in the chapter and is "
                  "encoded as a defeater, because it reduces a sentence that would otherwise "
                  "apply rather than creating an offence of its own.",
    },
    "scope": {
        "in_scope": [
            "s.119 hurt or grievous hurt to extort property, or to constrain an illegal act",
            "s.120 hurt or grievous hurt to extort a confession or compel restoration",
            "s.121 hurt or grievous hurt to deter a public servant from duty",
            "s.122 grave and sudden provocation (mitigating)",
            "s.123 hurt by poison or a stupefying substance",
            "s.124 grievous hurt by acid (attack and attempt)",
            "s.125 rash or negligent act endangering life",
        ],
        "out_of_scope": [
            "the hurt/grievous-hurt definitions - ss.114, 116, pack in.bns.hurt",
            "the ordinary sentences - s.115, s.117, packs in.bns.hurt and in.bns.grievous-hurt",
            "dangerous weapons under s.118 - pack in.bns.hurt-dangerous-means, except where "
            "acid is used, which s.124 governs specifically",
            "murder and culpable homicide - pack in.bns.homicide",
        ],
    },
    "sources": SOURCES,
    "citations": ["bns-2023#s119", "bns-2023#s120", "bns-2023#s121", "bns-2023#s122",
                  "bns-2023#s123", "bns-2023#s124", "bns-2023#s125"],
    "facts": [F_HURT_KIND, F_VOLUNTARY, F_PURPOSE, F_POISON, F_ACID, F_PROVOKED,
              F_DANGER_ONLY],
    "terms": TERMS,
    "parameters": {
        "max_years_119_hurt": 10,
        "max_years_120_hurt": 7,
        "max_years_120_grievous": 10,
        "max_years_121_hurt": 5,
        "min_years_121_grievous": 1,
        "max_years_121_grievous": 10,
        "max_years_123": 10,
        "min_years_acid": 10,
        "min_years_acid_attempt": 5,
        "max_years_acid_attempt": 7,
        "max_months_provocation_hurt": 1,
        "max_fine_provocation_hurt": 5000,
        "max_years_provocation_grievous": 5,
        "max_fine_provocation_grievous": 10000,
        "max_months_125_danger": 3,
        "max_months_125_hurt": 6,
        "max_years_125_grievous": 3,
    },
    "branches": [
        # ---- s.119: extortion / constraining an illegal act -------------------
        b("A-119-2", "s.119(2)", "offence", "grievous_hurt_to_extort", AGG_119_2_WHEN,
          "Whoever voluntarily causes grievous hurt for any purpose referred to in "
          "sub-section (1), shall be punished with imprisonment for life, or imprisonment of "
          "either description for a term which may extend to ten years, and shall also be "
          "liable to fine.",
          "Grievous hurt used as an instrument of extortion. Cognizable, non-bailable, "
          "triable by a Court of Session.", "bns-2023#s119"),
        b("A-119-1", "s.119(1)", "offence", "hurt_to_extort", AGG_119_1_WHEN,
          "Whoever voluntarily causes hurt, for the purpose of extorting from the sufferer, "
          "or from any person interested in the sufferer, any property or valuable security, "
          "or of constraining the sufferer or any person interested in such sufferer to do "
          "anything which is illegal or which may facilitate the commission of an offence, "
          "shall be punished with imprisonment of either description for a term which may "
          "extend to ten years, and shall also be liable to fine.",
          "The purpose, not the injury, drives the tariff: simple hurt here carries ten "
          "years, against one year under s.115.", "bns-2023#s119"),
        # ---- s.120: extort confession / compel restoration --------------------
        b("A-120-2", "s.120(2)", "offence", "grievous_hurt_to_extort_confession", AGG_120_2_WHEN,
          "Whoever voluntarily causes grievous hurt for any purpose referred to in "
          "sub-section (1), shall be punished with imprisonment of either description for a "
          "term which may extend to ten years, and shall also be liable to fine.",
          "Custodial or coercive violence to extract a confession or information.",
          "bns-2023#s120"),
        b("A-120-1", "s.120(1)", "offence", "hurt_to_extort_confession", AGG_120_1_WHEN,
          "Whoever voluntarily causes hurt, for the purpose of extorting from the sufferer, "
          "or any person interested in the sufferer, any confession or any information which "
          "may lead to the detection of an offence or misconduct, or for the purpose of "
          "compelling the sufferer ... to restore, or to cause the restoration of any "
          "property or valuable security, shall be punished with imprisonment of either "
          "description for a term which may extend to seven years, and shall also be liable to fine.",
          "The classic custodial-violence provision (s.330/331 IPC).", "bns-2023#s120"),
        # ---- s.121: deterring a public servant ---------------------------------
        b("A-121-2", "s.121(2)", "offence", "grievous_hurt_to_deter_public_servant", AGG_121_2_WHEN,
          "Whoever voluntarily causes grievous hurt to any person being a public servant in "
          "the discharge of his duty as such public servant ... shall be punished with "
          "imprisonment of either description for a term which shall not be less than one "
          "year but which may extend to ten years, and shall also be liable to fine.",
          "A one-year floor was added by the BNS. Cognizable, non-bailable, Court of Session.",
          "bns-2023#s121"),
        b("A-121-1", "s.121(1)", "offence", "hurt_to_deter_public_servant", AGG_121_1_WHEN,
          "Whoever voluntarily causes hurt to any person being a public servant in the "
          "discharge of his duty as such public servant ... shall be punished with "
          "imprisonment of either description for a term which may extend to five years, or "
          "with fine, or with both.",
          "Raised from three years to five by the BNS.", "bns-2023#s121"),
        # ---- s.123: poison / stupefying substance ------------------------------
        b("A-123", "s.123", "offence", "hurt_by_poison", AGG_123_WHEN,
          "Whoever administers to or causes to be taken by any person any poison or any "
          "stupefying, intoxicating or unwholesome drug, or other thing with intent to cause "
          "hurt to such person, or with intent to commit an offence or to intimidate, insult "
          "or annoy any person, shall be punished with imprisonment of either description "
          "for a term which may extend to ten years, and shall also be liable to fine.",
          "Poisoning carries ten years whatever the resulting injury, because the intent "
          "that accompanies administration is what the section punishes. A poisoning used "
          "as the means of an extortion is charged under s.119, which is why the purpose "
          "here must be none.", "bns-2023#s123"),
        # ---- s.124: acid -------------------------------------------------------
        b("A-124-1", "s.124(1)", "offence", "acid_attack", AGG_124_1_WHEN,
          "Whoever throws acid on any person or attempts to throw acid on any person or "
          "attempts to administer by any means whatsoever such acid ... and thereby causes "
          "permanent or partial damage or deformity to, or burns or maims or disfigures or "
          "disables, any part or parts of the body of a person, or causes grievous hurt ... "
          "shall be punished with imprisonment of either description for a term which shall "
          "not be less than ten years but which may extend to imprisonment for life, and "
          "with fine ...",
          "Acid is carved out of s.118 and punished specifically: a ten-year floor, up to "
          "life, plus a fine that must be just and reasonable to meet the victim's medical "
          "expenses and is payable to the victim. Cognizable, non-bailable, non-compoundable, "
          "Court of Session.", "bns-2023#s124"),
        # ---- residual: voluntary hurt with no aggravating feature --------------
        b("A-FALLTHROUGH", "ss.119-124", "not_offence", None, AGG_FALLTHROUGH_WHEN,
          "No branch of ss.119-124 is engaged by these facts.",
          "The hurt is voluntary but none of the aggravating purposes or means is present, "
          "so the ordinary tariff applies: s.115 for hurt, s.117 for grievous hurt. Those "
          "are quantified in the sibling packs; this pack routes the case there rather than "
          "duplicating the figures.", "bns-2023#s115"),
        # ---- everything else: nothing in ss.119-125 applies --------------------
        # Written as the exact negation of the union of the offence conditions and
        # the s.125 defeaters. Hand-written residuals kept leaving holes; deriving
        # the complement makes totality structural.
        b("A-NO-OFFENCE", "ss.119-125", "not_offence", None,
          {"not": {"or": _AGG_OFFENCE_CONDITIONS + [
              {"and": [{"==": [VAR("rash_negligent_act", "bool", False), True]}, NEG_NOT_VOL]},
          ]}},
          "No provision in ss.119-125 applies.",
          "Either no hurt was caused, or the hurt was neither voluntary nor the product of a "
          "rash or negligent act. That is the boundary of the chapter rather than an encoding "
          "defect, so it is decided instead of reported as a gap.",
          "bns-2023#s114"),
    ],
    # s.125 is a defeater rather than a branch: an act is either voluntary or rash
    # or negligent, never both, so it must beat the voluntary branches instead of
    # competing with them. Its conditions are mutually exclusive and together they
    # cover every rash-or-negligent combination of hurt_kind.
    "defeaters": [
        {
            "id": "A-125-B",
            "provision": "s.125(b)",
            "verdict": "offence",
            "offence": "negligent_act_causing_grievous_hurt",
            "when": {
                "and": [
                    {"==": [VAR("rash_negligent_act", "bool", False), True]},
                    NEG_NOT_VOL,
                    {"==": [VAR("hurt_kind", "str", "NONE"), "GRIEVOUS"]},
                ]
            },
            "overrides": ["A-FALLTHROUGH"],
            "text": "Whoever does any act so rashly or negligently as to endanger human life "
                    "or the personal safety of others, shall be punished - ... (b) where "
                    "grievous hurt is caused, with imprisonment of either description for a "
                    "term which may extend to three years, or with fine which may extend to "
                    "ten thousand rupees, or with both.",
            "notes": "Raised from two years to three by the BNS. Bailable throughout; "
                     "compoundable with permission. Rash and negligent DRIVING is s.281, not this.",
            "citations": ["bns-2023#s125"],
        },
        {
            "id": "A-125-A",
            "provision": "s.125(a)",
            "verdict": "offence",
            "offence": "negligent_act_causing_hurt",
            "when": {
                "and": [
                    {"==": [VAR("rash_negligent_act", "bool", False), True]},
                    NEG_NOT_VOL,
                    {"==": [VAR("hurt_kind", "str", "NONE"), "HURT"]},
                ]
            },
            "overrides": ["A-FALLTHROUGH"],
            "text": "Whoever does any act so rashly or negligently as to endanger human life "
                    "or the personal safety of others, shall be punished - (a) where hurt is "
                    "caused, with imprisonment of either description for a term which may "
                    "extend to six months, or with fine which may extend to five thousand "
                    "rupees, or with both.",
            "notes": "Successor to s.337 IPC.",
            "citations": ["bns-2023#s125"],
        },
        {
            "id": "A-125",
            "provision": "s.125",
            "verdict": "offence",
            "offence": "negligent_act_endangering_life",
            "when": {
                "and": [
                    {"==": [VAR("rash_negligent_act", "bool", False), True]},
                    NEG_NOT_VOL,
                    {"==": [VAR("hurt_kind", "str", "NONE"), "NONE"]},
                ]
            },
            "overrides": ["A-FALLTHROUGH"],
            "text": "Whoever does any act so rashly or negligently as to endanger human life "
                    "or the personal safety of others, shall be punished with imprisonment of "
                    "either description for a term which may extend to three months, or with "
                    "fine which may extend to two thousand five hundred rupees, or with both.",
            "notes": "The danger alone is enough; no injury need result. Successor to s.336 IPC.",
            "citations": ["bns-2023#s125"],
        },
    ],
    "outcomes": {
        "not_offence": {"label": "Not an aggravated hurt offence (see s.115/s.117 instead)",
                        "provision": None},
        "offence": {"label": "Offence under ss.119-125", "provision": "bns-2023#s119"},
        "indeterminate": {"label": "No provision applies - encoding gap", "provision": None},
    },
    "punishment_rules": [
        {"when": eq("offence_kind", "str", "", "grievous_hurt_to_extort"),
         "text": "Imprisonment for life, or up to ten years, and fine [s.119(2)]",
         "citations": ["bns-2023#s119"]},
        {"when": eq("offence_kind", "str", "", "hurt_to_extort"),
         "text": "Imprisonment up to ten years, and fine [s.119(1)]",
         "citations": ["bns-2023#s119"]},
        {"when": eq("offence_kind", "str", "", "grievous_hurt_to_extort_confession"),
         "text": "Imprisonment up to ten years, and fine [s.120(2)]",
         "citations": ["bns-2023#s120"]},
        {"when": eq("offence_kind", "str", "", "hurt_to_extort_confession"),
         "text": "Imprisonment up to seven years, and fine [s.120(1)]",
         "citations": ["bns-2023#s120"]},
        {"when": eq("offence_kind", "str", "", "grievous_hurt_to_deter_public_servant"),
         "text": "Imprisonment not less than one year and up to ten years, and fine [s.121(2)]",
         "citations": ["bns-2023#s121"]},
        {"when": eq("offence_kind", "str", "", "hurt_to_deter_public_servant"),
         "text": "Imprisonment up to five years, or fine, or both [s.121(1)]",
         "citations": ["bns-2023#s121"]},
        {"when": eq("offence_kind", "str", "", "hurt_by_poison"),
         "text": "Imprisonment up to ten years, and fine [s.123]",
         "citations": ["bns-2023#s123"]},
        {"when": eq("offence_kind", "str", "", "acid_attack"),
         "text": "Imprisonment not less than ten years, up to life, and fine payable to the "
                 "victim to meet medical expenses [s.124(1)]; an attempt alone is five to "
                 "seven years and fine [s.124(2)]",
         "citations": ["bns-2023#s124"]},
        {"when": eq("offence_kind", "str", "", "hurt_on_grave_sudden_provocation"),
         "text": "Simple hurt: up to one month, or fine up to Rs 5,000, or both [s.122(1)]. "
                 "Grievous hurt: up to five years, or fine up to Rs 10,000, or both [s.122(2)]",
         "citations": ["bns-2023#s122"]},
        {"when": eq("offence_kind", "str", "", "negligent_act_causing_grievous_hurt"),
         "text": "Imprisonment up to three years, or fine up to Rs 10,000, or both [s.125(b)]",
         "citations": ["bns-2023#s125"]},
        {"when": eq("offence_kind", "str", "", "negligent_act_causing_hurt"),
         "text": "Imprisonment up to six months, or fine up to Rs 5,000, or both [s.125(a)]",
         "citations": ["bns-2023#s125"]},
        {"when": eq("offence_kind", "str", "", "negligent_act_endangering_life"),
         "text": "Imprisonment up to three months, or fine up to Rs 2,500, or both [s.125]",
         "citations": ["bns-2023#s125"]},
    ],
    "ambiguities": [
        {
            "id": "AMB-122-SCOPE",
            "provision": "s.122",
            "status": "resolved_by_amendment",
            "question": "Does the s.122 provocation exception apply to every hurt offence, "
                        "or only to ss.115 and 117?",
            "why_it_matters": "If it applied to s.119 (extortion) it would let an extortionist "
                              "claim a one-month ceiling because the victim provoked him.",
            "position_a": "Only where the section itself says so: ss.115(2), 117(2) and "
                          "118 cross-refer to s.122, and s.119 does not (current encoding).",
            "position_b": "It is a general exception to the whole chapter.",
            "resolution": "The cross-references are express and selective. The mitigating "
                          "reading is therefore restricted to the plain hurt cases.",
            "citations": ["bns-2023#s122", "bns-2023#s119"],
            "variants": [
                {"id": "express-cross-refs", "label": "express cross-references only "
                                                      "(current encoding)", "patch": {}},
            ],
        },
        {
            "id": "AMB-124-ATTEMPT",
            "provision": "s.124(2)",
            "status": "resolved_by_amendment",
            "question": "Is an acid attack that misses punished under s.124 or as an attempt?",
            "why_it_matters": "At common law a missed attempt can be punished more lightly "
                              "than the completed offence; s.124 fixes its own tariff.",
            "position_a": "s.124(2) expressly punishes the throw or attempt with five to "
                          "seven years and fine even if no injury results (current encoding).",
            "position_b": "s.124 applies only on proof of the resulting injury.",
            "resolution": "The sub-section is explicit that the attempt is itself punishable. "
                          "The pack records the s.124(1) tariff for a completed attack and "
                          "the s.124(2) band for an attempt.",
            "citations": ["bns-2023#s124"],
            "variants": [{"id": "attempt-punishable",
                          "label": "attempt punishable under s.124(2) (current encoding)",
                          "patch": {}}],
        },
    ],
    "illustrations": [
        {
            "id": "ILL-119-EXTORT",
            "cites": "s.119(1)",
            "facts": {"hurt_kind": "HURT", "voluntary": True, "purpose": "EXTORT_PROPERTY",
                      "poison_or_stupefying": False, "acid_used": False,
                      "grave_sudden_provocation": False, "rash_negligent_act": False},
            "expect": {"offence_kind": "hurt_to_extort"},
            "text": "A twists B's arm until B signs over his shop. Simple hurt, but the "
                    "purpose is extortion: ten years under s.119(1), not one under s.115.",
        },
        {
            "id": "ILL-120-CONFESSION",
            "cites": "s.120(1)",
            "facts": {"hurt_kind": "HURT", "voluntary": True, "purpose": "EXTORT_CONFESSION",
                      "poison_or_stupefying": False, "acid_used": False,
                      "grave_sudden_provocation": False, "rash_negligent_act": False},
            "expect": {"offence_kind": "hurt_to_extort_confession"},
            "text": "An officer beats a suspect to extract a confession. Seven years under "
                    "s.120(1).",
        },
        {
            "id": "ILL-121-PUBLIC-SERVANT",
            "cites": "s.121(2)",
            "facts": {"hurt_kind": "GRIEVOUS", "voluntary": True, "purpose": "DETER_PUBLIC_SERVANT",
                      "poison_or_stupefying": False, "acid_used": False,
                      "grave_sudden_provocation": False, "rash_negligent_act": False},
            "expect": {"offence_kind": "grievous_hurt_to_deter_public_servant"},
            "text": "A mob fractures the arm of an officer serving process. One to ten years "
                    "under s.121(2), with the new one-year floor.",
        },
        {
            "id": "ILL-123-POISON",
            "cites": "s.123",
            "facts": {"hurt_kind": "HURT", "voluntary": True, "purpose": "NONE",
                      "poison_or_stupefying": True, "acid_used": False,
                      "grave_sudden_provocation": False, "rash_negligent_act": False},
            "expect": {"offence_kind": "hurt_by_poison"},
            "text": "A drugs B's drink to rob him. Ten years under s.123, whatever the injury.",
        },
        {
            "id": "ILL-124-ACID",
            "cites": "s.124(1)",
            "facts": {"hurt_kind": "GRIEVOUS", "voluntary": True, "purpose": "NONE",
                      "poison_or_stupefying": False, "acid_used": True,
                      "grave_sudden_provocation": False, "rash_negligent_act": False},
            "expect": {"offence_kind": "acid_attack"},
            "text": "A throws acid on B, disfiguring her face. Ten years minimum, up to life, "
                    "and a fine payable to B for her treatment: s.124(1).",
        },
        {
            "id": "ILL-125-GRIEVOUS",
            "cites": "s.125(b)",
            "facts": {"hurt_kind": "GRIEVOUS", "voluntary": False, "purpose": "NONE",
                      "poison_or_stupefying": False, "acid_used": False,
                      "grave_sudden_provocation": False, "rash_negligent_act": True},
            "expect": {"offence_kind": "negligent_act_causing_grievous_hurt"},
            "text": "A negligently secures a scaffold that collapses and fractures B's leg. "
                    "Three years under s.125(b); there was no intention or knowledge at all.",
        },
        {
            "id": "ILL-PLAIN-HURT",
            "cites": "s.115",
            "facts": {"hurt_kind": "HURT", "voluntary": True, "purpose": "NONE",
                      "poison_or_stupefying": False, "acid_used": False,
                      "grave_sudden_provocation": False, "rash_negligent_act": False},
            "expect": {"offence_kind": None},
            "text": "A plain punch with none of the aggravating features: the pack routes it "
                    "to s.115 (one year), where that tariff is quantified.",
        },
        {
            "id": "ILL-NO-HURT",
            "cites": "s.114",
            "facts": {"hurt_kind": "NONE", "voluntary": False, "purpose": "NONE",
                      "poison_or_stupefying": False, "acid_used": False,
                      "grave_sudden_provocation": False, "rash_negligent_act": False},
            "expect": {"offence_kind": None},
            "text": "No bodily pain, disease or infirmity at all: outside the chapter.",
        },
    ],
}


def write(pack: dict) -> None:
    path = os.path.join(OUT, pack["id"] + ".json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(pack, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print("wrote", os.path.relpath(path))


if __name__ == "__main__":
    for p in (HURT, GREVIOUS, DANGEROUS, AGGRAVATED):
        write(p)
