#!/usr/bin/env python3
"""
X12 Parse CLI — parse 835/837 files and emit structured output.

Supports output formats:
  json    — full nested JSON (default)
  ndjson  — newline-delimited JSON (one record per line)
  csv     — flat CSV files (claims, service lines, entities)
  sqlite  — normalized CSV bundle + schema.sql ready for SQLite import
  analytics — analytics-oriented CSV bundle for BI / reconciliation
  analytics-parquet — optional Parquet analytics bundle (requires `pip install -e .[parquet]`, currently pandas + pyarrow)
  reconcile — 835 reconciliation bundle / JSON report

Usage:
    python3 -m src.cli <input.edi> [-o <output.json>]
    python3 -m src.cli <input.edi> --format ndjson
    python3 -m src.cli <input.edi> --format csv -o output_dir/
    python3 -m src.cli <input.edi> --format sqlite -o output_dir/
    python3 -m src.cli <input.edi> --format analytics -o analytics_dir/
    python3 -m src.cli <input.edi> --format analytics-parquet -o analytics_parquet_dir/
    python3 -m src.cli <input.edi> --format reconcile --reference-csv expected_claims.csv -o reconcile_dir/
    python3 -m src.cli <input.edi> --summary

Examples:
    python3 -m src.cli tests/fixtures/sample_835.edi
    python3 -m src.cli tests/fixtures/sample_835.edi -o parsed.json
    python3 -m src.cli tests/fixtures/sample_835.edi --format ndjson
    python3 -m src.cli tests/fixtures/sample_835.edi --format csv -o extracts/
    python3 -m src.cli tests/fixtures/sample_835.edi --format sqlite -o db_export/
    python3 -m src.cli tests/fixtures/sample_835_rich.edi --format analytics -o analytics/
    python3 -m src.cli tests/fixtures/sample_835_rich.edi --format analytics-parquet -o analytics_parquet/
    python3 -m src.cli tests/fixtures/sample_835.edi --compact
    python3 -m src.cli tests/fixtures/sample_835.edi --summary
    python3 -m src.cli tests/fixtures/sample_837_prof.edi --summary
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

# Add project root to path

from src.parser import X12Parser
from src import exporter
from src.reconcile import read_reference_claims_csv, reconcile_data, write_reconciliation_bundle


def _fmt_money(v) -> str:
    """Format a numeric value as USD currency."""
    if v is None:
        return "—"
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)


def _format_summary(data: dict) -> str:
    """Produce a human-readable summary of the parsed X12 data."""
    lines = []
    for ic_idx, ic in enumerate(data.get("interchanges", [])):
        sender = ic.get("isa06_sender", "?")
        receiver = ic.get("isa08_receiver", "?")
        lines.append("=" * 56)
        lines.append(f"INTERCHANGE {ic_idx + 1}")
        lines.append("=" * 56)
        lines.append(f"  Sender:     {sender}")
        lines.append(f"  Receiver:   {receiver}")

        for fg_idx, fg in enumerate(ic.get("functional_groups", [])):
            gs = fg.get("header", {})
            gs_version = gs.get("elements", {}).get("e8", "?")
            lines.append(f"\n  Functional Group {fg_idx + 1}  [version: {gs_version}]")

            for ts_idx, ts in enumerate(fg.get("transactions", [])):
                st = ts.get("header", {})
                set_id = ts.get("set_id", "?")
                st_ctrl = st.get("elements", {}).get("e2", "?")
                lines.append(f"\n  Transaction {ts_idx + 1}: {set_id}  [ST control: {st_ctrl}]")

                summary = ts.get("summary", {})
                if not summary:
                    lines.append("    (no summary — unrecognized transaction type)")
                    continue

                # ── 835 summary ──────────────────────────────────────────────
                if set_id == "835":
                    lines.append(f"    Billed:       {_fmt_money(summary.get('total_billed_amount'))}")
                    lines.append(f"    Paid:         {_fmt_money(summary.get('total_paid_amount'))}")
                    lines.append(f"    Allowed:      {_fmt_money(summary.get('total_allowed_amount'))}")
                    lines.append(f"    Adjusted:     {_fmt_money(summary.get('total_adjustment_amount'))}")
                    lines.append(f"    Net diff:     {_fmt_money(summary.get('net_difference'))}")
                    lines.append(f"    Payment amt: {_fmt_money(summary.get('payment_amount'))}")
                    bpr_method = summary.get("bpr_payment_method_label")
                    if bpr_method:
                        lines.append(f"    Payment method: {bpr_method}")
                    check_trace = summary.get("check_trace")
                    if check_trace:
                        lines.append(f"    Check trace:  {check_trace}")
                    lines.append(f"    Claims:       {summary.get('claim_count', '?')}")
                    lines.append(f"    Service lines: {summary.get('service_line_count', '?')}")
                    if summary.get("duplicate_claim_ids"):
                        lines.append(f"    ⚠ Duplicate claim IDs: {', '.join(summary['duplicate_claim_ids'])}")
                    lines.append(f"    Payer:       {summary.get('payer_name', '?')}")
                    lines.append(f"    Provider:     {summary.get('provider_name', '?')}")
                    if summary.get("discrepancies"):
                        lines.append(f"\n    ⚠ Financial discrepancies ({len(summary['discrepancies'])}):")
                        for disc in summary["discrepancies"]:
                            disc_type = disc.get("type", "")
                            if disc_type == "billed_mismatch":
                                lines.append(
                                    f"      [{disc_type}] claim {disc['claim_id']}: "
                                    f"CLP billed {_fmt_money(disc.get('clp_billed', 0))} "
                                    f"vs SVC sum {_fmt_money(disc.get('sum_svc_billed', 0))} "
                                    f"(diff {_fmt_money(disc.get('difference', 0))})"
                                )
                            elif disc_type == "paid_mismatch":
                                lines.append(
                                    f"      [{disc_type}] claim {disc['claim_id']}: "
                                    f"CLP paid {_fmt_money(disc.get('clp_paid', 0))} "
                                    f"vs SVC sum {_fmt_money(disc.get('sum_svc_paid', 0))} "
                                    f"(diff {_fmt_money(disc.get('difference', 0))})"
                                )
                            elif disc_type == "zero_pay_inconsistency":
                                lines.append(
                                    f"      [{disc_type}] claim {disc['claim_id']}: "
                                    f"status={disc.get('status_code', '?')} "
                                    f"but SVC paid {_fmt_money(disc.get('svc_paid', 0))}"
                                )
                            elif disc_type == "cas_adjustment_mismatch":
                                lines.append(
                                    f"      [{disc_type}] claim {disc['claim_id']}: "
                                    f"CAS sum {_fmt_money(disc.get('cas_sum', 0))} "
                                    f"vs CLP adj {_fmt_money(disc.get('clp_adjustment', 0))}"
                                )
                            else:
                                # Fallback for any new types
                                lines.append(
                                    f"      [{disc_type}] claim {disc.get('claim_id', '?')}: "
                                    f"{disc.get('description', '')}"
                                )
                    if summary.get("plb_count", 0) > 0:
                        lines.append(f"\n    PLB adjustments ({summary['plb_count']}):")
                        ps = summary.get("plb_summary", {})
                        for code, amount in ps.get("adjustment_by_code", {}).items():
                            label = ps.get("adjustment_labels", {}).get(code, code)
                            lines.append(f"      {code} ({label}): {_fmt_money(amount)}")
                        lines.append(f"    Total PLB: {_fmt_money(ps.get('total_plb_adjustment'))}")

                    # Claim details
                    claims = summary.get("claims", [])
                    if claims:
                        lines.append(f"\n    Claim details:")
                        for cl in claims:
                            status = cl.get("status_label", cl.get("status_code", "?"))
                            cat = cl.get("status_category", "")
                            cat_str = f" [{cat}]" if cat else ""
                            lines.append(
                                f"      {cl['claim_id']}: "
                                f"billed {_fmt_money(cl['clp_billed'])} "
                                f"paid {_fmt_money(cl['clp_paid'])} "
                                f"status={status}{cat_str}"
                            )

                # ── 837 summary ──────────────────────────────────────────────
                elif set_id == "837":
                    variant = summary.get("variant", "?")
                    variant_indicator = summary.get("variant_indicator", "")
                    variant_str = f" ({variant.capitalize()})" if variant else ""
                    lines.append(f"    Variant:     {variant_indicator}{variant_str}")
                    lines.append(f"    Billed:      {_fmt_money(summary.get('total_billed_amount'))}")
                    lines.append(f"    Claims:      {summary.get('claim_count', '?')}")
                    lines.append(f"    Service lines: {summary.get('service_line_count', '?')}")
                    lines.append(f"    HL levels:   {summary.get('hl_count', '?')}")
                    lines.append(f"    Billing provider: {summary.get('billing_provider', '?')}")
                    lines.append(f"    Payer:       {summary.get('payer_name', '?')}")
                    bht_id = summary.get("bht_id")
                    bht_date = summary.get("bht_date")
                    if bht_id:
                        lines.append(f"    BHT ID:      {bht_id}")
                    if bht_date:
                        lines.append(f"    BHT date:    {bht_date}")
                    if summary.get("duplicate_claim_ids"):
                        lines.append(f"    ⚠ Duplicate claim IDs: {', '.join(summary['duplicate_claim_ids'])}")
                    # Hierarchy tree
                    hierarchy = summary.get("hierarchy", {})
                    hl_tree = hierarchy.get("hl_tree", []) if isinstance(hierarchy, dict) else hierarchy
                    if hl_tree:
                        lines.append(f"\n    HL hierarchy:")
                        for entry in hl_tree:
                            if not isinstance(entry, dict):
                                lines.append(f"      {entry}")
                                continue
                            hl_id = entry.get("id", "?")
                            parent = entry.get("parent_id")
                            role = entry.get("level_role", "?")
                            code = entry.get("level_code", "?")
                            parent_str = f" (parent HL@{parent})" if parent else ""
                            lines.append(f"      HL@{hl_id} level={code} role={role}{parent_str}")

                # ── Other ───────────────────────────────────────────────────
                else:
                    lines.append(f"    Claims:      {summary.get('claim_count', summary.get('segment_count', '?'))}")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="X12 835/837 Parser — JSON, NDJSON, CSV, SQLite exports",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("file", type=Path, help="Input X12 EDI file")
    parser.add_argument("-o", "--output", type=Path, help="Output file or directory (format-dependent)")
    parser.add_argument("--compact", action="store_true", help="No indentation in JSON output")
    parser.add_argument(
        "--summary", action="store_true",
        help="Human-readable summary instead of structured output",
    )
    parser.add_argument(
        "--format",
        choices=["json", "ndjson", "csv", "sqlite", "analytics", "analytics-parquet", "reconcile"],
        default="json",
        help="Output format: json (default), ndjson, csv, sqlite, analytics, analytics-parquet, or reconcile",
    )
    parser.add_argument(
        "--reference-csv",
        type=Path,
        help="Optional reference claims CSV for reconciliation mode (claim_id required; expected_paid optional)",
    )
    args = parser.parse_args()

    if not args.file.exists():
        print(f"ERROR: file not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    try:
        p = X12Parser.from_file(args.file)
        data = p.to_dict()
    except Exception as exc:
        print(f"ERROR parsing {args.file}: {exc}", file=sys.stderr)
        sys.exit(1)

    # ── Summary mode (human-readable) ───────────────────────────────────────
    if args.summary:
        text = _format_summary(data)
        if args.output:
            args.output.write_text(text)
            print(f"[OK] Written: {args.output}")
        else:
            print(text)
        return

    # ── Structured output modes ───────────────────────────────────────────────
    if args.format == "json":
        indent = None if args.compact else 2
        text = json.dumps(data, indent=indent, ensure_ascii=False)
        if args.output:
            args.output.write_text(text)
            print(f"[OK] Written: {args.output}")
        else:
            print(text)

    elif args.format == "ndjson":
        # NDJSON goes to file or stdout
        if args.output:
            with open(args.output, "w") as f:
                count = exporter.emit_ndjson(data, file=f)
            print(f"[OK] Written {count} NDJSON records: {args.output}")
        else:
            count = exporter.emit_ndjson(data)
            # count not printed to stdout since emit writes to sys.stdout already

    elif args.format == "csv":
        out_dir = args.output or Path(".")
        if not args.output:
            out_dir = Path(".")
        counts = exporter.write_csv(data, out_dir)
        total = sum(counts.values())
        for fname, cnt in sorted(counts.items()):
            print(f"[OK] {fname}: {cnt} records")
        print(f"Total: {total} records across {len(counts)} files in {out_dir}/")

    elif args.format == "sqlite":
        out_dir = args.output or Path(".")
        if not args.output:
            out_dir = Path(".")
        counts = exporter.write_sqlite_bundle(data, out_dir)
        total = sum(counts.values())
        for fname, cnt in sorted(counts.items()):
            print(f"[OK] {fname}: {cnt} records")
        print(f"Total: {total} records across {len(counts)} files in {out_dir}/")

    elif args.format == "analytics":
        out_dir = args.output or Path(".")
        if not args.output:
            out_dir = Path(".")
        counts = exporter.write_analytics_bundle(data, out_dir)
        total = sum(counts.values())
        for fname, cnt in sorted(counts.items()):
            print(f"[OK] {fname}: {cnt} records")
        print(f"Total: {total} records across {len(counts)} files in {out_dir}/")

    elif args.format == "analytics-parquet":
        out_dir = args.output or Path(".")
        if not args.output:
            out_dir = Path(".")
        try:
            counts = exporter.write_analytics_parquet_bundle(data, out_dir)
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(2)
        total = sum(counts.values())
        for fname, cnt in sorted(counts.items()):
            print(f"[OK] {fname}: {cnt} records")
        print(f"Total: {total} records across {len(counts)} files in {out_dir}/")

    elif args.format == "reconcile":
        reference_claims = []
        if args.reference_csv:
            if not args.reference_csv.exists():
                print(f"ERROR: reference CSV not found: {args.reference_csv}", file=sys.stderr)
                sys.exit(1)
            reference_claims = read_reference_claims_csv(args.reference_csv)
        result = reconcile_data(data, reference_claims=reference_claims)
        if args.output:
            counts = write_reconciliation_bundle(result, args.output)
            total = sum(counts.values())
            for fname, cnt in sorted(counts.items()):
                print(f"[OK] {fname}: {cnt} records")
            print(f"Total: {total} records across {len(counts)} files in {args.output}/")
        else:
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
