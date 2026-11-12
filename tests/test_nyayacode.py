"""Tests for the nyayacode library.

Three kinds of test, deliberately kept apart:

* **library tests** — the evaluator, the analyser, the amendment machinery;
* **statute tests** — does the encoding reproduce the illustrations and the
  structure of BNS ss.100-108 and MV Act s.185?
* **negative tests** — can the tool be caught being wrong? A tool that reports
  "no problems" on a deliberately broken pack is worse than no tool.

Run:  python3 -m pytest tests/ -q       or       python3 tests/test_nyayacode.py
"""

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from nyayacode import analyze, pack as packmod                      # noqa: E402
from nyayacode import eval as ev                                   # noqa: E402

HOMICIDE = "in.bns.homicide"
MV = "in.mv.drunken-driving"
NEGLIGENCE = "in.bns.negligence"
ABETMENT = "in.bns.abetment-suicide"
ATTEMPT = "in.bns.attempt-murder"
ATTEMPT_CH = "in.bns.attempt-culpable-homicide"
ORGANISED = "in.bns.organised-crime"
PETTY = "in.bns.petty-organised-crime"
TERRORIST = "in.bns.terrorist-act"


# --------------------------------------------------------------------- library

class EvaluatorTests(unittest.TestCase):
    def test_typed_var_defaults_make_expressions_total(self):
        expr = {"==": [{"var": "missing", "type": "bool", "default": False}, False]}
        self.assertTrue(ev.evaluate(expr, {}))

    def test_untyped_missing_var_is_an_error_not_false(self):
        # The opposite of JSON Logic, on purpose: a silent false hides encoding bugs.
        with self.assertRaises(ev.EvalError):
            ev.evaluate({"==": [{"var": "nope", "type": "bool"}, True]}, {})

    def test_unsupported_operator_is_rejected(self):
        with self.assertRaises(ev.EvalError):
            ev.evaluate({"+": [1, 2]}, {})
        with self.assertRaises(ev.EvalError):
            ev.evaluate({"if": [True, 1, 2]}, {})

    def test_dotted_parameter_paths_resolve(self):
        facts = {"param": {"threshold": 30}, "reading": 40}
        self.assertTrue(ev.evaluate(
            {">": [{"var": "reading", "type": "int"}, {"var": "param.threshold", "type": "int"}]},
            facts))

    def test_comparison_on_booleans_is_refused(self):
        with self.assertRaises(ev.EvalError):
            ev.evaluate({">": [{"var": "a", "type": "bool", "default": True}, 0]}, {})

    def test_in_operator_takes_a_list_literal(self):
        expr = {"in": [{"var": "x", "type": "str", "default": "b"}, ["a", "b"]]}
        self.assertTrue(ev.evaluate(expr, {}))

    def test_coercion_of_string_facts(self):
        expr = {"==": [{"var": "f", "type": "bool"}, True]}
        self.assertTrue(ev.evaluate(expr, {"f": "yes"}))
        expr = {"==": [{"var": "n", "type": "int"}, 7]}
        self.assertTrue(ev.evaluate(expr, {"n": "7"}))


class PackLoadingTests(unittest.TestCase):
    def test_all_shipped_packs_load_and_are_total(self):
        self.assertEqual(len(packmod.available()), 9)
        for pid in packmod.available():
            p = packmod.load(pid)
            self.assertGreater(analyze._domain_size(p), 0)

    def test_a_pack_with_a_non_total_condition_is_refused(self):
        # An int fact with no declared range makes `domain()` unbuildable, which
        # means the pack cannot be analysed — loading must fail, not guess.
        doc = _load(MV)
        doc["facts"][1] = {"name": "blood_alcohol_mg", "type": "int", "label": "x"}
        with self.assertRaises(packmod.PackError):
            packmod._validate(doc, "broken")

    def test_unknown_variable_in_a_condition_is_caught_at_load(self):
        doc = _load(MV)
        doc["branches"][0]["when"] = {"==": [{"var": "not_a_fact", "type": "bool"}, True]}
        with self.assertRaises(packmod.PackError):
            packmod._validate_analysable(packmod.Pack(doc), "broken")

    def test_unknown_citation_is_a_pack_error(self):
        doc = _load(MV)
        doc["branches"][0]["citations"] = ["no-such-source#1"]
        with self.assertRaises(packmod.PackError):
            packmod._validate(doc, "broken")

    def test_top_level_citation_must_resolve_too(self):
        doc = _load(MV)
        doc["citations"] = ["ghost-act#9"]
        with self.assertRaises(packmod.PackError):
            packmod._validate(doc, "broken")

    def test_defeater_overriding_an_unknown_branch_is_refused(self):
        doc = _load(MV)
        doc["defeaters"] = [{"id": "D-X", "verdict": "not_offence",
                             "when": {"==": [{"var": "was_driving", "type": "bool"}, True]},
                             "overrides": ["NO-SUCH-LIMB"]}]
        with self.assertRaises(packmod.PackError):
            packmod._validate(doc, "broken")

    def test_review_status_is_mandatory_and_typed(self):
        doc = _load(MV)
        doc["review"] = {"status": "probably fine"}
        with self.assertRaises(packmod.PackError):
            packmod._validate(doc, "broken")


