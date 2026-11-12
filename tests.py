"""Automated tests for NYAYA-RAC v0.5.0 (Phases 1-3 + admin gating).

Run: python3 tests.py

The suite runs against THROWAWAY databases: NYAYA_DB and NYAYA_EVIDENCE_DIR are
pointed at tempfiles/dirs *before* `server` is imported, and the engine's audit
DB is redirected too, so no test can touch the live nyaya-rac.sqlite3.
"""

import base64
import datetime as dt
import hashlib
import json
import os
import tempfile
import unittest
import uuid

# ---- isolate every database BEFORE importing the portal -------------------
_TMP = tempfile.mkdtemp(prefix="nyaya-test-")
os.environ["NYAYA_DB"] = os.path.join(_TMP, "test-portal.sqlite3")
os.environ["NYAYA_EVIDENCE_DIR"] = os.path.join(_TMP, "evidence")
os.environ["NYAYA_ADMIN_EMAIL"] = "admin@nyaya.test"
os.environ["NYAYA_ADMIN_PASSWORD"] = "TestAdminPass123"

import digilocker as dl              # noqa: E402
import engine as engine_mod          # noqa: E402
import uncertainty as uncertainty_mod  # noqa: E402
import legal_kb                      # noqa: E402
import server as portal              # noqa: E402


def setUpModule() -> None:
    portal.init_all()
    tmp = tempfile.NamedTemporaryFile(suffix="-audit.sqlite3", delete=False)
    tmp.close()
    portal.ENGINE.db_path = tmp.name
    portal.ENGINE._init_db()


def fresh_engine() -> engine_mod.Engine:
    eng = engine_mod.Engine()
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
    tmp.close()
    eng.db_path = tmp.name
    eng._init_db()
    return eng


BASE_FACTS = {
    "task_class": "SUBSTANTIVE",
    "domain": "CRIMINAL",
    "offence": {"start_yyyymmdd": 20261101, "end_yyyymmdd": 20261101},
}


def with_base(**extra):
    import copy
    f = copy.deepcopy(BASE_FACTS)
    f.update(extra)
    return f


# =========================================================== engine (v0.2.0)


class ConfigCompletenessTests(unittest.TestCase):
    """Config keys that made T-02 and all urgency rules dead code."""

    def test_minor_age_keys_present(self):
        cfg = engine_mod.EMBEDDED_DEMO["config"]
        self.assertEqual(cfg["minor_age_threshold_years"], 18)
        self.assertEqual(cfg["jj_act_preliminary_assessment_min_age_years"], 16)

    def test_urgency_thresholds_present(self):
        cfg = engine_mod.EMBEDDED_DEMO["config"]["urgency"]
        self.assertEqual(cfg["art22_2_hours_remaining_lte"], 6)
        self.assertEqual(cfg["default_bail_days_remaining_lte"], 7)
        self.assertEqual(cfg["limitation_days_remaining_lte"], 30)

    def test_jj_act_trigger_can_now_fire(self):
        eng = fresh_engine()
        res = eng.evaluate(facts=with_base(
            parties={"accused_minor_status": "CONFIRMED_MINOR",
                     "accused_age_min": 16, "accused_age_max": 17,
                     "victim_minor_status": "CONFIRMED_ADULT"},
            offences=[{"provision": "s.X", "statute": "DEMO",
                       "punishment": {"min_years": 7, "max_years": 10},
                       "verified_in_corpus": True}],
        ))
        ids = [t["id"] for t in res["output"]["manual_review"]["triggers_fired"]]
        self.assertIn("T-02", ids)
        self.assertEqual(res["output"]["manual_review"]["required_level"], "L3")

    def test_urgency_rule_can_now_fire(self):
        eng = fresh_engine()
        res = eng.evaluate(facts=with_base(**{
            "person_in_custody": True,
            "art22_2.hours_remaining": 5,
        }))
        self.assertEqual(res["output"]["manual_review"]["urgency"], "HIGH")


class NestedTriStateTests(unittest.TestCase):
    """Nested data handling / tri-state normalization."""

    def test_nested_bool_flags_become_tri_state_strings(self):
        eng = fresh_engine()
        res = eng.evaluate(facts=with_base(
            flags={"woman_victim_sexual_offence": True, "in_custody": False},
            parties={"victim_minor_status": "CONFIRMED_ADULT"},
            is_sexual_offence=True,
        ))
        flags = res["output"]["parties"]["vulnerability_flags"]
        self.assertEqual(flags["woman_victim_sexual_offence"], "TRUE")
        self.assertEqual(flags["in_custody"], "FALSE")

    def test_nested_bool_flag_drives_strict_comparison_derived_fact(self):
        # any_vulnerability_flag_true uses {"===": [flag, "TRUE"]} which could
        # never match a raw nested bool before the fix. With base tier >= 3,
        # T-10 depends on that derived fact and must now fire.
        eng = fresh_engine()
        res = eng.evaluate(facts=with_base(
            offences=[{"provision": "s.X", "statute": "DEMO",
                       "max_punishment": "10 years", "verified_in_corpus": True}],
            flags={"disability": True},
            parties={"victim_minor_status": "CONFIRMED_ADULT"},
        ))
        ids = [t["id"] for t in res["output"]["manual_review"]["triggers_fired"]]
        self.assertIn("T-10", ids)

    def test_non_tri_state_bools_stay_bools(self):
        eng = fresh_engine()
        facts = with_base(preventive_detention=True, is_sexual_offence=True,
                          parties={"victim_minor_status": "CONFIRMED_ADULT"})
        res = eng.evaluate(facts=facts)
        arts = [f["article"] for f in res["output"]["constitutional_flags"]]
        self.assertIn("22(3)-(7)", arts)

    def test_caller_facts_are_not_mutated(self):
        eng = fresh_engine()
        facts = {"flags": {"in_custody": True}, "is_sexual_offence": True,
                 **{k: v for k, v in BASE_FACTS.items()}}
        eng.evaluate(facts=facts)
        self.assertIs(facts["flags"]["in_custody"], True)
        self.assertIs(facts["is_sexual_offence"], True)

    def test_constitutional_custody_flag_fires_for_flat_bool(self):
        eng = fresh_engine()
        res = eng.evaluate(facts=with_base(in_custody=True))
        arts = [f["article"] for f in res["output"]["constitutional_flags"]]
        self.assertIn("22(1)-(2)", arts)

    def test_constitutional_custody_flag_fires_for_nested_tri_state(self):
        eng = fresh_engine()
        res = eng.evaluate(facts=with_base(flags={"in_custody": True}))
        arts = [f["article"] for f in res["output"]["constitutional_flags"]]
        self.assertIn("22(1)-(2)", arts)

    def test_art20_risk_accepts_string_true(self):
        eng = fresh_engine()
        res = eng.evaluate(facts=with_base(art20_double_jeopardy_risk="TRUE"))
        arts = [f["article"] for f in res["output"]["constitutional_flags"]]
        self.assertIn("20(2)", arts)

    def test_flat_dotted_layout_backwards_compatible(self):
        eng = fresh_engine()
        res = eng.evaluate(facts={
            "task_class": "SUBSTANTIVE", "domain": "CRIMINAL",
            "offence.start_yyyymmdd": 20261101, "offence.end_yyyymmdd": 20261101,
            "flags.woman_victim_sexual_offence": True,
            "parties.victim_minor_status": "CONFIRMED_ADULT",
            "is_sexual_offence": True,
        })
        flags = res["output"]["parties"]["vulnerability_flags"]
        self.assertEqual(flags["woman_victim_sexual_offence"], "TRUE")


class TriggerLevelTests(unittest.TestCase):
    """triggers_fired in engine output must carry their level."""

    def test_output_triggers_include_level(self):
        eng = fresh_engine()
        res = eng.evaluate(facts=with_base(
            is_sexual_offence=True,
            parties={"victim_minor_status": "CONFIRMED_ADULT"},
        ))
        fired = res["output"]["manual_review"]["triggers_fired"]
        self.assertTrue(fired)
        for t in fired:
            self.assertIn("level", t)
            self.assertIn(t["level"], ("L0", "L1", "L2", "L3"))
        ids = {t["id"]: t["level"] for t in fired}
        self.assertEqual(ids.get("T-11"), "L2")


