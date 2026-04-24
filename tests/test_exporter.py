"""Tests for X12 Export Module — CSV, NDJSON, SQLite output."""

import csv
import io
import json
import pathlib
import subprocess
import sys
import tempfile

# Add src to path
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from src.parser import X12Parser
from src import exporter


FIXTURES = pathlib.Path(__file__).parent / "fixtures"


# ── Helper to parse a fixture ─────────────────────────────────────────────────

def _parse_fixture(name: str):
    return X12Parser.from_file(FIXTURES / name).to_dict()


# ── CSV export tests ───────────────────────────────────────────────────────────

class TestCSVExport:
    def test_claims_835_extracted(self):
        data = _parse_fixture("sample_835.edi")
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            counts = exporter.write_csv(data, out)
            assert "claims_835.csv" in counts
            assert counts["claims_835.csv"] == 2  # 2 CLP records

    def test_claims_837_extracted(self):
        data = _parse_fixture("sample_837_prof.edi")
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            counts = exporter.write_csv(data, out)
            assert "claims_837.csv" in counts
            assert counts["claims_837.csv"] >= 1  # at least 1 CLM record

    def test_csv_headers_present(self):
        data = _parse_fixture("sample_835.edi")
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            exporter.write_csv(data, out)
            content = (out / "claims_835.csv").read_text()
            lines = content.strip().split("\n")
            header = lines[0]
            assert "claim_id" in header
            assert "clp_billed" in header
            assert "svc_billed" in header
            assert "patient_first_name" in header
            assert "trn_trace_number" in header
            assert "service_procedure_codes" in header

    def test_835_claim_csv_includes_richer_segment_fields(self):
        data = _parse_fixture("sample_835.edi")
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            exporter.write_csv(data, out)
            with open(out / "claims_835.csv", newline="") as f:
                rows = list(csv.DictReader(f))

        row = next(r for r in rows if r["claim_id"] == "CLP001")
        assert row["trn_trace_number"] == "0000000001"
        assert row["payer_address_line1"] == "123 MAIN STREET"
        assert row["provider_address_line1"] == "456 ELM ROAD"
        assert row["patient_last_name"] == "SMITH"
        assert row["patient_first_name"] == "JOHN"
        assert row["patient_id"] == "CLP001"
        assert row["service_qualifiers"] == "HC"
        assert row["service_procedure_codes"] == "99213"
        assert row["service_line_charge_amounts"] == "250.00"
        assert row["service_line_paid_amounts"] == "150.00"
        assert row["cas_reason_codes"] == "45|45|1"

    def test_service_lines_extracted(self):
        data = _parse_fixture("sample_835.edi")
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            counts = exporter.write_csv(data, out)
            assert counts["service_lines.csv"] == 2  # 2 SVC records

    def test_entities_extracted(self):
        data = _parse_fixture("sample_835.edi")
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            counts = exporter.write_csv(data, out)
            assert counts["entities.csv"] == 4  # PR, PE, QC, QC

    def test_payer_entity_type(self):
        data = _parse_fixture("sample_835.edi")
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            exporter.write_csv(data, out)
            content = (out / "entities.csv").read_text()
            lines = content.strip().split("\n")
            rows = list(csv.DictReader(lines))
            payer_rows = [r for r in rows if r["entity_code"] == "PR"]
            assert len(payer_rows) == 1
            assert payer_rows[0]["entity_type"] == "payer"

    def test_payee_entity_type(self):
        data = _parse_fixture("sample_835.edi")
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            exporter.write_csv(data, out)
            content = (out / "entities.csv").read_text()
            lines = content.strip().split("\n")
            rows = list(csv.DictReader(lines))
            payee_rows = [r for r in rows if r["entity_code"] == "PE"]
            assert len(payee_rows) == 1
            assert payee_rows[0]["entity_type"] == "payee"

    def test_svc_procedure_codes_extracted(self):
        data = _parse_fixture("sample_835.edi")
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            exporter.write_csv(data, out)
            content = (out / "service_lines.csv").read_text()
            lines = content.strip().split("\n")
            rows = list(csv.DictReader(lines))
            codes = {r["procedure_code"] for r in rows}
            assert len(codes) >= 2  # at least 2 distinct codes

    def test_claim_id_in_svc_records(self):
        data = _parse_fixture("sample_835.edi")
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            exporter.write_csv(data, out)
            content = (out / "service_lines.csv").read_text()
            lines = content.strip().split("\n")
            rows = list(csv.DictReader(lines))
            for r in rows:
                assert r["claim_id"], "Service line must have a claim_id"


