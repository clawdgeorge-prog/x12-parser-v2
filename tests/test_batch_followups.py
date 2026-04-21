import csv
import json
import pathlib
import tempfile

from src import exporter
from src.batch import build_batch_json
from src.parser import X12Parser
from src.reconcile import reconcile_data

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _doc(name: str) -> dict:
    path = FIXTURES / name
    return {**X12Parser.from_file(path).to_dict(), "source_file": path.name, "source_path": str(path)}


def test_analytics_batch_includes_source_columns():
    batch = build_batch_json([_doc("sample_835.edi"), _doc("sample_837_prof.edi")], [])
    with tempfile.TemporaryDirectory() as tmp:
        out = pathlib.Path(tmp)
        counts = exporter.write_analytics_bundle(batch, out)
        assert "claims_analytics_835.csv" in counts
        with open(out / "claims_analytics_835.csv", newline="") as f:
            rows = list(csv.DictReader(f))
        assert rows
        assert "source_file" in rows[0]
        assert any(r["source_file"] == "sample_835.edi" for r in rows)


def test_reconcile_batch_carries_source_lineage_and_summary():
    batch = build_batch_json([_doc("sample_835.edi"), _doc("sample_835_balancing.edi")], [])
    result = reconcile_data(batch)
    payload = result.to_dict()
    assert payload["matched_payments"]
    assert "source_file" in payload["matched_payments"][0]
    assert payload["summary"]["parsed_file_count"] == 2


def test_reconcile_bundle_writes_batch_summary_file_count(tmp_path):
    batch = build_batch_json([_doc("sample_835.edi"), _doc("sample_835_balancing.edi")], [])
    result = reconcile_data(batch)
    from src.reconcile import write_reconciliation_bundle
    write_reconciliation_bundle(result, tmp_path)
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["parsed_file_count"] == 2
