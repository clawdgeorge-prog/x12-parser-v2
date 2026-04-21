# X12 Parser — Demo

## What this demo shows

1. **Parse** an 835 EDI file → structured JSON
2. **Validate** an 835 EDI file → structural report
3. **Explain** findings → explainable validation v2 JSON grouped by envelope level
4. **Preflight** a file → rejection-risk summary with score + weighted factors
5. **Parse** an 837 EDI file → structured JSON
6. **Validate** a clean fixture → clean pass
7. **Summarize** an 835 or 837 file → human-readable summary (money amounts, claim counts, discrepancies)
8. **Export** → CSV, NDJSON, SQLite-ready normalized bundle, or analytics bundle
9. **Reconcile** → compare 835 claims against a reference CSV

> Note: 837 Dental is included only as a bounded scaffold/demo case. Variant detection works, but dental-specific semantics are not yet deep enough to treat it as full production-grade support.

---

## Run the demo

### Recommended external sample follow-up

After running the built-in demo, these curated external/public samples are good next checks:

```bash
# External 835 sample (HDI)
python3 -m src.cli external-test-files/hdi_835_all_fields.dat --summary
python3 -m src.validate external-test-files/hdi_835_all_fields.dat

# External 837 Professional sample (HDI)
python3 -m src.cli external-test-files/hdi_837p_all_fields.dat --summary
python3 -m src.validate external-test-files/hdi_837p_all_fields.dat

# External 837 Institutional sample (HDI)
python3 -m src.cli external-test-files/hdi_837i_all_fields.dat --summary
python3 -m src.validate external-test-files/hdi_837i_all_fields.dat

# Fragment / ST-SE-only samples
python3 -m src.validate external-test-files/jobisez_sample_835.edi --mode fragment-aware
python3 -m src.validate external-test-files/hdi_837_multi_tran.dat --mode fragment-aware
```

> These external samples are useful compatibility references, not guarantees of universal payer compatibility. The external 837I sample still carries an `SE_COUNT_MISMATCH` that currently appears to be a source-file/data-quality issue rather than a parser bug. For ST/SE-only or partial-envelope files, use `--mode fragment-aware` instead of pretending they are full production interchanges.

```bash
# From the project root
./demo/run.sh
```

Or run each command individually:

```bash
# Parse 835 → JSON (compact)
python3 -m src.cli tests/fixtures/sample_835.edi --compact

# Summarize 835 → human-readable summary
python3 -m src.cli tests/fixtures/sample_835.edi --summary

# Validate 835 → structural report
python3 -m src.validate tests/fixtures/sample_835.edi

# Explain validation findings → grouped explainable validation v2 JSON
python3 -m src.validate tests/fixtures/sample_missing_ge.edi --explain

# Preflight submission risk → rejection-risk summary JSON
python3 -m src.validate tests/fixtures/sample_missing_ge.edi --preflight

# Parse 837 → JSON (compact)
python3 -m src.cli tests/fixtures/sample_837_prof.edi --compact

# Summarize 837 → human-readable summary (includes HL hierarchy)
python3 -m src.cli tests/fixtures/sample_837_prof.edi --summary

# Validate a clean fixture (strict/default mode)
python3 -m src.validate tests/fixtures/sample_whitespace_irregular.edi

# Validate a fragment sample intentionally
python3 -m src.validate external-test-files/jobisez_sample_835.edi --mode fragment-aware

# Export 835 → CSV (claims, service lines, entities)
python3 -m src.cli tests/fixtures/sample_835.edi --format csv -o extracts/

# Export 835 → NDJSON (newline-delimited JSON, one record per line)
python3 -m src.cli tests/fixtures/sample_835.edi --format ndjson

# Export 835 → SQLite bundle (normalized CSVs + schema.sql)
python3 -m src.cli tests/fixtures/sample_835.edi --format sqlite -o db_export/

# Export 835 → analytics bundle (enriched claim facts + reconciliation-ready rows)
python3 -m src.cli tests/fixtures/sample_835_rich.edi --format analytics -o analytics/

# Reconcile 835 → compare against a reference claim list
python3 -m src.cli tests/fixtures/sample_835_rich.edi --format reconcile \
  --reference-csv reference_claims.csv \
  -o reconcile/
```

---

## Sample output

### Parse 835 — key fields extracted

```
↳ Interchange sender:  SUBMITTER
↳ Interchange receiver: RECEIVER
↳ Transaction type:     835
↳ Loops found:          9
  - 3 loop(s) of kind: entity
  - 2 loop(s) of kind: service
  - 2 loop(s) of kind: claim
  - 1 loop(s) of kind: adjustment
  - 1 loop(s) of kind: payment
```

### Validate 835 — structural report

```
============================================================
X12 STRUCTURAL VALIDATION REPORT
============================================================

✅  No structural errors found.

============================================================
Result: CLEAN
============================================================
```

> This built-in fixture now serves as a clean structural demo case. For examples of public files that still produce bounded warnings or sample-quality issues, see the curated external sample docs and reports.

### Explainable validation v2 — grouped machine output

```json
{
  "schema_version": "1.0",
  "explanation_version": "2.0",
  "clean": false,
  "sections": {
    "interchange": [],
    "functional_group": [
      {
        "code": "GS_GE_MISMATCH",
        "x12_location": "file",
        "recommendation": "Each functional group must have matching GS and GE counts. Check that the GE trailer count matches the GS count."
      }
    ],
    "transaction": []
  }
}
```

### Preflight — rejection-risk summary

```json
{
  "schema_version": "1.0",
  "rejection_risk_score": 71,
  "rejection_risk_level": "high",
  "blocking_issue_count": 1,
  "top_codes": ["GS_GE_MISMATCH", "EMPTY_GROUP"]
}
```

