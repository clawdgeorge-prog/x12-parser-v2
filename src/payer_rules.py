"""
Config-driven companion-guide / payer rules foundation.

This module intentionally keeps scope small:
- JSON rule packs only (stdlib, no YAML dependency)
- pack-level matching by transaction set, version, payer name/id
- a few bounded rule types:
  * presence: required | recommended | forbidden
  * value assertions on matching segments: equals | starts_with | in

It is not a TR3 engine. It is a pragmatic hook for trading-partner rules.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from src.parser import X12Parser, TransactionSet


@dataclass
class CompanionRuleIssue:
    severity: str
    code: str
    message: str
    rule_id: str = ""
    segment_tag: str = ""
    segment_position: int = 0


@dataclass
class CompanionRuleResult:
    issues: list[CompanionRuleIssue] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    def add(self, severity: str, code: str, message: str, rule_id: str = "", segment_tag: str = "", segment_position: int = 0) -> None:
        self.issues.append(CompanionRuleIssue(severity, code, message, rule_id, segment_tag, segment_position))


@dataclass
class RulePack:
    name: str
    description: str
    match: dict[str, Any]
    rules: list[dict[str, Any]]
    source_path: str = ""


class RulePackError(ValueError):
    pass


SUPPORTED_PRESENCE = {"required", "recommended", "forbidden"}
SUPPORTED_ASSERTIONS = {"equals", "starts_with", "in"}


def load_rule_pack(path: str | Path) -> RulePack:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    _validate_rule_pack_dict(raw, str(path))
    return RulePack(
        name=raw["name"],
        description=raw.get("description", ""),
        match=raw.get("match", {}),
        rules=raw.get("rules", []),
        source_path=str(path),
    )


def _validate_rule_pack_dict(data: dict[str, Any], path: str = "<memory>") -> None:
    if not isinstance(data, dict):
        raise RulePackError(f"Rule pack {path} must be a JSON object")
    if not isinstance(data.get("name"), str) or not data["name"].strip():
        raise RulePackError(f"Rule pack {path} must include non-empty string field 'name'")
    if "rules" not in data or not isinstance(data["rules"], list) or not data["rules"]:
        raise RulePackError(f"Rule pack {path} must include non-empty array field 'rules'")
    if "match" in data and not isinstance(data["match"], dict):
        raise RulePackError(f"Rule pack {path} field 'match' must be an object when present")

    for idx, rule in enumerate(data["rules"], start=1):
        if not isinstance(rule, dict):
            raise RulePackError(f"Rule pack {path} rule #{idx} must be an object")
        if not isinstance(rule.get("id"), str) or not rule["id"].strip():
            raise RulePackError(f"Rule pack {path} rule #{idx} must include non-empty string 'id'")
        if not isinstance(rule.get("segment"), str) or not rule["segment"].strip():
            raise RulePackError(f"Rule pack {path} rule {rule.get('id', '#'+str(idx))} must include non-empty string 'segment'")
        if "presence" in rule:
            if rule["presence"] not in SUPPORTED_PRESENCE:
                raise RulePackError(
                    f"Rule pack {path} rule {rule['id']} has unsupported presence {rule['presence']!r}; "
                    f"expected one of {sorted(SUPPORTED_PRESENCE)}"
                )
        assertions = [k for k in SUPPORTED_ASSERTIONS if k in rule]
        if len(assertions) > 1:
            raise RulePackError(f"Rule pack {path} rule {rule['id']} can only use one of {sorted(SUPPORTED_ASSERTIONS)}")
        if "presence" not in rule and not assertions:
            raise RulePackError(f"Rule pack {path} rule {rule['id']} must define 'presence' or one assertion ({sorted(SUPPORTED_ASSERTIONS)})")
        if "severity" in rule and rule["severity"] not in ("error", "warning"):
            raise RulePackError(f"Rule pack {path} rule {rule['id']} severity must be 'error' or 'warning'")
        if "element" in rule and (not isinstance(rule["element"], str) or not rule["element"].startswith("e")):
            raise RulePackError(f"Rule pack {path} rule {rule['id']} field 'element' must look like 'e1', 'e2', etc.")
        if "where" in rule and not isinstance(rule["where"], dict):
            raise RulePackError(f"Rule pack {path} rule {rule['id']} field 'where' must be an object when present")


class CompanionRuleEngine:
    def __init__(self, parser: X12Parser):
        self.parser = parser

    def apply_pack(self, pack: RulePack) -> CompanionRuleResult:
        result = CompanionRuleResult()
        self.parser._parse()
        for ic in self.parser.interchanges:
            for fg in ic.groups:
                version = self.parser._get_gs_version(fg) or ""
                for ts in fg.transactions:
                    ctx = _build_transaction_context(self.parser, ts, version)
                    if not _pack_matches(pack.match, ctx):
                        continue
                    for rule in pack.rules:
                        self._apply_rule(rule, ts, ctx, result)
        return result

    def _apply_rule(self, rule: dict[str, Any], ts: TransactionSet, ctx: dict[str, Any], result: CompanionRuleResult) -> None:
        severity = rule.get("severity", "warning")
        segment = rule["segment"]
        rule_id = rule["id"]
        matches = _matching_segments(ts, segment, rule.get("where"))

        if "presence" in rule:
            presence = rule["presence"]
            if presence == "required" and not matches:
                result.add(severity, "PAYER_RULE_REQUIRED_SEGMENT_MISSING", rule.get("message") or f"Rule {rule_id}: required segment {segment} not found", rule_id, segment)
            elif presence == "recommended" and not matches:
                result.add(severity, "PAYER_RULE_RECOMMENDED_SEGMENT_MISSING", rule.get("message") or f"Rule {rule_id}: recommended segment {segment} not found", rule_id, segment)
            elif presence == "forbidden" and matches:
                seg = matches[0]
                result.add(severity, "PAYER_RULE_FORBIDDEN_SEGMENT_PRESENT", rule.get("message") or f"Rule {rule_id}: forbidden segment {segment} is present", rule_id, segment, seg.position)
            return

        if not matches:
            return
        element_name = rule.get("element")
        if not element_name:
            return
        for seg in matches:
            actual = _element_value(seg, element_name)
            if actual is None:
                continue
            if "equals" in rule and actual != str(rule["equals"]):
                result.add(severity, "PAYER_RULE_VALUE_MISMATCH", rule.get("message") or f"Rule {rule_id}: expected {segment}.{element_name} == {rule['equals']!r}, got {actual!r}", rule_id, segment, seg.position)
            elif "starts_with" in rule and not actual.startswith(str(rule["starts_with"])):
                result.add(severity, "PAYER_RULE_VALUE_MISMATCH", rule.get("message") or f"Rule {rule_id}: expected {segment}.{element_name} to start with {rule['starts_with']!r}, got {actual!r}", rule_id, segment, seg.position)
            elif "in" in rule and actual not in {str(v) for v in rule["in"]}:
                result.add(severity, "PAYER_RULE_VALUE_MISMATCH", rule.get("message") or f"Rule {rule_id}: expected {segment}.{element_name} in {rule['in']!r}, got {actual!r}", rule_id, segment, seg.position)


def _build_transaction_context(parser: X12Parser, ts: TransactionSet, version: str) -> dict[str, Any]:
    payer_name = None
    payer_id = None
    provider_name = None
    for loop in ts.loops:
        for seg in loop.segments:
            if seg.tag == "N1":
                qualifier = parser._seg_get(seg, 1) or ""
                if qualifier == "PR":
                    payer_name = parser._seg_get(seg, 2) or payer_name
                    payer_id = parser._seg_get(seg, 4) or payer_id
                elif qualifier == "PE":
                    provider_name = parser._seg_get(seg, 2) or provider_name
            elif seg.tag == "NM1":
                qualifier = parser._seg_get(seg, 1) or ""
                if qualifier in ("40", "PR"):
                    payer_name = " ".join(filter(None, [parser._seg_get(seg, 3), parser._seg_get(seg, 4)])) or payer_name
                    payer_id = parser._seg_get(seg, 9) or payer_id
                elif qualifier in ("41", "85"):
                    provider_name = " ".join(filter(None, [parser._seg_get(seg, 3), parser._seg_get(seg, 4)])) or provider_name
    return {
        "transaction_set": ts.set_id,
        "version": version,
        "payer_name": payer_name or "",
        "payer_id": payer_id or "",
        "provider_name": provider_name or "",
    }


def _pack_matches(match: dict[str, Any], ctx: dict[str, Any]) -> bool:
    if not match:
        return True
    if "transaction_set" in match and str(match["transaction_set"]) != ctx["transaction_set"]:
        return False
    if "version" in match and str(match["version"]) != ctx["version"]:
        return False
    if "payer_id" in match and str(match["payer_id"]) != ctx["payer_id"]:
        return False
    if "payer_name_contains" in match and str(match["payer_name_contains"]).lower() not in ctx["payer_name"].lower():
        return False
    return True


def _matching_segments(ts: TransactionSet, segment_tag: str, where: Optional[dict[str, Any]]) -> list[Any]:
    out = []
    for loop in ts.loops:
        for seg in loop.segments:
            if seg.tag != segment_tag:
                continue
            if where:
                ok = True
                for key, expected in where.items():
                    actual = _element_value(seg, key)
                    if actual != str(expected):
                        ok = False
                        break
                if not ok:
                    continue
            out.append(seg)
    return out


def _element_value(seg: Any, key: str) -> Optional[str]:
    if not key.startswith("e"):
        return None
    try:
        idx = int(key[1:])
    except ValueError:
        return None
    if idx < 1 or idx > len(seg.elements):
        return None
    return seg.elements[idx - 1].raw
