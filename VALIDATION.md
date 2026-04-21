# X12 Parser — Validation Report

**Date:** 2026-04-04 12:18 MDT
**Version:** 0.2.0 (docs/QA alignment pass)
**Run by:** George

## Test Suites

| Suite | Tests | Passed | Failed |
|-------|-------|--------|--------|
| `run_tests.py` | 67 | 67 | 0 |
| `pytest -q` | 136 | 136 | 0 |
| **Total** | **203** | **203** | **0** |

## Command Used

```bash
cd /Users/georgeclawd/.openclaw/agents/coder/x12-parser
find . -name __pycache__ -exec rm -rf {} +
python3 run_tests.py
python3 -m pytest -q
```

## Fixture Inventory

| Fixture | Type | Transactions | Validation |
|---------|------|-------------|------------|
| `sample_835.edi` | 835 single IC | 1 ST/SE | CLEAN |
| `sample_835_rich.edi` | 835 rich (PLB, 4 LX, PER) | 1 ST/SE | CLEAN |
| `sample_837_prof.edi` | 837 professional | 1 ST/SE | CLEAN |
| `sample_837_prof_rich.edi` | 837 professional rich (nested HL) | 1 ST/SE | CLEAN |
| `sample_837_institutional.edi` | 837 institutional | 1 ST/SE | CLEAN |
| `sample_multi_transaction.edi` | Multi-ST/SE in one GS/GE | 3 ST/SE | CLEAN |
| `sample_multi_interchange.edi` | Multi-ISA/IEA (3 interchanges) | 3 ST/SE | CLEAN |
| `sample_whitespace_irregular.edi` | Irregular CR/LF/spacing | 1 ST/SE | CLEAN |
| `sample_trailing_whitespace.edi` | Trailing spaces and blank lines | 1 ST/SE | CLEAN |
| `sample_missing_se.edi` | Wrong SE segment count (9 vs 10) | 1 ST/SE | `SE_COUNT_MISMATCH` |
| `sample_missing_ge.edi` | Missing GE segment | 1 ST/SE | `GS_GE_MISMATCH` + `EMPTY_GROUP` |
| `sample_missing_iea.edi` | Missing IEA segment | 1 ST/SE | `ISA_IEA_MISMATCH` + `SE_COUNT_MISMATCH` |
| `sample_empty_transaction.edi` | ST immediately followed by SE | 1 ST/SE | `EMPTY_TRANSACTION` |
| `sample_se_count_wrong.edi` | SE declares 20, actual 10 | 1 ST/SE | `SE_COUNT_MISMATCH` |
| `sample_orphan_body_segment.edi` | Body segment (BPR) before first GS | 1 ST/SE | `SE_COUNT_MISMATCH` (count also wrong) |

All clean fixtures produce **zero errors** from the structural validator. The validation layer is intentionally bounded: it is designed to surface common structural and data-quality issues without implying full TR3/SNIP certification.

## Structural Validation Checks (validate.py)

| Check | Severity | Description |
|-------|----------|-------------|
| `ISA_IEA_MISMATCH` | error | ISA count != IEA count |
| `GS_GE_MISMATCH` | error | GS count != GE count within an interchange |
| `ST_SE_MISMATCH` | error | ST count != SE count within a functional group |
| `EMPTY_TRANSACTION` | error | No body segments between ST and SE |
| `EMPTY_GROUP` | warning | No ST/SE pairs between GS and GE |
| `ORPHAN_ISA/IEA/GS/GE/ST/SE` | error | Segment appears outside its valid envelope |
| `UNKNOWN_SEGMENT` | warning | Segment tag not in the known-inner-tag list |
| `SE_COUNT_MISMATCH` | error | SE e1 segment count != actual segment count |
| `SE_NO_COUNT` | warning | SE missing segment-count element |
| `SE_INVALID_COUNT` | warning | SE e1 is not a parseable integer |
| `ISA_DATE_INVALID` | warning | ISA-09 (date) is < 6 chars or non-numeric |
| `ISA_TIME_INVALID` | warning | ISA-10 (time) first 4 chars not HHMM digits |
| `REQUIRED_SEGMENT_MISSING` | error | 835: BPR/TRN/N1/CLP missing; 837: BHT/NM1/CLM missing |
| `NON_NUMERIC_AMOUNT` | warning | CLP/SVC/CAS monetary element is non-numeric |
| `CLAIM_ID_DUPLICATE` | warning | CLP (835) or CLM (837) ID appears more than once in a transaction |

## Automated test coverage snapshot

Current local test run status:

- `run_tests.py`: **67 passed**
- `pytest -q`: **136 passed**
- **Total automated checks:** **203 passed**

The pytest suite covers parser behavior, validation behavior, summary generation, discrepancy detection, hierarchy rollups, duplicate claim handling, issue categorization, and bounded 837 dental detection.

## Bugs Fixed in This Pass

| # | Bug | Fix |
|---|-----|-----|
| 1 | `VALID_INNER_TAGS` had duplicate `"PLB"` and duplicate `"BPR"` entries | Deduplicated; added missing tags `LQ`, `F9`, `N2`, `G93` |
| 2 | Dead code in orphan detection section (unused `envelope_positions` / `isa_positions` block) | Removed entire dead-code block |
| 3 | SE count check could crash if trailer was missing | Added null-check guard before accessing trailer elements |
| 4 | SE_COUNT_MISMATCH message didn't include ST control number | Added `st_control` (ST e2) to the error message |
| 5 | `main()` duplicated JSON generation instead of calling `format_json()` | Refactored to use `format_json()` with `--compact` support via `separators` |
| 6 | No test coverage for validate.py behavior | Added `tests/test_validate.py` with 26 tests covering clean fixtures, error fixtures, exit codes, and JSON output |
| 7 | No transaction summaries in parser output | Added `_compute_835_summary()` and `_compute_837_summary()` with financial totals, claim counts, party names |
| 8 | No actionable guidance in validation output | Added `_ISSUE_RECOMMENDATIONS` catalog; `format_json()` includes `recommendation` per issue; `format_report()` with `--verbose` shows inline recommendations |
| 9 | No semantic field validation | Added `NON_NUMERIC_AMOUNT` (CLP/SVC/CAS), `ISA_DATE_INVALID`, `ISA_TIME_INVALID` |
| 10 | No required-segment presence check | Added `REQUIRED_SEGMENT_MISSING` per transaction type |
| 11 | No duplicate claim ID detection | Added `CLAIM_ID_DUPLICATE` for CLP (835) and CLM (837) |

## Defects Still Open (Known Limitations)

- No X12 schema validation (segment order, required elements, code values)
- No full TR3/SNIP certification or enterprise-grade conformance claims
- Loop IDs are heuristic — may not match official X12 loop nomenclature
- Non-standard delimiters (other than `*`:`:`:`~`) may cause incorrect parsing
- Composite elements returned as raw strings (e.g., `"12:345"`) — not decomposed
- `validate.py` performs bounded envelope/structural/semantic checks — not a full X12 schema validator
- 837 Dental support remains scaffolded/bounded; detection and light handling exist, but dental-specific semantics are not yet deeply modeled
- ISA date/time warnings are format-only; do not validate CCYYMMDD/HHMM semantics
