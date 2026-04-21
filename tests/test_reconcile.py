"""Tests for 835 reconciliation helpers."""

import csv
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from src.reconcile import (
    read_reference_claims_csv,
    reconcile_data,
    reconcile_from_file,
    write_reconciliation_bundle,
)
from src.parser import X12Parser


FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _reference_claims(*rows):
    return list(rows)


class TestReconcile:
    def test_reconcile_without_reference_returns_all_claims(self):
        data = X12Parser.from_file(FIXTURES / "sample_835_rich.edi").to_dict()
        result = reconcile_data(data)
        assert result.summary["parsed_claim_count"] == 4
        assert result.summary["matched_claim_count"] == 4
        assert len(result.matched_payments) == 4

    def test_reconcile_matches_reference_by_claim_id_and_paid_amount(self):
        result = reconcile_from_file(
            FIXTURES / "sample_835_rich.edi",
            reference_claims=_reference_claims(
                {"claim_id": "CLP001", "expected_paid": "200.00"},
                {"claim_id": "CLP003", "expected_paid": "175.00"},
            ),
        )
        assert result.summary["matched_claim_count"] == 2
        assert result.summary["unmatched_reference_claim_count"] == 0
        # Verify match_reason is populated
        reasons = [m["match_reason"] for m in result.matched_payments]
        assert any("Exact amount match" in r for r in reasons)

    def test_reconcile_match_reason_includes_variance(self):
        result = reconcile_from_file(
            FIXTURES / "sample_835_rich.edi",
            reference_claims=_reference_claims(
                {"claim_id": "CLP001", "expected_paid": "200.01"},
            ),
            tolerance=0.02,
        )
        assert result.summary["matched_claim_count"] == 1
        # Variance is -0.01 (paid 200.00 - expected 200.01)
        assert "negative variance" in result.matched_payments[0]["match_reason"]

    def test_reconcile_unmatched_claim_includes_reason(self):
        result = reconcile_from_file(
            FIXTURES / "sample_835_rich.edi",
            reference_claims=_reference_claims({"claim_id": "MISSING-1", "expected_paid": "10.00"}),
        )
        assert len(result.unmatched_reference_claims) == 1
        assert "No claim found with ID 'MISSING-1'" in result.unmatched_reference_claims[0].get("match_reason", "")

    def test_reconcile_includes_all_claims_without_reference(self):
        result = reconcile_from_file(FIXTURES / "sample_835_rich.edi")
        assert len(result.matched_payments) == 4
        # All should have the "included without reference matching" reason
        for m in result.matched_payments:
            assert "Included without reference matching" in m["match_reason"]

    def test_reconcile_unmatched_reference_claim_is_reported(self):
        result = reconcile_from_file(
            FIXTURES / "sample_835_rich.edi",
            reference_claims=_reference_claims({"claim_id": "MISSING-1", "expected_paid": "10.00"}),
        )
        assert result.summary["matched_claim_count"] == 0
        assert result.summary["unmatched_reference_claim_count"] == 1
        assert result.unmatched_reference_claims[0]["claim_id"] == "MISSING-1"

    def test_reconcile_tolerance_allows_small_paid_variance(self):
        result = reconcile_from_file(
            FIXTURES / "sample_835_rich.edi",
            reference_claims=_reference_claims({"claim_id": "CLP001", "expected_paid": "200.01"}),
            tolerance=0.02,
        )
        assert result.summary["matched_claim_count"] == 1
        assert result.matched_payments[0]["variance_paid"] == -0.01

    def test_reconcile_detects_balance_anomalies(self):
        data = X12Parser.from_file(FIXTURES / "sample_835_discrepancy.edi").to_dict()
        result = reconcile_data(data)
        assert result.summary["balance_anomaly_count"] >= 1
        assert result.balance_anomalies

    def test_reconciliation_bundle_written(self):
        data = X12Parser.from_file(FIXTURES / "sample_835_rich.edi").to_dict()
        result = reconcile_data(data)
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            counts = write_reconciliation_bundle(result, out)
            assert (out / "reconciliation_report.csv").exists()
            assert (out / "summary.json").exists()
            assert counts["reconciliation_report.csv"] == 4

    def test_reference_claims_csv_reader(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "reference.csv"
            with open(path, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["claim_id", "expected_paid"])
                w.writeheader()
                w.writerow({"claim_id": "CLP001", "expected_paid": "200.00"})
            rows = read_reference_claims_csv(path)
            assert rows[0]["claim_id"] == "CLP001"
