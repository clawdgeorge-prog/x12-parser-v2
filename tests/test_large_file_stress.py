"""
Large file stress tests for X12 parser and exporters.

These tests verify that the parser and export pipeline handle large EDI files
(1000+ claims) without crashing, excessive memory consumption, or performance
degradation.

NOTE on 835 service_line_count in summary:
  The summary's service_line_count may show 0 even when SVC segments are present
  in the file. This happens when SVC segments are grouped inside DTM-led loops
  (DTM*001*SVC) rather than as SVC-led loops. The _compute_835_summary only
  counts loops with leader_tag == 'SVC'. The exporter's _walk_loops_for_svc
  correctly finds all SVC segments by searching all loops, so exported
  service_lines.csv is accurate regardless.
"""

from __future__ import annotations

import json
import os
import pathlib
import random
import shutil
import sys
import tempfile
import time
import tracemalloc
import gc

import pytest

# Ensure local src is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.parser import X12Parser, parse
from src.exporter import write_csv, write_sqlite_bundle, emit_ndjson, write_analytics_bundle


# ── Test fixture data ────────────────────────────────────────────────────────────

SCRIPT_DIR = pathlib.Path(__file__).parent.parent / "scripts"
LARGE_835_PATH = pathlib.Path(__file__).parent / "fixtures" / "large_835_1000claims.edi"

# Reusable PRNG so we can deterministically recreate the same EDI content
rng = random.Random(42)

PROCEDURE_CODES = [
    "99213", "99214", "99215", "99203", "99204", "99205",
    "99281", "99282", "99283", "99284", "99285",
    "90834", "90837", "90847",
    "99495", "99496", "99497", "99498",
    "36415", "81000", "85025", "80053",
    "27130", "27447", "29825",
]
REASON_CODES = ["CO", "PR", "PI", "AO", "WO", "CV", "DISC"]
PAYER_NAMES = ["BLUE CROSS BLUE SHIELD", "AETNA LIFE INSURANCE",
               "UNITED HEALTHCARE", "CIGNA HEALTH", "MEDICARE PART B"]
PROVIDER_NAMES = ["CITY HOSPITAL", "MEDICAL ASSOCIATES CLINIC",
                  "URGENT CARE CENTER", "SPECIALTY PHYSICIANS GROUP"]
LAST_NAMES = ["SMITH", "JOHNSON", "WILLIAMS", "BROWN", "JONES", "GARCIA",
              "MILLER", "DAVIS", "RODRIGUEZ", "MARTINEZ", "ANDERSON", "TAYLOR"]
FIRST_NAMES = ["JAMES", "MARY", "JOHN", "PATRICIA", "ROBERT", "JENNIFER",
               "MICHAEL", "LINDA", "WILLIAM", "ELIZABETH", "DAVID", "BARBARA"]


def rnd_choice(seq):
    return rng.choice(seq)


def rnd_int(a, b):
    return rng.randint(a, b)


def _build_segment(tag, *elements):
    return f"{tag}*{'*'.join(str(e) for e in elements)}~"