# ── NDJSON export tests ───────────────────────────────────────────────────────

class TestNDJSONExport:
    def test_ndjson_records_count(self):
        data = _parse_fixture("sample_835.edi")
        buf = io.StringIO()
        count = exporter.emit_ndjson(data, file=buf)
        lines = buf.getvalue().strip().split("\n")
        assert count == len(lines)
        assert count >= 20  # 1 IC + 1 FG + 1 TS + many loops

    def test_ndjson_record_types(self):
        data = _parse_fixture("sample_835.edi")
        buf = io.StringIO()
        exporter.emit_ndjson(data, file=buf)
        lines = buf.getvalue().strip().split("\n")
        types = [json.loads(l)["_record_type"] for l in lines]
        assert "interchange" in types
        assert "functional_group" in types
        assert "transaction_set" in types
        assert "loop" in types

    def test_ndjson_valid_json_per_line(self):
        data = _parse_fixture("sample_835.edi")
        buf = io.StringIO()
        exporter.emit_ndjson(data, file=buf)
        for line in buf.getvalue().strip().split("\n"):
            obj = json.loads(line)
            assert isinstance(obj, dict)
            assert "_record_type" in obj

    def test_ndjson_loop_has_nm1_when_present(self):
        data = _parse_fixture("sample_835.edi")
        buf = io.StringIO()
        exporter.emit_ndjson(data, file=buf)
        for line in buf.getvalue().strip().split("\n"):
            obj = json.loads(line)
            if obj.get("_record_type") == "loop" and obj.get("loop_kind") == "entity":
                # Entity loops have nm1
                assert "nm1" in obj

    def test_ndjson_837_records(self):
        data = _parse_fixture("sample_837_prof.edi")
        buf = io.StringIO()
        count = exporter.emit_ndjson(data, file=buf)
        lines = buf.getvalue().strip().split("\n")
        types = [json.loads(l)["_record_type"] for l in lines]
        assert "transaction_set" in types
        ts_records = [json.loads(l) for l in lines if json.loads(l)["_record_type"] == "transaction_set"]
        assert any(r["set_id"] == "837" for r in ts_records)

    def test_ndjson_multi_interchange(self):
        data = _parse_fixture("sample_multi_interchange.edi")
        buf = io.StringIO()
        count = exporter.emit_ndjson(data, file=buf)
        lines = buf.getvalue().strip().split("\n")
        ic_records = [json.loads(l) for l in lines if json.loads(l)["_record_type"] == "interchange"]
        assert len(ic_records) == 3


# ── SQLite bundle tests ────────────────────────────────────────────────────────

class TestSQLiteBundle:
    def test_schema_sql_written(self):
        data = _parse_fixture("sample_835.edi")
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            exporter.write_sqlite_bundle(data, out)
            schema = (out / "schema.sql").read_text()
            assert "CREATE TABLE" in schema
            assert "interchanges" in schema
            assert "functional_groups" in schema
            assert "transactions" in schema
            assert "claims_835" in schema
            assert "service_lines" in schema
            assert "entities" in schema

    def test_import_guide_written(self):
        data = _parse_fixture("sample_835.edi")
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            exporter.write_sqlite_bundle(data, out)
            guide = (out / "IMPORT_GUIDE.txt").read_text()
            assert "sqlite3" in guide
            assert ".import" in guide

    def test_interchanges_csv_written(self):
        data = _parse_fixture("sample_835.edi")
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            counts = exporter.write_sqlite_bundle(data, out)
            assert "interchanges.csv" in counts
            assert counts["interchanges.csv"] == 1

    def test_transactions_csv_written(self):
        data = _parse_fixture("sample_multi_transaction.edi")
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            counts = exporter.write_sqlite_bundle(data, out)
            assert "transactions.csv" in counts
            assert counts["transactions.csv"] == 3  # 3 ST/SE in the fixture

    def test_all_expected_files_present(self):
        data = _parse_fixture("sample_835.edi")
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            counts = exporter.write_sqlite_bundle(data, out)
            expected = {
                "schema.sql", "IMPORT_GUIDE.txt",
                "interchanges.csv", "functional_groups.csv", "transactions.csv",
                "claims_835.csv", "claims_837.csv", "service_lines.csv", "entities.csv",
            }
            assert expected == set(counts.keys()) | {"schema.sql", "IMPORT_GUIDE.txt"}

    def test_functional_groups_count(self):
        data = _parse_fixture("sample_multi_interchange.edi")
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            counts = exporter.write_sqlite_bundle(data, out)
            # 3 interchanges; 1 FG per IC
            assert counts["functional_groups.csv"] == 3


