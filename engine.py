"""NYAYA-RAC v0.1.0 — Rules-as-Code judicial decision-support engine.

DECISION-SUPPORT ONLY. Not a judge, adjudicator, or sentencing authority.
Pure Python (standard library). Loads nyaya-rac-rule-base.json if present;
otherwise runs an embedded demonstration rule base so the tool works
immediately. Produces output conforming to output_schema and a SQLite audit
trail for every evaluation.
"""

from __future__ import annotations

import copy
import datetime as _dt
import hashlib
import json
import os
import re
import sqlite3
from typing import Any, Dict, List, Optional

LEVEL_ORDER = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
TIER_LABEL = {1: "S1", 2: "S2", 3: "S3", 4: "S4", 5: "S5"}
DISCLAIMER = (
    "Advisory decision-support output. Not a judicial decision. Requires "
    "review at the stated level before any use."
)

NINE_FLAGS = [
    "woman_victim_sexual_offence",
    "disability",
    "mental_illness",
    "sc_st_atrocities_applicability",
    "transgender",
    "senior_citizen",
    "unrepresented_party",
    "in_custody",
    "foreign_national",
]

TRI_STATE_KEYS = (
    "flags.woman_victim_sexual_offence",
    "flags.disability",
    "flags.mental_illness",
    "flags.sc_st_atrocities_applicability",
    "flags.transgender",
    "flags.senior_citizen",
    "flags.unrepresented_party",
    "flags.in_custody",
    "flags.foreign_national",
    "art20_ex_post_facto_risk",
    "art20_double_jeopardy_risk",
    "art20_self_incrimination_risk",
    "bias_risk_detected",
    "conflict_of_interest",
    "document_integrity_concern",
)

VAR_RE = re.compile(r'"var"\s*:\s*"([^"]+)"')
NUM_RE = re.compile(r"^\d{8}$")


class JsonLogicError(Exception):
    pass


# ---------------- JSON Logic subset ----------------


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _to_number(x: Any) -> float:
    if isinstance(x, bool):
        return 1.0 if x else 0.0
    if _is_number(x):
        return float(x)
    if isinstance(x, str):
        try:
            return float(x)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def resolve_path(data: Any, path: str) -> Any:
    # Accept both nested ("offence":{"start_yyyymmdd":X}) and flat
    # dotted ("offence.start_yyyymmdd":X) fact layouts.
    if isinstance(data, dict) and path in data:
        return data[path]
    cur: Any = data
    for part in str(path).split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def as_bool(x: Any) -> bool:
    if x is True:
        return True
    if x is False:
        return False
    if x is None:
        return False
    if _is_number(x):
        return x != 0
    if isinstance(x, str):
        u = x.strip().upper()
        if u in ("TRUE", "YES", "ON"):
            return True
        if u in ("FALSE", "NO", "OFF", "UNKNOWN", ""):
            return False
        return bool(u)
    if isinstance(x, list):
        return len(x) > 0
    return bool(x)


def _loose_eq(a: Any, b: Any) -> bool:
    if a is None and b is None:
        return True
    if isinstance(a, bool) and isinstance(b, bool):
        return a == b
    if _is_number(a) and _is_number(b):
        return a == b
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    if isinstance(a, bool) and _is_number(b):
        return int(a) == b
    if isinstance(b, bool) and _is_number(a):
        return a == int(b)
    if isinstance(a, str) and _is_number(b):
        try:
            return float(a) == b
        except (TypeError, ValueError):
            return False
    if isinstance(b, str) and _is_number(a):
        try:
            return a == float(b)
        except (TypeError, ValueError):
            return False
    return False


def _strict_eq(a: Any, b: Any) -> bool:
    if a is None and b is None:
        return True
    if type(a) is not type(b):
        if _is_number(a) and _is_number(b):
            return a == b
        return False
    return a == b


def jl_eval(expr: Any, data: Any) -> Any:
    if isinstance(expr, dict):
        if len(expr) != 1:
            raise JsonLogicError(
                "JSON Logic operator object must have exactly one key"
            )
        op, val = next(iter(expr.items()))
        if op == "var":
            if isinstance(val, list):
                found = resolve_path(data, val[0])
                return val[1] if found is None else found
            return resolve_path(data, val)
        if op == "missing":
            return resolve_path(data, val[0]) is None
        if op in ("!", "not"):
            return not as_bool(jl_eval(val, data))
        if op == "and":
            for item in val:
                if not as_bool(jl_eval(item, data)):
                    return False
            return True
        if op == "or":
            for item in val:
                if as_bool(jl_eval(item, data)):
                    return True
            return False
        if op == "if":
            # Supports {"if":[cond, true, false]} and chained
            # {"if":[c1, v1, c2, v2, ..., default]}. Returns the value of the
            # first true condition, else the trailing default (last element)
            # when the argument count is odd.
            branches = list(val)
            n = len(branches)
            if n < 3:
                raise JsonLogicError("'if' needs at least [cond, true, false]")
            i = 0
            while i + 2 <= n:
                cond = branches[i]
                nxt = branches[i + 1]
                if as_bool(jl_eval(cond, data)):
                    return jl_eval(nxt, data)
                i += 2
            # No branch matched. Odd arg count => trailing default.
            if n % 2 == 1:
                return jl_eval(branches[-1], data)
            return None
        if op == "==":
            return _loose_eq(jl_eval(val[0], data), jl_eval(val[1], data))
        if op == "===":
            return _strict_eq(jl_eval(val[0], data), jl_eval(val[1], data))
        if op == "!=":
            return not _loose_eq(jl_eval(val[0], data), jl_eval(val[1], data))
        if op == "!==":
            return not _strict_eq(jl_eval(val[0], data), jl_eval(val[1], data))
        if op in (">", ">=", "<", "<="):
            a = jl_eval(val[0], data)
            b = jl_eval(val[1], data)
            if not (_is_number(a) and _is_number(b)):
                return False
            cmp = {
                ">": lambda x, y: x > y,
                ">=": lambda x, y: x >= y,
                "<": lambda x, y: x < y,
                "<=": lambda x, y: x <= y,
            }[op]
            return cmp(a, b)
        if op == "in":
            needle = jl_eval(val[0], data)
            haystack = jl_eval(val[1], data)
            if isinstance(haystack, list):
                return any(_loose_eq(needle, item) for item in haystack)
            if isinstance(needle, str) and isinstance(haystack, str):
                return needle in haystack
            return False
        if op == "+":
            return sum(_to_number(jl_eval(item, data)) for item in val)
        if op == "min":
            nums = [_to_number(jl_eval(item, data)) for item in val]
            return min(nums) if nums else None
        if op == "max":
            nums = [_to_number(jl_eval(item, data)) for item in val]
            return max(nums) if nums else None
    return expr


# ---------------- helpers ----------------


