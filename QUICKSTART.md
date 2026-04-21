# X12 Parser Quickstart

This is the shortest path from raw X12 to something you can inspect, validate, and analyze.

## 1) Install

```bash
pip install -e .
```

No third-party runtime dependencies are required.

## 2) Parse a file

```bash
python3 -m src.cli tests/fixtures/sample_835.edi
```

The JSON hierarchy is:
- `interchanges[]`
- `functional_groups[]`
- `transactions[]`
- `loops[]`
- `segments[]`

If you only want the high-level business view:

```bash
python3 -m src.cli tests/fixtures/sample_835.edi --summary
```

## 3) Validate structure and data quality

```bash
python3 -m src.validate tests/fixtures/sample_835.edi --verbose
```

Useful when you need to catch:
- envelope mismatches
- missing required segments
- duplicate claim IDs
- non-numeric amount fields
- 835 balancing/reconciliation warnings

## 4) Export for downstream analysis

### Standard flat CSV export

```bash
python3 -m src.cli tests/fixtures/sample_835_rich.edi --format csv -o out/csv
```

Writes:
- `claims_835.csv`
- `claims_837.csv`
- `service_lines.csv`
- `entities.csv`

### SQLite-ready export

```bash
python3 -m src.cli tests/fixtures/sample_835_rich.edi --format sqlite -o out/sqlite
```

Writes normalized CSVs plus `schema.sql` and `IMPORT_GUIDE.txt`.

### Analytics-native export bundle

```bash
python3 -m src.cli tests/fixtures/sample_835_rich.edi --format analytics -o out/analytics
```

Writes:
- `claims_analytics_835.csv` — enriched 835 claim facts
- `claims_analytics_837.csv` — enriched 837 claim facts
- `reconciliation_835.csv` — claim-level reconciliation status
- `service_lines_analytics.csv` — service-line facts
- `ANALYTICS_SCHEMA.json` — field/type hints for warehouse import
- `duckdb_import.sql` — starter DuckDB SQL for the emitted CSV files

These analytics exports add bounded derived fields such as:
- estimated unpaid amount
- allowed-gap amount
- CAS adjustments by group (JSON)
- payment match key (`claim_id|check_trace`)
- BPR-vs-paid balancing fields

Optional Parquet variant:

```bash
python3 -m src.cli tests/fixtures/sample_835_rich.edi --format analytics-parquet -o out/analytics_parquet
```

This currently requires `pip install -e .[parquet]` (pandas + pyarrow). The project is still CSV-first; Parquet is provided as a convenience export for DuckDB / warehouse workflows.

## 5) Reconcile an 835 against a reference claim list

Create a reference CSV with at least `claim_id`. `expected_paid` is optional but recommended.

Example:

```csv
claim_id,expected_paid
CLP001,200.00
CLP002,150.00
```

Then run:

```bash
python3 -m src.cli tests/fixtures/sample_835_rich.edi \
  --format reconcile \
  --reference-csv reference_claims.csv \
  -o out/reconcile
```

Writes:
- `reconciliation_report.csv`
- `unmatched_reference_claims.csv`
- `duplicate_suspects.csv`
- `balance_anomalies.csv`
- `summary.json`

## 6) Recommended new-user workflow

For a new file, this order works well:

1. `--summary` to see what is in the file
2. `src.validate --verbose` to catch structural/data issues
3. `--format analytics` for BI/review work
4. `--format reconcile` if you have an expected-claims list

## Notes on scope

This project is a parser and bounded structural checker. It does **not** claim full TR3 certification or full revenue-cycle posting automation. The reconciliation outputs are review aids, not accounting truth.