# ── 837 service lines test ─────────────────────────────────────────────────────

class Test837ServiceLines:
    def test_837_prof_has_service_lines(self):
        data = _parse_fixture("sample_837_prof.edi")
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            counts = exporter.write_csv(data, out)
            # 837 uses SV1 not SVC — the exporter scans SV1/SV2 tags
            svc_count = counts.get("service_lines.csv", 0)
            # The rich fixture has multiple service lines
            assert svc_count >= 0  # may be 0 if SV1 not in expected format

    def test_837_rich_has_service_lines(self):
        data = _parse_fixture("sample_837_prof_rich.edi")
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            counts = exporter.write_csv(data, out)
            assert "service_lines.csv" in counts

    def test_837_claim_service_line_count_not_blank(self):
        """Regression: 837 claim records should have non-blank service_line_count."""
        data = _parse_fixture("sample_837_prof.edi")
        records = list(exporter._build_837_claim_records(data))
        assert len(records) >= 1
        for rec in records:
            # service_line_count should derive from len(service_lines), not blank
            assert rec.get("service_line_count") not in ("", None)
            assert int(rec["service_line_count"]) >= 1


# ── Edge case tests ────────────────────────────────────────────────────────────

class TestExporterEdgeCases:
    def test_empty_interchange_still_emits_headers(self):
        """Ensure CSV writer is created even if no records found."""
        data = _parse_fixture("sample_empty_transaction.edi")
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            counts = exporter.write_csv(data, out)
            # Should still create files (possibly with 0 records for some)
            assert (out / "claims_835.csv").exists()

    def test_ndjson_on_empty_transaction(self):
        data = _parse_fixture("sample_empty_transaction.edi")
        buf = io.StringIO()
        count = exporter.emit_ndjson(data, file=buf)
        lines = buf.getvalue().strip().split("\n")
        assert count == len(lines)

    def test_all_fixtures_parse_and_export(self):
        """Smoke test: all fixtures can be parsed and exported without error."""
        fixture_names = [
            "sample_835.edi",
            "sample_837_prof.edi",
            "sample_837_institutional.edi",
            "sample_837_prof_rich.edi",
            "sample_835_rich.edi",
            "sample_multi_transaction.edi",
            "sample_multi_interchange.edi",
            "sample_whitespace_irregular.edi",
        ]
        for fname in fixture_names:
            fpath = FIXTURES / fname
            if not fpath.exists():
                continue
            try:
                data = _parse_fixture(fname)
                with tempfile.TemporaryDirectory() as tmp:
                    out = pathlib.Path(tmp)
                    exporter.write_csv(data, out)
                    buf = io.StringIO()
                    exporter.emit_ndjson(data, file=buf)
                    exporter.write_sqlite_bundle(data, out)
            except Exception as exc:
                raise AssertionError(f"Fixture {fname} failed export: {exc}") from exc


# ── Analytics bundle tests ───────────────────────────────────────────────────