def _load(pack_id):
    """Load a pack document fresh, so a test can mutate it."""
    with open(os.path.join(packmod.PACK_DIR, pack_id + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------- statute

class HomicideEncodingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = packmod.load(HOMICIDE)

    def test_every_statutory_illustration_is_reproduced(self):
        for ill in self.p.doc["illustrations"]:
            want = ill["expect"]["offence_kind"]
            got = self.p.decide(ill["facts"]).get("offence")
            self.assertEqual(got, want, f"{ill['id']} ({ill['cites']}): got {got}, want {want}")

    def test_no_death_is_never_murder(self):
        # The analyser caught this bug in an earlier draft of the pack: murder
        # limbs did not test death_caused at all.
        for mr in ("intention_death", "intention_injury_sufficient",
                   "knowledge_imminently_dangerous_no_excuse"):
            for exc in ("none", "sudden_fight", "grave_sudden_provocation"):
                d = self.p.decide({"death_caused": False, "mens_rea": mr, "exception_state": exc})
                self.assertIsNone(d.get("offence"), f"{mr}/{exc} without death")

    def test_each_exception_reduces_murder_to_culpable_homicide(self):
        base = {"death_caused": True, "mens_rea": "intention_death"}
        self.assertEqual(self.p.decide(base)["offence"], "murder")
        for exc, extra in (("grave_sudden_provocation", {}),
                           ("private_defence_excess", {}),
                           ("public_servant_good_faith", {}),
                           ("sudden_fight", {}),
                           ("consent", {"victim_consent_adult": True})):
            d = self.p.decide({**base, "exception_state": exc, **extra})
            self.assertEqual(d["offence"], "culpable_homicide", exc)
            self.assertTrue(d["defeater"])

    def test_proviso_to_exception_1_restores_murder(self):
        facts = {"death_caused": True, "mens_rea": "intention_death",
                 "exception_state": "grave_sudden_provocation",
                 "provocation_excluded": True}
        self.assertEqual(self.p.decide(facts)["offence"], "murder")

    def test_undue_advantage_defeats_exception_4(self):
        facts = {"death_caused": True, "mens_rea": "intention_death",
                 "exception_state": "sudden_fight", "undue_advantage_cruel": True}
        self.assertEqual(self.p.decide(facts)["offence"], "murder")

    def test_consent_exception_requires_an_adult(self):
        facts = {"death_caused": True, "mens_rea": "intention_death",
                 "exception_state": "consent", "victim_consent_adult": False}
        self.assertEqual(self.p.decide(facts)["offence"], "murder")

    def test_murder_outranks_the_sentence_of_culpable_homicide(self):
        murder = self.p.decide({"death_caused": True, "mens_rea": "intention_death"})
        ch = self.p.decide({"death_caused": True, "mens_rea": "knowledge_likely_death"})
        self.assertIn("103", analyze.sentence_key(self.p, {}, murder))
        self.assertIn("105", analyze.sentence_key(self.p, {}, ch))

    def test_section_104_applies_to_a_life_convict(self):
        facts = {"death_caused": True, "mens_rea": "intention_death",
                 "offender_under_life_sentence": True}
        self.assertIn("remainder of that person", analyze.sentence_key(self.p, facts))

    def test_missing_facts_do_not_create_a_gap(self):
        # A pack that needs every fact supplied would be useless in practice.
        self.assertEqual(analyze.find_gaps(self.p)["count"], 0)


class MVEncodingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = packmod.load(MV)

    def test_every_illustration_is_reproduced(self):
        for ill in self.p.doc["illustrations"]:
            self.assertEqual(self.p.decide(ill["facts"]).get("offence"),
                             ill["expect"]["offence_kind"], ill["id"])

    def test_threshold_is_strictly_exceeding(self):
        self.assertIsNone(self.p.decide({"was_driving": True, "blood_alcohol_mg": 30}).get("offence"))
        self.assertEqual(self.p.decide({"was_driving": True, "blood_alcohol_mg": 31}).get("offence"),
                         "drunken_driving")

    def test_not_driving_is_not_an_offence_however_drunk(self):
        self.assertIsNone(self.p.decide({"was_driving": False, "blood_alcohol_mg": 60}).get("offence"))

    def test_drug_limb_needs_no_number(self):
        self.assertEqual(self.p.decide({"was_driving": True, "blood_alcohol_mg": 0,
                                        "incapable_due_to_drug": True}).get("offence"),
                         "drunken_driving")

    def test_lawful_driving_is_an_outcome_not_a_gap(self):
        g = analyze.find_gaps(self.p)
        self.assertEqual(g["count"], 0, "below-threshold driving must be decided, not missing")


class NegligenceEncodingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = packmod.load(NEGLIGENCE)

    def test_every_illustration_is_reproduced(self):
        for ill in self.p.doc["illustrations"]:
            self.assertEqual(self.p.decide(ill["facts"]).get("offence"),
                             ill["expect"]["offence_kind"], ill["id"])

    def test_no_death_is_never_a_negligence_offence(self):
        # The analyser caught this bug in an earlier draft of the homicide
        # pack: limbs did not test death_caused at all.
        for culp in ("rash_negligent", "knowledge_possibility_death", "intention_death"):
            for drv in ("not_driving", "ordinary_driving", "dangerous_or_racing"):
                d = self.p.decide({"death_caused": False, "culpability": culp,
                                   "driving_context": drv})
                self.assertIsNone(d.get("offence"), f"{culp}/{drv} without death")

    def test_intention_is_not_s106(self):
        # 'not amounting to culpable homicide' excludes intention and
        # knowledge of likely death: those are ss.100-105, not s.106.
        for culp in ("intention_death", "knowledge_likely_death"):
            d = self.p.decide({"death_caused": True, "culpability": culp,
                               "driving_context": "not_driving"})
            self.assertIsNone(d.get("offence"), culp)
            self.assertEqual(d["branch"], "N-CULPABLE-HOMICIDE", culp)

    def test_dangerous_driving_is_106_2_not_106_1(self):
        d = self.p.decide({"death_caused": True, "culpability": "rash_negligent",
                           "driving_context": "dangerous_or_racing"})
        self.assertEqual(d.get("offence"), "causing_death_by_dangerous_driving")
        self.assertEqual(d["branch"], "N-106-2")

    def test_ordinary_negligent_driving_is_106_1(self):
        d = self.p.decide({"death_caused": True, "culpability": "rash_negligent",
                           "driving_context": "ordinary_driving"})
        self.assertEqual(d.get("offence"), "causing_death_by_negligence")
        self.assertEqual(d["branch"], "N-106-1")

    def test_pure_accident_is_not_an_offence(self):
        d = self.p.decide({"death_caused": True, "culpability": "none",
                           "driving_context": "not_driving"})
        self.assertIsNone(d.get("offence"))
        self.assertEqual(d["branch"], "N-NO-FAULT")

    def test_no_gaps_and_no_contentions(self):
        self.assertEqual(analyze.find_gaps(self.p)["count"], 0)
        self.assertEqual(analyze.find_overlaps(self.p)["count"], 0)
        self.assertEqual(analyze.find_unreachable(self.p)["count"], 0)

    def test_possibility_knowledge_boundary_moves_cases(self):
        # The recorded ambiguity is real: flipping the parameter moves the
        # possibility-knowledge cases out of s.106.
        sens = analyze.find_ambiguity_sensitivity(self.p)
        amb = [a for a in sens["ambiguities"] if a["ambiguity"] == "AMB-106-KNOWLEDGE-BOUNDARY"][0]
        self.assertEqual(amb["max_moved"], 3)
        self.assertEqual(amb["max_sentence_moved"], 0)


class AbetmentEncodingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = packmod.load(ABETMENT)

    def test_every_illustration_is_reproduced(self):
        for ill in self.p.doc["illustrations"]:
            self.assertEqual(self.p.decide(ill["facts"]).get("offence"),
                             ill["expect"]["offence_kind"], ill["id"])

    def test_no_suicide_is_never_abetment(self):
        for cat in ("adult", "child", "mental_illness", "delirious", "intoxicated"):
            d = self.p.decide({"suicide_occurred": False, "abetted": True,
                               "victim_category": cat})
            self.assertIsNone(d.get("offence"), cat)

    def test_vulnerable_victim_gets_enhanced_tariff(self):
        for cat in ("child", "mental_illness", "delirious", "intoxicated"):
            d = self.p.decide({"suicide_occurred": True, "abetted": True,
                               "victim_category": cat})
            self.assertEqual(d.get("offence"), "abetment_suicide_vulnerable", cat)
            self.assertEqual(d["branch"], "N-107", cat)

    def test_adult_gets_general_tariff(self):
        d = self.p.decide({"suicide_occurred": True, "abetted": True,
                           "victim_category": "adult"})
        self.assertEqual(d.get("offence"), "abetment_suicide")
        self.assertEqual(d["branch"], "N-108")

    def test_no_gaps_and_no_contentions(self):
        self.assertEqual(analyze.find_gaps(self.p)["count"], 0)
        self.assertEqual(analyze.find_overlaps(self.p)["count"], 0)
        self.assertEqual(analyze.find_unreachable(self.p)["count"], 0)


class AttemptEncodingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = packmod.load(ATTEMPT)

    def test_every_illustration_is_reproduced(self):
        for ill in self.p.doc["illustrations"]:
            self.assertEqual(self.p.decide(ill["facts"]).get("offence"),
                             ill["expect"]["offence_kind"], ill["id"])

    def test_death_is_never_an_attempt(self):
        # An attempt that succeeds is murder, not an attempt.
        d = self.p.decide({"attempt_act": True, "death_caused": True,
                           "hurt_caused": True})
        self.assertIsNone(d.get("offence"))
        self.assertEqual(d["branch"], "N-DEATH")

    def test_hurt_raises_tariff_to_life(self):
        d = self.p.decide({"attempt_act": True, "death_caused": False,
                           "hurt_caused": True})
        self.assertEqual(d.get("offence"), "attempt_murder_hurt")
        d2 = self.p.decide({"attempt_act": True, "death_caused": False,
                            "hurt_caused": False})
        self.assertEqual(d2.get("offence"), "attempt_murder")

    def test_no_gaps_and_no_contentions(self):
        self.assertEqual(analyze.find_gaps(self.p)["count"], 0)
        self.assertEqual(analyze.find_overlaps(self.p)["count"], 0)
        self.assertEqual(analyze.find_unreachable(self.p)["count"], 0)


class AttemptCulpableHomicideEncodingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = packmod.load(ATTEMPT_CH)

    def test_every_illustration_is_reproduced(self):
        for ill in self.p.doc["illustrations"]:
            self.assertEqual(self.p.decide(ill["facts"]).get("offence"),
                             ill["expect"]["offence_kind"], ill["id"])

    def test_death_is_never_an_attempt(self):
        d = self.p.decide({"attempt_act": True, "death_caused": True,
                           "hurt_caused": True})
        self.assertIsNone(d.get("offence"))
        self.assertEqual(d["branch"], "N-DEATH")

    def test_hurt_raises_tariff_to_seven_years(self):
        d = self.p.decide({"attempt_act": True, "death_caused": False,
                           "hurt_caused": True})
        self.assertEqual(d.get("offence"), "attempt_culpable_homicide_hurt")
        d2 = self.p.decide({"attempt_act": True, "death_caused": False,
                            "hurt_caused": False})
        self.assertEqual(d2.get("offence"), "attempt_culpable_homicide")

    def test_no_gaps_and_no_contentions(self):
        self.assertEqual(analyze.find_gaps(self.p)["count"], 0)
        self.assertEqual(analyze.find_overlaps(self.p)["count"], 0)
        self.assertEqual(analyze.find_unreachable(self.p)["count"], 0)


class OrganisedCrimeEncodingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = packmod.load(ORGANISED)

    def test_every_illustration_is_reproduced(self):
        for ill in self.p.doc["illustrations"]:
            self.assertEqual(self.p.decide(ill["facts"]).get("offence"),
                             ill["expect"]["offence_kind"], ill["id"])

    def test_death_separates_the_top_tariff(self):
        base = {"activity": "organised_crime", "role": "commits"}
        self.assertEqual(self.p.decide({**base, "death_caused": True})["offence"],
                         "organised_crime_death")
        self.assertEqual(self.p.decide({**base, "death_caused": False})["offence"],
                         "organised_crime")

    def test_each_role_is_a_distinct_offence(self):
        roles = {"abet_conspire": "organised_crime_abet",
                 "membership": "organised_crime_membership",
                 "harbouring": "organised_crime_harbouring",
                 "possession": "organised_crime_possession",
                 "unaccounted_property": "organised_crime_unaccounted"}
        for role, want in roles.items():
            d = self.p.decide({"activity": "organised_crime", "role": role,
                               "death_caused": False})
            self.assertEqual(d.get("offence"), want, role)

    def test_no_activity_is_never_organised_crime(self):
        for role in ("commits", "membership", "harbouring"):
            d = self.p.decide({"activity": "other", "role": role,
                               "death_caused": True})
            self.assertIsNone(d.get("offence"), role)

    def test_no_gaps_and_no_contentions(self):
        self.assertEqual(analyze.find_gaps(self.p)["count"], 0)
        self.assertEqual(analyze.find_overlaps(self.p)["count"], 0)
        self.assertEqual(analyze.find_unreachable(self.p)["count"], 0)


class PettyOrganisedCrimeEncodingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = packmod.load(PETTY)

    def test_every_illustration_is_reproduced(self):
        for ill in self.p.doc["illustrations"]:
            self.assertEqual(self.p.decide(ill["facts"]).get("offence"),
                             ill["expect"]["offence_kind"], ill["id"])

    def test_each_listed_act_is_petty_organised_crime(self):
        for act in ("theft", "snatching", "cheating", "ticket_tout",
                    "betting", "exam_papers", "similar"):
            d = self.p.decide({"gang_member": True, "act_type": act,
                               "commits": True})
            self.assertEqual(d.get("offence"), "petty_organised_crime", act)

    def test_lone_actor_is_not_petty_organised_crime(self):
        d = self.p.decide({"gang_member": False, "act_type": "theft",
                           "commits": True})
        self.assertIsNone(d.get("offence"))
        self.assertEqual(d["branch"], "N-NO-GANG")

    def test_no_gaps_and_no_contentions(self):
        self.assertEqual(analyze.find_gaps(self.p)["count"], 0)
        self.assertEqual(analyze.find_overlaps(self.p)["count"], 0)
        self.assertEqual(analyze.find_unreachable(self.p)["count"], 0)


class TerroristActEncodingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = packmod.load(TERRORIST)

    def test_every_illustration_is_reproduced(self):
        for ill in self.p.doc["illustrations"]:
            self.assertEqual(self.p.decide(ill["facts"]).get("offence"),
                             ill["expect"]["offence_kind"], ill["id"])

    def test_death_separates_the_top_tariff(self):
        base = {"act_type": "terrorist_act", "role": "commits"}
        self.assertEqual(self.p.decide({**base, "death_caused": True})["offence"],
                         "terrorist_act_death")
        self.assertEqual(self.p.decide({**base, "death_caused": False})["offence"],
                         "terrorist_act")

    def test_each_role_is_a_distinct_offence(self):
        roles = {"conspire_abet": "terrorist_act_abet",
                 "organise_recruit": "terrorist_act_organise",
                 "membership": "terrorist_act_membership",
                 "harbouring": "terrorist_act_harbouring",
                 "possession": "terrorist_act_possession"}
        for role, want in roles.items():
            d = self.p.decide({"act_type": "terrorist_act", "role": role,
                               "death_caused": False})
            self.assertEqual(d.get("offence"), want, role)

    def test_no_act_is_never_a_terrorist_act(self):
        for role in ("commits", "membership", "harbouring"):
            d = self.p.decide({"act_type": "other", "role": role,
                               "death_caused": True})
            self.assertIsNone(d.get("offence"), role)

    def test_no_gaps_and_no_contentions(self):
        self.assertEqual(analyze.find_gaps(self.p)["count"], 0)
        self.assertEqual(analyze.find_overlaps(self.p)["count"], 0)
        self.assertEqual(analyze.find_unreachable(self.p)["count"], 0)


# ------------------------------------------------------------------- amendments

class AmendmentTests(unittest.TestCase):
    def _cmp(self, amendment_id):
        am = packmod.load_amendment(amendment_id)
        base = packmod.load(am.pack_id)
        before = analyze.amended(base, am.before_patch, "before") if am.before_patch else base
        after = analyze.amended(base, am.after_patch, "after") if am.after_patch else base
        return analyze.compare(before, after)

    def test_all_shipped_amendments_apply_cleanly(self):
        self.assertEqual(len(packmod.amendments()), 4)
        for aid in packmod.amendments():
            c = self._cmp(aid)
            self.assertGreater(c["checked"], 0, aid)

    def test_the_106_penalty_amendment_moves_no_decision_but_sentences(self):
        c = self._cmp("amend.bns.106-penalty")
        self.assertEqual(c["decisions_changed"], 0,
                         "raising a maximum cannot change whether conduct is an offence")
        self.assertEqual(c["sentences_changed"], 4)
        for m in c["moved"]:
            self.assertEqual(m["kind"], "sentence")

    def test_repealing_exception_4_moves_exactly_those_cases(self):
        c = self._cmp("amend.bns.exc4-abolished")
        self.assertEqual(c["decisions_changed"], 256)
        self.assertEqual(c["sentences_changed"], 0)
        self.assertEqual(c["matrix"]["culpable_homicide"]["murder"], 256)
        # nothing else moves: murder stays murder, non-offences stay non-offences
        self.assertEqual(c["matrix"]["murder"], {"murder": c["matrix"]["murder"]["murder"]})
        for m in c["moved"]:
            self.assertEqual(m["before"], "culpable_homicide")
            self.assertEqual(m["after"], "murder")
            self.assertEqual(m["facts"]["exception_state"], "sudden_fight")

    def test_the_2019_penalty_amendment_moves_no_decision_but_many_sentences(self):
        c = self._cmp("amend.mv.2019-penalty")
        self.assertEqual(c["decisions_changed"], 0,
                         "changing a fine cannot change whether conduct is an offence")
        self.assertGreater(c["sentences_changed"], 0)
        for m in c["moved"]:
            self.assertEqual(m["kind"], "sentence")

    def test_the_interpretive_change_moves_cases_between_offences(self):
        c = self._cmp("amend.bns.101b-generic-knowledge")
        self.assertGreater(c["decisions_changed"], 0)
        self.assertEqual(c["matrix"]["culpable_homicide"].get("murder"), c["decisions_changed"])

    def test_minimal_witness_is_reduced_and_still_changes(self):
        am = packmod.load_amendment("amend.bns.exc4-abolished")
        base = packmod.load(am.pack_id)
        after = analyze.amended(base, am.after_patch, "after")
        c = analyze.compare(base, after)
        witnesses = analyze.minimal_witnesses(base, after, c["moved"], limit=3)
        self.assertTrue(witnesses)
        for w in witnesses:
            self.assertLessEqual(len(w["facts"]), 3, w["facts"])
            self.assertNotEqual(base.decide(w["facts"]).get("offence"),
                                after.decide(w["facts"]).get("offence"))

    def test_amendment_that_removes_an_unknown_node_is_refused(self):
        base = packmod.load(MV)
        with self.assertRaises(packmod.PackError):
            analyze.amended(base, {"remove_branches": ["NO-SUCH-BRANCH"]}, "bad")

    def test_amendment_kind_is_mandatory_and_bounded(self):
        path = os.path.join(packmod.AMEND_DIR, "amend.mv.2019-penalty.json")
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        doc["kind"] = "probably"
        tmp = os.path.join("/tmp", "amend-kind-test.json")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        with self.assertRaises(packmod.PackError):
            packmod.load_amendment(tmp)


# -------------------------------------------------------------------- negative

class AnalyserCatchesItsOwnBugsTests(unittest.TestCase):
    """A green report must mean something. These tests break a pack on purpose."""

    @classmethod
    def setUpClass(cls):
        cls.base = packmod.load(HOMICIDE)

    def test_deleting_a_limb_that_an_exception_overrides_is_refused(self):
        # Structural integrity: M-101a is named in every exception's `overrides`,
        # so removing it would leave a defeater pointing at nothing.
        with self.assertRaises(packmod.PackError):
            analyze.amended(self.base, {"remove_branches": ["M-101a"]}, "broken")

    def test_a_deleted_branch_shows_up_as_a_gap(self):
        # B-100-CULPABLE-ONLY is not referenced by any defeater, so this is a
        # legal removal — and it leaves the s.100-only mental elements undecided.
        broken = analyze.amended(self.base, {"remove_branches": ["B-100-CULPABLE-ONLY"]},
                                 "broken")
        d = broken.decide({"death_caused": True, "mens_rea": "knowledge_likely_death"})
        self.assertTrue(d.get("unmatched"), d)
        gaps = analyze.find_gaps(broken)
        self.assertGreater(gaps["count"], 0)
        # and the healthy pack has none
        self.assertEqual(analyze.find_gaps(self.base)["count"], 0)

    def test_a_widened_condition_produces_an_undeclared_contention(self):
        # Make the culpable-homicide branch claim every mental element, which
        # collides with every murder limb.
        broken = analyze.amended(self.base, {"edit_branches": {
            "B-100-CULPABLE-ONLY": {"when": {
                "==": [{"var": "death_caused", "type": "bool", "default": True}, True]}}}},
            "broken")
        o = analyze.find_overlaps(broken)
        self.assertGreater(o["count"], 0)
        # and the healthy pack must not report the same thing
        self.assertEqual(analyze.find_overlaps(self.base)["count"], 0)

    def test_an_unreachable_branch_is_reported(self):
        broken = analyze.amended(self.base, {"add_branches": [{
            "id": "IMPOSSIBLE", "provision": "n/a", "verdict": "offence",
            "offence": "unreachable",
            "when": {"and": [
                {"==": [{"var": "death_caused", "type": "bool", "default": True}, True]},
                {"==": [{"var": "death_caused", "type": "bool", "default": True}, False]}]}}]},
            "broken")
        u = analyze.find_unreachable(broken)
        self.assertIn("IMPOSSIBLE", [x["id"] for x in u["points"]])

    def test_ordering_dependence_is_visible(self):
        # Two identical-priority branches with opposite outcomes: whichever the
        # author lists first decides every case. The tool must say so.
        broken = analyze.amended(self.base, {"add_branches": [{
            "id": "CONTRADICTS-101a", "provision": "n/a", "verdict": "not_offence",
            "offence": None,
            "when": {"and": [
                {"==": [{"var": "death_caused", "type": "bool", "default": True}, True]},
                {"==": [{"var": "mens_rea", "type": "enum", "default": "none"},
                        "intention_death"]}]}}]}, "broken")
        o = analyze.find_overlaps(broken)
        self.assertGreater(o["count"], 0)
        self.assertTrue(any(pt["resolved_by_ordering"] for pt in o["points"]))

    def test_digest_is_stable_and_changes_with_the_law(self):
        d1 = analyze.digest(self.base)
        d2 = analyze.digest(packmod.load(HOMICIDE))
        self.assertEqual(d1, d2)
        changed = analyze.amended(self.base, {"remove_branches": ["D-EXC4-SUDDEN-FIGHT"]}, "x")
        self.assertNotEqual(analyze.digest(changed), d1)


# --------------------------------------------------------------------- domain

class DomainTests(unittest.TestCase):
    def test_domain_size_is_the_product_of_the_facts(self):
        p = packmod.load(MV)
        expect = 1
        for values in p.domain().values():
            expect *= len(values)
        self.assertEqual(expect, 2 * 61 * 2 * 3)

    def test_comparison_runs_over_the_union_when_a_fact_is_added(self):
        base = packmod.load(MV)
        wider = analyze.amended(base, {"facts": base.doc["facts"] + [
            {"name": "vehicle_is_commercial", "type": "bool", "label": "commercial vehicle"}]},
            "wider")
        c = analyze.compare(base, wider)
        self.assertEqual(c["facts_added"], ["vehicle_is_commercial"])
        self.assertEqual(c["checked"], 732 * 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