class SeverityTests(unittest.TestCase):
    """Punishment text parsing + double-escalation guard."""

    def _tier(self, offences):
        eng = fresh_engine()
        res = eng.evaluate(facts=with_base(
            offences=offences, parties={"victim_minor_status": "CONFIRMED_ADULT"}))
        return res["output"]["severity"], res["output"]["manual_review"]

    def test_seven_year_text_gives_s2(self):
        sev, _ = self._tier([{"provision": "s.X", "statute": "DEMO",
                              "max_punishment": "7 years", "verified_in_corpus": True}])
        self.assertEqual(sev["base_tier"], "S2")
        self.assertEqual(sev["final_tier"], "S2")

    def test_ten_year_text_gives_s3(self):
        sev, _ = self._tier([{"provision": "s.X", "statute": "DEMO",
                              "max_punishment": "up to 10 years", "verified_in_corpus": True}])
        self.assertEqual(sev["base_tier"], "S3")

    def test_range_text_takes_top_number(self):
        sev, _ = self._tier([{"provision": "s.X", "statute": "DEMO",
                              "max_punishment": "3 to 7 years", "verified_in_corpus": True}])
        self.assertEqual(sev["base_tier"], "S2")

    def test_life_text_gives_s4(self):
        sev, _ = self._tier([{"provision": "s.X", "statute": "DEMO",
                              "max_punishment": "imprisonment for life", "verified_in_corpus": True}])
        self.assertEqual(sev["base_tier"], "S4")

    def test_death_text_gives_s5_and_L3(self):
        sev, mr = self._tier([{"provision": "s.X", "statute": "DEMO",
                               "max_punishment": "death", "verified_in_corpus": True}])
        self.assertEqual(sev["final_tier"], "S5")
        self.assertEqual(mr["required_level"], "L3")
        self.assertIn("T-01", [t["id"] for t in mr["triggers_fired"]])

    def test_not_specified_text_is_ignored(self):
        sev, _ = self._tier([{"provision": "s.X", "statute": "DEMO",
                              "max_punishment": "Not specified", "verified_in_corpus": False}])
        self.assertEqual(sev["base_tier"], "S1")

    def test_structured_punishment_dict_still_preferred(self):
        sev, _ = self._tier([{"provision": "s.X", "statute": "DEMO",
                              "punishment": {"min_years": 10, "max_years": 20},
                              "max_punishment": "3 years", "verified_in_corpus": True}])
        self.assertEqual(sev["base_tier"], "S4")  # 20 > 10 → S4, text ignored

    def test_child_victim_escalates_once(self):
        sev, _ = self._tier([{"provision": "s.X", "statute": "DEMO",
                              "max_punishment": "7 years", "verified_in_corpus": True}])
        self.assertEqual(sev["base_tier"], "S2")
        eng = fresh_engine()
        res = eng.evaluate(facts=with_base(
            offences=[{"provision": "s.X", "statute": "DEMO",
                       "max_punishment": "7 years", "verified_in_corpus": True}],
            parties={"victim_minor_status": "CONFIRMED_MINOR"},
        ))
        self.assertEqual(res["output"]["severity"]["final_tier"], "S3")  # M-01 once
        self.assertIn("M-01", res["output"]["severity"]["modifiers_applied"])

    def test_child_specific_statute_blocks_double_escalation(self):
        eng = fresh_engine()
        res = eng.evaluate(facts=with_base(
            offences=[{"provision": "s.X", "statute": "POCSO Act",
                       "max_punishment": "7 years", "child_specific_statute": True,
                       "verified_in_corpus": True}],
            parties={"victim_minor_status": "CONFIRMED_MINOR"},
        ))
        self.assertNotIn("M-01", res["output"]["severity"]["modifiers_applied"])
        self.assertEqual(res["output"]["severity"]["final_tier"], "S2")

    def test_heinous_from_life_or_death(self):
        agg = engine_mod.compute_agg(
            [{"punishment": {"life": True}}], {"heinous_min_punishment_years": 7})
        self.assertTrue(agg["heinous_any"])
        agg = engine_mod.compute_agg(
            [{"max_punishment": "7 years"}], {"heinous_min_punishment_years": 7})
        self.assertFalse(agg["heinous_any"])  # max 7 with unknown minimum is not heinous
        agg = engine_mod.compute_agg(
            [{"min_punishment": "7 years", "max_punishment": "10 years"}],
            {"heinous_min_punishment_years": 7})
        self.assertTrue(agg["heinous_any"])


# =================================================== Phase 1: strict validation


class PanchayatDateValidationTests(unittest.TestCase):
    """Phase 1: the engine refuses malformed / impossible / reversed dates."""

    def test_missing_dates_still_allowed(self):
        eng = fresh_engine()
        res = eng.evaluate(facts={"task_class": "SUBSTANTIVE", "domain": "CRIMINAL"})
        self.assertIn("output", res)  # UNDETERMINED regime, not an error

    def test_string_date_rejected(self):
        eng = fresh_engine()
        with self.assertRaises(ValueError):
            eng.evaluate(facts=with_base(offence={"start_yyyymmdd": "2026-11-01"}))

    def test_impossible_calendar_date_rejected(self):
        eng = fresh_engine()
        with self.assertRaises(ValueError):
            eng.evaluate(facts=with_base(offence={"start_yyyymmdd": 20260230}))

    def test_end_before_start_rejected(self):
        eng = fresh_engine()
        with self.assertRaises(ValueError):
            eng.evaluate(facts=with_base(
                offence={"start_yyyymmdd": 20261105, "end_yyyymmdd": 20261101}))

    def test_out_of_range_year_rejected(self):
        eng = fresh_engine()
        with self.assertRaises(ValueError):
            eng.evaluate(facts=with_base(offence={"start_yyyymmdd": 17990101}))

    def test_short_digit_string_rejected(self):
        eng = fresh_engine()
        with self.assertRaises(ValueError):
            eng.evaluate(facts=with_base(offence={"start_yyyymmdd": 2026111}))


class JsonSchemaValidatorTests(unittest.TestCase):
    """Phase 1: the internal draft-07 subset validator."""

    def test_required_and_type(self):
        errs = engine_mod.validate_json_schema({"a": 1}, {"type": "object", "required": ["b"]})
        self.assertTrue(any("b" in e for e in errs))
        errs = engine_mod.validate_json_schema("x", {"type": "object"})
        self.assertTrue(errs)

    def test_enum_and_range(self):
        schema = {"properties": {"k": {"enum": ["A", "B"]}}}
        self.assertEqual(engine_mod.validate_json_schema({"k": "A"}, schema), [])
        self.assertTrue(engine_mod.validate_json_schema({"k": "C"}, schema))

    def test_array_items(self):
        schema = {"properties": {"l": {"type": "array", "items": {"type": "string"}}}}
        self.assertEqual(engine_mod.validate_json_schema({"l": ["a", "b"]}, schema), [])
        self.assertTrue(engine_mod.validate_json_schema({"l": ["a", 2]}, schema))

    def test_real_output_conforms_to_embedded_schema(self):
        eng = fresh_engine()
        res = eng.evaluate(facts=with_base(
            parties={"victim_minor_status": "CONFIRMED_ADULT"}))
        self.assertEqual(
            engine_mod.validate_json_schema(res["output"], engine_mod.EMBEDDED_DEMO["output_schema"]), [])
        ov01 = [v for v in res["validators"] if v["id"] == "OV-01"][0]
        self.assertEqual(ov01["status"], "passed")

    def test_audit_can_be_suppressed(self):
        eng = fresh_engine()
        res = eng.evaluate(facts=with_base(), record_audit=False)
        self.assertIsNone(res["audit_id"])
        res = eng.evaluate(facts=with_base(), case_id="AUD")
        self.assertIsNotNone(res["audit_id"])


# ============================================== intake mapping (server layer)


class PortalIntakeTests(unittest.TestCase):
    """Intake mapping, strict portal dates, keyword scan."""

    ANSWERS = {
        "domain": "CRIMINAL", "victim_under18": "no", "woman_or_girl": "yes",
        "sexual_offence": "yes", "accused_in_custody": "no",
        "liberty_threat": "yes", "accused_under18": "", "has_lawyer": "not_yet",
        "provision": "s.352", "statute": "BNS",
        "disability": False, "mental_illness": False, "sc_st_atrocities": False,
        "transgender": False, "senior_citizen": False,
    }

    def test_build_engine_inputs(self):
        facts, rt = portal.build_engine_inputs(self.ANSWERS, dt.date(2026, 11, 2), None)
        self.assertEqual(facts["parties"]["victim_minor_status"], "CONFIRMED_ADULT")
        self.assertEqual(facts["flags"]["woman_victim_sexual_offence"], "TRUE")
        self.assertEqual(facts["offence"]["start_yyyymmdd"], 20261102)
        self.assertTrue(facts["touches_personal_liberty"])
        self.assertTrue(facts["is_sexual_offence"])
        self.assertEqual(rt["legal_aid_check_status"], "UNRESOLVED")
        self.assertTrue(rt["victim_unrepresented"])
        self.assertEqual(facts["offences"][0]["statute"], "BNS")

    def test_prefer_not_to_say_is_protective(self):
        a = dict(self.ANSWERS, victim_under18="prefer_not")
        facts, _ = portal.build_engine_inputs(a, dt.date(2026, 11, 2), None)
        self.assertEqual(facts["parties"]["victim_minor_status"], "UNDETERMINED")

    def test_intake_to_engine_end_to_end(self):
        facts, rt = portal.build_engine_inputs(self.ANSWERS, dt.date(2026, 11, 2), None)
        eng = fresh_engine()
        res = eng.evaluate(facts=facts, runtime_variables=rt, case_id="T-E2E")
        mr = res["output"]["manual_review"]
        ids = {t["id"]: t["level"] for t in mr["triggers_fired"]}
        self.assertIn("T-11", ids)   # sexual offence
        self.assertIn("T-12", ids)   # personal liberty
        self.assertIn("T-15", ids)   # unrepresented, legal aid unresolved
        self.assertEqual(mr["required_level"], "L2")
        self.assertEqual(res["case_id"], "T-E2E")

    def test_strict_date_validation(self):
        ok = portal.parse_incident_date("2026-11-02", "Incident date")
        self.assertEqual(ok, dt.date(2026, 11, 2))
        for bad in ["2026-02-30", "2026-13-01", "garbage", "2026/11/02",
                    (dt.date.today() + dt.timedelta(days=1)).isoformat(), "1899-12-31"]:
            with self.assertRaises(ValueError):
                portal.parse_incident_date(bad, "Incident date")

    def test_keyword_scan(self):
        hits = portal.scan_keywords("He threatened to kill me and took my phone.")
        self.assertIn("threat/coercion", hits)
        self.assertIn("violence/injury", hits)
        self.assertEqual(portal.scan_keywords("A quiet civil dispute over rent."), {})

    def test_enrich_triggers_prefers_engine_level(self):
        enriched = portal._enrich_triggers([{"id": "T-11", "level": "L2", "reason": "x"}])
        self.assertEqual(enriched[0]["level"], "L2")
        enriched = portal._enrich_triggers([{"id": "T-11", "reason": "x"}])
        self.assertEqual(enriched[0]["level"], "L2")  # joined from rule base


