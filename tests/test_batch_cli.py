import csv
import json
import pathlib
import subprocess
import sys

from src import exporter
from src.batch import build_batch_json, discover_input_files, parse_inputs
from src.parser import X12Parser

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
REPO_ROOT = pathlib.Path(__file__).parent.parent


def _doc(name: str) -> dict:
    path = FIXTURES / name
    return {**X12Parser.from_file(path).to_dict(), "source_file": path.name, "source_path": str(path)}


def test_discover_input_files_directory():
    files = discover_input_files(FIXTURES)
    names = {p.name for p in files}
    assert "sample_835.edi" in names
    assert "sample_837_prof.edi" in names


def test_parse_inputs_collects_documents():
    docs, failures = parse_inputs([FIXTURES / "sample_835.edi", FIXTURES / "sample_837_prof.edi"])
    assert len(docs) == 2
    assert failures == []
    assert docs[0]["source_file"].endswith(".edi")


def test_write_csv_batch_aggregates_rows(tmp_path):
    batch = build_batch_json([_doc("sample_835.edi"), _doc("sample_837_prof.edi")], [])
    counts = exporter.write_csv(batch, tmp_path)
    assert counts["claims_835.csv"] == 2
    assert counts["claims_837.csv"] >= 1

    with open(tmp_path / "claims_835.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    assert all(row["source_file"] for row in rows)
    assert any(row["source_file"] == "sample_835.edi" for row in rows)

    summary = json.loads((tmp_path / "batch_summary.json").read_text())
    assert summary["files_parsed"] == 2


def test_write_sqlite_bundle_batch_aggregates_rows(tmp_path):
    batch = build_batch_json([_doc("sample_835.edi"), _doc("sample_837_prof.edi")], [])
    counts = exporter.write_sqlite_bundle(batch, tmp_path)
    assert counts["interchanges.csv"] == 2
    assert counts["transactions.csv"] >= 2

    with open(tmp_path / "transactions.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    assert all(row["source_file"] for row in rows)


def test_cli_csv_directory_mode(tmp_path):
    out_dir = tmp_path / "csv_out"
    result = subprocess.run(
        [sys.executable, "-m", "src.cli", str(FIXTURES), "--format", "csv", "-o", str(out_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "claims_835.csv" in result.stdout
    assert (out_dir / "claims_835.csv").exists()
    assert (out_dir / "batch_summary.json").exists()


def test_cli_sqlite_directory_mode(tmp_path):
    out_dir = tmp_path / "sqlite_out"
    result = subprocess.run(
        [sys.executable, "-m", "src.cli", str(FIXTURES), "--format", "sqlite", "-o", str(out_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "transactions.csv" in result.stdout
    assert (out_dir / "schema.sql").exists()
    with open(out_dir / "interchanges.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) >= 2
    assert "source_file" in rows[0]
