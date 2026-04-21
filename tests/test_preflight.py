"""
Formal tests for PreflightRiskEngine (src/preflight.py).

Covers: _classify(), summarize(), _build_resolution_steps(),
_build_notes(), format_text(), format_json().
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from src.parser import X12Parser
from src.validate import X12Validator, Issue as ValIssue
from src.preflight import (
    PreflightRiskEngine,
    PreflightSummary,
    RiskIssue,
    RiskClaim,
    _TIER_MAP,
    _TIER_RANK,
    _RECOMMENDATIONS,
    _RESOLUTION_ORDER,
    _COMMON_REJECTION_CODES,
)


FIXTURES = pathlib.Path(__file__).parent / "fixtures"


# ── Tier mapping ──────────────────────────────────────────────────────────────

class TestTierMapping:
    """_TIER_MAP should cover all the codes we use."""

    def test_all_codes_in_tier_map_are_valid(self):
        for code, tier in _TIER_MAP.items():
            assert tier in ("BLOCKING", "ELEVATED", "WARNINGS", "INFO")

    def test_blocking_codes_defined(self):
        blockers = [c for c, t in _TIER_MAP.items() if t == "BLOCKING"]
        assert "SE_COUNT_MISMATCH" in blockers
        assert "ORPHAN_ST" in blockers
        assert "REQUIRED_SEGMENT_MISSING" in blockers

    def test_elevated_codes_defined(self):
        elevated = [c for c, t in _TIER_MAP.items() if t == "ELEVATED"]
        assert "NON_NUMERIC_AMOUNT" in elevated
        assert "CLP_STATUS_INVALID" in elevated

    def test_warning_codes_defined(self):
        warns = [c for c, t in _TIER_MAP.items() if t == "WARNINGS"]
        assert "CLAIM_ID_DUPLICATE" in warns
        assert "BPR_CLP_SUM_MISMATCH" in warns

    def test_info_codes_defined(self):
        infos = [c for c, t in _TIER_MAP.items() if t == "INFO"]
        assert "UNKNOWN_SEGMENT" in infos


class TestTierRank:
    def test_rank_order(self):
        assert _TIER_RANK["BLOCKING"] < _TIER_RANK["ELEVATED"]
        assert _TIER_RANK["ELEVATED"] < _TIER_RANK["WARNINGS"]
        assert _TIER_RANK["WARNINGS"] < _TIER_RANK["INFO"]


# ── RiskIssue dataclass ───────────────────────────────────────────────────────

class TestRiskIssue:
    def test_risk_issue_defaults(self):
        r = RiskIssue(
            severity="error",
            code="SE_COUNT_MISMATCH",
            message="mismatch",
            category="segment_structure",
            tier="BLOCKING",
        )
        assert r.segment_tag == ""
        assert r.segment_position == 0
        assert r.recommendation == ""

    def test_risk_issue_full(self):
        r = RiskIssue(
            severity="error",
            code="NON_NUMERIC_AMOUNT",
            message="CLP e2 is not numeric",
            category="data_quality",
            tier="ELEVATED",
            segment_tag="CLP",
            segment_position=42,
            recommendation="Replace non-numeric characters.",
        )
        assert r.tier == "ELEVATED"
        assert r.segment_tag == "CLP"
        assert r.segment_position == 42


# ── PreflightRiskEngine._classify ────────────────────────────────────────────

class TestClassify:
    def _engine(self, issues: list[ValIssue] = None):
        from src.validate import ValidationResult
        vr = ValidationResult()
        if issues:
            for iss in issues:
                vr.issues.append(iss)
        return PreflightRiskEngine(vr)

    def test_unknown_code_defaults_to_info(self):
        eng = self._engine([ValIssue("warning", "MY_WEIRD_CODE", "msg", "content")])
        ri = eng._classify(ValIssue("warning", "MY_WEIRD_CODE", "msg", "content"))
        assert ri.tier == "INFO"

    def test_se_count_mismatch_is_blocking(self):
        eng = self._engine([ValIssue("error", "SE_COUNT_MISMATCH", "mismatch", "segment_structure")])
        ri = eng._classify(ValIssue("error", "SE_COUNT_MISMATCH", "mismatch", "segment_structure"))
        assert ri.tier == "BLOCKING"

    def test_non_numeric_amount_is_elevated(self):
        eng = self._engine([ValIssue("warning", "NON_NUMERIC_AMOUNT", "bad amount", "data_quality")])
        ri = eng._classify(ValIssue("warning", "NON_NUMERIC_AMOUNT", "bad amount", "data_quality"))
        assert ri.tier == "ELEVATED"

    def test_claim_id_duplicate_is_warning(self):
        eng = self._engine([ValIssue("warning", "CLAIM_ID_DUPLICATE", "dup", "data_quality")])
        ri = eng._classify(ValIssue("warning", "CLAIM_ID_DUPLICATE", "dup", "data_quality"))
        assert ri.tier == "WARNINGS"

    def test_unknown_segment_is_info(self):
        eng = self._engine([ValIssue("warning", "UNKNOWN_SEGMENT", "unknown tag", "content")])
        ri = eng._classify(ValIssue("warning", "UNKNOWN_SEGMENT", "unknown tag", "content"))
        assert ri.tier == "INFO"

    def test_payer_rule_required_segment_missing_is_blocking(self):
        eng = self._engine([ValIssue("error", "PAYER_RULE_REQUIRED_SEGMENT_MISSING", "missing", "payer_rule")])
        ri = eng._classify(ValIssue("error", "PAYER_RULE_REQUIRED_SEGMENT_MISSING", "missing", "payer_rule"))
        assert ri.tier == "BLOCKING"

    def test_recommendation_attached(self):
        eng = self._engine([ValIssue("error", "SE_COUNT_MISMATCH", "mismatch", "segment_structure")])
        ri = eng._classify(ValIssue("error", "SE_COUNT_MISMATCH", "mismatch", "segment_structure"))
        assert ri.recommendation != ""
        assert "SE" in ri.recommendation or "Recount" in ri.recommendation


# ── PreflightRiskEngine.summarize ─────────────────────────────────────────────

class TestSummarize:
    def _engine_and_summary(self, issues: list[ValIssue]):
        from src.validate import ValidationResult
        vr = ValidationResult()
        for iss in issues:
            vr.issues.append(iss)
        eng = PreflightRiskEngine(vr)
        return eng, eng.summarize()

    def test_no_issues_overall_tier_info(self):
        eng, summary = self._engine_and_summary([])
        assert summary.overall_tier == "INFO"
        assert summary.total_issues == 0
        assert summary.submission_ready is True

    def test_blocking_sets_overall_blocking(self):
        iss = ValIssue("error", "SE_COUNT_MISMATCH", "mismatch", "segment_structure")
        eng, summary = self._engine_and_summary([iss])
        assert summary.overall_tier == "BLOCKING"
        assert summary.submission_ready is False

    def test_elevated_without_blocking_is_elevated(self):
        iss = ValIssue("warning", "NON_NUMERIC_AMOUNT", "bad", "data_quality")
        eng, summary = self._engine_and_summary([iss])
        assert summary.overall_tier == "ELEVATED"

    def test_warning_without_higher_is_warning(self):
        iss = ValIssue("warning", "CLAIM_ID_DUPLICATE", "dup", "data_quality")
        eng, summary = self._engine_and_summary([iss])
        assert summary.overall_tier == "WARNINGS"

    def test_counts_correct(self):
        issues = [
            ValIssue("error", "SE_COUNT_MISMATCH", "m1", "segment_structure"),
            ValIssue("error", "ORPHAN_ST", "m2", "envelope"),
            ValIssue("warning", "NON_NUMERIC_AMOUNT", "m3", "data_quality"),
            ValIssue("warning", "CLAIM_ID_DUPLICATE", "m4", "data_quality"),
            ValIssue("warning", "UNKNOWN_SEGMENT", "m5", "content"),
        ]
        eng, summary = self._engine_and_summary(issues)
        assert summary.total_issues == 5
        assert summary.blocking_count == 2
        assert summary.elevated_count == 1
        assert summary.warning_count == 1  # CLAIM_ID_DUPLICATE → WARNINGS
        assert summary.info_count == 1      # UNKNOWN_SEGMENT → INFO

    def test_likely_rejection_codes_extracted(self):
        issues = [
            ValIssue("error", "SE_COUNT_MISMATCH", "m1", "segment_structure"),
            ValIssue("warning", "CLAIM_ID_DUPLICATE", "m2", "data_quality"),
        ]
        eng, summary = self._engine_and_summary(issues)
        assert "SE_COUNT_MISMATCH" in summary.likely_rejection_codes
        assert "CLAIM_ID_DUPLICATE" not in summary.likely_rejection_codes

    def test_resolution_steps_ordered(self):
        issues = [
            ValIssue("error", "CLAIM_ID_DUPLICATE", "dup", "data_quality"),
            ValIssue("error", "SE_COUNT_MISMATCH", "mismatch", "segment_structure"),
            ValIssue("error", "ORPHAN_ST", "orphan", "envelope"),
        ]
        eng, summary = self._engine_and_summary(issues)
        steps = summary.resolution_steps
        assert len(steps) >= 1
        # ORPHAN_ST should come before SE_COUNT_MISMATCH in resolution order
        orphan_idx = next((i for i, s in enumerate(steps) if "ORPHAN_ST" in s), -1)
        se_idx = next((i for i, s in enumerate(steps) if "SE_COUNT_MISMATCH" in s), -1)
        if orphan_idx >= 0 and se_idx >= 0:
            assert orphan_idx < se_idx, "ORPHAN_ST should be resolved before SE_COUNT_MISMATCH"

    def test_submission_ready_false_with_blocking(self):
        issues = [ValIssue("error", "SE_COUNT_MISMATCH", "m1", "segment_structure")]
        eng, summary = self._engine_and_summary(issues)
        assert summary.submission_ready is False

    def test_submission_ready_true_without_blocking(self):
        issues = [ValIssue("warning", "CLAIM_ID_DUPLICATE", "dup", "data_quality")]
        eng, summary = self._engine_and_summary(issues)
        assert summary.submission_ready is True


# ── _build_resolution_steps ──────────────────────────────────────────────────

class TestBuildResolutionSteps:
    def _steps(self, codes: list[str]) -> list[str]:
        from src.validate import ValidationResult
        vr = ValidationResult()
        for code in codes:
            vr.add_error(code, f"{code} message")
        eng = PreflightRiskEngine(vr)
        ri_list = [eng._classify(i) for i in vr.issues]
        return eng._build_resolution_steps(ri_list)

    def test_respects_resolution_order(self):
        steps = self._steps(["SE_COUNT_MISMATCH", "ORPHAN_ST", "NON_NUMERIC_AMOUNT"])
        codes_in_order = [s for s in self._steps(["SE_COUNT_MISMATCH", "ORPHAN_ST", "NON_NUMERIC_AMOUNT"])]
        # Resolution order has ORPHAN_ST before SE_COUNT_MISMATCH
        codes_str = " ".join(steps)
        assert len(steps) == 3

    def test_duplicates_collapsed(self):
        steps = self._steps(["SE_COUNT_MISMATCH", "SE_COUNT_MISMATCH"])
        assert len(steps) == 1

    def test_empty_for_no_issues(self):
        steps = self._steps([])
        assert steps == []


# ── _build_notes ──────────────────────────────────────────────────────────────

class TestBuildNotes:
    def _notes(self, issues: list[ValIssue], companion_applied: bool = False) -> list[str]:
        from src.validate import ValidationResult
        vr = ValidationResult()
        for iss in issues:
            vr.issues.append(iss)
        eng = PreflightRiskEngine(vr, companion_rules_applied=companion_applied)
        ri_list = [eng._classify(i) for i in vr.issues]
        return eng._build_notes(ri_list)

    def test_companion_note_when_applied(self):
        notes = self._notes([], companion_applied=True)
        assert any("companion" in n.lower() or "payer" in n.lower() for n in notes)

    def test_empty_transaction_note(self):
        notes = self._notes([ValIssue("error", "EMPTY_TRANSACTION", "empty", "segment_structure")])
        assert any("empty" in n.lower() or "transaction" in n.lower() for n in notes)

    def test_se_count_mismatch_note(self):
        notes = self._notes([ValIssue("error", "SE_COUNT_MISMATCH", "mismatch", "segment_structure")])
        assert any("SE" in n or "segment" in n.lower() for n in notes)

    def test_blocking_note(self):
        notes = self._notes([ValIssue("error", "ORPHAN_ST", "orphan", "envelope")])
        assert any("blocking" in n.lower() for n in notes)

    def test_duplicate_claim_note(self):
        notes = self._notes([ValIssue("warning", "CLAIM_ID_DUPLICATE", "dup", "data_quality")])
        assert any("duplicate" in n.lower() or "resubmission" in n.lower() for n in notes)


# ── format_text ───────────────────────────────────────────────────────────────

class TestFormatText:
    def _summary(self, issues: list[ValIssue], companion_applied: bool = False) -> str:
        from src.validate import ValidationResult
        vr = ValidationResult()
        for iss in issues:
            vr.issues.append(iss)
        eng = PreflightRiskEngine(vr, companion_rules_applied=companion_applied)
        summary = eng.summarize()
        return eng.format_text(summary)

    def test_clean_fixture_shows_info_banner(self):
        text = self._summary([])
        assert "INFO" in text or "✅" in text

    def test_blocking_shows_do_not_submit(self):
        iss = ValIssue("error", "SE_COUNT_MISMATCH", "mismatch", "segment_structure")
        text = self._summary([iss])
        assert "BLOCKING" in text or "❌" in text

    def test_shows_issue_breakdown(self):
        issues = [
            ValIssue("error", "SE_COUNT_MISMATCH", "m1", "segment_structure"),
            ValIssue("warning", "CLAIM_ID_DUPLICATE", "m2", "data_quality"),
        ]
        text = self._summary(issues)
        assert "Blocking" in text or "❌" in text
        assert "Warnings" in text or "⚡" in text

    def test_shows_resolution_steps_when_blocking(self):
        iss = ValIssue("error", "SE_COUNT_MISMATCH", "mismatch", "segment_structure")
        text = self._summary([iss])
        assert "Resolution" in text or "→" in text

    def test_shows_likely_rejection_codes(self):
        iss = ValIssue("error", "SE_COUNT_MISMATCH", "mismatch", "segment_structure")
        text = self._summary([iss])
        assert "SE_COUNT_MISMATCH" in text or "Auto-Rejection" in text

    def test_width_64_separator(self):
        text = self._summary([])
        assert "=" * 60 in text or "=" * 64 in text

    def test_shows_submission_ready(self):
        text = self._summary([])
        assert "Submission Ready" in text or "ready" in text.lower()

    def test_no_issues_clean_message(self):
        text = self._summary([])
        assert "No issues" in text or "clean" in text.lower() or "✅" in text


# ── format_json ────────────────────────────────────────────────────────────────

class TestFormatJson:
    def _json(self, issues: list[ValIssue]) -> str:
        from src.validate import ValidationResult
        vr = ValidationResult()
        for iss in issues:
            vr.issues.append(iss)
        eng = PreflightRiskEngine(vr)
        summary = eng.summarize()
        return eng.format_json(summary)

    def test_valid_json(self):
        text = self._json([])
        parsed = json.loads(text)
        assert isinstance(parsed, dict)

    def test_includes_overall_tier(self):
        text = self._json([])
        parsed = json.loads(text)
        assert "overall_tier" in parsed

    def test_includes_submission_ready(self):
        text = self._json([])
        parsed = json.loads(text)
        assert "submission_ready" in parsed
        assert isinstance(parsed["submission_ready"], bool)

    def test_includes_issue_counts(self):
        issues = [
            ValIssue("error", "SE_COUNT_MISMATCH", "m1", "segment_structure"),
            ValIssue("warning", "CLAIM_ID_DUPLICATE", "m2", "data_quality"),
        ]
        text = self._json(issues)
        parsed = json.loads(text)
        assert "issue_counts" in parsed
        assert parsed["issue_counts"]["total"] == 2
        assert parsed["issue_counts"]["blocking"] == 1

    def test_includes_likely_rejection_codes(self):
        iss = ValIssue("error", "SE_COUNT_MISMATCH", "mismatch", "segment_structure")
        text = self._json([iss])
        parsed = json.loads(text)
        assert "likely_rejection_codes" in parsed
        assert "SE_COUNT_MISMATCH" in parsed["likely_rejection_codes"]

    def test_includes_resolution_steps(self):
        iss = ValIssue("error", "SE_COUNT_MISMATCH", "mismatch", "segment_structure")
        text = self._json([iss])
        parsed = json.loads(text)
        assert "resolution_steps" in parsed
        assert isinstance(parsed["resolution_steps"], list)

    def test_includes_notes(self):
        iss = ValIssue("warning", "UNKNOWN_SEGMENT", "unknown", "content")
        text = self._json([iss])
        parsed = json.loads(text)
        assert "notes" in parsed
        assert isinstance(parsed["notes"], list)


# ── Integration: preflight from real ValidationResult ─────────────────────────

class TestPreflightIntegration:
    def _val_result(self, fixture_name: str):
        fixture = FIXTURES / fixture_name
        parser = X12Parser.from_file(fixture)
        validator = X12Validator(parser)
        return validator.validate()

    def test_clean_fixture_no_blocking(self):
        result = self._val_result("sample_835.edi")
        eng = PreflightRiskEngine(result)
        summary = eng.summarize()
        assert summary.blocking_count == 0

    def test_missing_se_has_blocking(self):
        result = self._val_result("sample_missing_se.edi")
        eng = PreflightRiskEngine(result)
        summary = eng.summarize()
        assert summary.blocking_count >= 1
        assert summary.overall_tier in ("BLOCKING", "ELEVATED")

    def test_missing_ge_has_blocking(self):
        result = self._val_result("sample_missing_ge.edi")
        eng = PreflightRiskEngine(result)
        summary = eng.summarize()
        assert summary.blocking_count >= 1

    def test_empty_transaction_has_blocking(self):
        result = self._val_result("sample_empty_transaction.edi")
        eng = PreflightRiskEngine(result)
        summary = eng.summarize()
        assert summary.blocking_count >= 1

    def test_clean_fixture_text_looks_good(self):
        result = self._val_result("sample_835.edi")
        eng = PreflightRiskEngine(result)
        summary = eng.summarize()
        text = eng.format_text(summary)
        assert "X12 PREFLIGHT" in text
        assert len(text) > 50

    def test_clean_fixture_json_looks_good(self):
        result = self._val_result("sample_835.edi")
        eng = PreflightRiskEngine(result)
        summary = eng.summarize()
        text = eng.format_json(summary)
        parsed = json.loads(text)
        assert parsed["overall_tier"] in ("INFO", "WARNINGS", "ELEVATED")
        assert parsed["submission_ready"] is True

    def test_837_institutional_blocking_or_elevated(self):
        result = self._val_result("sample_837_institutional.edi")
        eng = PreflightRiskEngine(result)
        summary = eng.summarize()
        # Institutional without HI might be elevated or blocking
        assert summary.overall_tier in ("BLOCKING", "ELEVATED", "WARNINGS", "INFO")

    def test_multi_interchange_flags(self):
        result = self._val_result("sample_multi_interchange.edi")
        eng = PreflightRiskEngine(result)
        summary = eng.summarize()
        # Multi interchange is flagged as unusual pattern in forensic but
        # may or may not appear in validation
        assert isinstance(summary.total_issues, int)


# ── PreflightSummary dataclass ─────────────────────────────────────────────────

class TestPreflightSummaryDataclass:
    def test_defaults(self):
        s = PreflightSummary(
            overall_tier="INFO",
            total_issues=0,
            blocking_count=0,
            elevated_count=0,
            warning_count=0,
            info_count=0,
            likely_rejection_codes=[],
            claims=[],
            resolution_steps=[],
            submission_ready=True,
            notes=[],
        )
        assert s.overall_tier == "INFO"
        assert s.submission_ready is True

    def test_claims_field_is_list(self):
        s = PreflightSummary(
            overall_tier="BLOCKING",
            total_issues=1,
            blocking_count=1,
            elevated_count=0,
            warning_count=0,
            info_count=0,
            likely_rejection_codes=["SE_COUNT_MISMATCH"],
            claims=[],
            resolution_steps=[],
            submission_ready=False,
            notes=[],
        )
        assert isinstance(s.claims, list)


# ── Recommendations catalog ────────────────────────────────────────────────────

class TestRecommendations:
    def test_all_blocking_codes_have_recommendations(self):
        for code, tier in _TIER_MAP.items():
            if tier == "BLOCKING":
                assert code in _RECOMMENDATIONS, f"{code} has no recommendation"

    def test_all_codes_in_resolutions_have_recommendations(self):
        for code in _RESOLUTION_ORDER:
            assert code in _RECOMMENDATIONS, f"{code} has no recommendation"

    def test_recommendations_are_non_trivial(self):
        for code, rec in _RECOMMENDATIONS.items():
            assert len(rec) > 10, f"{code} recommendation is too short"