# ================================================== Phase 2: statutory KB


class KnowledgeBaseTests(unittest.TestCase):
    """Versioned statutory DB, verification gate, precedents, conflicts."""

    def test_provision_normalisation(self):
        self.assertEqual(legal_kb.norm_provision("Section 302"), "302")
        self.assertEqual(legal_kb.norm_provision("s. 302"), "302")
        self.assertEqual(legal_kb.norm_statute("I.P.C."), "ipc")

    def test_seed_rows_are_shipped_unverified(self):
        # (another suite deliberately verifies the IPC row, so assert on the
        # demo-only seeds plus the add-time default)
        demo = [r for r in legal_kb.statute_rows() if r["statute"] == "DEMO Act"]
        self.assertTrue(demo)
        self.assertTrue(all(r["verified"] == 0 for r in demo))
        legal_kb.add_statute_version("T-VER", "1", "V1", "2020-01-01", None, added_by="test")
        self.assertEqual(legal_kb.resolve_provision("T-VER", "1", "2021-01-01")["row"]["verified"], 0)

    def test_resolution_matrix(self):
        legal_kb.add_statute_version("T-KB", "10", "T1", "2020-01-01", "2021-12-31",
                                     pun_max_years=3, added_by="test")
        legal_kb.add_statute_version("T-KB", "10", "T2", "2022-01-01", None,
                                     pun_max_years=7, added_by="test")
        # inside range, still unverified → punishment withheld
        res = legal_kb.resolve_provision("T-KB", "10", "2020-06-01")
        self.assertEqual(res["kind"], "UNVERIFIED")
        # before any version
        self.assertEqual(legal_kb.resolve_provision("T-KB", "10", "2019-06-01")["kind"],
                         "NO_VERSION_FOR_DATE")
        # unknown citation
        self.assertEqual(legal_kb.resolve_provision("T-KB", "999", "2020-06-01")["kind"],
                         "NOT_IN_KB")
        self.assertEqual(legal_kb.resolve_provision("T-KB", "", "2020-06-01")["kind"],
                         "NO_CITATION")
        # human verification unlocks punishment for the whole version
        legal_kb.mark_statute_verified(res["row"]["id"], "tester")
        res = legal_kb.resolve_provision("T-KB", "10", "2020-06-01")
        self.assertEqual(res["kind"], "VERIFIED")
        ctx = legal_kb.kb_context_for("T-KB", "10", "2020-06-01")
        self.assertEqual(ctx["punishment"], {"max_years": 3})
        self.assertTrue(ctx["sources"])
        # the newer, still-unverified version does not leak punishment
        ctx2 = legal_kb.kb_context_for("T-KB", "10", "2022-06-01")
        self.assertIsNone(ctx2["punishment"])
        self.assertEqual(ctx2["resolution"]["kind"], "UNVERIFIED")

    def test_unverified_punishment_never_reaches_engine(self):
        facts = {"offences": [{"provision": "s.999", "statute": "GHOST",
                               "max_punishment": "Not specified"}]}
        kb = legal_kb.kb_context_for("GHOST", "999", "2026-01-01")
        portal.apply_kb_context(facts, kb)
        self.assertNotIn("punishment", facts["offences"][0])
        self.assertEqual(kb["resolution"]["kind"], "NOT_IN_KB")

    def test_verified_punishment_does_reach_engine(self):
        legal_kb.add_statute_version("T-KB2", "5", "K1", "2020-01-01", None,
                                     pun_death=True, pun_min_years=10, added_by="test")
        row = legal_kb.resolve_provision("T-KB2", "5", "2026-01-01")["row"]
        legal_kb.mark_statute_verified(row["id"], "tester")
        facts = {"offences": [{"provision": "s.5", "statute": "T-KB2"}]}
        portal.apply_kb_context(facts, legal_kb.kb_context_for("T-KB2", "5", "2026-01-01"))
        self.assertEqual(facts["offences"][0]["punishment"]["death"], True)
        self.assertTrue(facts["offences"][0]["verified_in_corpus"])

    def test_rule_version_missing_sets_t16_fact(self):
        kb = legal_kb.kb_context_for("T-KB", "10", "1990-01-01")
        self.assertEqual(kb["resolution"]["kind"], "NO_VERSION_FOR_DATE")
        self.assertTrue(kb["facts_extra"].get("rule_version_missing_for_date"))
        eng = fresh_engine()
        facts = with_base()
        portal.apply_kb_context(facts, kb)
        res = eng.evaluate(facts=facts)
        self.assertIn("T-16", [t["id"] for t in res["output"]["manual_review"]["triggers_fired"]])

    def test_precedent_conflict_sets_t05_fact(self):
        legal_kb.add_precedent("(T) Strict v State", "Test Court", "2024-01-01",
                               statute="T-CONF", provision="7", holding_tag="SUPPORTS_STRICT",
                               added_by="test")
        legal_kb.add_precedent("(T) Lenient v State", "Test Court", "2024-02-02",
                               statute="T-CONF", provision="7", holding_tag="SUPPORTS_LENIENT",
                               added_by="test")
        kb = legal_kb.kb_context_for("T-CONF", "7", "2026-01-01")
        self.assertTrue(kb["facts_extra"].get("precedent_conflict"))
        kinds = {c["kind"] for c in kb["conflicts"]}
        self.assertIn("PRECEDENT_CONFLICT", kinds)
        eng = fresh_engine()
        facts = with_base()
        portal.apply_kb_context(facts, kb)
        res = eng.evaluate(facts=facts)
        self.assertIn("T-05", [t["id"] for t in res["output"]["manual_review"]["triggers_fired"]])

    def test_set_precedent_status(self):
        pid = legal_kb.add_precedent("(T) Old v State", "Test Court", "2020-01-01",
                                     statute="T-OVR", provision="1", holding_tag="PROCEDURAL",
                                     added_by="test")
        legal_kb.set_precedent_status(pid, "OVERRULED", overruled_by="(T) New v State")
        row = [p for p in legal_kb.precedent_rows() if p["id"] == pid][0]
        self.assertEqual(row["status"], "OVERRULED")
        self.assertEqual(row["overruled_by"], "(T) New v State")
        with self.assertRaises(ValueError):
            legal_kb.set_precedent_status(pid, "NOT_A_STATUS")

    def test_overlapping_versions_detected(self):
        legal_kb.add_statute_version("T-OVL", "2", "O1", "2020-01-01", "2024-12-31",
                                     added_by="test")
        legal_kb.add_statute_version("T-OVL", "2", "O2", "2022-01-01", "2026-12-31",
                                     added_by="test")
        kinds = {c["kind"] for c in legal_kb.detect_conflicts()
                 if c["statute"] == "T-OVL"}
        self.assertIn("OVERLAPPING_VERSIONS", kinds)
        self.assertTrue(legal_kb.kb_context_for("T-OVL", "2", "2023-01-01")["facts_extra"]
                        .get("provision_ambiguous"))

    def test_provenance_chain_links_disclosure_and_revision(self):
        chain = legal_kb.provenance_chain("STATUTE_VERSION", "BNS-2023|103", depth=2)
        self.assertTrue(chain["nodes"])
        edges = {(e["predicate"], e["object"]["type"]) for e in chain["edges"]}
        self.assertIn(("AMENDS", "STATUTE_VERSION"), edges)


# ==================================== portal fixtures shared by portal tests


def make_user(name="Test User", email=None, role="USER"):
    email = email or (name.lower().replace(" ", ".") + "@nyaya.test")
    try:
        portal.create_user(name, email, "testpass123", role=role)
    except ValueError:
        pass
    return portal.authenticate(email, "testpass123")


def intake_body(**over):
    body = {
        "narrative": ("The accused threatened to kill me, pushed me against a wall and "
                      "took my phone so I could not call for help. I have photos."),
        "incident_date": "2026-11-01",
        "location": "Gwalior",
        "domain": "CRIMINAL",
        "victim_under18": "no", "woman_or_girl": "yes", "sexual_offence": "no",
        "accused_in_custody": "no", "liberty_threat": "yes",
        "accused_under18": "", "has_lawyer": "not_yet",
        "provision": "", "statute": "",
        "disability": False, "mental_illness": False, "sc_st_atrocities": False,
        "transgender": False, "senior_citizen": False,
        "declaration": True,
        "evidence": [{"name": "photo.png", "type": "image/png",
                      "data_b64": base64.b64encode(b"fake-png-bytes").decode()}],
    }
    body.update(over)
    return body


