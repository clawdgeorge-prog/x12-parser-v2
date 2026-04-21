#!/usr/bin/env bash
# run.sh — X12 Parser Demo
# Run from the project root:  ./demo/run.sh
set -e

DEMO_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$DEMO_DIR")"
cd "$PROJECT_DIR"

echo "============================================================"
echo "X12 Parser — Quick Demo"
echo "============================================================"
echo ""

# ── 1. Parse an 835 file ───────────────────────────────────────
echo ">>> 1. PARSE  (835 Healthcare Claim Payment/Advice)"
echo "    Command: python3 -m src.cli tests/fixtures/sample_835.edi --compact"
echo ""
python3 -m src.cli tests/fixtures/sample_835.edi --compact | python3 -c "
import json, sys
data = json.load(sys.stdin)
ic = data['interchanges'][0]
fg = ic['functional_groups'][0]
ts = fg['transactions'][0]
print(f'    ↳ Interchange sender:  {ic[\"isa06_sender\"]}')
print(f'    ↳ Interchange receiver: {ic[\"isa08_receiver\"]}')
print(f'    ↳ Transaction type:     {ts[\"set_id\"]}')
print(f'    ↳ Loops found:          {len(ts[\"loops\"])}')
loops_by_kind = {}
for l in ts['loops']:
    k = l['kind']
    loops_by_kind[k] = loops_by_kind.get(k, 0) + 1
for k, v in loops_by_kind.items():
    print(f'      - {v} loop(s) of kind: {k}')
"
echo ""

# ── 2. Validate an 835 file ───────────────────────────────────
echo ">>> 2. VALIDATE  (structural checks)"
echo "    Command: python3 -m src.validate tests/fixtures/sample_835.edi"
echo ""
python3 -m src.validate tests/fixtures/sample_835.edi || true
echo ""

# ── 2b. Explainable validation v2 ─────────────────────────────
echo ">>> 2b. EXPLAIN  (grouped explainable validation v2)"
echo "    Command: python3 -m src.validate tests/fixtures/sample_missing_ge.edi --explain"
echo ""
python3 -m src.validate tests/fixtures/sample_missing_ge.edi --explain || true
echo ""

# ── 2c. Preflight rejection-risk summary ──────────────────────
echo ">>> 2c. PREFLIGHT  (rejection-risk summary)"
echo "    Command: python3 -m src.validate tests/fixtures/sample_missing_ge.edi --preflight"
echo ""
python3 -m src.validate tests/fixtures/sample_missing_ge.edi --preflight || true
echo ""

# ── 3. Parse an 837 file ───────────────────────────────────────
echo ">>> 3. PARSE  (837 Healthcare Claim — Professional)"
echo "    Command: python3 -m src.cli tests/fixtures/sample_837_prof.edi --compact"
echo ""
python3 -m src.cli tests/fixtures/sample_837_prof.edi --compact | python3 -c "
import json, sys
data = json.load(sys.stdin)
ic = data['interchanges'][0]
fg = ic['functional_groups'][0]
ts = fg['transactions'][0]
print(f'    ↳ Interchange sender:  {ic[\"isa06_sender\"]}')
print(f'    ↳ Interchange receiver: {ic[\"isa08_receiver\"]}')
print(f'    ↳ Transaction type:     {ts[\"set_id\"]}')
print(f'    ↳ Loops found:          {len(ts[\"loops\"])}')
loops_by_kind = {}
for l in ts['loops']:
    k = l['kind']
    loops_by_kind[k] = loops_by_kind.get(k, 0) + 1
for k, v in loops_by_kind.items():
    print(f'      - {v} loop(s) of kind: {k}')
"
echo ""

# ── 4. Forensic analysis ───────────────────────────────────
echo ">>> 4. FORENSIC  (deep claim tracing + unusual pattern detection)"
echo "    Command: python3 -m src.validate tests/fixtures/sample_835.edi --forensic"
echo ""
python3 -m src.validate tests/fixtures/sample_835.edi --forensic
echo ""

# ── 5. Payer rules + transparent rules trace ─────────────────
echo ">>> 5. PAYER RULES + RULES TRACE  (companion-guide pack with transparent trace)"
echo "    Command: python3 -m src.validate tests/fixtures/sample_837_institutional.edi ..."
echo "             --rules examples/rules/medicare-837i-companion.sample.json --rules-trace"
echo ""
python3 -m src.validate tests/fixtures/sample_837_institutional.edi \
    --rules examples/rules/medicare-837i-companion.sample.json --rules-trace || true
echo ""

# ── 6. Validate a clean fixture ───────────────────────────────
echo ">>> 6. VALIDATE  (clean fixture — no structural errors)"
echo "    Command: python3 -m src.validate tests/fixtures/sample_whitespace_irregular.edi"
echo ""
python3 -m src.validate tests/fixtures/sample_whitespace_irregular.edi
echo ""

# ── 7. Analytics export ───────────────────────────────────────
echo ">>> 7. ANALYTICS EXPORT  (835 rich fixture → analytics bundle)"
echo "    Command: python3 -m src.cli tests/fixtures/sample_835_rich.edi --format analytics -o demo/analytics_out"
echo ""
rm -rf demo/analytics_out
python3 -m src.cli tests/fixtures/sample_835_rich.edi --format analytics -o demo/analytics_out
echo ""

# ── 8. Sample payer-pack inventory + optional parquet export ─────────────
echo ">>> 8. SAMPLE PAYER PACKS  (inventory check)"
find examples/rules -maxdepth 1 -name '*.json' -print | sort | sed 's#^#    - #' 
echo ""

echo ">>> 9. OPTIONAL PARQUET EXPORT  (dependency-gated)"
echo "    Command: python3 -m src.cli tests/fixtures/sample_835_rich.edi --format analytics-parquet -o demo/analytics_parquet_out"
echo ""
rm -rf demo/analytics_parquet_out
if python3 -m src.cli tests/fixtures/sample_835_rich.edi --format analytics-parquet -o demo/analytics_parquet_out; then
  echo "    ↳ Parquet export succeeded."
else
  echo "    ↳ Parquet export skipped: install optional deps with pip install -e .[parquet]"
fi
echo ""

echo "============================================================"
echo "Demo complete.  See DEMO.md for full documentation."
echo "============================================================"
