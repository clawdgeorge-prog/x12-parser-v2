# X12 Parser Workflows Guide

This guide explains what the newer workflow-oriented features do, when to use them, and how they change day-to-day operations.

## Who this is for

Use this guide if you are:
- onboarding to the parser for the first time
- triaging messy payer or clearinghouse files
- reviewing 835 remittances for reconciliation issues
- preparing 837s for submission
- exporting parsed data into SQL, BI, QA, or AI workflows

---

## 1. Explainable validation v2

### What it does
Explainable validation turns raw structural findings into grouped, machine-readable, human-usable guidance.

Instead of only returning issue codes, it adds:
- stable contract metadata
- issue grouping by envelope level
- `x12_location` fields so you can find the exact area of the file
- clearer recommendations for what to fix next

### Best used for
- QA review
- CI checks
- analyst handoff
- support tickets where a human needs to understand *why* a file is bad

### Command

```bash
python3 -m src.validate file.edi --explain
```

### Workflow value
This is the best first stop when someone says:
- “Why did this fail?”
- “Is this a transaction problem or an envelope problem?”
- “What should I fix first?”

---

## 2. Preflight / rejection-risk summary

### What it does
Preflight converts validation results into a bounded submission-readiness signal.

It adds:
- `rejection_risk_score`
- `rejection_risk_level`
- blocking vs warning counts
- top issue codes
- weighted factors behind the score

### Best used for
- pre-submission review
- operational triage
- routing files into “submit / fix / review” queues

### Command

```bash
python3 -m src.validate file.edi --preflight
```

### Workflow value
This is useful when the real question is not just “is the file valid?” but:
- “Should we submit this?”
- “Will this likely get rejected?”
- “What are the biggest rejection risks?”

---

## 3. Forensic mode

### What it does
Forensic mode is for ugly, partial, or suspicious files.

It produces:
- claim-level segment journey traces
- entity snapshots
- unusual pattern flags
- missing-expected-segment observations
- a human-readable research/debugging report

### Best used for
- malformed or partial public samples
- trading-partner troubleshooting
- payer-specific weirdness
- root-cause analysis after a failed exchange

### Command

```bash
python3 -m src.validate file.edi --forensic
```

### Workflow value
This helps when a normal parser error is not enough.
It is designed for questions like:
- “What is actually in this broken file?”
- “Is this a fragment, a malformed file, or a real parser problem?”
- “Where does the claim go off the rails?”

---

## 4. Transparent payer-rule traces

### What it does
Rule tracing shows how a companion-guide / payer-rule pack was evaluated.

It shows:
- each rule checked
- what segment/element was inspected
- what value was found
- whether the rule matched

### Best used for
- auditing payer-specific rule behavior
- debugging rule packs
- explaining why a trading-partner rule fired

### Command

```bash
python3 -m src.validate file.edi \
  --rules examples/rules/premier-835-companion.sample.json \
  --rules-trace
```

### Workflow value
This turns payer validation from a black box into something inspectable.
That matters when teams need confidence that:
- the rule pack is behaving correctly
- the file really violates the companion guide
- a warning is coming from payer logic, not core X12 structure

---

## 5. Analytics-native exports

### What they do
Analytics exports turn parsed X12 into review-friendly fact tables.

Current bundle outputs include:
- `claims_analytics_835.csv`
- `claims_analytics_837.csv`
- `reconciliation_835.csv`
- `service_lines_analytics.csv`
- `ANALYTICS_SCHEMA.json`
- `duckdb_import.sql`

### Best used for
- SQL / DuckDB / BI analysis
- payment review
- QA dashboards
- anomaly detection
- downstream AI summarization over structured facts

### Command

```bash
python3 -m src.cli file.edi --format analytics -o out/analytics
```

Optional Parquet convenience export:

```bash
python3 -m src.cli file.edi --format analytics-parquet -o out/analytics_parquet
```

That Parquet mode is intentionally optional and dependency-gated. This repo does **not** claim full native DuckDB support; it emits warehouse-friendly CSVs plus starter artifacts that DuckDB can read directly.

### Workflow value
This is the bridge from parser output to analyst workflow.
Use it when the next question is:
- “Can I query this?”
- “Can I compare claims at scale?”
- “Can I load this into a dashboard?”

---

## 6. 835 reconciliation bundle

### What it does
The reconciliation bundle compares parsed 835 claims against an optional reference claim list.

It writes:
- matched payments
- unmatched reference claims
- duplicate suspects
- balance anomalies
- summary metrics

### Best used for
- payment review
- expected-vs-actual checks
- light-weight analyst reconciliation
- spotting anomalies before manual posting review

### Command

```bash
python3 -m src.cli file.edi \
  --format reconcile \
  --reference-csv expected_claims.csv \
  -o out/reconcile
```

Reference CSV should include:
- `claim_id`
- optional `expected_paid`

### Workflow value
This helps answer:
- “Did this remit pay what we expected?”
- “Which claims did not match?”
- “Which ones deserve manual review first?”

This is intentionally bounded and review-oriented — not full ERA posting automation.

---

## 7. Stable output contracts

### What they do
Stable output contracts make parser and validator results safer to embed in other tools.

Current contract markers include:
- parser output: `schema_version: "1.0"`
- validation output: `schema_version: "1.0"`
- explainable validation: `explanation_version: "2.0"`

### Best used for
- automation
- downstream apps
- dashboards
- integration tests
- AI tooling that expects stable field names

### Workflow value
This matters when the parser becomes infrastructure rather than a one-off tool.
It reduces breakage in:
- scripts
- ETL jobs
- review apps
- CI checks
- external consumers

---

## Recommended real-world workflow order

For a new file, this sequence usually works best:

1. **Summary**
   ```bash
   python3 -m src.cli file.edi --summary
   ```
   Use to quickly understand what kind of file you have.

2. **Explainable validation**
   ```bash
   python3 -m src.validate file.edi --explain
   ```
   Use to see the main issues and where they live.

3. **Preflight**
   ```bash
   python3 -m src.validate file.edi --preflight
   ```
   Use to judge submission readiness and rejection risk.

4. **Forensic mode** *(if the file looks weird or partial)*
   ```bash
   python3 -m src.validate file.edi --forensic
   ```

5. **Analytics export**
   ```bash
   python3 -m src.cli file.edi --format analytics -o out/analytics
   ```

6. **Reconciliation** *(for 835s with expected claim/payment context)*
   ```bash
   python3 -m src.cli file.edi --format reconcile --reference-csv expected_claims.csv -o out/reconcile
   ```

7. **Payer-rule trace** *(when a companion guide matters)*
   ```bash
   python3 -m src.validate file.edi --rules pack.json --rules-trace
   ```

---

## Support boundary

This project is intentionally honest about scope.
It is strong at:
- parsing
- bounded validation
- explainability
- forensic inspection
- analytics export
- review-oriented reconciliation

It does **not** claim:
- full TR3 certification
- full clearinghouse replacement
- full claim posting automation
- payer acceptance guarantees

That boundary is a feature, not a weakness: it keeps the tool trustworthy.