class PortalFixture(unittest.TestCase):
    counter = 0

    @classmethod
    def setUpClass(cls):
        PortalFixture.counter += 1
        n = PortalFixture.counter
        cls.owner = make_user(f"Owner {n}", f"owner{n}@nyaya.test")
        cls.other = make_user(f"Stranger {n}", f"stranger{n}@nyaya.test")
        try:
            portal.create_user("Administrator", "admin@nyaya.test", "TestAdminPass123", role="ADMIN")
        except ValueError:
            pass
        cls.admin = portal.authenticate("admin@nyaya.test", "TestAdminPass123")

    def new_report(self, **over):
        """Submit an intake and return the flat summary the UI consumes."""
        return portal.intake_report(self.owner, intake_body(**over))["summary"]

    def revise(self, report_id, body, actor_user=None):
        return portal.revise_report(actor_user or self.owner, report_id, body)["summary"]


# =========================================== access control + disclosure gate


class AccessControlTests(PortalFixture):
    """Strict admin gating: nothing is visible until disclosed AND approved."""

    def test_private_by_default(self):
        rep = self.new_report()
        self.assertEqual(rep["disclosure_status"], "PRIVATE")
        self.assertEqual(rep["manual_check_status"], "UNCHECKED")

    def test_owner_sees_full_payload(self):
        rep = self.new_report()
        payload = portal.build_case_payload(self.owner, rep["report_id"])
        self.assertEqual(payload["access"], "FULL")
        self.assertTrue(payload["viewer"]["is_owner"])
        self.assertIn("narrative", payload)
        self.assertNotIn("user_id", payload)

    def test_admin_sees_full_payload(self):
        rep = self.new_report()
        payload = portal.build_case_payload(self.admin, rep["report_id"])
        self.assertEqual(payload["access"], "FULL")
        self.assertFalse(payload["viewer"]["is_owner"])
        self.assertEqual(payload["viewer"]["role"], "ADMIN")

    def test_stranger_gets_not_found_not_forbidden(self):
        rep = self.new_report()
        with self.assertRaises(portal.NotFound):
            portal.build_case_payload(self.other, rep["report_id"])

    def test_pending_request_is_still_hidden(self):
        rep = self.new_report()
        portal.request_disclosure(self.owner, rep["report_id"], "please publish")
        with self.assertRaises(portal.NotFound):
            portal.build_case_payload(self.other, rep["report_id"])
        self.assertNotIn(rep["report_id"],
                         [c["id"] for c in portal.disclosed_list(self.other)["cases"]])

    def test_approved_anonymized_redacts_everything_identifying(self):
        rep = self.new_report()
        portal.request_disclosure(self.owner, rep["report_id"])
        portal.admin_disclosure(self.admin, rep["report_id"], "APPROVE", "ANONYMIZED", "ok")
        payload = portal.build_case_payload(self.other, rep["report_id"])
        self.assertEqual(payload["access"], "ANONYMIZED")
        self.assertIn("Redacted", payload["narrative"])
        self.assertEqual(payload["location"], "")
        self.assertEqual(payload["answers"], {})
        self.assertEqual(payload["facts"], {})
        self.assertEqual(payload["keywords"], {})
        self.assertTrue(all(e["filename"] == "[hidden]" for e in payload["evidence"]))
        self.assertTrue(all(r["reason"] == "[redacted]" for r in payload["revisions"]))
        self.assertNotIn("user_id", payload)
        # the routing answer itself (the useful part) survives
        self.assertIn(payload["review_level"], ("L0", "L1", "L2", "L3"))

    def test_approved_full_disclosure_reveals_narrative(self):
        rep = self.new_report()
        portal.request_disclosure(self.owner, rep["report_id"])
        portal.admin_disclosure(self.admin, rep["report_id"], "APPROVE", "FULL")
        payload = portal.build_case_payload(self.other, rep["report_id"])
        self.assertEqual(payload["access"], "FULL")
        self.assertNotIn("Redacted", payload["narrative"])
        listed = [c for c in portal.disclosed_list(self.other)["cases"] if c["id"] == rep["report_id"]]
        self.assertEqual(len(listed), 1)
        self.assertIn("excerpt", listed[0])

    def test_anonymized_excerpt_hidden_in_registry(self):
        rep = self.new_report()
        portal.request_disclosure(self.owner, rep["report_id"])
        portal.admin_disclosure(self.admin, rep["report_id"], "APPROVE", "ANONYMIZED")
        item = [c for c in portal.disclosed_list(self.other)["cases"] if c["id"] == rep["report_id"]][0]
        self.assertNotIn("excerpt", item)
        # admins still see the excerpt
        admin_item = [c for c in portal.disclosed_list(self.admin)["cases"] if c["id"] == rep["report_id"]][0]
        self.assertIn("excerpt", admin_item)


class DisclosureLifecycleTests(PortalFixture):
    def test_full_lifecycle(self):
        rep = self.new_report()
        rid = rep["report_id"]
        self.assertEqual(portal.request_disclosure(self.owner, rid)["disclosure_status"], "PENDING")
        with self.assertRaises(ValueError):  # cannot double-request while pending
            portal.request_disclosure(self.owner, rid)
        portal.admin_disclosure(self.admin, rid, "REJECT", "ANONYMIZED", "identifying detail")
        row = portal.build_case_payload(self.owner, rid)
        self.assertEqual(row["disclosure_status"], "REJECTED")
        with self.assertRaises(portal.NotFound):
            portal.build_case_payload(self.other, rid)
        # rejected cases may be re-requested
        self.assertEqual(portal.request_disclosure(self.owner, rid)["disclosure_status"], "PENDING")
        portal.admin_disclosure(self.admin, rid, "APPROVE", "FULL")
        portal.admin_disclosure(self.admin, rid, "REVOKE", "FULL")
        self.assertEqual(portal.build_case_payload(self.owner, rid)["disclosure_status"], "PRIVATE")
        with self.assertRaises(portal.NotFound):
            portal.build_case_payload(self.other, rid)

    def test_direct_disclose_without_request(self):
        rep = self.new_report()
        portal.admin_disclosure(self.admin, rep["report_id"], "DISCLOSE", "ANONYMIZED")
        self.assertEqual(portal.build_case_payload(self.other, rep["report_id"])["access"], "ANONYMIZED")

    def test_only_owner_may_request(self):
        rep = self.new_report()
        with self.assertRaises(portal.AccessDenied):
            portal.request_disclosure(self.other, rep["report_id"])

    def test_non_admin_cannot_decide(self):
        rep = self.new_report()
        portal.request_disclosure(self.owner, rep["report_id"])
        for actor in (self.owner, self.other):
            with self.assertRaises(portal.AccessDenied):
                portal.admin_disclosure(actor, rep["report_id"], "APPROVE", "FULL")

    def test_invalid_action_and_mode(self):
        rep = self.new_report()
        with self.assertRaises(ValueError):
            portal.admin_disclosure(self.admin, rep["report_id"], "PUBLISH", "FULL")
        with self.assertRaises(ValueError):
            portal.admin_disclosure(self.admin, rep["report_id"], "DISCLOSE", "PARTIAL")


# ======================================================= revisions / re-check


class RevisionTests(PortalFixture):
    def test_revision_creates_immutable_history(self):
        rep = self.new_report()
        rid = rep["report_id"]
        self.assertEqual(rep["rev_no"], 1)
        rev = portal.revise_report(self.owner, rid, intake_body(
            reason="Corrected the incident date after checking my diary.",
            incident_date="2026-10-20", sexual_offence="no"))["summary"]
        self.assertEqual(rev["rev_no"], 2)
        payload = portal.build_case_payload(self.owner, rid)
        self.assertEqual(payload["current_rev_no"], 2)
        self.assertEqual([r["rev_no"] for r in payload["revisions"]], [1, 2])
        self.assertEqual(payload["revisions"][1]["actor"], "OWNER")
        self.assertEqual(payload["revisions"][1]["reason"][:9], "Corrected")
        # rev 1 snapshot is preserved verbatim (audit integrity)
        self.assertEqual(payload["revisions"][0]["reason"], "Original submission")
        self.assertEqual(len(payload["revisions"]), 2)

    def test_reason_is_mandatory(self):
        rep = self.new_report()
        with self.assertRaises(ValueError):
            portal.revise_report(self.owner, rep["report_id"], intake_body(reason=""))

    def test_stranger_cannot_revise(self):
        rep = self.new_report()
        with self.assertRaises(portal.AccessDenied):
            portal.revise_report(self.other, rep["report_id"], intake_body(reason="meddling here"))

    def test_admin_can_revise_on_behalf(self):
        rep = self.new_report()
        rev = portal.revise_report(self.admin, rep["report_id"], intake_body(
            reason="Registry corrected the answers during manual review."))["summary"]
        self.assertEqual(rev["actor"], "ADMIN")

    def test_revision_resets_verification(self):
        rep = self.new_report()
        rid = rep["report_id"]
        portal.apply_manual_check(self.admin, rid, "VERIFIED", "looks right")
        self.assertEqual(portal.build_case_payload(self.owner, rid)["manual_check_status"], "VERIFIED")
        portal.revise_report(self.owner, rid, intake_body(reason="Fixed a wrongly answered question."))
        self.assertEqual(portal.build_case_payload(self.owner, rid)["manual_check_status"], "UNCHECKED")

    def test_manual_check_statuses(self):
        rep = self.new_report()
        rid = rep["report_id"]
        for status in ("NEEDS_CORRECTION", "REJECTED", "VERIFIED"):
            portal.apply_manual_check(self.admin, rid, status, "note " + status)
            payload = portal.build_case_payload(self.owner, rid)
            self.assertEqual(payload["manual_check_status"], status)
            self.assertEqual(payload["manual_check_by"], "Administrator")
        with self.assertRaises(ValueError):
            portal.apply_manual_check(self.admin, rid, "MAYBE")
        with self.assertRaises(portal.AccessDenied):
            portal.apply_manual_check(self.owner, rid, "VERIFIED")

    def test_revision_provenance_supersedes(self):
        rep = self.new_report()
        rid = rep["report_id"]
        portal.revise_report(self.owner, rid, intake_body(reason="Second look at the facts."))
        payload = portal.build_case_payload(self.owner, rid)
        preds = {e["predicate"] for e in payload["provenance"]["edges"]}
        self.assertIn("HAS_REVISION", preds)
        self.assertIn("EVALUATED_BY", preds)
        # the revision graph itself records that #2 supersedes #1
        rev_chain = legal_kb.provenance_chain("REVISION", payload["ref"] + "#2", depth=1)
        rev_preds = {e["predicate"] for e in rev_chain["edges"]}
        self.assertIn("SUPERSEDES", rev_preds)
        self.assertEqual(payload["revisions"][-1]["rev_no"], 2)