def _generate_one_claim(claim_num, n_svc, payer_name, provider_name):
    """Return list of EDI segment strings for one claim."""
    claim_id = f"CLM{claim_num:06d}"
    status = rng.choice(["1", "2", "3", "4", "19", "20", "21"])
    patient_last = rnd_choice(LAST_NAMES)
    patient_first = rnd_choice(FIRST_NAMES)

    svc_billed_total = 0.0
    svc_paid_total = 0.0
    svc_lines = []
    for _ in range(n_svc):
        proc = rnd_choice(PROCEDURE_CODES)
        billed = float(rnd_int(50, 500))
        paid = billed * rng.uniform(0.5, 0.95)
        svc_billed_total += billed
        svc_paid_total += paid
        svc_lines.append((proc, billed, paid))

    clp_billed = svc_billed_total
    clp_paid = svc_paid_total
    patient_resp = clp_billed - clp_paid

    segs = []
    segs.append(_build_segment("LX", 1))
    segs.append(_build_segment("CLP", claim_id, status, clp_billed, clp_paid, patient_resp, "", "", "CL", "12", "345"))
    if patient_resp > 0.01:
        cas_amount = patient_resp * rng.uniform(0.3, 0.7)
        segs.append(_build_segment("CAS", "CO", rnd_choice(["45", "1", "2"]), cas_amount))
        remaining = patient_resp - cas_amount
        if remaining > 0.01:
            segs.append(_build_segment("CAS", "PR", "1", remaining))
    segs.append(_build_segment("NM1", "QC", "1", patient_last, patient_first, "", "", "", "34", claim_id))
    segs.append(_build_segment("DTM", "001", "20250412"))
    for proc, billed, paid in svc_lines:
        segs.append(_build_segment("SVC", f"HC:{proc}", billed, paid, "", "", "1"))
        segs.append(_build_segment("DTP", "001", "20250412"))
    return segs


def _generate_large_835(n_claims, n_svc_per_claim):
    """Build a complete 835 EDI string."""
    payer_name = rnd_choice(PAYER_NAMES)
    provider_name = rnd_choice(PROVIDER_NAMES)
    check_num = 1000000000

    lines = []
    lines.append("ISA*00*          *00*          *ZZ*SUBMITTER     *ZZ*RECEIVER      *250413*1522*^*00501*000000001*0*P*:~")
    lines.append("GS*HP*SUBMITTER*RECEIVER*20250413*1522*1*X*005010X221A1~")
    lines.append("ST*835*0001*005010X221A1~")

    total_payment = 0.0
    claim_seg_counts = []
    for i in range(1, n_claims + 1):
        segs = _generate_one_claim(i, n_svc_per_claim, payer_name, provider_name)
        for seg in segs:
            lines.append(seg)
        claim_seg_counts.append(len(segs))
        total_payment += 100.0 + rng.uniform(0, 400)

    # BPR uses total of individual payments (not accounting formula)
    lines.append(_build_segment("BPR", "H", total_payment, "C", "ACH", "CTX", "01", "012345678", "DA", "1234567890", "0", "", "", "ACH", "CC", "0123456789"))
    lines.append(_build_segment("TRN", "1", f"{check_num:010d}", "0123456789"))
    lines.append(_build_segment("DTM", "001", "20250413"))
    lines.append(_build_segment("N1", "PR", payer_name, "PI", "123456789"))
    lines.append("N3*123 MAIN STREET~")
    lines.append("N4*CITY*ST*12345~")
    lines.append(_build_segment("REF", "2U", "123456789"))
    lines.append(_build_segment("N1", "PE", provider_name, "XX", "987654321"))
    lines.append("N3*456 ELM ROAD~")
    lines.append("N4*TOWN*ST*67890~")
    lines.append(_build_segment("PER", "IC", "JOHN DOE", "TE", "8005551234"))

    extra_header_segs = 12
    seg_count = sum(claim_seg_counts) + extra_header_segs
    lines.append(_build_segment("SE", seg_count, "0001"))
    lines.append("GE*1*1~")
    lines.append("IEA*1*000000001~")
    return "\n".join(lines) + "\n"


@pytest.fixture(scope="module")
def large_835_edi():
    """Return the path to the large_835_1000claims.edi fixture, creating it if needed."""
    if LARGE_835_PATH.exists():
        return LARGE_835_PATH

    # Generate deterministically
    content = _generate_large_835(1000, 3)
    LARGE_835_PATH.parent.mkdir(parents=True, exist_ok=True)
    LARGE_835_PATH.write_text(content, encoding="utf-8")
    return LARGE_835_PATH


@pytest.fixture(scope="module")
def large_835_parsed(large_835_edi):
    """Parse the large fixture once and cache the result for all tests."""
    parser = X12Parser.from_file(str(large_835_edi))
    return parser.to_dict()