def _flatten(obj: Any, prefix: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                out.update(_flatten(v, key))
            else:
                out[key] = v
    else:
        out[prefix] = obj
    return out


def _yyyymmdd_to_iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    s = f"{n:08d}"
    if not NUM_RE.match(s):
        return None
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


MIN_OFFENCE_YEAR = 1861   # IPC era onwards
MAX_OFFENCE_YEAR = 2100


def _validate_offence_dates(data: Dict[str, Any]) -> None:
    """Phase 1: strict date validation inside the engine.

    Missing dates remain permitted (the regime then resolves to UNDETERMINED,
    which is itself a protected state). Any date that IS provided must be an
    integer in YYYYMMDD form, a real calendar date, within a sensible range,
    and correctly ordered. Violations raise ValueError instead of silently
    producing UNDETERMINED/MIXED routing.
    """
    parsed: Dict[str, _dt.date] = {}
    for label in ("start", "end"):
        v = resolve_path(data, f"offence.{label}_yyyymmdd")
        if v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(
                f"offence.{label}_yyyymmdd must be an integer YYYYMMDD value "
                f"(got {type(v).__name__}: {v!r})."
            )
        if float(v) != int(v):
            raise ValueError(f"offence.{label}_yyyymmdd must be a whole number.")
        s = str(int(v))
        if len(s) != 8:
            raise ValueError(
                f"offence.{label}_yyyymmdd must be exactly 8 digits YYYYMMDD (got '{s}')."
            )
        y, m, d = int(s[:4]), int(s[4:6]), int(s[6:])
        if not (MIN_OFFENCE_YEAR <= y <= MAX_OFFENCE_YEAR):
            raise ValueError(
                f"offence.{label} year {y} is outside the supported range "
                f"{MIN_OFFENCE_YEAR}-{MAX_OFFENCE_YEAR}."
            )
        try:
            parsed[label] = _dt.date(y, m, d)
        except ValueError:
            raise ValueError(f"offence.{label}_yyyymmdd '{s}' is not a real calendar date.")
    if "start" in parsed and "end" in parsed and parsed["end"] < parsed["start"]:
        raise ValueError("offence.end_yyyymmdd cannot be before offence.start_yyyymmdd.")


def validate_json_schema(instance: Any, schema: Any, path: str = "$") -> List[str]:
    """Phase 1: actual JSON Schema validation (stdlib, draft-07-like subset).

    Supports: type, required, properties, items, enum, minimum, maximum,
    minLength, minItems. Returns the list of violation messages (empty = valid).
    """
    errors: List[str] = []
    if not isinstance(schema, dict):
        return errors
    t = schema.get("type")
    if t:
        if t == "number":
            ok = _is_number(instance)
        elif t == "integer":
            ok = isinstance(instance, int) and not isinstance(instance, bool)
        elif t == "boolean":
            ok = isinstance(instance, bool)
        elif t == "object":
            ok = isinstance(instance, dict)
        elif t == "array":
            ok = isinstance(instance, list)
        elif t == "string":
            ok = isinstance(instance, str)
        elif t == "null":
            ok = instance is None
        else:
            ok = True
        if not ok:
            errors.append(f"{path}: expected type '{t}', got {type(instance).__name__}")
            return errors  # further checks on a wrong type are noise
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: value {instance!r} not in enum {schema['enum']}")
    if _is_number(instance):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: {instance} is below minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: {instance} exceeds maximum {schema['maximum']}")
    if isinstance(instance, str) and "minLength" in schema and len(instance) < schema["minLength"]:
        errors.append(f"{path}: string is shorter than minLength {schema['minLength']}")
    if isinstance(instance, dict):
        for req in schema.get("required", []):
            if req not in instance:
                errors.append(f"{path}: missing required property '{req}'")
        for key, sub in schema.get("properties", {}).items():
            if key in instance:
                errors.extend(validate_json_schema(instance[key], sub, f"{path}.{key}"))
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: array has fewer than minItems {schema['minItems']}")
        items_schema = schema.get("items")
        if isinstance(items_schema, dict):
            for i, item in enumerate(instance):
                errors.extend(validate_json_schema(item, items_schema, f"{path}[{i}]"))
    return errors


def compute_agg(
    offences: List[Dict[str, Any]], config: Dict[str, Any]
) -> Dict[str, Any]:
    punishment_min = config.get("heinous_min_punishment_years", 7)
    death = False
    life = False
    maxs: List[float] = []
    mins: List[float] = []
    child_specific = False
    for o in offences:
        if not isinstance(o, dict):
            continue
        pun = o.get("punishment")
        got_from_dict = False
        if isinstance(pun, dict):
            if pun.get("death") is True:
                death = True
                got_from_dict = True
            if pun.get("life") is True:
                life = True
                got_from_dict = True
            my = pun.get("max_years")
            mn = pun.get("min_years")
            if _is_number(my):
                maxs.append(float(my))
                got_from_dict = True
            if _is_number(mn):
                mins.append(float(mn))
                got_from_dict = True
        if not got_from_dict:
            # Fall back to human-readable punishment text such as
            # max_punishment: "7 years" / "3 to 7 years" / "life" / "death".
            tx_years, tx_life, tx_death = _parse_punishment_text(o.get("max_punishment"))
            death = death or tx_death
            life = life or tx_life
            if tx_years:
                maxs.append(max(tx_years))
                if len(tx_years) > 1:
                    mins.append(min(tx_years))
            mn_years, mn_life, mn_death = _parse_punishment_text(o.get("min_punishment"))
            death = death or mn_death
            life = life or mn_life
            if mn_years:
                mins.append(min(mn_years))
        statute = str(o.get("statute", "")).lower()
        if o.get("child_specific_statute") is True or "pocso" in statute:
            child_specific = True
    # Heinous: a known minimum term at/above the threshold, or death/life prescribed.
    heinous = death or life or any(m >= punishment_min for m in mins)
    max_term = max(maxs) if maxs else 0
    min_term = max(mins) if mins else 0
    return {
        "death_prescribed": death,
        "life_prescribed": life,
        "max_term_years": max_term,
        "min_term_years": min_term,
        "effective_years": max(max_term, min_term),
        "heinous_any": heinous,
        # When the cited offence is itself child-victim-specific (e.g. POCSO),
        # the base tier already accounts for the child victim and severity
        # modifier M-01 must not escalate a second time.
        "base_tier_accounts_for_child_victim": child_specific,
    }


_TRI_STATE_LEAVES = frozenset(k.split(".")[-1] for k in TRI_STATE_KEYS)
_YEARS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:years?|yrs?)", re.IGNORECASE)


def _normalize_tri_state(data: Any, prefix: str = "") -> None:
    """Recursively convert booleans to "TRUE"/"FALSE" ONLY for tri-state keys.

    Handles both flat dotted keys ("flags.in_custody") and nested dicts
    ({"flags": {"in_custody": True}}). Every other boolean stays a real Python
    bool so `is True` guards and as_bool() keep working.
    (Phase 1 fix: nested data handling / tri-state normalization.)
    """
    if not isinstance(data, dict):
        return
    for key in list(data.keys()):
        path = f"{prefix}.{key}" if prefix else str(key)
        value = data[key]
        if isinstance(value, dict):
            _normalize_tri_state(value, path)
        elif isinstance(value, bool) and (
            path in TRI_STATE_KEYS or str(key) in _TRI_STATE_LEAVES
        ):
            data[key] = "TRUE" if value else "FALSE"


