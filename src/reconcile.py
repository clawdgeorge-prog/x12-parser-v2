"""835 reconciliation helpers.

This module provides a bounded reconciliation layer on top of the parser's
existing 835 summary output. It is intentionally simple and dependency-free:
reference claims are matched by claim_id and optional expected_paid amount.

It does **not** claim full ERA/AR posting parity. It produces review-friendly
outputs for analysts who want a payment register, unmatched claims, duplicate
suspects, and claim-level balancing flags.
"""
from __future__ import annotations

from dataclasses import dataclass
import csv
import json
from pathlib import Path
from typing import Any, Iterable, List

from src.parser import X12Parser


@dataclass
class ReconciliationResult:
    matched_payments: list[dict]
    unmatched_reference_claims: list[dict]
    duplicate_suspects: list[dict]
    balance_anomalies: list[dict]
    summary: dict

    def to_dict(self) -> dict:
        return {
            "matched_payments": self.matched_payments,
            "unmatched_reference_claims": self.unmatched_reference_claims,
            "duplicate_suspects": self.duplicate_suspects,
            "balance_anomalies": self.balance_anomalies,
            "summary": self.summary,
        }


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _match_reason(ref: dict, match: dict | None, variance_paid: float | None) -> str:
    """Generate human-readable reason for match result."""
    if match is None:
        claim_id = ref.get("claim_id", "")
        expected = ref.get("expected_paid")
        if expected:
            return f"No claim found with ID '{claim_id}' and amount near {expected}"
        return f"No claim found with ID '{claim_id}'"
    if variance_paid is None:
        return "Matched by claim_id only (no expected_paid in reference)"
    if abs(variance_paid) < 0.001:
        return "Exact amount match"
    if variance_paid > 0:
        return f"Matched with positive variance ({variance_paid:+.2f})"
    return f"Matched with negative variance ({variance_paid:+.2f})"


def _claim_rows_from_data(data: dict) -> list[dict]:
    rows: list[dict] = []
    for ic in data.get("interchanges", []):
        interchange_ctrl = ic.get("header", {}).get("elements", {}).get("e13", "")
        for fg in ic.get("functional_groups", []):
            for ts in fg.get("transactions", []):
                if ts.get("set_id") != "835":
                    continue
                summary = ts.get("summary", {})
                balancing = summary.get("balancing_summary", {})
                st_ctrl = ts.get("header", {}).get("elements", {}).get("e2", "")
                for claim in summary.get("claims", []):
                    row = {
                        "interchange_ctrl": interchange_ctrl,
                        "st_ctrl": st_ctrl,
                        "claim_id": claim.get("claim_id", ""),
                        "status_code": claim.get("status_code", ""),
                        "status_label": claim.get("status_label", ""),
                        "status_category": claim.get("status_category", ""),
                        "patient_name": claim.get("patient_name", ""),
                        "clp_billed": claim.get("clp_billed"),
                        "clp_allowed": claim.get("clp_allowed"),
                        "clp_paid": claim.get("clp_paid"),
                        "svc_billed": claim.get("svc_billed"),
                        "svc_paid": claim.get("svc_paid"),
                        "clp_adjustment": claim.get("clp_adjustment"),
                        "cas_adjustment_sum": claim.get("cas_adjustment_sum"),
                        "has_billed_discrepancy": bool(claim.get("has_billed_discrepancy", False)),
                        "has_paid_discrepancy": bool(claim.get("has_paid_discrepancy", False)),
                        "payer_name": summary.get("payer_name", ""),
                        "provider_name": summary.get("provider_name", ""),
                        "payment_amount": summary.get("payment_amount"),
                        "check_trace": summary.get("check_trace", ""),
                        "bpr_payment_method": summary.get("bpr_payment_method", ""),
                        "bpr_account_type": summary.get("bpr_account_type", ""),
                        "bpr_vs_paid_difference": balancing.get("bpr_vs_clp_difference"),
                        "bpr_vs_paid_balanced": balancing.get("bpr_vs_clp_balanced"),
                    }
                    rows.append(row)
    return rows