# ================================================================== feedback


class FeedbackTests(PortalFixture):
    def test_upsert_and_my_vote(self):
        rep = self.new_report()
        rid = rep["report_id"]
        r = portal.add_feedback(self.owner, rid, 1, "Helpful routing advice.")
        self.assertEqual((r["up"], r["down"], r["my_vote"]), (1, 0, 1))
        r = portal.add_feedback(self.owner, rid, -1, "Wrong urgency band for my case.")
        self.assertEqual((r["up"], r["down"], r["my_vote"]), (0, 1, -1))
        payload = portal.build_case_payload(self.owner, rid)
        self.assertEqual(payload["feedback"]["my_vote"], -1)
        self.assertEqual(payload["feedback"]["up"], 0)

    def test_invalid_vote(self):
        rep = self.new_report()
        with self.assertRaises(ValueError):
            portal.add_feedback(self.owner, rep["report_id"], 0)

    def test_private_case_feedback_hidden_from_stranger(self):
        rep = self.new_report()
        with self.assertRaises(portal.NotFound):
            portal.add_feedback(self.other, rep["report_id"], 1)

    def test_net_negative_flags_for_review(self):
        rep = self.new_report()
        rid = rep["report_id"]
        portal.request_disclosure(self.owner, rid)
        portal.admin_disclosure(self.admin, rid, "APPROVE", "FULL")
        u2 = make_user("Voter Two", "voter2@nyaya.test")
        u3 = make_user("Voter Three", "voter3@nyaya.test")
        self.assertFalse(portal.add_feedback(u2, rid, -1)["flagged"])
        r = portal.add_feedback(u3, rid, -1)
        self.assertTrue(r["flagged"])  # net -2 → flagged for admin review
        self.assertTrue(portal.build_case_payload(self.owner, rid)["feedback"]["flagged"])
        self.assertIn(rid, [c["id"] for c in portal.admin_overview(self.admin)["queues"]["flagged"]])

    def test_dataset_export_shape(self):
        rep = self.new_report()
        portal.add_feedback(self.owner, rep["report_id"], 1, "Good call.")
        lines = [ln for ln in portal.feedback_dataset().splitlines() if ln.strip()]
        self.assertTrue(lines)
        rec = json.loads(lines[-1]) if lines else {}
        self.assertIn(rec["label"], (1, -1))
        for key in ("ref", "rev_no", "comment", "voted_at", "features"):
            self.assertIn(key, rec)
        for key in ("domain", "answers", "keyword_categories", "review_level",
                    "urgency", "severity_tier", "confidence", "triggers_fired"):
            self.assertIn(key, rec["features"])

    def test_analytics_counts(self):
        rep = self.new_report()
        portal.add_feedback(self.owner, rep["report_id"], 1)
        stats = portal.feedback_analytics()
        self.assertGreaterEqual(stats["total"], 1)
        self.assertGreaterEqual(stats["up"], 1)


# ========================================================= evidence mapping


class EvidenceMappingTests(PortalFixture):
    def _with_evidence(self):
        return self.new_report()

    def test_map_and_coverage(self):
        rep = self._with_evidence()
        rid = rep["report_id"]
        ev = portal.build_case_payload(self.owner, rid)["evidence"][0]
        out = portal.map_evidence_to_fact(self.owner, rid, ev["id"], "liberty_threat", "SUPPORTS",
                                          "photo of the phone being taken")
        self.assertGreaterEqual(out["coverage"]["coverage"], 0.0)
        self.assertIn("liberty_threat", out["coverage"]["supported"])
        self.assertIn("incident_date", out["coverage"]["mappable_facts"])

    def test_upsert_is_idempotent(self):
        rep = self._with_evidence()
        rid = rep["report_id"]
        ev = portal.build_case_payload(self.owner, rid)["evidence"][0]
        portal.map_evidence_to_fact(self.owner, rid, ev["id"], "liberty_threat", "SUPPORTS")
        portal.map_evidence_to_fact(self.owner, rid, ev["id"], "liberty_threat", "CONTRADICTS")
        maps = portal.build_case_payload(self.owner, rid)["evidence_map"]
        rows = [m for m in maps if m["evidence_id"] == ev["id"] and m["fact_key"] == "liberty_threat"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["relation"], "CONTRADICTS")
        cov = portal.build_case_payload(self.owner, rid)["coverage"]
        self.assertIn("liberty_threat", cov["contradicted"])
        self.assertNotIn("liberty_threat", cov["supported"])

    def test_validation_errors(self):
        rep = self._with_evidence()
        rid = rep["report_id"]
        ev = portal.build_case_payload(self.owner, rid)["evidence"][0]
        with self.assertRaises(ValueError):
            portal.map_evidence_to_fact(self.owner, rid, ev["id"], "not_a_fact", "SUPPORTS")
        with self.assertRaises(ValueError):
            portal.map_evidence_to_fact(self.owner, rid, ev["id"], "liberty_threat", "PROVES")
        with self.assertRaises(portal.NotFound):
            portal.map_evidence_to_fact(self.owner, rid, 999999, "liberty_threat", "SUPPORTS")

    def test_stranger_cannot_map(self):
        rep = self._with_evidence()
        rid = rep["report_id"]
        ev = portal.build_case_payload(self.owner, rid)["evidence"][0]
        with self.assertRaises(portal.AccessDenied):
            portal.map_evidence_to_fact(self.other, rid, ev["id"], "liberty_threat", "SUPPORTS")

    def test_no_evidence_ack_path(self):
        rep = self.new_report(evidence=[], no_evidence_ack=True)
        payload = portal.build_case_payload(self.owner, rep["report_id"])
        self.assertTrue(payload["no_evidence_ack"])
        self.assertEqual(payload["evidence"], [])
        self.assertEqual(payload["coverage"]["coverage"], 0.0)

    def test_evidence_or_ack_required(self):
        with self.assertRaises(ValueError):
            self.new_report(evidence=[], no_evidence_ack=False)


# ================================================= admin gating + amendment


class AdminGatingTests(PortalFixture):
    def test_overview_requires_admin(self):
        for actor in (self.owner, self.other):
            with self.assertRaises(portal.AccessDenied):
                portal.admin_overview(actor)
        stats = portal.admin_overview(self.admin)["stats"]
        for key in ("users", "admins", "reports", "revisions", "feedback_up", "feedback_down",
                    "flagged", "disclosed"):
            self.assertIn(key, stats)
        self.assertGreaterEqual(stats["admins"], 1)

    def test_amendment_requires_admin(self):
        with self.assertRaises(portal.AccessDenied):
            portal.amendment_impact(self.owner, "DEMO Act", "1")

    def test_ensure_admin_is_idempotent(self):
        portal.ensure_admin()
        with portal.db() as c:
            n = c.execute("SELECT COUNT(*) n FROM users WHERE role='ADMIN' AND email=?",
                          (portal.ADMIN_EMAIL,)).fetchone()["n"]
        self.assertEqual(n, 1)

    def test_promote_admin(self):
        u = make_user("Promotion Candidate", "promote.me@nyaya.test")
        self.assertEqual(u["role"], "USER")
        self.assertTrue(portal.promote_admin("promote.me@nyaya.test"))
        self.assertEqual(portal.authenticate("promote.me@nyaya.test", "testpass123")["role"], "ADMIN")
        self.assertFalse(portal.promote_admin("nobody@nyaya.test"))