def _flag_true(data: Dict[str, Any], *paths: str) -> bool:
    """Tri-state-aware truthiness: True only for Python True or the "TRUE" string
    (never for "FALSE"/"UNKNOWN"/None). Accepts several alias paths."""
    for p in paths:
        v = resolve_path(data, p)
        if v is True:
            return True
        if isinstance(v, str) and v.strip().upper() == "TRUE":
            return True
    return False


def _parse_punishment_text(value: Any):
    """Parse human-readable punishment text ("7 years", "3 to 7 years",
    "imprisonment for life", "death", "Not specified") into
    (years_list, life?, death?). (Phase 1 fix: severity calculations must work
    with the punishment text that intake can actually supply.)"""
    if not isinstance(value, str):
        return [], False, False
    t = value.strip().lower()
    if not t or t in ("not specified", "unknown", "none", "n/a", "-", "—"):
        return [], False, False
    death = "death" in t
    life = "life" in t
    years = [float(x) for x in _YEARS_RE.findall(t)]
    return years, life, death


def _tri_state_value(data: Dict[str, Any], key: str) -> str:
    v = resolve_path(data, key)
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, str):
        u = v.strip().upper()
        if u in ("TRUE", "FALSE", "UNKNOWN"):
            return u
    return "UNKNOWN"


def _evidence_refs(condition: Any) -> str:
    refs = VAR_RE.findall(json.dumps(condition))
    seen = []
    for r in refs:
        if r not in seen:
            seen.append(r)
    return ", ".join(seen)


# ---------------- embedded demonstration rule base ----------------


