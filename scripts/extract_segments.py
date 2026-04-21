#!/usr/bin/env python3
"""
Segment element extractor — pull named values from parsed X12 JSON.

Usage:
    python3 scripts/extract_segments.py <file.edi> <segment> <element>

Examples:
    python3 scripts/extract_segments.py sample.edi CLP 2     # CLP01 = claim status code
    python3 scripts/extract_segments.py sample.edi CLP 3       # CLP02 = monetary amount
    python3 scripts/extract_segments.py sample.edi SVC 1       # SVC01 = composite医疗
"""
from __future__ import annotations
import json, sys, pathlib

# Element names for 835 and 837 (partial — extend as needed)
ELEMENT_NAMES = {
    "CLP": {1: "Claim Status Code", 2: "Monetary Amount", 3: "Claim Filing Code", 4: "Ref ID", 5: "Free Text"},
    "SVC": {1: "Composite Medical Code", 2: "Monetary Amount", 3: "Monetary Amount", 4: "Qty"},
    "BPR": {1: "Handling Code", 2: "Monetary Amount", 3: "Credit/Debit Flag", 4: "Payment Method"},
    "TRN": {1: "Trace Type", 2: "Trace Number", 3: "Orig Company ID"},
    "N1":  {1: "Entity ID Code", 2: "Name", 3: "ID Code Qualifier", 4: "ID Code"},
    "NM1": {1: "Entity ID Code", 2: "Entity Type", 3: "Name Last", 4: "Name First",
            5: "Name Middle", 6: "Prefix", 7: "Suffix", 8: "ID Code Qualifier", 9: "ID Code"},
    "DTM": {1: "Date Time Qualifier", 2: "Date"},
    "HI":  {1: "Diagnosis Code 1", 2: "Diagnosis Code 2"},
    "CLM": {1: "Claim Submitter ID", 2: "Monetary Amount", 3: "Claim Filing Code",
            4: "Ref ID", 5: "Facility Code", 6: "Freq Type"},
    "SV1": {1: "Composite Medical Code", 2: "Monetary Amount"},
    "SV2": {1: "Composite Medical Code", 2: "Monetary Amount"},
    "REF": {1: "Reference Qualifier", 2: "Reference ID"},
    "AMT": {1: "Amount Qualifier", 2: "Monetary Amount"},
    "QTY": {1: "Qty Qualifier", 2: "Quantity"},
    "ADJ": {1: "Adjustment Seq", 2: "Adjustment Reason", 3: "Adjustment Amount"},
    "CAS": {1: "Claim Adjustment Group", 2: "Reason Code", 3: "Amount"},
    "BHT": {1: "BHT01", 2: "BHT02", 3: "Reference ID", 4: "Date", 5: "Time", 6: "Code"},
    "HL":  {1: "Hierarchical ID", 2: "Hierarchical Parent", 3: "Level Code", 4: "Child Code"},
    "SBR": {1: "Payer Seq", 2: "Individual Rel", 3: "Ref ID", 4: "Name", 5: "Insurance Type", 6: "COB", 7: "Coord", 8: "Employee Status", 9: "Claim Type"},
    "DMG": {1: "Date Time Qualifier", 2: "Date", 3: "Gender", 4: "City", 5: "State"},
}

def extract(parser_result: dict, segment_tag: str, element_num: int) -> list[str]:
    results = []
    for ic in parser_result.get("interchanges", []):
        for fg in ic.get("functional_groups", []):
            for ts in fg.get("transactions", []):
                for loop in ts.get("loops", []):
                    for seg in loop.get("segments", []):
                        if seg.get("tag") == segment_tag:
                            key = f"e{element_num}"
                            val = seg.get("elements", {}).get(key, "")
                            if val:
                                results.append(val)
    return results

def main() -> None:
    if len(sys.argv) < 4:
        print(f"Usage: {sys.argv[0]} <file.edi> <segment> <element>")
        print(f"  segment: e.g. CLP, SVC, BPR, NM1, HI, CLM")
        print(f"  element: 1-based element index within segment")
        sys.exit(1)

    edi_file = pathlib.Path(sys.argv[1])
    seg_tag = sys.argv[2].upper()
    try:
        elem_num = int(sys.argv[3])
    except ValueError:
        print(f"Element must be integer, got: {sys.argv[3]}", file=sys.stderr)
        sys.exit(1)

    from src.parser import X12Parser
    p = X12Parser.from_file(edi_file)
    d = p.to_dict()
    vals = extract(d, seg_tag, elem_num)

    elem_name = ELEMENT_NAMES.get(seg_tag, {}).get(elem_num, "(unnamed)")
    print(f"# {seg_tag}-{elem_num} ({elem_name}) from {edi_file}")
    for v in vals:
        print(v)

if __name__ == "__main__":
    main()