class AmendmentImpactTests(PortalFixture):
    def test_dry_run_reports_but_does_not_write(self):
        rep = self.new_report(statute="DEMO Act", provision="1")
        rid = rep["report_id"]
        before = portal.build_case_payload(self.owner, rid)["current_rev_no"]
        out = portal.amendment_impact(self.admin, "DEMO Act", "1")
        self.assertIn(rid, [i["report_id"] for i in out["impacts"]])
        row = out["impacts"][0]
        self.assertEqual(row["report_id"], rid)
        self.assertIn("current", row)
        self.assertIn("reevaluated", row)
        self.assertNotIn("applied", out)
        self.assertEqual(portal.build_case_payload(self.owner, rid)["current_rev_no"], before)

    def test_apply_creates_system_revision(self):
        rep = self.new_report(statute="DEMO Act", provision="2")
        rid = rep["report_id"]
        out = portal.amendment_impact(self.admin, "DEMO Act", "2", apply_report_id=rid)
        self.assertIn("applied", out)
        payload = portal.build_case_payload(self.owner, rid)
        self.assertEqual(payload["current_rev_no"], out["applied"]["rev_no"])
        last = payload["revisions"][-1]
        self.assertEqual(last["actor"], "SYSTEM")
        self.assertIn("Amendment impact", last["reason"])

    def test_apply_on_unrelated_case_is_not_found(self):
        rep = self.new_report(statute="DEMO Act", provision="1")
        other = self.new_report(statute="DEMO Act", provision="2")
        with self.assertRaises(portal.NotFound):
            portal.amendment_impact(self.admin, "DEMO Act", "1", apply_report_id=other["report_id"])

    def test_kb_citation_flows_into_intake(self):
        # unverified citation → punishment withheld, note explains why
        rep = self.new_report(statute="IPC", provision="302", incident_date="2020-06-01")
        self.assertEqual(rep["kb_resolution"], "UNVERIFIED")
        self.assertTrue(any("NOT yet human-verified" in n for n in rep["intake_notes"]))
        self.assertNotIn("punishment", portal.build_case_payload(self.owner, rep["report_id"])["facts"]["offences"][0])
        # verify the version, then the same citation feeds punishment into routing
        row = legal_kb.resolve_provision("IPC", "302", "2020-01-01")["row"]
        legal_kb.mark_statute_verified(row["id"], "test-officer")
        rep2 = self.new_report(statute="IPC", provision="302", incident_date="2020-06-01")
        self.assertEqual(rep2["kb_resolution"], "VERIFIED")
        facts = portal.build_case_payload(self.owner, rep2["report_id"])["facts"]
        self.assertEqual(facts["offences"][0]["punishment"]["life"], True)
        self.assertGreaterEqual(facts["offences"][0]["punishment"]["min_years"], 10)


# ============================================================ misc / summary


class PayloadIntegrityTests(PortalFixture):
    def test_payload_has_every_documented_key(self):
        rep = self.new_report()
        p = portal.build_case_payload(self.owner, rep["report_id"])
        for key in ("id", "ref", "narrative", "incident_date", "domain", "answers", "facts",
                    "engine_output", "kb_context", "level_name", "access", "viewer", "evidence",
                    "revisions", "evidence_map", "coverage", "provenance", "feedback",
                    "disclosure_status", "manual_check_status", "current_rev_no"):
            self.assertIn(key, p)
        self.assertIn("triggers_fired", p["engine_output"]["manual_review"])

    def test_list_endpoint_summary_shape(self):
        rep = self.new_report()
        with portal.db() as c:
            rows = [dict(r) for r in c.execute(
                "SELECT id,ref,disclosure_status,manual_check_status,current_rev_no FROM reports "
                "WHERE user_id=? ORDER BY created_at DESC", (self.owner["id"],)).fetchall()]
        mine = [r for r in rows if r["id"] == rep["report_id"]][0]
        self.assertEqual(mine["disclosure_status"], "PRIVATE")
        self.assertEqual(mine["current_rev_no"], 1)

    def test_summary_fields(self):
        rep = self.new_report()
        for key in ("report_id", "ref", "level", "level_name", "urgency", "severity",
                    "confidence", "triggers_fired", "next_steps", "disclaimer",
                    "digilocker", "kb_resolution"):
            self.assertIn(key, rep)
        self.assertTrue(rep["digilocker"]["implemented"])  # DigiLocker flow model is wired in
        self.assertTrue(rep["digilocker"]["simulated"])     # …and says so, loudly
        self.assertEqual(rep["digilocker"]["linked"], False)


# =========================================== DigiLocker verification model


class DigiLockerCalibrationTests(unittest.TestCase):
    """The identity flow must behave like the real one, and admit it is simulated."""

    def test_real_world_constants_are_declared(self):
        self.assertEqual(dl.SIMULATION["mode"], "SIMULATED")
        self.assertTrue(dl.SIMULATION["simulated"])
        self.assertIn("UIDAI", dl.REAL_WORLD["allowed_issuers"])
        self.assertTrue(dl.REAL_WORLD["code_single_use"])
        self.assertTrue(dl.REAL_WORLD["pkce_required"])
        self.assertEqual(dl.REAL_WORLD["consent_validity_minutes"], 30)

    def test_pkce_pair_is_well_formed(self):
        verifier, challenge = dl._pkce_pair()
        self.assertTrue(43 <= len(verifier) <= 128)
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        self.assertEqual(challenge, expected)
        self.assertNotIn("=", challenge)

    def test_dob_and_name_normalisation(self):
        self.assertEqual(dl.normalise_dob("14-09-1990"), "1990-09-14")
        self.assertEqual(dl.normalise_dob("1990-09-14"), "1990-09-14")
        self.assertEqual(dl.normalise_dob("garbage"), "")
        self.assertEqual(dl.normalise_name("Asha  K. Verma"), "ashakverma")

    def test_artefact_validation_rejects_bad_documents(self):
        cases = {
            "UNKNOWN_ISSUER": {"name": "A", "dob": "1990-01-01", "issuer": "Random Trust"},
            "MISSING_NAME": {"name": "", "dob": "1990-01-01", "issuer": "UIDAI"},
            "MISSING_DOB": {"name": "A", "dob": "", "issuer": "UIDAI"},
            "BAD_DOB": {"name": "A", "dob": "31-02-1990", "issuer": "UIDAI"},
            "FUTURE_DOB": {"name": "A", "dob": "2999-01-01", "issuer": "UIDAI"},
        }
        for expected, doc in cases.items():
            codes = [c for c, _ in dl.validate_artefact(doc)]
            self.assertIn(expected, codes, f"{expected} not raised for {doc}")
        good = {"name": "Asha Verma", "dob": "1990-09-14", "issuer": "UIDAI"}
        self.assertEqual(dl.validate_artefact(good), [])

    def test_expired_consent_is_detected(self):
        doc = {"name": "Asha", "dob": "1990-09-14", "issuer": "UIDAI"}
        past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=31)).isoformat()
        codes = [c for c, _ in dl.validate_artefact(doc, consent_expires_at=past)]
        self.assertIn("CONSENT_EXPIRED", codes)