def reconcile_data(data: dict, reference_claims: Iterable[dict] | None = None, tolerance: float = 0.02) -> ReconciliationResult:
    """Reconcile parsed 835 claim rows against optional reference claims."""
    claim_rows = _claim_rows_from_data(data)
    reference_claims = list(reference_claims or [])

    matched_payments: list[dict] = []
    unmatched_reference_claims: list[dict] = []
    duplicate_suspects: list[dict] = []
    balance_anomalies: list[dict] = []

    rows_by_claim_id: dict[str, list[dict]] = {}
    for row in claim_rows:
        rows_by_claim_id.setdefault(str(row.get("claim_id", "")), []).append(row)

    for claim_id, rows in rows_by_claim_id.items():
        if len(rows) > 1:
            duplicate_suspects.append({
                "claim_id": claim_id,
                "occurrence_count": len(rows),
                "check_traces": sorted({str(r.get("check_trace", "")) for r in rows}),
                "paid_amounts": [r.get("clp_paid") for r in rows],
            })
        for row in rows:
            if row.get("has_billed_discrepancy") or row.get("has_paid_discrepancy"):
                balance_anomalies.append({
                    "claim_id": claim_id,
                    "status_code": row.get("status_code", ""),
                    "status_label": row.get("status_label", ""),
                    "clp_billed": row.get("clp_billed"),
                    "svc_billed": row.get("svc_billed"),
                    "clp_paid": row.get("clp_paid"),
                    "svc_paid": row.get("svc_paid"),
                    "check_trace": row.get("check_trace", ""),
                })

    if reference_claims:
        used_row_ids: set[int] = set()
        for ref in reference_claims:
            claim_id = str(ref.get("claim_id", "") or "")
            expected_paid = _to_float(ref.get("expected_paid"))
            candidates = rows_by_claim_id.get(claim_id, [])
            match = None
            for idx, row in enumerate(candidates):
                row_id = id(row)
                if row_id in used_row_ids:
                    continue
                if expected_paid is None:
                    match = row
                    used_row_ids.add(row_id)
                    break
                actual_paid = _to_float(row.get("clp_paid"))
                if actual_paid is not None and abs(actual_paid - expected_paid) <= tolerance:
                    match = row
                    used_row_ids.add(row_id)
                    break
            if match is None:
                unmatched = dict(ref)
                unmatched["match_reason"] = _match_reason(ref, None, None)
                unmatched_reference_claims.append(unmatched)
                continue
            variance_paid = None
            actual_paid = _to_float(match.get("clp_paid"))
            if expected_paid is not None and actual_paid is not None:
                variance_paid = round(actual_paid - expected_paid, 2)
            matched_payments.append({
                **dict(ref),
                **match,
                "variance_paid": variance_paid,
                "match_reason": _match_reason(ref, match, variance_paid),
                "matched": True,
            })
    else:
        matched_payments = [{**row, "matched": True, "variance_paid": None, "match_reason": "Included without reference matching (all claims)"} for row in claim_rows]

    total_paid = round(sum(_to_float(r.get("clp_paid")) or 0.0 for r in claim_rows), 2)
    total_billed = round(sum(_to_float(r.get("clp_billed")) or 0.0 for r in claim_rows), 2)
    summary = {
        "parsed_claim_count": len(claim_rows),
        "matched_claim_count": len(matched_payments),
        "unmatched_reference_claim_count": len(unmatched_reference_claims),
        "duplicate_suspect_count": len(duplicate_suspects),
        "balance_anomaly_count": len(balance_anomalies),
        "total_billed_amount": total_billed,
        "total_paid_amount": total_paid,
        "tolerance": tolerance,
        "reference_claim_count": len(reference_claims),
        "match_rate": round((len(matched_payments) / len(reference_claims)), 4) if reference_claims else 1.0,
    }

    return ReconciliationResult(
        matched_payments=matched_payments,
        unmatched_reference_claims=unmatched_reference_claims,
        duplicate_suspects=duplicate_suspects,
        balance_anomalies=balance_anomalies,
        summary=summary,
    )


def reconcile_from_parser(parser: X12Parser, reference_claims: Iterable[dict] | None = None, tolerance: float = 0.02) -> ReconciliationResult:
    return reconcile_data(parser.to_dict(), reference_claims=reference_claims, tolerance=tolerance)


def reconcile_from_file(edi_path: str | Path, reference_claims: Iterable[dict] | None = None, tolerance: float = 0.02) -> ReconciliationResult:
    parser = X12Parser.from_file(edi_path)
    return reconcile_from_parser(parser, reference_claims=reference_claims, tolerance=tolerance)


def read_reference_claims_csv(path: str | Path) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def write_reconciliation_bundle(result: ReconciliationResult, output_dir: str | Path) -> dict[str, int]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "reconciliation_report.csv": result.matched_payments,
        "unmatched_reference_claims.csv": result.unmatched_reference_claims,
        "duplicate_suspects.csv": result.duplicate_suspects,
        "balance_anomalies.csv": result.balance_anomalies,
    }
    counts: dict[str, int] = {}
    for filename, rows in files.items():
        rows = list(rows)
        fieldnames = sorted({key for row in rows for key in row.keys()}) if rows else ["note"]
        with open(output_dir / filename, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            if rows:
                for row in rows:
                    w.writerow(row)
        counts[filename] = len(rows)

    (output_dir / "summary.json").write_text(json.dumps(result.summary, indent=2, ensure_ascii=False))
    counts["summary.json"] = 1
    return counts