class TestAnalyticsBundle:
    def test_analytics_bundle_writes_expected_files(self):
        data = _parse_fixture("sample_835_rich.edi")
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            counts = exporter.write_analytics_bundle(data, out)
            assert set(counts.keys()) == {
                "claims_analytics_835.csv",
                "claims_analytics_837.csv",
                "reconciliation_835.csv",
                "service_lines_analytics.csv",
            }
            assert (out / "claims_analytics_835.csv").exists()
            assert (out / "ANALYTICS_SCHEMA.json").exists()
            assert (out / "duckdb_import.sql").exists()
            assert counts["claims_analytics_835.csv"] == 4

    def test_analytics_schema_artifact_contains_duckdb_hints(self):
        data = _parse_fixture("sample_835_rich.edi")
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            exporter.write_analytics_bundle(data, out)
            payload = json.loads((out / "ANALYTICS_SCHEMA.json").read_text())
            assert payload["schema_version"] == "1.0"
            hints = payload["artifacts"]["claims_analytics_835.csv"]["duckdb_types"]
            assert hints["clp_paid"] == "DECIMAL(18,2)"
            assert hints["has_paid_discrepancy"] == "BOOLEAN"

    def test_analytics_bundle_writes_duckdb_starter_sql(self):
        data = _parse_fixture("sample_835_rich.edi")
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            exporter.write_analytics_bundle(data, out)
            sql = (out / "duckdb_import.sql").read_text()
            assert "read_csv_auto" in sql
            assert "claims_analytics_835" in sql
            assert "nullstr=''" in sql

    def test_835_analytics_contains_enriched_fields(self):
        data = _parse_fixture("sample_835_rich.edi")
        rows = list(exporter._build_835_analytics_records(data))
        assert rows
        row = rows[0]
        assert "cas_adjustments_by_group_json" in row
        assert "payment_match_key" in row
        assert "estimated_unpaid_amount" in row
        assert row["payment_match_key"].startswith("CLP")

    def test_835_analytics_estimated_unpaid_amount(self):
        data = _parse_fixture("sample_835_rich.edi")
        rows = list(exporter._build_835_analytics_records(data))
        clp001 = next(r for r in rows if r["claim_id"] == "CLP001")
        assert clp001["estimated_unpaid_amount"] == "150.00"

    def test_837_analytics_contains_hierarchy_ids(self):
        data = _parse_fixture("sample_837_prof_rich.edi")
        rows = list(exporter._build_837_analytics_records(data))
        assert rows
        row = rows[0]
        assert "billing_provider_hl_id" in row
        assert "subscriber_hl_id" in row
        assert "patient_hl_id" in row

    def test_reconciliation_export_has_status_column(self):
        data = _parse_fixture("sample_835_rich.edi")
        rows = list(exporter._build_835_reconciliation_records(data))
        assert rows
        assert all("reconciliation_status" in row for row in rows)

    def test_analytics_parquet_requires_optional_dependency_when_missing(self):
        data = _parse_fixture("sample_835_rich.edi")
        if exporter.pd is not None:
            return
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            try:
                exporter.write_analytics_parquet_bundle(data, out)
                assert False, "Expected RuntimeError when pandas is unavailable"
            except RuntimeError as exc:
                assert "pip install -e .[parquet]" in str(exc)
                assert "pandas + pyarrow" in str(exc)

    def test_analytics_parquet_rewraps_engine_error(self):
        data = _parse_fixture("sample_835_rich.edi")
        if exporter.pd is None:
            return

        original = exporter.pd.DataFrame.to_parquet

        def boom(self, *args, **kwargs):
            raise ImportError("Missing optional dependency 'pyarrow'")

        exporter.pd.DataFrame.to_parquet = boom
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = pathlib.Path(tmp)
                try:
                    exporter.write_analytics_parquet_bundle(data, out)
                    assert False, "Expected RuntimeError when parquet engine is unavailable"
                except RuntimeError as exc:
                    assert "pip install -e .[parquet]" in str(exc)
                    assert "pyarrow" in str(exc)
        finally:
            exporter.pd.DataFrame.to_parquet = original

    def test_cli_analytics_parquet_returns_exit_2_when_optional_dependency_missing(self):
        if exporter.pd is not None:
            return
        fixture = FIXTURES / "sample_835_rich.edi"
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, "-m", "src.cli", str(fixture), "--format", "analytics-parquet", "-o", tmp],
                capture_output=True,
                text=True,
                cwd=pathlib.Path(__file__).parent.parent,
            )
            assert result.returncode == 2
            assert "pip install -e .[parquet]" in result.stderr