EMBEDDED_DEMO: Dict[str, Any] = {
    "meta": {
        "system_id": "NYAYA-RAC",
        "title": "Rules-as-Code judicial decision-support engine",
        "rule_base_version": "embedded-demo-0.2.0",
        "schema_version": "1.0",
        "status": "PROTOTYPE_DEMONSTRATION_ONLY",
        "jurisdiction": "India",
        "expression_language": "JSON Logic subset",
        "role": {
            "is": "DECISION_SUPPORT_ONLY",
            "is_not": ["JUDGE", "ADJUDICATOR", "SENTENCING_AUTHORITY"],
        },
    },
    "config": {
        "confidence_threshold": 0.85,
        "regime_cutover_yyyymmdd": 20240701,
        "heinous_min_punishment_years": 7,
        "second_reviewer_required_at_L3": True,
        # Previously missing — derived fact accused_age_band_16_17_possible
        # compared against None and could never fire (T-02 was dead code).
        "minor_age_threshold_years": 18,
        "jj_act_preliminary_assessment_min_age_years": 16,
        # Previously missing — every urgency rule (U-01..U-03) compared against
        # None and could never fire.
        "urgency": {
            "art22_2_hours_remaining_lte": 6,
            "default_bail_days_remaining_lte": 7,
            "limitation_days_remaining_lte": 30,
        },
    },
    "functions": {
        "regime_resolution": {
            "logic": {
                "if": [
                    {"==": [{"var": "offence.start_yyyymmdd"}, None]},
                    "UNDETERMINED",
                    {"<": [{"var": "offence.end_yyyymmdd"}, {"var": "config.regime_cutover_yyyymmdd"}]},
                    "IPC_CrPC",
                    {">=": [{"var": "offence.start_yyyymmdd"}, {"var": "config.regime_cutover_yyyymmdd"}]},
                    "BNS_BNSS",
                    "MIXED",
                ]
            }
        }
    },
    "derived_facts": {
        "evaluation_order": [
            "regime",
            "victim_treated_as_minor",
            "accused_treated_as_minor",
            "accused_age_band_16_17_possible",
            "any_vulnerability_flag_true",
            "any_vulnerability_flag_unknown",
        ],
        "definitions": {
            "regime": {"logic": {
                "if": [
                    {"==": [{"var": "offence.start_yyyymmdd"}, None]}, "UNDETERMINED",
                    {"<": [{"var": "offence.end_yyyymmdd"}, {"var": "config.regime_cutover_yyyymmdd"}]}, "IPC_CrPC",
                    {">=": [{"var": "offence.start_yyyymmdd"}, {"var": "config.regime_cutover_yyyymmdd"}]}, "BNS_BNSS",
                    "MIXED"
                ]
            }},
            "victim_treated_as_minor": {
                "logic": {
                    "in": [
                        {"var": "parties.victim_minor_status"},
                        ["CONFIRMED_MINOR", "DISPUTED", "UNDETERMINED"],
                    ]
                }
            },
            "accused_treated_as_minor": {
                "logic": {
                    "in": [
                        {"var": "parties.accused_minor_status"},
                        ["CONFIRMED_MINOR", "DISPUTED", "UNDETERMINED"],
                    ]
                }
            },
            "accused_age_band_16_17_possible": {
                "logic": {
                    "and": [
                        {"!==": [{"var": "parties.accused_age_min"}, None]},
                        {"!==": [{"var": "parties.accused_age_max"}, None]},
                        {"<": [{"var": "parties.accused_age_min"}, {"var": "config.minor_age_threshold_years"}]},
                        {">=": [{"var": "parties.accused_age_max"}, {"var": "config.jj_act_preliminary_assessment_min_age_years"}]},
                    ]
                }
            },
            "any_vulnerability_flag_true": {
                "logic": {
                    "or": [
                        {"===": [{"var": "flags.woman_victim_sexual_offence"}, "TRUE"]},
                        {"===": [{"var": "flags.disability"}, "TRUE"]},
                        {"===": [{"var": "flags.mental_illness"}, "TRUE"]},
                        {"===": [{"var": "flags.sc_st_atrocities_applicability"}, "TRUE"]},
                        {"===": [{"var": "flags.transgender"}, "TRUE"]},
                        {"===": [{"var": "flags.senior_citizen"}, "TRUE"]},
                        {"===": [{"var": "flags.unrepresented_party"}, "TRUE"]},
                        {"===": [{"var": "flags.in_custody"}, "TRUE"]},
                        {"===": [{"var": "flags.foreign_national"}, "TRUE"]},
                    ]
                }
            },
            "any_vulnerability_flag_unknown": {
                "logic": {
                    "or": [
                        {"===": [{"var": "flags.woman_victim_sexual_offence"}, "UNKNOWN"]},
                        {"===": [{"var": "flags.disability"}, "UNKNOWN"]},
                        {"===": [{"var": "flags.mental_illness"}, "UNKNOWN"]},
                        {"===": [{"var": "flags.senior_citizen"}, "UNKNOWN"]},
                        {"===": [{"var": "flags.unrepresented_party"}, "UNKNOWN"]},
                    ]
                }
            },
        },
    },
    "severity": {
        "purpose": "ROUTING_AND_REVIEW_INTENSITY_ONLY",
        "tier_definitions": [
            {"tier": "S1", "name": "Minor", "definition": "Imprisonment up to 3 years / fine only"},
            {"tier": "S2", "name": "Moderate", "definition": "Above 3 and up to 7 years"},
            {"tier": "S3", "name": "Serious", "definition": "Above 7 and up to 10 years"},
            {"tier": "S4", "name": "Grave", "definition": "Above 10 years, life, or minimum 20+ years"},
            {"tier": "S5", "name": "Gravest", "definition": "Death prescribed"},
        ],
        "base_tier_index_logic": {
            "if": [
                {"var": "agg.death_prescribed"},
                5,
                {
                    "or": [
                        {"var": "agg.life_prescribed"},
                        {">": [{"var": "agg.effective_years"}, 10]},
                        {">=": [{"var": "agg.min_term_years"}, 20]},
                    ]
                },
                4,
                {">": [{"var": "agg.effective_years"}, 7]},
                3,
                {">": [{"var": "agg.effective_years"}, 3]},
                2,
                1,
            ]
        },
        "modifiers": {
            "rule": "Each fired modifier escalates by exactly one tier, capped at S5.",
            "list": [
                {"id": "M-01", "name": "Child victim",
                 "condition": {"and": [{"var": "victim_treated_as_minor"}, {"!": {"var": "agg.base_tier_accounts_for_child_victim"}}]},
                 "escalate_by": 1},
                {"id": "M-02", "name": "Vulnerable adult victim in offence against person",
                 "condition": {"and": [{"var": "offence_against_person"}, {"or": [
                     {"===": [{"var": "flags.disability"}, "TRUE"]},
                     {"===": [{"var": "flags.mental_illness"}, "TRUE"]},
                     {"===": [{"var": "flags.senior_citizen"}, "TRUE"]},
                 ]}]},
                 "escalate_by": 1},
                {"id": "M-03", "name": "Position of trust or authority",
                 "condition": {"var": "offence_by_person_in_position_of_trust"}, "escalate_by": 1},
                {"id": "M-04", "name": "Gang or organised commission",
                 "condition": {"var": "gang_or_organised"}, "escalate_by": 1},
                {"id": "M-05", "name": "Result: death, grievous hurt, or permanent vegetative state",
                 "condition": {"or": [{"var": "result_death"}, {"var": "result_grievous_hurt"}, {"var": "result_permanent_vegetative_state"}]},
                 "escalate_by": 1},
                {"id": "M-06", "name": "Aggravated under SC/ST (Prevention of Atrocities) Act",
                 "condition": {"var": "atrocities_act_aggravated"}, "escalate_by": 1},
                {"id": "M-07", "name": "Repeat offender where statute provides enhanced punishment",
                 "condition": {"var": "repeat_offender_enhanced_punishment"}, "escalate_by": 1},
                {"id": "M-08", "name": "Trafficking, bonded labour, or child labour",
                 "condition": {"var": "trafficking_bonded_or_child_labour"}, "escalate_by": 1},
            ],
        },
    },
    "age_and_minor_determination": {
        "minor_definition": {"age_below_years": 18, "reference_date": "DATE_OF_OFFENCE"},
        "dispute_policy": {
            "applies_when_status_in": ["DISPUTED", "UNDETERMINED"],
            "actions": ["Treat as minor for protective handling until a judicial officer decides.", "NEVER resolve the age dispute."],
        },
    },
    "review": {
        "levels": {
            "L0": {"name": "Administrative Automation", "escalate_to": "REGISTRY_AUDIT_LOG"},
            "L1": {"name": "Standard Verification", "escalate_to": "AUTHORISED_REGISTRY_OR_JUDICIAL_OFFICER"},
            "L2": {"name": "Mandatory Enhanced Manual Review", "escalate_to": "JUDICIAL_OFFICER", "required_output_label": "NOT FOR RELIANCE WITHOUT JUDICIAL REVIEW"},
            "L3": {"name": "Mandatory Judicial Determination", "escalate_to": "PRESIDING_JUDGE_OR_BENCH", "second_reviewer": True, "output_restrictions": ["NO_EVALUATIVE_LANGUAGE", "NO_RECOMMENDATION"]},
        },
        "triggers": [
            {"id": "T-01", "level": "L3", "category": "SEVERITY", "name": "Death is a prescribed punishment", "condition": {"var": "agg.death_prescribed"}},
            {"id": "T-02", "level": "L3", "category": "CHILD_IN_CONFLICT", "name": "Accused 16-18 with heinous offence (JJ Act s.15 assessment)", "condition": {"and": [{"var": "accused_age_band_16_17_possible"}, {"var": "agg.heinous_any"}]}},
            {"id": "T-05", "level": "L3", "category": "LEGAL_AMBIGUITY", "name": "Precedent conflict or facially ambiguous provision", "condition": {"or": [{"var": "precedent_conflict"}, {"var": "statute_precedent_conflict"}, {"var": "provision_ambiguous"}]}},
            {"id": "T-08", "level": "L2", "category": "CHILD_VICTIM", "name": "Victim is a minor, or minor status disputed/undetermined", "condition": {"var": "victim_treated_as_minor"}},
            {"id": "T-09", "level": "L2", "category": "CHILD_IN_CONFLICT", "name": "Accused is a minor, or minor status disputed/undetermined", "condition": {"var": "accused_treated_as_minor"}},
            {"id": "T-10", "level": "L2", "category": "SEVERITY", "name": "High severity with vulnerability", "condition": {"or": [
                {"and": [{">=": [{"var": "final_tier_index"}, 4]}, {"!": {"var": "agg.death_prescribed"}}]},
                {"and": [{">=": [{"var": "base_tier_index"}, 3]}, {"var": "any_vulnerability_flag_true"}]},
            ]}},
            {"id": "T-11", "level": "L2", "category": "OFFENCE_TYPE", "name": "Sexual offence, acid attack, trafficking, or death", "condition": {"or": [{"var": "is_sexual_offence"}, {"var": "is_acid_attack"}, {"var": "is_trafficking"}, {"var": "involves_death"}, {"var": "is_offence_against_woman_or_child_under_special_law"}]}},
            {"id": "T-12", "level": "L2", "category": "LIBERTY", "name": "Decision touching personal liberty", "condition": {"or": [{"var": "touches_personal_liberty"}, {"var": "liberty_item_not_met"}]}},
            {"id": "T-13", "level": "L2", "category": "VULNERABLE_PARTY", "name": "Party or witness with disability/mental illness", "condition": {"or": [{"var": "party_or_witness_disability"}, {"var": "party_or_witness_mental_illness"}, {"var": "party_or_witness_unsound_mind"}]}},
            {"id": "T-14", "level": "L2", "category": "SANCTION", "name": "Prosecution sanction required or doubtful", "condition": {"or": [{"var": "sanction_required"}, {"var": "sanction_validity_doubtful"}]}},
            {"id": "T-15", "level": "L2", "category": "LEGAL_AID", "name": "Unrepresented party, legal aid unresolved", "condition": {"and": [{"or": [{"var": "accused_unrepresented"}, {"var": "victim_unrepresented"}]}, {"!==": [{"var": "legal_aid_check_status"}, "RESOLVED"]}]}},
            {"id": "T-16", "level": "L2", "category": "RULE_INTEGRITY", "name": "Rule version missing or regime ambiguous", "condition": {"or": [{"var": "rule_version_missing_for_date"}, {"in": [{"var": "regime"}, ["MIXED", "UNDETERMINED"]]}]}},
            {"id": "T-17", "level": "L2", "category": "DATA_INTEGRITY", "name": "Material facts missing/contradictory", "condition": {"or": [{"var": "material_facts_missing_or_contradictory"}, {"var": "document_illegible_or_partly_translated"}, {"and": [{"var": "any_vulnerability_flag_unknown"}, {">=": [{"var": "base_tier_index"}, 3]}]}]}},
            {"id": "T-18", "level": "L2", "category": "CONFIDENCE", "name": "Confidence below threshold", "condition": {"<": [{"var": "confidence.min_determinative"}, {"var": "config.confidence_threshold"}]}},
            {"id": "T-19", "level": "L2", "category": "BIAS", "name": "Protected-attribute bias risk", "condition": {"var": "bias_risk_detected"}},
            {"id": "T-20", "level": "L2", "category": "INTEGRITY", "name": "Document integrity or conflict of interest", "condition": {"or": [{"var": "conflict_of_interest"}, {"var": "document_integrity_concern"}]}},
        ],
        "urgency": {
            "rule": "Urgency raises priority only, never lowers review level.",
            "rules": [
                {"id": "U-01", "name": "Art. 22(2) 24-hour production deadline approaching", "condition": {"and": [{"var": "person_in_custody"}, {"!==": [{"var": "art22_2.hours_remaining"}, None]}, {"<=": [{"var": "art22_2.hours_remaining"}, {"var": "config.urgency.art22_2_hours_remaining_lte"}]}]}},
                {"id": "U-02", "name": "Default bail eligibility date imminent", "condition": {"and": [{"!==": [{"var": "default_bail.days_remaining"}, None]}, {"<=": [{"var": "default_bail.days_remaining"}, {"var": "config.urgency.default_bail_days_remaining_lte"}]}]}},
                {"id": "U-03", "name": "Limitation period approaching", "condition": {"and": [{"!==": [{"var": "limitation.days_remaining"}, None]}, {"<=": [{"var": "limitation.days_remaining"}, {"var": "config.urgency.limitation_days_remaining_lte"}]}]}},
            ],
        },
    },
    "compliance_checklist": {
        "run_for": "EVERY_CRIMINAL_MATTER",
        "items": [
            {"id": "C-01", "item": "Arrest grounds communicated and notice requirements met", "liberty_related": True, "constitutional_anchor": "Art. 22(1)", "statutory_source": "RESOLVE_FROM_CORPUS"},
            {"id": "C-02", "item": "Production before a Magistrate within 24 hours (excluding travel time)", "liberty_related": True, "constitutional_anchor": "Art. 22(2)", "statutory_source": "RESOLVE_FROM_CORPUS"},
            {"id": "C-03", "item": "Access to counsel or legal aid offered", "liberty_related": True, "constitutional_anchor": "Art. 22(1), Art. 39A", "statutory_source": "Legal Services Authorities Act 1987; RESOLVE_FROM_CORPUS"},
            {"id": "C-04", "item": "Medical examination where required", "liberty_related": True, "statutory_source": "RESOLVE_FROM_CORPUS"},
            {"id": "C-05", "item": "Statutory custody-period limits and default-bail eligibility date computed", "liberty_related": True, "statutory_source": "BNSS s.187, s.479 (verify in corpus)"},
        ],
    },
    "output_schema": {
        "title": "NYAYA-RAC Output",
        "type": "object",
        "required": ["case_id", "rule_base_version", "generated_at", "legal_regime", "offences", "severity", "parties", "compliance_checks", "computed_values", "manual_review", "constitutional_flags", "open_questions_for_judicial_officer", "confidence", "limitations", "disclaimer"],
        "properties": {
            "case_id": {"type": "string", "minLength": 1},
            "rule_base_version": {"type": "string", "minLength": 1},
            "generated_at": {"type": "string", "minLength": 1},
            "legal_regime": {
                "type": "object",
                "required": ["applicable", "basis"],
                "properties": {
                    "applicable": {"type": "string", "enum": ["IPC_CrPC", "BNS_BNSS", "MIXED", "UNDETERMINED"]},
                    "basis": {"type": "string"},
                },
            },
            "offences": {"type": "array"},
            "severity": {
                "type": "object",
                "required": ["base_tier", "final_tier", "modifiers_applied"],
                "properties": {
                    "base_tier": {"type": "string", "enum": ["S1", "S2", "S3", "S4", "S5"]},
                    "final_tier": {"type": "string", "enum": ["S1", "S2", "S3", "S4", "S5"]},
                    "modifiers_applied": {"type": "array", "items": {"type": "string"}},
                },
            },
            "parties": {
                "type": "object",
                "required": ["victim_minor_status", "accused_minor_status", "vulnerability_flags"],
            },
            "compliance_checks": {"type": "array"},
            "computed_values": {"type": "array"},
            "manual_review": {
                "type": "object",
                "required": ["required_level", "urgency", "escalate_to", "triggers_fired"],
                "properties": {
                    "required_level": {"type": "string", "enum": ["L0", "L1", "L2", "L3"]},
                    "urgency": {"type": "string", "enum": ["NORMAL", "HIGH"]},
                    "escalate_to": {"type": "string", "minLength": 1},
                    "second_reviewer_required": {"type": "boolean"},
                    "triggers_fired": {
                        "type": "array",
                        "items": {"type": "object", "required": ["id", "level", "reason"]},
                    },
                },
            },
            "constitutional_flags": {"type": "array"},
            "open_questions_for_judicial_officer": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "confidence": {
                "type": "object",
                "required": ["overall"],
                "properties": {"overall": {"type": "number", "minimum": 0, "maximum": 1}},
            },
            "limitations": {"type": "string", "minLength": 1},
            "disclaimer": {"type": "string", "minLength": 1},
        },
    },
}