class DigiLockerFlowTests(PortalFixture):
    """End-to-end: consent → grant → callback → attest, plus every failure mode."""

    def _fresh_user(self, tag):
        return make_user(f"Iden Tity {tag}", f"identity.{tag}.{uuid.uuid4().hex[:6]}@nyaya.test")

    def test_happy_path_attests_and_links(self):
        u = self._fresh_user("ok")
        req = dl.create_consent_request(u)
        for key in ("request_id", "state", "code_challenge", "expires_at", "scope"):
            self.assertIn(key, req)
        self.assertEqual(req["code_challenge_method"], "S256")
        self.assertEqual(req["mode"], "SIMULATED")
        self.assertFalse(dl.status(u)["linked"])
        grant = dl.grant_consent(u, req["request_id"], consent=True)
        self.assertEqual(grant["status"], "CONSENT_GIVEN")
        out = dl.exchange_code(req["request_id"], grant["code"], grant["state"], u)
        self.assertTrue(out["ok"] and out["verified"])
        self.assertEqual(out["document"]["issuer"] in dl.REAL_WORLD["allowed_issuers"], True)
        self.assertNotIn("issuer_ref", out["document"])       # masked, never raw
        self.assertIn("issuer_ref_masked", out["document"])
        st = dl.status(u)
        self.assertEqual(st["status"], "LINKED")
        self.assertTrue(st["verified"])
        self.assertEqual(st["artefact_id"], out["artefact_id"])
        with portal.db() as c:
            row = c.execute("SELECT digilocker_status, digilocker_ref FROM users WHERE id=?",
                            (u["id"],)).fetchone()
        self.assertEqual(row["digilocker_status"], "LINKED")
        self.assertEqual(row["digilocker_ref"], out["artefact_id"])

    def test_consent_denied_stores_nothing(self):
        u = self._fresh_user("deny")
        req = dl.create_consent_request(u)
        out = dl.grant_consent(u, req["request_id"], consent=False)
        self.assertEqual(out["status"], "DENIED")
        self.assertFalse(out["stored"])
        self.assertIsNone(dl.identity_row(u["id"]))
        self.assertEqual(dl.status(u)["status"], "NOT_LINKED")

    def test_state_mismatch_rejected(self):
        u = self._fresh_user("state")
        req = dl.create_consent_request(u)
        grant = dl.grant_consent(u, req["request_id"], consent=True)
        out = dl.exchange_code(req["request_id"], grant["code"], "st_forged", u)
        self.assertFalse(out["ok"])
        self.assertEqual(out["reason_code"], "STATE_MISMATCH")
        self.assertIsNone(dl.identity_row(u["id"]))

    def test_code_is_single_use(self):
        u = self._fresh_user("replay")
        req = dl.create_consent_request(u)
        grant = dl.grant_consent(u, req["request_id"], consent=True)
        self.assertTrue(dl.exchange_code(req["request_id"], grant["code"], grant["state"], u)["ok"])
        again = dl.exchange_code(req["request_id"], grant["code"], grant["state"], u)
        self.assertEqual(again["reason_code"], "CODE_REPLAYED")

    def test_invalid_code_rejected(self):
        u = self._fresh_user("code")
        req = dl.create_consent_request(u)
        dl.grant_consent(u, req["request_id"], consent=True)
        out = dl.exchange_code(req["request_id"], "code_wrong", req["state"], u)
        self.assertEqual(out["reason_code"], "CODE_INVALID")

    def test_expired_consent_is_persisted_on_failure(self):
        u = self._fresh_user("expiry")
        req = dl.create_consent_request(u)
        with portal.db() as c:
            c.execute("UPDATE dl_requests SET expires_at=? WHERE id=?",
                      ("2020-01-01T00:00:00+00:00", req["request_id"]))
        with self.assertRaises(ValueError):
            dl.grant_consent(u, req["request_id"], consent=True)
        with portal.db() as c:
            status = c.execute("SELECT status FROM dl_requests WHERE id=?",
                               (req["request_id"],)).fetchone()["status"]
        self.assertEqual(status, "EXPIRED")   # the transition must survive the raise

    def test_already_linked_blocks_new_consent(self):
        u = self._fresh_user("linked")
        req = dl.create_consent_request(u)
        grant = dl.grant_consent(u, req["request_id"], consent=True)
        dl.exchange_code(req["request_id"], grant["code"], grant["state"], u)
        with self.assertRaises(ValueError) as ctx:
            dl.create_consent_request(u)
        self.assertIn("ALREADY_LINKED", str(ctx.exception))

    def test_consent_quota_is_enforced(self):
        u = self._fresh_user("quota")
        for _ in range(dl.REAL_WORLD["max_consent_requests_per_day"]):
            req = dl.create_consent_request(u)
            dl.grant_consent(u, req["request_id"], consent=False)
        self.assertEqual(dl.consent_quota(u["id"])["remaining"], 0)
        with self.assertRaises(ValueError) as ctx:
            dl.create_consent_request(u)
        self.assertIn("limit", str(ctx.exception).lower())

    def test_other_user_cannot_touch_the_request(self):
        owner = self._fresh_user("owner")
        other = self._fresh_user("other")
        req = dl.create_consent_request(owner)
        with self.assertRaises(LookupError):
            dl.consent_status(other, req["request_id"])
        with self.assertRaises(LookupError):
            dl.grant_consent(other, req["request_id"], consent=True)

    def test_artefact_integrity_and_revocation(self):
        u = self._fresh_user("artefact")
        req = dl.create_consent_request(u)
        grant = dl.grant_consent(u, req["request_id"], consent=True)
        out = dl.exchange_code(req["request_id"], grant["code"], grant["state"], u)
        check = dl.verify_artefact(out["artefact_id"])
        self.assertTrue(check["valid"])
        self.assertEqual(check["integrity"], "INTACT")
        self.assertTrue(check["simulated"])
        dl.revoke(u, "consent withdrawn")
        check = dl.verify_artefact(out["artefact_id"])
        self.assertFalse(check["valid"])
        self.assertEqual(check["state"], "REVOKED")
        self.assertFalse(dl.status(u)["linked"])
        self.assertFalse(dl.verify_artefact("dlv_does_not_exist")["found"])

    def test_identity_cannot_be_reused_across_accounts(self):
        first = self._fresh_user("dup1")
        req = dl.create_consent_request(first)
        grant = dl.grant_consent(first, req["request_id"], consent=True)
        out = dl.exchange_code(req["request_id"], grant["code"], grant["state"], first)
        with portal.db() as c:
            raw = json.loads(c.execute("SELECT doc_json FROM dl_identities WHERE artefact_id=?",
                                       (out["artefact_id"],)).fetchone()["doc_json"])
        second = self._fresh_user("dup2")
        # Force the same issuer reference: the second account must be refused.
        req2 = dl.create_consent_request(second)
        grant2 = dl.grant_consent(second, req2["request_id"], consent=True)
        original = dl._simulated_artefact
        try:
            dl._simulated_artefact = lambda name, **kw: {**raw, "name": name}  # noqa: ARG005
            res = dl.exchange_code(req2["request_id"], grant2["code"], grant2["state"], second)
        finally:
            dl._simulated_artefact = original
        self.assertFalse(res["ok"])
        self.assertEqual(res["reason_code"], "IDENTITY_IN_USE")

    def test_events_are_recorded(self):
        u = self._fresh_user("events")
        req = dl.create_consent_request(u)
        grant = dl.grant_consent(u, req["request_id"], consent=True)
        dl.exchange_code(req["request_id"], grant["code"], grant["state"], u)
        names = [e["event"] for e in dl.events(u["id"])]
        for expected in ("CONSENT_REQUESTED", "CONSENT", "CODE_EXCHANGED", "ATTESTED"):
            self.assertIn(expected, names)

    def test_report_carries_identity_signal(self):
        verified = self._fresh_user("sigok")
        req = dl.create_consent_request(verified)
        grant = dl.grant_consent(verified, req["request_id"], consent=True)
        dl.exchange_code(req["request_id"], grant["code"], grant["state"], verified)
        body = intake_body()
        body.pop("evidence")
        body["no_evidence_ack"] = True
        rep = portal.intake_report(verified, body)["summary"]
        self.assertTrue(rep["digilocker"]["linked"])
        self.assertTrue(rep["digilocker"]["simulated"])
        self.assertEqual(rep["digilocker"]["mode"], "SIMULATED")
        self.assertTrue(any("DigiLocker artefact" in n for n in rep["intake_notes"]))
        unverified = self._fresh_user("signo")
        rep2 = portal.intake_report(unverified, body)["summary"]
        self.assertFalse(rep2["digilocker"]["linked"])
        self.assertTrue(any("not verified" in n for n in rep2["intake_notes"]))
        self.assertTrue(rep2["digilocker"]["implemented"])   # the flow exists…
        self.assertFalse(rep2["digilocker"]["verified"])     # …but nothing is claimed for this user


class DigiLockerAdminSignalTests(PortalFixture):
    def test_admin_overview_surfaces_identity_stats(self):
        ov = portal.admin_overview(self.admin)
        for key in ("identities_verified", "identities_revoked", "identity_failures",
                    "reports_unverified_identity"):
            self.assertIn(key, ov["stats"])
        self.assertIn("verified", ov["identity"])
        self.assertTrue(all("digilocker_status" in c for c in ov["cases"]))


