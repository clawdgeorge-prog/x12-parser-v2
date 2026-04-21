"""
X12 Preflight Rejection-Risk Analyzer.

Classifies validation issues into submission-risk tiers and produces
an actionable pre-submission risk summary.

Usage:
    from src.preflight import PreflightRiskEngine, RiskTier
    engine = PreflightRiskEngine(validator_result, payer_rules_result)
    summary = engine.summarize()

Risk tiers:
  BLOCKING  — will almost certainly cause automatic rejection at the clearinghouse/payer
  ELEVATED  — likely to cause rejection or require manual review
  WARNINGS  — payer/trading-partner may flag but usually accepted
  INFO      — informational observations, not rejection risks

The engine maps known X12 validation codes to risk tiers based on
real-world clearinghouse rejection patterns.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.validate import ValidationResult, Issue as ValIssue


# ── Risk tier definitions ─────────────────────────────────────────────────────

@dataclass
class RiskIssue:
    severity: str          # mirrors ValidationResult issue severity
    code: str              # validation issue code
    message: str
    category: str
    tier: str              # BLOCKING | ELEVATED | WARNINGS | INFO
    segment_tag: str = ""
    segment_position: int = 0
    recommendation: str = ""


@dataclass
class RiskClaim:
    claim_id: str
    risk_tier: str
    blocking_issues: list[str]
    elevated_issues: list[str]
    warning_messages: list[str]


@dataclass
class PreflightSummary:
    """Full preflight risk summary."""
    overall_tier: str                # worst tier across all issues
    total_issues: int
    blocking_count: int
    elevated_count: int
    warning_count: int
    info_count: int
    likely_rejection_codes: list[str]   # codes that commonly cause auto-rejection
    claims: list[RiskClaim]
    resolution_steps: list[str]         # ordered list of what to fix first
    submission_ready: bool               # True if no blocking issues
    notes: list[str]                     # contextual notes


# ── Risk tier mapping ─────────────────────────────────────────────────────────
# Maps validation issue codes (or categories) to risk tiers.
# Based on common clearinghouse and ERA rejection patterns.

_TIER_MAP: dict[str, str] = {
    # BLOCKING — structural issues that will cause automatic rejection
    "SE_COUNT_MISMATCH":       "BLOCKING",
    "SE_NO_COUNT":             "BLOCKING",
    "SE_INVALID_COUNT":        "BLOCKING",
    "ORPHAN_ISA":             "BLOCKING",
    "ORPHAN_IEA":             "BLOCKING",
    "ORPHAN_GS":              "BLOCKING",
    "ORPHAN_GE":              "BLOCKING",
    "ORPHAN_ST":              "BLOCKING",
    "ORPHAN_SE":              "BLOCKING",
    "ISA_IEA_MISMATCH":       "BLOCKING",
    "GS_GE_MISMATCH":         "BLOCKING",
    "ST_SE_MISMATCH":         "BLOCKING",
    "EMPTY_TRANSACTION":       "BLOCKING",
    "REQUIRED_SEGMENT_MISSING": "BLOCKING",
    "PAYER_RULE_REQUIRED_SEGMENT_MISSING": "BLOCKING",

    # ELEVATED — content/semantic issues that commonly cause rejection on first pass
    "NON_NUMERIC_AMOUNT":      "ELEVATED",
    "CLP_STATUS_INVALID":      "ELEVATED",
    "CLP_STATUS_OUT_OF_RANGE": "ELEVATED",
    "NM1_BILLING_PROVIDER_MISSING": "ELEVATED",
    "N1_PR_MISSING":          "ELEVATED",
    "N1_PE_MISSING":          "ELEVATED",
    "PAYER_RULE_VALUE_MISMATCH": "ELEVATED",
    "EMPTY_GROUP":             "ELEVATED",

    # WARNINGS — usually accepted but may trigger manual review or downstream rejection
    "CLAIM_ID_DUPLICATE":     "WARNINGS",
    "BPR_CLP_SUM_MISMATCH":   "WARNINGS",
    "CLAIM_WITHOUT_SERVICE_LINES": "WARNINGS",
    "PLB_REFERENCE_INVALID":  "WARNINGS",
    "PAYER_RULE_RECOMMENDED_SEGMENT_MISSING": "WARNINGS",
    "PAYER_RULE_FORBIDDEN_SEGMENT_PRESENT": "WARNINGS",
    "ISA_DATE_INVALID":        "WARNINGS",
    "ISA_TIME_INVALID":        "WARNINGS",

    # INFO — observations, not rejection risks
    "UNKNOWN_SEGMENT":        "INFO",
    "HI_MISSING_INSTITUTIONAL": "INFO",
}


# Codes that are very commonly seen as auto-rejection reasons
_COMMON_REJECTION_CODES = {
    "SE_COUNT_MISMATCH",
    "REQUIRED_SEGMENT_MISSING",
    "NON_NUMERIC_AMOUNT",
    "ORPHAN_ISA",
    "ORPHAN_ST",
    "CLP_STATUS_INVALID",
}


_RESOLUTION_ORDER = [
    # Blockers first
    "ORPHAN_ISA",
    "ORPHAN_IEA",
    "ORPHAN_GS",
    "ORPHAN_GE",
    "ORPHAN_ST",
    "ORPHAN_SE",
    "ISA_IEA_MISMATCH",
    "GS_GE_MISMATCH",
    "ST_SE_MISMATCH",
    "SE_COUNT_MISMATCH",
    "SE_NO_COUNT",
    "SE_INVALID_COUNT",
    "EMPTY_TRANSACTION",
    "REQUIRED_SEGMENT_MISSING",
    "PAYER_RULE_REQUIRED_SEGMENT_MISSING",
    # Elevated
    "NON_NUMERIC_AMOUNT",
    "CLP_STATUS_INVALID",
    "CLP_STATUS_OUT_OF_RANGE",
    "NM1_BILLING_PROVIDER_MISSING",
    "N1_PR_MISSING",
    "N1_PE_MISSING",
    "PAYER_RULE_VALUE_MISMATCH",
    "EMPTY_GROUP",
    # Warnings
    "CLAIM_ID_DUPLICATE",
    "BPR_CLP_SUM_MISMATCH",
    "CLAIM_WITHOUT_SERVICE_LINES",
    "PLB_REFERENCE_INVALID",
    "PAYER_RULE_RECOMMENDED_SEGMENT_MISSING",
    "PAYER_RULE_FORBIDDEN_SEGMENT_PRESENT",
    "ISA_DATE_INVALID",
    "ISA_TIME_INVALID",
]


_RECOMMENDATIONS: dict[str, str] = {
    "SE_COUNT_MISMATCH": "Recount segments between ST and SE and correct the SE trailer count.",
    "SE_NO_COUNT": "Add the correct segment count to the SE trailer.",
    "SE_INVALID_COUNT": "Ensure SE e1 contains a valid integer.",
    "ORPHAN_ISA": "Close the previous interchange with IEA before starting a new ISA.",
    "ORPHAN_IEA": "Verify the IEA trailer matches the preceding ISA.",
    "ORPHAN_GS": "Place GS inside an ISA/IEA interchange envelope.",
    "ORPHAN_GE": "Verify the GE trailer matches the preceding GS.",
    "ORPHAN_ST": "Place ST inside a GS/GE functional group envelope.",
    "ORPHAN_SE": "Verify the SE trailer matches the preceding ST.",
    "ISA_IEA_MISMATCH": "Ensure each interchange has exactly one ISA and one IEA.",
    "GS_GE_MISMATCH": "Ensure each functional group has matching GS and GE counts.",
    "ST_SE_MISMATCH": "Ensure each transaction set has matching ST and SE counts.",
    "EMPTY_TRANSACTION": "Add segments to the transaction or remove the empty ST/SE pair.",
    "REQUIRED_SEGMENT_MISSING": "Add the missing required segment or verify the file is a complete X12 instance.",
    "NON_NUMERIC_AMOUNT": "Replace non-numeric characters in monetary fields; check for delimiter errors.",
    "CLP_STATUS_INVALID": "Replace the CLP status code with a valid numeric code (1-29).",
    "CLP_STATUS_OUT_OF_RANGE": "Use a CLP status code in the valid range 1-29 per X12 835 TR3.",
    "NM1_BILLING_PROVIDER_MISSING": "Add NM1*85 (billing provider) or NM1*41 (submitter) to the 837.",
    "N1_PR_MISSING": "Add N1*PR (payer) segment to the 835 remittance.",
    "N1_PE_MISSING": "Add N1*PE (provider/payee) segment to the 835 remittance.",
    "EMPTY_GROUP": "Add ST/SE pairs to the functional group or remove the empty GS/GE pair.",
    "CLAIM_ID_DUPLICATE": "Verify whether duplicate claim IDs are intentional resubmissions or data errors.",
    "BPR_CLP_SUM_MISMATCH": "Reconcile the BPR payment total against the sum of CLP paid amounts; "
        "ensure PLB adjustments are accounted for separately.",
    "CLAIM_WITHOUT_SERVICE_LINES": "Add service line segments (SVC) to the claim or confirm "
        "the denial/pend status with the payer.",
    "PLB_REFERENCE_INVALID": "Format PLB e3 as 'REASON:CLAIMREF', e.g. 'CV:CLP001'.",
    "ISA_DATE_INVALID": "Correct ISA-09 to the CCYYMMDD format.",
    "ISA_TIME_INVALID": "Correct ISA-10 to the HHMM format.",
    "PAYER_RULE_REQUIRED_SEGMENT_MISSING": "Add the required segment per the trading-partner companion guide.",
    "PAYER_RULE_VALUE_MISMATCH": "Correct the element value to match the payer-specific requirement.",
    "PAYER_RULE_RECOMMENDED_SEGMENT_MISSING": "Review the companion guide; add the recommended segment if required by the payer.",
    "PAYER_RULE_FORBIDDEN_SEGMENT_PRESENT": "Remove or remap the forbidden segment per the payer companion guide.",
}


_TIER_RANK = {"BLOCKING": 0, "ELEVATED": 1, "WARNINGS": 2, "INFO": 3}


class PreflightRiskEngine:
    """
    Turns a ValidationResult (and optionally CompanionRuleResult) into
    an actionable pre-submission risk summary.

    Parameters:
        validation_result: ValidationResult from X12Validator.validate()
        payer_result: Optional CompanionRuleResult from CompanionRuleEngine.apply_pack()
        companion_rules_applied: bool — whether payer rules were applied (affects notes)
    """

    def __init__(
        self,
        validation_result: ValidationResult,
        payer_result=None,
        companion_rules_applied: bool = False,
    ):
        self.validation = validation_result
        self.payer = payer_result
        self.companion_rules_applied = companion_rules_applied

    def summarize(self) -> PreflightSummary:
        all_issues = list(self.validation.issues)
        if self.payer:
            for pi in self.payer.issues:
                # Mirror payer issues into ValidationResult-style
                all_issues.append(ValIssue(
                    severity=pi.severity,
                    code=pi.code,
                    message=pi.message,
                    category="payer_rule",
                    segment_tag=pi.segment_tag,
                    segment_position=pi.segment_position,
                ))

        risk_issues = [self._classify(issue) for issue in all_issues]

        blocking = [i for i in risk_issues if i.tier == "BLOCKING"]
        elevated = [i for i in risk_issues if i.tier == "ELEVATED"]
        warnings = [i for i in risk_issues if i.tier == "WARNINGS"]
        info = [i for i in risk_issues if i.tier == "INFO"]

        # Overall tier = worst tier present
        if blocking:
            overall_tier = "BLOCKING"
        elif elevated:
            overall_tier = "ELEVATED"
        elif warnings:
            overall_tier = "WARNINGS"
        else:
            overall_tier = "INFO"

        # Common rejection codes found
        likely_rejection = [
            i.code for i in risk_issues
            if i.code in _COMMON_REJECTION_CODES
        ]

        # Resolution steps (ordered)
        resolution_steps = self._build_resolution_steps(risk_issues)

        # Contextual notes
        notes = self._build_notes(risk_issues)

        return PreflightSummary(
            overall_tier=overall_tier,
            total_issues=len(risk_issues),
            blocking_count=len(blocking),
            elevated_count=len(elevated),
            warning_count=len(warnings),
            info_count=len(info),
            likely_rejection_codes=likely_rejection,
            claims=[],  # populated by subclass/extended analysis if needed
            resolution_steps=resolution_steps,
            submission_ready=len(blocking) == 0,
            notes=notes,
        )

    def _classify(self, issue: ValIssue) -> RiskIssue:
        tier = _TIER_MAP.get(issue.code, _TIER_MAP.get(issue.category, "INFO"))
        recommendation = _RECOMMENDATIONS.get(issue.code, "")
        return RiskIssue(
            severity=issue.severity,
            code=issue.code,
            message=issue.message,
            category=issue.category,
            tier=tier,
            segment_tag=issue.segment_tag,
            segment_position=issue.segment_position,
            recommendation=recommendation,
        )

    def _build_resolution_steps(self, risk_issues: list[RiskIssue]) -> list[str]:
        steps = []
        seen_codes = set()
        for code in _RESOLUTION_ORDER:
            matching = [i for i in risk_issues if i.code == code and code not in seen_codes]
            if matching:
                steps.append(f"[{code}] {_RECOMMENDATIONS.get(code, 'Review and correct.')}")
                seen_codes.add(code)
        return steps

    def _build_notes(self, risk_issues: list[RiskIssue]) -> list[str]:
        notes = []
        if self.companion_rules_applied:
            notes.append(
                "Companion-guide / payer rule pack was applied. "
                "Issues tagged with PAYER_RULE_* reflect payer-specific requirements "
                "that go beyond standard X12 structural validation."
            )
        if any(i.code == "EMPTY_TRANSACTION" for i in risk_issues):
            notes.append(
                "Empty transactions (ST..SE with no body) will be rejected by most clearinghouses. "
                "Remove empty transactions before submission."
            )
        if any(i.code == "SE_COUNT_MISMATCH" for i in risk_issues):
            notes.append(
                "SE segment count mismatch is a common auto-rejection trigger. "
                "Verify the SE count against the actual number of segments in the transaction."
            )
        if any(i.tier == "BLOCKING" for i in risk_issues):
            notes.append(
                "Blocking issues must be resolved before submission. "
                "Files with blocking issues will be rejected automatically at the clearinghouse."
            )
        if any(i.code == "CLAIM_ID_DUPLICATE" for i in risk_issues):
            notes.append(
                "Duplicate claim IDs may be accepted as resubmissions by some payers but "
                "rejected by others. Confirm with the payer's timely filing and resubmission policy."
            )
        return notes

    # ── Output formatters ─────────────────────────────────────────────────────

    def format_text(self, summary: PreflightSummary) -> str:
        """Human-readable preflight risk report."""
        lines = []
        tier_banner = {
            "BLOCKING": "❌  BLOCKING — DO NOT SUBMIT",
            "ELEVATED": "⚠️   ELEVATED — Review before submitting",
            "WARNINGS": "⚡  WARNINGS — Likely accepted; monitor",
            "INFO": "✅  INFO — No material rejection risk",
        }.get(summary.overall_tier, summary.overall_tier)

        lines.append("=" * 64)
        lines.append("X12 PREFLIGHT REJECTION-RISK SUMMARY")
        lines.append("=" * 64)
        lines.append(f"\nOverall Risk Tier: {tier_banner}")
        lines.append(f"Submission Ready: {'✅ YES' if summary.submission_ready else '❌ NO — fix blocking issues first'}")

        if summary.total_issues == 0:
            lines.append("\n✅  No issues detected. File appears clean for submission.")
            lines.append("=" * 64)
            return "\n".join(lines)

        lines.append(f"\nIssue Breakdown:")
        if summary.blocking_count:
            lines.append(f"  ❌  Blocking:    {summary.blocking_count}")
        if summary.elevated_count:
            lines.append(f"  ⚠️   Elevated:    {summary.elevated_count}")
        if summary.warning_count:
            lines.append(f"  ⚡  Warnings:    {summary.warning_count}")
        if summary.info_count:
            lines.append(f"  ℹ️   Informational: {summary.info_count}")

        if summary.likely_rejection_codes:
            lines.append(f"\n⚠️  Auto-Rejection Risk Codes Detected:")
            for code in summary.likely_rejection_codes:
                lines.append(f"    • {code}")

        if not summary.submission_ready and summary.resolution_steps:
            lines.append(f"\nResolution Steps (in priority order):")
            for step in summary.resolution_steps:
                lines.append(f"  → {step}")

        if summary.notes:
            lines.append(f"\nContextual Notes:")
            for note in summary.notes:
                lines.append(f"  • {note}")

        lines.append("\n" + "=" * 64)
        return "\n".join(lines)

    def format_json(self, summary: PreflightSummary) -> str:
        """Machine-readable JSON preflight report."""
        import json
        # Derive a risk level consistent with validate.py's scoring
        score = min(100, (
            summary.blocking_count * 40
            + summary.elevated_count * 15
            + summary.warning_count * 5
        ))
        if score >= 70:
            risk_level = "high"
        elif score >= 30:
            risk_level = "medium"
        elif score > 0:
            risk_level = "low"
        else:
            risk_level = "minimal"
        return json.dumps(
            {
                "overall_tier": summary.overall_tier,
                "rejection_risk_score": score,
                "rejection_risk_level": risk_level,
                "submission_ready": summary.submission_ready,
                "issue_counts": {
                    "total": summary.total_issues,
                    "blocking": summary.blocking_count,
                    "elevated": summary.elevated_count,
                    "warnings": summary.warning_count,
                    "info": summary.info_count,
                },
                "likely_rejection_codes": summary.likely_rejection_codes,
                "resolution_steps": summary.resolution_steps,
                "notes": summary.notes,
            },
            indent=2,
            ensure_ascii=False,
        )