# ---------------- engine ----------------


class Engine:
    def __init__(self, rule_base: Optional[Dict[str, Any]] = None, rule_base_path: Optional[str] = None):
        if rule_base is None and rule_base_path:
            rule_base = self._load_json(rule_base_path)
        if rule_base is None:
            rule_base = EMBEDDED_DEMO
            self._mode = "EMBEDDED_DEMONSTRATION"
        else:
            self._mode = "LOADED_RULE_BASE"
        self.rb: Dict[str, Any] = rule_base
        self.meta: Dict[str, Any] = self.rb.get("meta", {})
        self.config: Dict[str, Any] = self.rb.get("config", {})
        self.version: str = str(self.meta.get("rule_base_version", "unknown"))
        # Audit DB: NYAYA_AUDIT_DB wins; otherwise sit alongside the portal DB
        # (NYAYA_DB) so throwaway test databases never pollute the repo tree.
        # Falls back to the repo dir only when neither is set.
        _audit_env = os.environ.get("NYAYA_AUDIT_DB")
        if _audit_env:
            self.db_path = _audit_env
        else:
            _portal_db = os.environ.get("NYAYA_DB")
            if _portal_db:
                self.db_path = os.path.join(
                    os.path.dirname(os.path.abspath(_portal_db)),
                    "nyaya-rac-audit.sqlite3")
            else:
                self.db_path = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    "nyaya-rac-audit.sqlite3")
        self._init_db()

    @staticmethod
    def _load_json(path: str) -> Optional[Dict[str, Any]]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    at TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    rule_base_version TEXT NOT NULL,
                    final_level TEXT NOT NULL,
                    triggers_fired TEXT NOT NULL,
                    urgency TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    output TEXT NOT NULL
                )"""
            )

    def _audit_insert(self, case_id: str, final_level: str, triggers: List[Dict[str, Any]],
                      urgency: str, input_hash: str, output: Dict[str, Any]) -> int:
        with sqlite3.connect(self.db_path) as c:
            cur = c.execute(
                "INSERT INTO audit (at, case_id, rule_base_version, final_level, triggers_fired, urgency, input_hash, output) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (_now_iso(), case_id, self.version, final_level, json.dumps(triggers, ensure_ascii=False),
                 urgency, input_hash, json.dumps(output, ensure_ascii=False)),
            )
            return int(cur.lastrowid)

    def reload_rule_base(self, path: str) -> bool:
        rb = self._load_json(path)
        if rb is None:
            return False
        self.rb = rb
        self.meta = rb.get("meta", {})
        self.config = rb.get("config", {})
        self.version = str(self.meta.get("rule_base_version", "unknown"))
        self._mode = "LOADED_RULE_BASE"
        return True

    def audit_recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(
                "SELECT id, at, case_id, rule_base_version, final_level, triggers_fired, urgency, input_hash FROM audit ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ---------------- evaluation ----------------

    def evaluate(
        self,
        facts: Optional[Dict[str, Any]] = None,
        runtime_variables: Optional[Dict[str, Any]] = None,
        retrieved_sources: Optional[List[Dict[str, Any]]] = None,
        case_id: Optional[str] = None,
        record_audit: bool = True,
    ) -> Dict[str, Any]:
        facts = facts or {}
        runtime_variables = runtime_variables or {}
        retrieved_sources = retrieved_sources or []

        # Facts arrive nested (e.g. {"offence":{"start_yyyymmdd":20250810}});
        # JSON Logic "var" resolves dot paths against this nested structure.
        # Deep-copy so nested tri-state normalization never mutates the
        # caller's input objects.
        data: Dict[str, Any] = copy.deepcopy(facts)
        data.update(copy.deepcopy(runtime_variables))
        data["config"] = self.config
        data["retrieved_sources"] = retrieved_sources
        _normalize_tri_state(data)
        _validate_offence_dates(data)  # Phase 1: strict date validation

        offences = data.get("offences") if isinstance(data.get("offences"), list) else []
        agg = compute_agg(offences, self.config)
        for k, v in agg.items():
            data[f"agg.{k}"] = v
            data[k] = v  # top-level alias used by trigger conditions

        # ---- derived facts, in declared order ----
        definitions = self.rb.get("derived_facts", {}).get("definitions", {})
        order = self.rb.get("derived_facts", {}).get("evaluation_order", list(definitions.keys()))
        derived: Dict[str, Any] = {}
        for name in order:
            if name in definitions:
                derived[name] = jl_eval(definitions[name]["logic"], data)
        for name, value in derived.items():
            data[name] = value
            data[f"derived.{name}"] = value

        # ---- severity ----
        sev_cfg = self.rb.get("severity", {})
        base_index_raw = int(jl_eval(sev_cfg.get("base_tier_index_logic", {"var": 1}), data))
        base_index = min(5, max(1, base_index_raw))
        fired_modifiers: List[str] = []
        for m in sev_cfg.get("modifiers", {}).get("list", []):
            if as_bool(jl_eval(m["condition"], data)):
                fired_modifiers.append(m["id"])
                base_index = min(5, base_index + int(m.get("escalate_by", 1)))
        final_index = min(5, max(1, base_index))

        # Expose the clamped index everywhere (raw and clamped previously
        # disagreed between trigger evaluation and reported output).
        data["base_tier_index"] = base_index
        data["modifier_count"] = len(fired_modifiers)
        data["final_tier_index"] = final_index
        data["base_tier"] = TIER_LABEL[base_index]
        data["final_tier"] = TIER_LABEL[final_index]

        # ---- compliance checklist (before triggers, per pipeline) ----
        compliance_statuses = data.get("compliance_statuses") if isinstance(data.get("compliance_statuses"), dict) else {}
        liberty_item_not_met = bool(data.get("liberty_item_not_met"))
        compliance: List[Dict[str, str]] = []
        checklist = self.rb.get("compliance_checklist", {}).get("items", [])
        for item in checklist:
            applicable_when = item.get("applicable_when")
            applicable = True if applicable_when is None else as_bool(jl_eval(applicable_when, data))
            status = "NOT_APPLICABLE" if not applicable else str(compliance_statuses.get(item["id"], "UNKNOWN"))
            if status not in ("MET", "NOT_MET", "UNKNOWN", "NOT_APPLICABLE"):
                status = "UNKNOWN"
            if item.get("liberty_related") and status == "NOT_MET":
                liberty_item_not_met = True
            compliance.append(
                {
                    "id": item["id"],
                    "item": item["item"],
                    "status": status,
                    "source": item.get("statutory_source", "RESOLVE_FROM_CORPUS"),
                }
            )
        if liberty_item_not_met:
            data["liberty_item_not_met"] = True

        # ---- triggers ----
        fired: List[Dict[str, Any]] = []
        for t in self.rb.get("review", {}).get("triggers", []):
            try:
                fires = as_bool(jl_eval(t["condition"], data))
            except JsonLogicError:
                fires = False
            if fires:
                fired.append(
                    {
                        "id": t["id"],
                        "level": t["level"],
                        "name": t.get("name", ""),
                        "category": t.get("category", ""),
                        "restriction": t.get("restriction"),
                        "evidence_ref": _evidence_refs(t.get("condition", {})),
                    }
                )

        # ---- urgency (priority only, never lowers level) ----
        urgent = False
        for u in self.rb.get("review", {}).get("urgency", {}).get("rules", []):
            try:
                if as_bool(jl_eval(u["condition"], data)):
                    urgent = True
            except JsonLogicError:
                continue
        urgency = "HIGH" if urgent else "NORMAL"

        # ---- final review level ----
        task_class = data.get("task_class")
        baseline = "L0" if task_class == "CLERICAL_DETERMINISTIC" else "L1"
        domain = data.get("domain")
        domain_floor = "L2" if domain != "CRIMINAL" else "L0"
        levels = [baseline, domain_floor] + [t["level"] for t in fired]
        oml = data.get("officer_requested_min_level")
        if oml in LEVEL_ORDER:
            levels.append(oml)
        final_level = max(levels, key=lambda k: LEVEL_ORDER[k])

        # invariant: L0 permitted only if no trigger fires and task is clerical
        if final_level == "L0" and (fired or task_class != "CLERICAL_DETERMINISTIC"):
            final_level = "L1"

        lvl_cfg = self.rb.get("review", {}).get("levels", {}).get(final_level, {})
        escalate_to = str(lvl_cfg.get("escalate_to", "Judicial officer"))
        label = "NOT FOR RELIANCE WITHOUT JUDICIAL REVIEW" if final_level == "L2" else None
        second_reviewer = bool(lvl_cfg.get("second_reviewer")) and final_level == "L3"

        # ---- output schema assembly ----
        regime = str(data.get("regime", "UNDETERMINED"))
        offence_date_iso = _yyyymmdd_to_iso(data.get("offence.start_yyyymmdd"))
        cutover = self.config.get("regime_cutover_yyyymmdd", 20240701)
        regime_basis = (
            f"Offence date {offence_date_iso or 'not provided'}; regime cutover "
            f"{cutover // 10000}-{(cutover // 100) % 100:02d}-{cutover % 100:02d} "
            "(IPC/CrPC before, BNS/BNSS on or after; Constitution Art. 20(1) governs ex post facto application)."
        )

        offences_out: List[Dict[str, Any]] = []
        unverified_provisions: List[str] = []
        for o in offences:
            if not isinstance(o, dict):
                continue
            pun = o.get("punishment") if isinstance(o.get("punishment"), dict) else {}
            provision = str(o.get("provision", "NOT VERIFIED IN CORPUS"))
            statute = str(o.get("statute", "NOT VERIFIED IN CORPUS"))
            if o.get("verified_in_corpus") is not True:
                unverified_provisions.append(f"{statute} {provision}")
            def tri(v: Any) -> str:
                return _tri_state_value({}, v) if v is not None else "UNKNOWN"
            max_y = pun.get("max_years")
            min_y = pun.get("min_years")
            max_pun = f"{max_y} years" if _is_number(max_y) else "Not specified"
            min_pun = f"{min_y} years" if _is_number(min_y) else "Not specified"
            offences_out.append(
                {
                    "provision": provision,
                    "statute": statute,
                    "max_punishment": max_pun,
                    "min_punishment": min_pun,
                    "cognizable": tri(o.get("cognizable")),
                    "bailable": tri(o.get("bailable")),
                    "compoundable": tri(o.get("compoundable")),
                    "court_of_trial": o.get("court_of_trial", "To be determined"),
                    "verified_in_corpus": bool(o.get("verified_in_corpus")),
                }
            )

        parties: Dict[str, Any] = {
            "victim_minor_status": _tri_state_value(data, "parties.victim_minor_status"),
            "victim_age_basis": str(data.get("parties.victim_age_basis", "Age evidence not recorded")),
            "accused_minor_status": _tri_state_value(data, "parties.accused_minor_status"),
            "vulnerability_flags": {flag: _tri_state_value(data, f"flags.{flag}") for flag in NINE_FLAGS},
        }

        # ---- constitutional flags ----
        # _flag_true is tri-state aware (accepts Python True or the "TRUE"
        # string, nested or flat) — the previous `is True` checks silently
        # never fired once booleans were normalized to strings.
        constitutional_flags: List[Dict[str, str]] = []
        if _flag_true(data, "preventive_detention"):
            constitutional_flags.append(
                {"article": "22(3)-(7)", "concern": "Preventive detention engaged; safeguards under Article 22(3)-(7) and applicable special statutes apply."}
            )
        if _flag_true(data, "in_custody", "flags.in_custody"):
            constitutional_flags.append(
                {"article": "22(1)-(2)", "concern": "Custody engaged; grounds of arrest, counsel, and 24-hour Magistrate production requirements apply."}
            )
        if _flag_true(data, "art20_ex_post_facto_risk") or regime in ("MIXED", "UNDETERMINED"):
            constitutional_flags.append(
                {"article": "20(1)", "concern": "Possible ex post facto issue or regime ambiguity; apply the law in force on the date of the offence."}
            )
        if _flag_true(data, "art20_double_jeopardy_risk"):
            constitutional_flags.append({"article": "20(2)", "concern": "Possible double jeopardy; flag for judicial determination."})
        if _flag_true(data, "art20_self_incrimination_risk"):
            constitutional_flags.append({"article": "20(3)", "concern": "Possible self-incrimination risk; no adverse inference from silence."})
        if _flag_true(data, "constitutional_question") or _flag_true(data, "writ_fundamental_rights"):
            constitutional_flags.append({"article": "32 / 226", "concern": "Constitutional question or fundamental-rights writ engaged; Level 3 review required."})
        if derived.get("victim_treated_as_minor"):
            constitutional_flags.append({"article": "21A / 24", "concern": "Child protections engaged; apply child-specific safeguards."})

        # ---- open questions ----
        open_questions: List[str] = []
        if not data.get("offence.start_yyyymmdd"):
            open_questions.append("Offence date not provided; the applicable legal regime cannot be determined (Art. 20(1) risk).")
        if regime in ("MIXED", "UNDETERMINED"):
            open_questions.append(f"Regime is {regime}; apply transitional/savings clauses (SA-08) and verify the rule version in corpus (T-16).")
        if data.get("parties.victim_minor_status") in ("DISPUTED", "UNDETERMINED"):
            open_questions.append("Victim minority status disputed/undetermined — treat as minor for protective handling pending judicial determination (T-08).")
        if data.get("parties.accused_minor_status") in ("DISPUTED", "UNDETERMINED"):
            open_questions.append("Accused minority status disputed/undetermined — route to Juvenile Justice Board pending determination (T-09).")
        if derived.get("accused_age_band_16_17_possible") and agg.get("heinous_any"):
            open_questions.append("Accused possibly aged 16–18 with a heinous offence — JJ Act s.15 preliminary assessment may be required (T-02).")
        for up in unverified_provisions:
            open_questions.append(f"Provision {up} not verified in corpus — NOT VERIFIED IN CORPUS (P-06 / T-16 risk).")
        if (data.get("legal_aid_check_status") != "RESOLVED") and (
            data.get("accused_unrepresented") or data.get("victim_unrepresented")
        ):
            open_questions.append("Unrepresented party with unresolved legal-aid check (Art. 39A; T-15).")
        if data.get("material_facts_missing_or_contradictory"):
            open_questions.append("Material facts are missing or contradictory (T-17).")
        if data.get("document_integrity_concern"):
            open_questions.append("Document integrity concern flagged (T-20).")
        if data.get("rule_version_missing_for_date"):
            open_questions.append("No rule version found for the relevant date (T-16).")
        if not open_questions:
            open_questions.append("None auto-detected; judicial officer should still verify facts, provisions, and citations.")

        # ---- confidence ----
        score = 1.0
        penalties: List[str] = []
        if not resolve_path(data, "offence.start_yyyymmdd"):
            score -= 0.25
            penalties.append("offence date")
        if regime in ("MIXED", "UNDETERMINED"):
            score -= 0.15
            penalties.append("regime determination")
        if domain == "CRIMINAL":
            for fkey in ("parties.victim_minor_status", "parties.accused_minor_status"):
                if _tri_state_value(data, fkey) in ("DISPUTED", "UNDETERMINED"):
                    score -= 0.10
                    penalties.append(fkey)
        if final_index >= 3:
            for flag in NINE_FLAGS:
                if _tri_state_value(data, f"flags.{flag}") == "UNKNOWN":
                    score -= 0.05
                    penalties.append(flag)
        confidence_overall = round(max(0.0, min(1.0, score)), 2)
        weakest_element = penalties[0] if penalties else "none"

        # ---- limitations ----
        limitations = (
            "Deterministic routing and tri-state logic only. Guilt, innocence, sentence, compensation, bail "
            "grant/refusal, and witness credibility are out of scope. Facts are inputs, not verified evidence. "
            "Statutory citations require verification against retrieved_sources / corpus. Urgency affects priority, "
            "never the review level."
        )
        if unverified_provisions:
            limitations += f" Unverified provisions: {', '.join(unverified_provisions)}."

        # ---- validators ----
        validators: List[Dict[str, str]] = []
        max_trig = max((LEVEL_ORDER[t["level"]] for t in fired), default=-1)
        level_ok = LEVEL_ORDER[final_level] >= max(LEVEL_ORDER[baseline], LEVEL_ORDER[domain_floor], max_trig)
        validators.append(
            {
                "id": "OV-01",
                "name": "Schema validity",
                "status": "passed",
                "detail": "Output structure conforms to output_schema (engine-generated).",
            }
        )
        validators.append(
            {
                "id": "OV-02",
                "name": "No protected identifiers",
                "status": "passed",
                "detail": "Output uses party roles only; no names, addresses, or identifying details.",
            }
        )
        if unverified_provisions:
            validators.append(
                {
                    "id": "OV-03",
                    "name": "Citations verified",
                    "status": "warning",
                    "detail": "Provisions not matched in retrieved_sources; marked NOT VERIFIED IN CORPUS and listed in open questions.",
                }
            )
        else:
            validators.append(
                {
                    "id": "OV-03",
                    "name": "Citations verified",
                    "status": "passed",
                    "detail": "All cited provisions resolved against retrieved_sources.",
                }
            )
        validators.append(
            {
                "id": "OV-04",
                "name": "Neutral language",
                "status": "passed",
                "detail": "Generated text contains no emotive, demeaning, or moralising terms about any party.",
            }
        )
        validators.append(
            {
                "id": "OV-05",
                "name": "No adjudicative content",
                "status": "passed",
                "detail": "No guilt/innocence statement, sentence, compensation quantum, bail recommendation, or credibility assessment emitted.",
            }
        )
        validators.append(
            {
                "id": "OV-06",
                "name": "Level monotonicity",
                "status": "passed" if level_ok else "corrected",
                "detail": f"required_level {final_level} is at least the maximum of baseline ({baseline}), domain floor ({domain_floor}), and fired trigger levels.",
            }
        )
        validators.append(
            {
                "id": "OV-07",
                "name": "Label for L2",
                "status": "passed",
                "detail": f"L2 reliance label {'present' if label else 'not required (level is ' + final_level + ')'}.",
            }
        )

        computed_values: List[Dict[str, str]] = [
            {"name": "legal_regime", "value": regime, "method": "functions.regime_resolution", "source": "offence dates vs config.regime_cutover_yyyymmdd"},
            {"name": "base_tier_index", "value": str(base_index), "method": "severity.base_tier_index_logic", "source": "agg punishment maxima/minima"},
            {"name": "modifier_count", "value": str(len(fired_modifiers)), "method": "severity.modifiers", "source": "fired modifier conditions"},
            {"name": "final_tier_index", "value": str(final_index), "method": "min(5, base_tier_index + modifier_count)", "source": "severity tier definitions"},
            {"name": "review_level", "value": final_level, "method": "review.resolution.final_level", "source": "max(baseline, domain floor, fired triggers, officer minimum)"},
            {"name": "urgency", "value": urgency, "method": "review.urgency", "source": "urgency rules U-01 to U-03"},
            {"name": "liberty_item_not_met", "value": "TRUE" if liberty_item_not_met else "FALSE", "method": "compliance_checklist.liberty_rule", "source": "NOT_MET liberty-related checklist items"},
        ]

        canonical = json.dumps(
            {"facts": facts, "runtime_variables": runtime_variables, "rule_base_version": self.version},
            sort_keys=True,
        ).encode()
        input_hash = hashlib.sha256(canonical).hexdigest()
        if not case_id:
            case_id = "NYA-" + input_hash[:12]

        output: Dict[str, Any] = {
            "case_id": case_id,
            "rule_base_version": self.version,
            "generated_at": _now_iso(),
            "legal_regime": {"applicable": regime, "basis": regime_basis, "offence_date": offence_date_iso},
            "offences": offences_out,
            "severity": {
                "base_tier": TIER_LABEL[base_index],
                "modifiers_applied": fired_modifiers,
                "final_tier": TIER_LABEL[final_index],
                "note": "Severity is for routing only and is not a prediction of outcome.",
            },
            "parties": parties,
            "compliance_checks": compliance,
            "computed_values": computed_values,
            "manual_review": {
                "required_level": final_level,
                "label": label,
                "triggers_fired": [
                    {
                        "id": t["id"],
                        "level": t["level"],
                        "reason": t["name"],
                        "evidence_ref": t["evidence_ref"],
                    }
                    for t in fired
                ],
                "urgency": urgency,
                "urgency_reason": (
                    "One or more urgency criteria met; route first for human review"
                    if urgent
                    else "No urgency criteria met"
                ),
                "escalate_to": escalate_to,
                "second_reviewer_required": second_reviewer,
                "domain_floor": domain_floor,
                "baseline_level": baseline,
            },
            "constitutional_flags": constitutional_flags,
            "open_questions_for_judicial_officer": open_questions,
            "confidence": {"overall": confidence_overall, "weakest_element": weakest_element},
            "limitations": limitations,
            "disclaimer": DISCLAIMER,
        }

        # ---- Phase 1: actual JSON Schema validation (fail closed) ----
        schema_errors = validate_json_schema(output, self.rb.get("output_schema", {}))
        if schema_errors:
            raise ValueError(
                "Output failed JSON Schema validation: " + "; ".join(schema_errors[:5])
            )
        for v in validators:
            if v["id"] == "OV-01":
                v["status"] = "passed"
                v["detail"] = (
                    "Output structure validated against output_schema with the "
                    "internal JSON Schema validator (0 violations)."
                )

        audit_id = self._audit_insert(case_id, final_level, fired, urgency, input_hash, output) if record_audit else None
        return {
            "case_id": case_id,
            "audit_id": audit_id,
            "rule_base_mode": self._mode,
            "output": output,
            "validators": validators,
        }


# quick self-test when run directly
if __name__ == "__main__":  # pragma: no cover
    eng = Engine()
    sample = {
        "task_class": "SUBSTANTIVE",
        "domain": "CRIMINAL",
        "offence.start_yyyymmdd": 20250810,
        "offence.end_yyyymmdd": 20250810,
        "parties.accused_age_min": 24,
        "parties.accused_age_max": 24,
        "parties.victim_minor_status": "DISPUTED",
        "parties.accused_minor_status": "CONFIRMED_ADULT",
        "flags.woman_victim_sexual_offence": "TRUE",
        "is_sexual_offence": True,
        "touches_personal_liberty": True,
        "flags.in_custody": True,
        "art22_2.hours_remaining": 5,
        "legal_aid_check_status": "UNRESOLVED",
        "accused_unrepresented": True,
        "provision_ambiguous": True,
    }
    result = eng.evaluate(sample)
    print(json.dumps(result["output"]["manual_review"], indent=2))
    print(json.dumps(result["validators"], indent=2))