### Parse 837 — key fields extracted

```
↳ Interchange sender:  BILLINGAGENCY
↳ Interchange receiver: PAYERBLUE
↳ Transaction type:     837
↳ Loops found:          18
  - 1 loop(s) of kind: header
  - 6 loop(s) of kind: entity
  - 1 loop(s) of kind: contact
  - 2 loop(s) of kind: hierarchy
  - 1 loop(s) of kind: reference
  - 1 loop(s) of kind: demographic
  - 1 loop(s) of kind: claim
  - 1 loop(s) of kind: diagnosis
  - 4 loop(s) of kind: service
```

### Validate clean fixture

```
============================================================
X12 STRUCTURAL VALIDATION REPORT
============================================================

✅  No structural errors found.

============================================================
Result: CLEAN
============================================================
```

### Export CSV — sample claims_835.csv output

```
claim_id,status_code,clp_billed,clp_paid,svc_billed,svc_paid,service_line_count,payer_name,provider_name,...
CLP001,?,0.00,0.00,250.00,150.00,1,INSURANCE COMPANY ONE,PROVIDER CLINIC,...
CLP002,?,0.00,0.00,150.00,120.00,1,INSURANCE COMPANY ONE,PROVIDER CLINIC,...
```

### Export NDJSON — sample records

```
{"_record_type": "interchange", "interchange_ctrl": "000000001", ...}
{"_record_type": "functional_group", "gs_version": "005010X221A1", ...}
{"_record_type": "transaction_set", "set_id": "835", "summary": {...}, ...}
{"_record_type": "loop", "loop_id": "PR", "loop_kind": "entity", ...}
```

---

## Output format — parsed JSON

The parser emits nested JSON:

```json
{
  "version": "0.2.1",
  "schema_version": "1.0",
  "interchanges": [
    {
      "header": { "tag": "ISA", "elements": { "e1": "00", ... }, "raw": "ISA*00*..." },
      "isa06_sender": "SUBMITTER",
      "isa08_receiver": "RECEIVER",
      "functional_groups": [
        {
          "header": { "tag": "GS", ... },
          "transactions": [
            {
              "header": { "tag": "ST", ... },
              "set_id": "835",
              "loops": [
                {
                  "id": "PR",
                  "leader_tag": "N1",
                  "leader_code": "PR",
                  "kind": "entity",
                  "description": "Payer Name",
                  "segments": [
                    { "tag": "N1", "elements": { "e1": "PR", "e2": "INSURANCE COMPANY ONE", ... } }
                  ]
                }
              ],
              "trailer": { "tag": "SE", ... }
            }
          ],
          "trailer": { "tag": "GE", ... }
        }
      ],
      "trailer": { "tag": "IEA", ... }
    }
  ]
}
```

Each `elements` dict maps `e{N}` (1-based) to its raw string value.

---

## Output modes reference

| Format | Flag | Output | Use case |
|--------|------|--------|----------|
| JSON (default) | `--format json` | Full nested JSON | Full structure, loop-level detail |
| NDJSON | `--format ndjson` | One JSON object per line | Streaming, log-friendly, large files |
| CSV | `--format csv -o dir/` | Flat CSV files per record type | Spreadsheet review, analytics |
| SQLite | `--format sqlite -o dir/` | Normalized CSVs + schema.sql | Database import, SQL queries |

### CSV/SQLite bundle — file inventory

| File | Description |
|------|-------------|
| `claims_835.csv` | One row per CLP loop (835 remits) |
| `claims_837.csv` | One row per CLM loop (837 claims) |
| `service_lines.csv` | One row per SVC/SV1/SV2 service line |
| `entities.csv` | One row per NM1/N1 entity (payer, provider, patient) |
| `interchanges.csv` | One row per ISA envelope |
| `functional_groups.csv` | One row per GS envelope |
| `transactions.csv` | One row per ST/SE transaction set |
| `schema.sql` | SQLite CREATE TABLE statements |
| `IMPORT_GUIDE.txt` | Quick-reference import commands |

---

## External sample notes

- `external-test-files/hdi_835_all_fields.dat` — stronger external 835 reference sample
- `external-test-files/hdi_837p_all_fields.dat` — stronger external 837 Professional reference sample
- `external-test-files/hdi_837i_all_fields.dat` — stronger external 837 Institutional reference sample
- `external-test-results/external_835_test_summary.json` — machine-generated external 835 run summary
- `external-test-results/external_837_test_summary.json` — machine-generated external 837 run summary
- `EXTERNAL_835_COMPATIBILITY_REPORT.md` — current external compatibility posture and caveats
- `EXTERNAL_SAMPLE_TAXONOMY.md` — sample classes (full-envelope vs fragment vs coverage/stress)
- `ROOT_CAUSE_ANALYSIS_EXTERNAL_SAMPLES.md` — why specific external warnings/errors are sample-driven vs tool-driven

## Pre-generated outputs

| File | Description |
|------|-------------|
| `sample_835_parsed.json` | Pre-generated compact JSON for `sample_835.edi` |
| `sample_835_validate.txt` | Validation report for `sample_835.edi` (shows error) |
| `sample_ws_validate.txt`  | Validation report for the whitespace-irregular fixture (clean) |

## Recommended first workflow

For a new user, this sequence usually gives the best signal quickly:

1. `python3 -m src.cli <file> --summary`
2. `python3 -m src.validate <file> --verbose`
3. `python3 -m src.cli <file> --format analytics -o analytics/`
4. `python3 -m src.cli <file> --format reconcile --reference-csv expected.csv -o reconcile/` (if you have an expected-claims list)