@pytest.fixture(scope="module")
def large_835_size(large_835_edi):
    return large_835_edi.stat().st_size


# ── Parser stress tests ─────────────────────────────────────────────────────────

class TestLargeFileParsing:
    """Stress tests for parsing large EDI files."""

    def test_large_file_no_crash(self, large_835_edi):
        """Verify the parser does not crash on a 1000-claim 835 file."""
        parser = X12Parser.from_file(str(large_835_edi))
        data = parser.to_dict()
        assert data is not None

    def test_large_file_correct_claim_count(self, large_835_parsed):
        """Verify exactly 1000 claims were parsed."""
        ic_count = len(large_835_parsed["interchanges"])
        assert ic_count == 1, f"Expected 1 interchange, got {ic_count}"

        total_claims = 0
        for ic in large_835_parsed["interchanges"]:
            for fg in ic["functional_groups"]:
                for ts in fg["transactions"]:
                    total_claims += ts["summary"].get("claim_count", 0)
        assert total_claims == 1000, f"Expected 1000 claims, got {total_claims}"

    def test_large_file_total_svc_lines(self, large_835_parsed):
        """Verify exactly 3000 service lines were exported (1000 claims × 3)."""
        total_svc = 0
        for ic in large_835_parsed["interchanges"]:
            for fg in ic["functional_groups"]:
                for ts in fg["transactions"]:
                    for loop in ts["loops"]:
                        total_svc += sum(1 for s in loop["segments"] if s["tag"] == "SVC")
        assert total_svc == 3000, f"Expected 3000 SVC segments, got {total_svc}"

    def test_large_file_financial_totals_nonzero(self, large_835_parsed):
        """Verify the summary computed non-zero financial totals."""
        for ic in large_835_parsed["interchanges"]:
            for fg in ic["functional_groups"]:
                for ts in fg["transactions"]:
                    s = ts["summary"]
                    assert s["total_billed_amount"] > 0, "total_billed should be > 0"
                    assert s["total_paid_amount"] > 0, "total_paid should be > 0"
                    assert s["claim_count"] == 1000

    def test_large_file_loop_and_segment_counts(self, large_835_parsed):
        """Verify expected loop and segment counts for a 1000-claim file."""
        total_loops = 0
        total_segs = 0
        for ic in large_835_parsed["interchanges"]:
            for fg in ic["functional_groups"]:
                for ts in fg["transactions"]:
                    total_loops += len(ts["loops"])
                    total_segs += sum(len(l["segments"]) for l in ts["loops"])
        # With 1000 claims × 3 svc lines + 1 LX each + CAS + NM1 + DTM = 6007 loops
        assert total_loops > 5000, f"Expected > 5000 loops, got {total_loops}"
        assert total_segs > 10000, f"Expected > 10000 segments, got {total_segs}"

    def test_large_file_memory_under_100mb(self, large_835_edi):
        """Parse the large file and verify peak memory stays under 100 MB."""
        gc.collect()
        tracemalloc.start()
        try:
            parser = X12Parser.from_file(str(large_835_edi))
            data = parser.to_dict()
            assert data is not None
            _, peak = tracemalloc.get_traced_memory()
            peak_mb = peak / 1024 / 1024
            assert peak_mb < 100, f"Peak memory {peak_mb:.1f} MB exceeds 100 MB limit"
        finally:
            tracemalloc.stop()

    def test_large_file_parse_time_under_30s(self, large_835_edi):
        """Verify parsing completes in under 30 seconds."""
        t0 = time.perf_counter()
        parser = X12Parser.from_file(str(large_835_edi))
        data = parser.to_dict()
        elapsed = time.perf_counter() - t0
        assert data is not None
        assert elapsed < 30, f"Parse took {elapsed:.1f}s, exceeds 30s limit"


