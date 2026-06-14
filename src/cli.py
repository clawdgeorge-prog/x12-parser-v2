#!/usr/bin/env python3
"""
X12 Parse CLI — parse 835/837 files and emit structured output.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src import exporter
from src.batch import build_batch_json, discover_input_files, parse_inputs
from src.parser import X12Parser
from src.reconcile import read_reference_claims_csv, reconcile_data, write_reconciliation_bundle


def _fmt_money(v) -> str:
    """Format a numeric value as USD currency."""
    if v is None:
        return "—"
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)


def _format_single_summary(data: dict) -> str:
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
                else:
                    lines.append(f"    Claims:      {summary.get('claim_count', summary.get('segment_count', '?'))}")

    return "\n".join(lines)


def _format_summary(data: dict) -> str:
    if data.get("batch"):
        parts = []
        for doc in data.get("documents", []):
            parts.append(f"# FILE: {doc.get('source_file', '')}")
            parts.append(_format_single_summary(doc))
        if data.get("failures"):
            parts.append("# FAILURES")
            for failure in data.get("failures", []):
                parts.append(f"- {failure['source_file']}: {failure['error']}")
        return "\n\n".join(parts)
    return _format_single_summary(data)


def _load_input(path: Path) -> dict:
    if path.is_file():
        return X12Parser.from_file(path).to_dict()

    files = discover_input_files(path)
    if not files:
        raise FileNotFoundError(f"No supported X12 files found in directory: {path}")
    documents, failures = parse_inputs(files)
    return build_batch_json(documents, failures)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="X12 835/837 Parser — JSON, NDJSON, CSV, SQLite exports",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("file", type=Path, help="Input X12 EDI file or directory")
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
        data = _load_input(args.file)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    except OSError as exc:
        print(f"ERROR reading {args.file}: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.summary:
        text = _format_summary(data)
        if args.output:
            args.output.write_text(text)
            print(f"[OK] Written: {args.output}")
        else:
            print(text)
        return

    if args.format == "json":
        indent = None if args.compact else 2
        text = json.dumps(data, indent=indent, ensure_ascii=False)
        if args.output:
            out_path = args.output
            if out_path.is_dir():
                out_path = out_path / "batch.json"
            out_path.write_text(text)
            print(f"[OK] Written: {out_path}")
        else:
            print(text)

    elif args.format == "ndjson":
        if args.output:
            out_path = args.output
            if out_path.is_dir():
                out_path = out_path / "batch.ndjson"
            with open(out_path, "w") as f:
                count = exporter.emit_ndjson(data, file=f)
            print(f"[OK] Written {count} NDJSON records: {out_path}")
        else:
            exporter.emit_ndjson(data)

    elif args.format == "csv":
        out_dir = args.output or Path(".")
        counts = exporter.write_csv(data, out_dir)
        total = sum(counts.values())
        for fname, cnt in sorted(counts.items()):
            print(f"[OK] {fname}: {cnt} records")
        print(f"Total: {total} records across {len(counts)} files in {out_dir}/")

    elif args.format == "sqlite":
        out_dir = args.output or Path(".")
        counts = exporter.write_sqlite_bundle(data, out_dir)
        total = sum(counts.values())
        for fname, cnt in sorted(counts.items()):
            print(f"[OK] {fname}: {cnt} records")
        print(f"Total: {total} records across {len(counts)} files in {out_dir}/")

    elif args.format == "analytics":
        out_dir = args.output or Path(".")
        counts = exporter.write_analytics_bundle(data, out_dir)
        total = sum(counts.values())
        for fname, cnt in sorted(counts.items()):
            print(f"[OK] {fname}: {cnt} records")
        print(f"Total: {total} records across {len(counts)} files in {out_dir}/")

    elif args.format == "analytics-parquet":
        out_dir = args.output or Path(".")
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