class SessionContinuityTests(unittest.TestCase):
    """The portal is often opened inside a cross-site preview iframe where the
    session cookie is third-party (dropped) and web storage throws. These are
    static guards on the client that keep that case working."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "assets", "auth.js"), encoding="utf-8") as fh:
            cls.auth = fh.read()

    def test_storage_access_is_guarded(self):
        # Reading window.localStorage can itself throw; the access must be wrapped.
        self.assertIn("function _ls()", self.auth)
        self.assertIn("function _ss()", self.auth)
        for bad in ("_safeGet(window.localStorage)", "_safeSet(window.localStorage",
                    "_safeGet(window.sessionStorage)", "_safeSet(window.sessionStorage"):
            self.assertNotIn(bad, self.auth)

    def test_internal_links_carry_the_session(self):
        self.assertIn("function addToken", self.auth)
        self.assertIn("installLinkRelay", self.auth)
        self.assertIn("document.addEventListener('click'", self.auth)

    def test_token_param_is_set_never_appended(self):
        self.assertIn("u.searchParams.set('st', token)", self.auth)
        self.assertIn("u.searchParams.set('st', t)", self.auth)

    def test_frame_surviving_channel_exists(self):
        self.assertIn("function nameToken", self.auth)
        self.assertIn("setNameToken", self.auth)

    def test_bootstrap_never_hard_fails(self):
        self.assertIn("bootstrapSession", self.auth)
        self.assertIn("'/api/session'", self.auth)
        # getToken() must not be able to throw out of bootstrapSession.
        self.assertIn("try { t = getToken(); } catch (e) { t = null; }", self.auth)

    def test_pages_use_public_bootstrap_not_requireAuth(self):
        pages = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pages")
        with open(os.path.join(pages, "disclosed.html"), encoding="utf-8") as fh:
            disclosed = fh.read()
        self.assertIn("bootstrapSession()", disclosed)
        self.assertNotIn("await requireAuth()", disclosed)

    def test_server_dual_cookie_contract(self):
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn('RELAY_COOKIE = "nyaya_relay"', src)
        self.assertIn("def _session_cookie_headers", src)
        self.assertIn("def _clear_cookie_headers", src)
        self.assertIn('Referrer-Policy", "no-referrer"', src)
        # SameSite=None without Secure is silently rejected by browsers.
        self.assertNotIn('return "SameSite=None"', src)


class EvidenceDownloadTests(PortalFixture):
    """Evidence bytes are owner/admin-only; disclosed viewers never get them."""

    def _evidence_id(self):
        rep = self.new_report()
        return portal.build_case_payload(self.owner, rep["report_id"])["evidence"][0]["id"]

    def test_owner_can_download_bytes(self):
        eid = self._evidence_id()
        fname, ctype, blob = portal.evidence_download(self.owner, eid)
        self.assertEqual(fname, "photo.png")
        self.assertEqual(blob, b"fake-png-bytes")

    def test_admin_can_download_bytes(self):
        eid = self._evidence_id()
        _fname, _ctype, blob = portal.evidence_download(self.admin, eid)
        self.assertEqual(blob, b"fake-png-bytes")

    def test_stranger_gets_404(self):
        eid = self._evidence_id()
        with self.assertRaises(portal.NotFound):
            portal.evidence_download(self.other, eid)

    def test_unknown_id_gets_404(self):
        with self.assertRaises(portal.NotFound):
            portal.evidence_download(self.owner, 999999999)

    def test_disclosed_viewer_never_gets_bytes(self):
        rep = self.new_report()
        rid = rep["report_id"]
        eid = portal.build_case_payload(self.owner, rid)["evidence"][0]["id"]
        portal.request_disclosure(self.owner, rid)
        portal.admin_disclosure(self.admin, rid, "APPROVE", "FULL")
        # The stranger now has FULL access to the case payload...
        self.assertEqual(portal.build_case_payload(self.other, rid)["access"], "FULL")
        # ...but evidence bytes stay owner/admin-only.
        with self.assertRaises(portal.NotFound):
            portal.evidence_download(self.other, eid)


class SessionPurgeTests(PortalFixture):
    def test_expired_sessions_are_purged(self):
        import datetime as dt
        user = make_user("Purge User", f"purge{uuid.uuid4().hex[:6]}@nyaya.test")
        live = portal.create_session(user["id"])
        # Insert an expired session directly.
        with portal.db() as c:
            c.execute("INSERT INTO sessions VALUES(?,?,?,?)",
                      ("expired-token", user["id"], "2020-01-01T00:00:00+00:00",
                       "2020-01-02T00:00:00+00:00"))
        purged = portal.purge_expired_sessions()
        self.assertGreaterEqual(purged, 1)
        # Live session survives; expired one is gone.
        self.assertIsNotNone(portal.session_user(live))
        self.assertIsNone(portal.session_user("expired-token"))


# =========================================== graded uncertainty (uncertainty.py)


class UncertaintyBandTests(unittest.TestCase):
    """The bands and their exact edges. Off-by-one here changes a legal answer."""

    def test_band_edges_are_half_open(self):
        U = uncertainty_mod
        cases = [
            (0.0, "FALSE"), (0.0999, "FALSE"),
            (0.10, "MAYBE_NOT"), (0.3499, "MAYBE_NOT"),
            (0.35, "MIGHT_NOT_BE"), (0.4999, "MIGHT_NOT_BE"),
            (0.50, "MIGHT_BE"), (0.6499, "MIGHT_BE"),
            (0.65, "MAYBE"), (0.8999, "MAYBE"),
            (0.90, "TRUE"), (1.0, "TRUE"),
        ]
        for p, expected in cases:
            with self.subTest(p=p):
                self.assertEqual(U.classify(p), expected)

    def test_predicates_agree_with_classify(self):
        U = uncertainty_mod
        for p in (U.BANDS["MAYBE"][0], 0.5, 0.4, 0.2):
            label = U.classify(p)
            for name in ("maybe", "might_be", "might_not_be", "maybe_not"):
                fn = getattr(U, name)
                with self.subTest(p=p, label=name):
                    self.assertEqual(fn(p), label == name.upper())

    def test_out_of_range_is_an_error_not_an_answer(self):
        """An age must never be read as 'definitely true'."""
        U = uncertainty_mod
        for bad in (17, -0.2, 1.5, float("nan")):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    U.classify(bad)
        for bad in ("0.7", None, [0.7]):
            with self.subTest(bad=bad):
                with self.assertRaises(TypeError):
                    U.classify(bad)

    def test_bools_are_definite_answers_not_probabilities(self):
        U = uncertainty_mod
        self.assertEqual(U.classify(True), "TRUE")
        self.assertEqual(U.classify(False), "FALSE")
        self.assertEqual(U.to_tri_state(True), "TRUE")
        self.assertEqual(U.to_tri_state(False), "FALSE")

    def test_tri_state_collapses_every_graded_band_to_unknown(self):
        """The safety rule: doubt goes to human review, never to TRUE/FALSE."""
        U = uncertainty_mod
        for p in (0.10, 0.2, 0.35, 0.45, 0.50, 0.6, 0.65, 0.89):
            with self.subTest(p=p):
                self.assertEqual(U.to_tri_state(p), "UNKNOWN")
        for label in ("maybe", "MIGHT_BE", "might-not-be", " Maybe_Not "):
            with self.subTest(label=label):
                self.assertEqual(U.to_tri_state(label), "UNKNOWN")

    def test_definite_numbers_collapse(self):
        U = uncertainty_mod
        self.assertEqual(U.to_tri_state(0.95), "TRUE")
        self.assertEqual(U.to_tri_state(0.05), "FALSE")

    def test_integer_likelihoods_are_accepted(self):
        """0 and 1 are likelihoods; the type check used to reject them while
        classify() accepted them, so the two disagreed."""
        U = uncertainty_mod
        self.assertEqual(U.to_tri_state(0), "FALSE")
        self.assertEqual(U.to_tri_state(1), "TRUE")

    def test_unrecognised_values_pass_through_as_none(self):
        U = uncertainty_mod
        for v in ("TRUE", "FALSE", "unknown", None, {"a": 1}, [0.7]):
            with self.subTest(v=v):
                self.assertIsNone(U.to_tri_state(v))


class EngineGradedFactTests(unittest.TestCase):
    """Graded intake must reach the engine as UNKNOWN and be named in the report."""

    def setUp(self):
        self.engine = engine_mod.Engine()

    def evaluate(self, **flags):
        facts = with_base(flags=flags)
        return self.engine.evaluate(facts, record_audit=False)["output"]

    def test_graded_flag_becomes_unknown_and_is_reported(self):
        out = self.evaluate(disability="maybe")
        note = [
            q for q in out["open_questions_for_judicial_officer"] if "Graded" in q
        ]
        self.assertEqual(len(note), 1)
        self.assertIn("flags.disability", note[0])

    def test_likelihood_and_label_are_equivalent(self):
        a = self.evaluate(disability=0.7)
        b = self.evaluate(disability="maybe")
        self.assertEqual(
            a["open_questions_for_judicial_officer"],
            b["open_questions_for_judicial_officer"],
        )

    def test_definite_answers_raise_no_doubt_note(self):
        for value in (True, "TRUE", 0.95):
            with self.subTest(value=value):
                out = self.evaluate(disability=value)
                self.assertFalse(
                    [q for q in out["open_questions_for_judicial_officer"] if "Graded" in q]
                )

    def test_clean_intake_raises_no_doubt_note(self):
        out = self.evaluate()
        self.assertFalse(
            [q for q in out["open_questions_for_judicial_officer"] if "Graded" in q]
        )

    def test_config_floats_are_not_mistaken_for_likelihoods(self):
        """confidence_threshold is 0.85 -- a number, not a probability answer.
        An early version collapsed it and silently changed the engine's own
        config, which is exactly the class of bug this module must not cause."""
        self.assertEqual(engine_mod.EMBEDDED_DEMO["config"]["confidence_threshold"], 0.85)
        out = self.evaluate()
        self.assertGreater(out["confidence"]["overall"], 0.0)

    def test_non_likelihood_numbers_are_left_alone(self):
        facts = with_base(victim_age=17)
        out = self.engine.evaluate(facts, record_audit=False)["output"]
        self.assertFalse(
            [q for q in out["open_questions_for_judicial_officer"] if "victim_age" in q]
        )

    def test_graded_flag_raises_human_review_through_t17(self):
        """The whole point of fail-closed: doubt on a vulnerability flag must
        escalate, not be absorbed. T-17 requires an UNKNOWN vulnerability flag
        *and* a base tier of 3+, so it only fires on a serious matter."""
        facts = with_base(
            offences=[{"provision": "BNS s.103", "statute": "BNS",
                       "max_punishment": "death", "verified_in_corpus": True}],
            flags={"disability": "maybe"},
        )
        out = self.engine.evaluate(facts, record_audit=False)["output"]
        triggers = [t["id"] for t in out["manual_review"]["triggers_fired"]]
        self.assertIn("T-17", triggers)
        self.assertEqual(out["manual_review"]["required_level"], "L3")

    def test_definite_flag_does_not_fabricate_the_t17_route(self):
        """The same case with a definite answer must not claim doubt."""
        facts = with_base(
            offences=[{"provision": "BNS s.103", "statute": "BNS",
                       "max_punishment": "death", "verified_in_corpus": True}],
            flags={"disability": True},
        )
        out = self.engine.evaluate(facts, record_audit=False)["output"]
        triggers = [t["id"] for t in out["manual_review"]["triggers_fired"]]
        self.assertNotIn("T-17", triggers)

    def test_graded_facts_do_not_mutate_caller_input(self):
        facts = with_base(flags={"disability": "maybe"})
        self.engine.evaluate(facts, record_audit=False)
        self.assertEqual(facts["flags"]["disability"], "maybe")


if __name__ == "__main__":
    unittest.main(verbosity=2)