# ── Exporter stress tests ───────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def _tmp_export_dir():
    """Shared temporary directory for export tests, cleaned up after all tests."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="x12_stress_"))
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


class TestLargeFileCsvExport:
    """Stress tests for CSV export of large parsed files."""

    def test_csv_export_no_crash(self, large_835_parsed, _tmp_export_dir):
        """Verify write_csv does not crash on large parsed data."""
        counts = write_csv(large_835_parsed, _tmp_export_dir / "csv")
        assert counts is not None
        assert len(counts) == 4  # claims_835, claims_837, service_lines, entities

    def test_csv_claims_count(self, large_835_parsed, _tmp_export_dir):
        """Verify exactly 1000 claim rows were written."""
        write_csv(large_835_parsed, _tmp_export_dir / "csv2")
        path = _tmp_export_dir / "csv2" / "claims_835.csv"
        with open(path) as f:
            rows = sum(1 for _ in f) - 1  # subtract header
        assert rows == 1000, f"Expected 1000 claim rows, got {rows}"

    def test_csv_service_lines_count(self, large_835_parsed, _tmp_export_dir):
        """Verify exactly 3000 service line rows were written."""
        write_csv(large_835_parsed, _tmp_export_dir / "csv3")
        path = _tmp_export_dir / "csv3" / "service_lines.csv"
        with open(path) as f:
            rows = sum(1 for _ in f) - 1
        assert rows == 3000, f"Expected 3000 svc rows, got {rows}"

    def test_csv_export_time_under_5s(self, large_835_parsed, _tmp_export_dir):
        """Verify CSV export completes in under 5 seconds."""
        gc.collect()
        t0 = time.perf_counter()
        write_csv(large_835_parsed, _tmp_export_dir / "csv4")
        elapsed = time.perf_counter() - t0
        assert elapsed < 5, f"CSV export took {elapsed:.1f}s, exceeds 5s limit"


class TestLargeFileSqliteExport:
    """Stress tests for SQLite bundle export of large parsed files."""

    def test_sqlite_export_no_crash(self, large_835_parsed, _tmp_export_dir):
        """Verify write_sqlite_bundle does not crash on large parsed data."""
        counts = write_sqlite_bundle(large_835_parsed, _tmp_export_dir / "sqlite")
        assert counts is not None

    def test_sqlite_claims_count(self, large_835_parsed, _tmp_export_dir):
        """Verify exactly 1000 claim rows in SQLite bundle."""
        write_sqlite_bundle(large_835_parsed, _tmp_export_dir / "sqlite2")
        path = _tmp_export_dir / "sqlite2" / "claims_835.csv"
        with open(path) as f:
            rows = sum(1 for _ in f) - 1
        assert rows == 1000, f"Expected 1000 claim rows, got {rows}"

    def test_sqlite_service_lines_count(self, large_835_parsed, _tmp_export_dir):
        """Verify exactly 3000 service line rows in SQLite bundle."""
        write_sqlite_bundle(large_835_parsed, _tmp_export_dir / "sqlite3")
        path = _tmp_export_dir / "sqlite3" / "service_lines.csv"
        with open(path) as f:
            rows = sum(1 for _ in f) - 1
        assert rows == 3000, f"Expected 3000 svc rows, got {rows}"

    def test_sqlite_bundle_has_schema(self, large_835_parsed, _tmp_export_dir):
        """Verify the schema.sql file was written."""
        write_sqlite_bundle(large_835_parsed, _tmp_export_dir / "sqlite4")
        schema_path = _tmp_export_dir / "sqlite4" / "schema.sql"
        assert schema_path.exists(), "schema.sql not found in SQLite bundle"
        content = schema_path.read_text()
        assert "CREATE TABLE" in content
        assert "interchanges" in content
        assert "claims_835" in content

    def test_sqlite_export_time_under_5s(self, large_835_parsed, _tmp_export_dir):
        """Verify SQLite bundle export completes in under 5 seconds."""
        gc.collect()
        t0 = time.perf_counter()
        write_sqlite_bundle(large_835_parsed, _tmp_export_dir / "sqlite5")
        elapsed = time.perf_counter() - t0
        assert elapsed < 5, f"SQLite export took {elapsed:.1f}s, exceeds 5s limit"


class TestLargeFileNdjsonExport:
    """Stress tests for NDJSON export of large parsed files."""

    def test_ndjson_export_no_crash(self, large_835_parsed, _tmp_export_dir):
        """Verify emit_ndjson does not crash on large parsed data."""
        path = _tmp_export_dir / "large.ndjson"
        with open(path, "w") as f:
            count = emit_ndjson(large_835_parsed, f)
        assert count > 0

    def test_ndjson_record_count(self, large_835_parsed, _tmp_export_dir):
        """Verify NDJSON emits one record per interchange + group + transaction + loop."""
        path = _tmp_export_dir / "large2.ndjson"
        with open(path, "w") as f:
            count = emit_ndjson(large_835_parsed, f)
        # 1 interchange + 1 functional group + 1 transaction + 6007 loops = 6010
        assert count == 6010, f"Expected 6010 NDJSON records, got {count}"

    def test_ndjson_export_time_under_5s(self, large_835_parsed, _tmp_export_dir):
        """Verify NDJSON export completes in under 5 seconds."""
        gc.collect()
        t0 = time.perf_counter()
        path = _tmp_export_dir / "large3.ndjson"
        with open(path, "w") as f:
            emit_ndjson(large_835_parsed, f)
        elapsed = time.perf_counter() - t0
        assert elapsed < 5, f"NDJSON export took {elapsed:.1f}s, exceeds 5s limit"


class TestLargeFileAnalyticsExport:
    """Stress tests for analytics bundle export of large parsed files."""

    def test_analytics_export_no_crash(self, large_835_parsed, _tmp_export_dir):
        """Verify write_analytics_bundle does not crash."""
        counts = write_analytics_bundle(large_835_parsed, _tmp_export_dir / "analytics")
        assert counts is not None

    def test_analytics_claims_count(self, large_835_parsed, _tmp_export_dir):
        """Verify analytics bundle writes 1000 claim records."""
        counts = write_analytics_bundle(large_835_parsed, _tmp_export_dir / "analytics2")
        assert counts.get("claims_analytics_835.csv", 0) == 1000

    def test_analytics_reconciliation_count(self, large_835_parsed, _tmp_export_dir):
        """Verify reconciliation extract has 1000 rows."""
        write_analytics_bundle(large_835_parsed, _tmp_export_dir / "analytics3")
        path = _tmp_export_dir / "analytics3" / "reconciliation_835.csv"
        with open(path) as f:
            rows = sum(1 for _ in f) - 1
        assert rows == 1000

    def test_analytics_export_time_under_10s(self, large_835_parsed, _tmp_export_dir):
        """Verify analytics export completes in under 10 seconds."""
        gc.collect()
        t0 = time.perf_counter()
        write_analytics_bundle(large_835_parsed, _tmp_export_dir / "analytics4")
        elapsed = time.perf_counter() - t0
        assert elapsed < 10, f"Analytics export took {elapsed:.1f}s, exceeds 10s limit"


# ── Performance regression baseline ────────────────────────────────────────────

class TestPerformanceRegression:
    """Performance measurements for the large-file fixture to detect regressions."""

    @pytest.fixture(scope="class")
    def _perf_results(self, large_835_edi):
        gc.collect()
        tracemalloc.start()
        t0 = time.perf_counter()
        parser = X12Parser.from_file(str(large_835_edi))
        data = parser.to_dict()
        parse_time = time.perf_counter() - t0
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return {"parse_time": parse_time, "peak_mb": peak / 1024 / 1024}

    def test_parse_time_baseline(self, _perf_results):
        """Document baseline parse time. Fails if > 30s."""
        assert _perf_results["parse_time"] < 30

    def test_peak_memory_baseline(self, _perf_results):
        """Document baseline peak memory. Fails if > 100 MB."""
        assert _perf_results["peak_mb"] < 100
