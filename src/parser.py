"""
X12 Parser — Healthcare EDI 835/837 transactions.

Scope (v0.2.1):
  - ISA/IEA envelope parsing with **dynamic delimiter extraction**
  - GS/GE functional-group envelope
  - ST/SE transaction set framing
  - 835: Healthcare Claim Payment/Advice
  - 837: Healthcare Claim — Professional (CMS-1500)
  - 837: Healthcare Claim — Institutional (UB-04)
  - 837: Healthcare Claim — Dental (basic scaffolding)
  - Segment, loop, and element extraction
  - Transaction summaries with financial totals, claim counts, HL hierarchy
  - Structured JSON output

Known limitations (documented in README):
  - No schema validation against official X12 specs
  - Composite elements returned as strings (not decomposed)
  - Repetition separator (ISA-11) extracted but not used for segment parsing
"""

from __future__ import annotations

__version__ = "0.2.1"
OUTPUT_SCHEMA_VERSION = "1.0"

import re
import json
import pathlib
from dataclasses import dataclass, field, asdict
from typing import Optional, List

# Taxonomy tables (moved to src.taxonomy for maintainability)
from src.taxonomy import (
    _LOOP_DESCRIPTIONS_835,
    _LOOP_DESCRIPTIONS_837,
    _LOOP_KINDS,
    _CLP_STATUS_CODES,
    _PLB_REASON_CODES,
    _DISCREPANCY_TAXONOMY,
    _TRANSACTION_REGISTRY,
    _GS_FUNCTIONAL_CODES,
)


# ── Character set ────────────────────────────────────────────────────────────
# X12 uses: segment terminator (default ~), element separator (default *),
#           component separator (default :), repetition separator (default ^)

DEFAULT_SEG_TERM = "~"
DEFAULT_ELEM_SEP = "*"
DEFAULT_COMP_SEP = ":"


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class Element:
    raw: str
    position: int          # 1-based index within segment

@dataclass
class Segment:
    tag: str
    elements: List[Element]
    raw: str
    position: int          # line/sequence number in file

@dataclass
class Loop:
    id: str               # e.g. "PR", "QC", "CLM" — heuristic, first element of leader segment
    leader_tag: str       # tag that triggered loop creation, e.g. "NM1", "CLM", "LX"
    leader_code: str      # first element of leader segment, e.g. "PR", "QC", "IL"
    kind: str             # practical category: "entity", "claim", "service", "header", "amount", "other"
    description: str      # short human-readable label
    segments: List[Segment]

@dataclass
class TransactionSet:
    header: Segment       # ST segment
    loops: List[Loop]
    trailer: Segment      # SE segment
    set_id: str           # "835" or "837"
    # Computed summary fields (populated by _parse_summary)
    summary: dict = field(default_factory=dict)

@dataclass
class FunctionalGroup:
    header: Segment       # GS
    transactions: List[TransactionSet]
    trailer: Segment      # GE

@dataclass
class Interchange:
    header: Segment       # ISA
    groups: List[FunctionalGroup]
    trailer: Segment      # IEA
    isa06_sender: str = ""
    isa08_receiver: str = ""


# ── Core tokenizer ─────────────────────────────────────────────────────────────

class X12Tokenizer:
    """Split an X12 string into raw segments."""

    def __init__(
        self,
        seg_term: str = DEFAULT_SEG_TERM,
        elem_sep: str = DEFAULT_ELEM_SEP,
        comp_sep: str = DEFAULT_COMP_SEP,
    ):
        self.seg_term = seg_term
        self.elem_sep = elem_sep
        self.comp_sep = comp_sep

    def tokenize(self, text: str) -> List[str]:
        """Return list of raw segment strings (no terminator).

        Splits on segment terminator (~) OR newline.
        This handles both ~-terminated X12 files and line-delimited files
        where the ISA line may end with a component separator (:) rather than ~.
        """
        raw = text.strip()
        # Normalize line endings
        raw = raw.replace("\r\n", "\n").replace("\r", "\n")
        # Replace segment terminator (~) with newline so we split on either
        raw = raw.replace(self.seg_term, "\n")
        # Also split on any remaining newlines between segments
        segs: List[str] = []
        for line in raw.split("\n"):
            stripped = line.strip()
            if stripped:
                segs.append(stripped)
        return segs


# ── Segment / Loop / Transaction parsers ──────────────────────────────────────

class X12SegmentParser:
    """Parse a single raw segment string into a Segment dataclass."""

    def __init__(self, elem_sep: str = DEFAULT_ELEM_SEP):
        self.elem_sep = elem_sep

    def parse(self, raw: str, position: int = 0) -> Segment:
        parts = raw.split(self.elem_sep)
        tag = parts[0] if parts else ""
        elements = [
            Element(raw=e, position=i + 1)
            for i, e in enumerate(parts[1:])
        ]
        return Segment(tag=tag, elements=elements, raw=raw, position=position)

    def get(self, seg: Segment, index: int, sub_index: Optional[int] = None) -> Optional[str]:
        """Get element value by 1-based index. Optionally sub-element by 2nd index."""
        idx = index - 1
        if idx < 0 or idx >= len(seg.elements):
            return None
        e = seg.elements[idx].raw
        if sub_index is not None:
            parts = e.split(":")
            si = sub_index - 1
            return parts[si] if si < len(parts) else None
        return e


# ── 835-aware parser ─────────────────────────────────────────────────────────

# Loop descriptions moved to src/taxonomy/__init__.py
# Note: _LOOP_835 and _LOOP_837 were defined but never used (dead code)


# ── Transaction / version registry ─────────────────────────────────────────
# Maps X12 version strings to human-readable transaction type labels.
# Keyed by the version string found in GS-8 (functional code) or ST-3.
_TRANSACTION_REGISTRY: dict[str, dict] = {
    # 835 — Healthcare Claim Payment/Advice
    "005010X221A1": {
        "set_id": "835",
        "name": "Healthcare Claim Payment/Advice",
        "description": "835 — Payment/Remittance",
        "category": "payment",
    },
    # 837 — Healthcare Claim
    "005010X222A1": {
        "set_id": "837",
        "name": "Healthcare Claim — Professional (CMS-1500)",
        "description": "837P — Professional Claim",
        "category": "claim",
        "variant": "professional",
    },
    "005010X223A1": {
        "set_id": "837",
        "name": "Healthcare Claim — Institutional (UB-04)",
        "description": "837I — Institutional Claim",
        "category": "claim",
        "variant": "institutional",
    },
    "005010X224A1": {
        "set_id": "837",
        "name": "Healthcare Claim — Dental",
        "description": "837D — Dental Claim",
        "category": "claim",
        "variant": "dental",
    },
}

# GS functional code → set_id / category mapping (used when version string not available)
_GS_FUNCTIONAL_CODES: dict[str, dict] = {
    "HP": {"set_id": "835", "name": "Healthcare Claim Payment/Advice", "category": "payment"},
    "HC": {"set_id": "837", "name": "Healthcare Claim", "category": "claim"},
    "HI": {"set_id": "837", "name": "Healthcare Claim — Institutional", "category": "claim"},
}

# CLP status codes — maps numeric code to description and category
_CLP_STATUS_CODES: dict[str, dict] = {
    "1":  {"label": "Processed as Primary",         "category": "paid"},
    "2":  {"label": "Processed as Secondary",       "category": "paid"},
    "3":  {"label": "Processed as Tertiary",         "category": "paid"},
    "4":  {"label": "Denied",                      "category": "denied"},
    "5":  {"label": "Pended",                      "category": "pended"},
    "6":  {"label": "Pending",                    "category": "pended"},
    "7":  {"label": "Received — Not Yet Processed", "category": "pended"},
    "8":  {"label": "Not Processed",               "category": "denied"},
    "9":  {"label": "Processed as Primary — Forwarded to Another Payer", "category": "forwarded"},
    "10": {"label": "Processed as Secondary — Forwarded to Another Payer",  "category": "forwarded"},
    "11": {"label": "Processed as Tertiary — Forwarded to Another Payer",   "category": "forwarded"},
    "12": {"label": "Resubmission",                 "category": "resubmission"},
    "13": {"label": "Audit Complete",               "category": "completed"},
    "14": {"label": "Matched to Original Claim",    "category": "pended"},
    "15": {"label": "Claim Contains No Payment or Return Claim Information", "category": "informational"},
    "16": {"label": "Claim Was Returned — More Information Needed",          "category": "pended"},
    "17": {"label": "Claim Was Returned — Invalid",  "category": "denied"},
    "19": {"label": "Processed as Primary — Forwarded to Dental",  "category": "forwarded"},
    "20": {"label": "Processed as Secondary — Forwarded to Dental", "category": "forwarded"},
    "21": {"label": "Processed as Tertiary — Forwarded to Dental",  "category": "forwarded"},
    "22": {"label": "Forwarded to Dental — Additional Information Needed", "category": "pended"},
    "23": {"label": "Forwarded to Dental — Already Paid",           "category": "informational"},
    "24": {"label": "Forwarded to Dental — Cannot Process",        "category": "denied"},
    "25": {"label": "Cannot Process — Forwarded to Another Payer","category": "forwarded"},
    "27": {"label": "Processed as Primary — Forwarded to Vision",  "category": "forwarded"},
    "28": {"label": "Processed as Secondary — Forwarded to Vision", "category": "forwarded"},
    "29": {"label": "Processed as Tertiary — Forwarded to Vision",  "category": "forwarded"},
}

# PLB adjustment reason codes — common group codes used in 835 PLB and CAS segments
_PLB_REASON_CODES: dict[str, dict] = {
    "CO": {"label": "Contractual Obligation",     "category": "contractual"},
    "PR": {"label": "Patient Responsibility",    "category": "patient"},
    "PI": {"label": "Payer Initiated Reduction", "category": "payer"},
    "AO": {"label": "Administrative/Scientific",   "category": "administrative"},
    "WO": {"label": "Write-Off",                 "category": "writeoff"},
    "CV": {"label": "Covered",                   "category": "covered"},
    "CAD": {"label": "Carve-Out",               "category": "carveout"},
    "DISC": {"label": "Discount",               "category": "discount"},
    "LAB": {"label": "Laboratory",              "category": "lab"},
    "ODO": {"label": "Dental",                 "category": "dental"},
}

# Kind inference from leader tag / code
# Reconciliation discrepancy taxonomy — describes what kind of mismatch was found
_DISCREPANCY_TAXONOMY = {
    "billed_mismatch": {
        "severity": "warning",
        "description": "CLP billed amount differs from sum of SVC billed amounts",
    },
    "paid_mismatch": {
        "severity": "warning",
        "description": "CLP paid amount differs from sum of SVC paid amounts",
    },
    "zero_pay_inconsistency": {
        "severity": "info",
        "description": "CLP status indicates denied/pending but service lines show non-zero payment",
    },
    "cas_adjustment_mismatch": {
        "severity": "info",
        "description": "Sum of CAS adjustments does not equal the reported CLP adjustment amount",
    },
}

_LOOP_KINDS = {
    # NM1 entity type codes → kind
    "QC": "entity",    # patient/claimant
    "IL": "entity",    # insured/subscriber
    "PR": "entity",    # payer
    "PE": "entity",    # payee/provider
    "85": "entity",    # billing provider
    "41": "entity",    # submitter
    "40": "entity",    # receiver
    "77": "entity",    # service facility location
    "8": "entity",     #配偶
    # Claim / service leaders
    "CLM": "claim",
    "CLP": "claim",
    "LX": "service",
    "SV1": "service",
    "SV2": "service",
    "SV3": "service",
    "SV4": "service",
    "SV5": "service",
    "HI": "diagnosis",
    "HCP": "pricing",
    "BHT": "header",
    "PLB": "adjustment",
    "ADJ": "adjustment",
    "CAS": "adjustment",
    "AMT": "amount",
    "QTY": "quantity",
    "DTM": "date",
    "REF": "reference",
    "N1": "entity",
    "N3": "address",
    "N4": "geography",
    "PER": "contact",
    "DMG": "demographic",
    "PAT": "patient",
    "SBR": "subscriber",
    "CUR": "currency",
    "NTE": "note",
    "LIN": "line_item",
    "CTP": "pricing",
    "RDM": "remittance",
    "HL": "hierarchy",
    "CR1": "ambulance",
    "CR2": "spine",
    "CR3": "oxygen",
    "CR4": "durable_medical",
    "CR5": "vision",
    "ENT": "entity",
    "RDM": "remittance",
    "BPR": "payment",
    "TRN": "trace",
    "CR1": "ambulance",
    "CR2": "spine",
    "CR3": "oxygen",
    "CR4": "durable_medical",
    "CR5": "vision",
    # Known-optional 835 segments — recognized as loop leaders, not deeply semanticized
    "TS2": "statistics",
    "TS3": "statistics",
    "MIA": "statistics",
    "MOA": "statistics",
}

# Look-up description tables (leader_code → short description)
_LOOP_DESCRIPTIONS_835 = {
    "1000A": "Submitter Name",
    "1000B": "Receiver Name",
    "1000C": "Billing Provider Name",
    "1500":  "Payment Information",
    "2000":  "Service Payment Information",
    "2100":  "Claim Payment Information",
    "2110":  "Service Payment Detail",
    "2200":  "Adjustment",
    "2300":  "Remark Codes",
    # NM1 entity qualifiers (pragmatic labels)
    "PR": "Payer Name",
    "PE": "Provider Name",
    "QC": "Patient/Claimant Name",
    "NM1": "Entity Name",
    # Known-optional 835 segments (recognized but not deeply semanticized)
    "TS2": "Transaction Statistics (Provider)",
    "TS3": "Transaction Statistics (Insured)",
    "MIA": "Medicare Inpatient Adjudication",
    "MOA": "Medicare Outpatient Adjudication",
}

_LOOP_DESCRIPTIONS_837 = {
    "1000A": "Submitter Name",
    "1000B": "Receiver Name",
    "1000C": "Billing Provider Name",
    "1000D": "Subscriber Name",
    "1000E": "Patient Name",
    "2000A": "Hierarchical Parent",
    "2000B": "Billing Provider Hierarchical Level",
    "2000C": "Subscriber Hierarchical Level",
    "2000D": "Patient Hierarchical Level",
    "2300":  "Claim Information",
    "2305":  "Prior Authorization or Referral",
    "2310A": "Physician or Facility Name",
    "2310B": "Operating Physician Name",
    "2310C": "Service Facility Location",
    "2310D": "Referring Provider Name",
    "2320":  "Subscriber or Patient Amount",
    "2330A": "Subscriber Name",
    "2330B": "Payer Name",
    "2330C": "Patient Name",
    "2330D": "Responsible Party Name",
    "2400":  "Service Line Number",
    "2410":  "Drug Identification",
    "2420A": "Operating Physician Name",
    "2420B": "Other Physician Name",
    "2420C": "Service Facility Location",
    "2430":  "Line Adjudication Information",
    "2440":  "Form Identification",
    # NM1 entity qualifiers
    "41": "Submitter Name",
    "40": "Receiver Name",
    "85": "Billing Provider Name",
    "IL": "Subscriber Name",
    "QC": "Patient Name",
    "PR": "Payer Name",
    "NM1": "Entity Name",
}


def _infer_loop_description(leader_tag: str, leader_code: str) -> str:
    """Look up a human-readable description for a loop from known tables."""
    # First check by leader_code (first element of leader segment)
    desc = _LOOP_DESCRIPTIONS_835.get(leader_code) or _LOOP_DESCRIPTIONS_837.get(leader_code)
    if desc:
        return desc
    # Fallback: check by leader_tag (segment tag) for segments like TS2/TS3/MIA/MOA
    desc = _LOOP_DESCRIPTIONS_835.get(leader_tag) or _LOOP_DESCRIPTIONS_837.get(leader_tag)
    if desc:
        return desc
    # Final fallback: tag-based generic label
    return f"{leader_tag} Loop"


def _detect_loops(segments: List[Segment]) -> List[Loop]:
    """
    Walk segments and group them into loops based on segment IDs
    that act as loop initiators per X12 spec.

    Each Loop carries:
      - id           : the leader segment's first element (heuristic loop key)
      - leader_tag   : the segment tag that started this loop
      - leader_code  : same as id (first element of leader segment)
      - kind         : practical category (entity, claim, service, etc.)
      - description  : short human-readable label
      - segments     : all segments in this loop
    """
    # Tags that trigger a new loop grouping
    # TS2/TS3/MIA are 835-specific optional segments — recognized as loop leaders
    # in 835 context but not deeply semanticized
    LOOP_LEADER_TAGS = frozenset((
        "NM1", "CLM", "N1", "LX", "SV1", "SV2", "SV3", "HI", "BPR",
        "CLP", "PLB",
        "ADJ", "CAS", "REF", "DTM", "PER", "AMT", "QTY", "CTP",
        "HCP", "TRN", "CUR", "DMG", "PAT", "NTE", "LIN", "CR1",
        "CR2", "CR3", "CR4", "CR5", "RDM", "BHT", "HL",
        "TS2", "TS3", "MIA", "MOA",
    ))

    loops: List[Loop] = []
    current_loop_segments: List[Segment] = []
    current_loop_id = ""
    current_leader_tag = ""
    i = 0
    while i < len(segments):
        seg = segments[i]
        tag = seg.tag

        if tag in LOOP_LEADER_TAGS:
            leader_code = seg.elements[0].raw if seg.elements else ""

            if current_loop_id and current_loop_segments:
                # Use current_loop_id (the previous loop's key) for kind lookup;
                # fall back to the previous leader_tag for tag-keyed entries.
                kind = (
                    _LOOP_KINDS.get(current_loop_id) or
                    _LOOP_KINDS.get(current_leader_tag) or
                    "other"
                )
                desc = _infer_loop_description(current_leader_tag, current_loop_id)
                loops.append(Loop(
                    id=current_loop_id,
                    leader_tag=current_leader_tag,
                    leader_code=current_loop_id,
                    kind=kind,
                    description=desc,
                    segments=current_loop_segments,
                ))
            current_loop_id = leader_code
            current_leader_tag = tag
            current_loop_segments = [seg]
        else:
            current_loop_segments.append(seg)
        i += 1

    if current_loop_id and current_loop_segments:
        kind = (
            _LOOP_KINDS.get(current_loop_id) or
            _LOOP_KINDS.get(current_leader_tag) or
            "other"
        )
        desc = _infer_loop_description(current_leader_tag, current_loop_id)
        loops.append(Loop(
            id=current_loop_id,
            leader_tag=current_leader_tag,
            leader_code=current_loop_id,
            kind=kind,
            description=desc,
            segments=current_loop_segments,
        ))

    return loops


def _segment_to_dict(seg: Segment) -> dict:
    elems = {}
    for e in seg.elements:
        elems[f"e{e.position}"] = e.raw
    return {
        "tag": seg.tag,
        "elements": elems,
        "raw": seg.raw,
        "position": seg.position,
    }


def _loop_to_dict(loop: Loop) -> dict:
    return {
        "id": loop.id,
        "leader_tag": loop.leader_tag,
        "leader_code": loop.leader_code,
        "kind": loop.kind,
        "description": loop.description,
        "segments": [_segment_to_dict(s) for s in loop.segments],
    }


# ── Main parser ───────────────────────────────────────────────────────────────

class X12Parser:
    """
    Parse an X12 string or file into structured dataclasses and emit JSON.

    Supports ISA/IEA, GS/GE, ST/SE envelopes and transaction sets 835 and 837.
    """

    def __init__(self, text: Optional[str] = None):
        self._raw_text = text or ""
        self.segments: List[Segment] = []
        self.interchanges: List[Interchange] = []
        self._seg_parser = X12SegmentParser()
        self._parsed = False
        self._summary_computed = False

    @classmethod
    def from_file(cls, path: str | pathlib.Path) -> "X12Parser":
        text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
        return cls(text=text)

    def _detect_delimiters(self, text: str) -> tuple[str, str, str, str]:
        """Detect delimiters from ISA segment.
        
        Extracts:
        - Element separator (ISA-3)
        - Component separator (ISA-16)
        - Repetition separator (ISA-11) - extracted but not used
        - Segment terminator
        
        Returns (elem_sep, comp_sep, rep_sep, seg_term).
        """
        # Find ISA segment (up to ~ or newline)
        isa_full_match = re.search(r"ISA[^\r\n~]*", text)
        if not isa_full_match:
            return DEFAULT_ELEM_SEP, DEFAULT_COMP_SEP, "^", DEFAULT_SEG_TERM
            
        isa = isa_full_match.group()
        
        # Defaults per X12 spec
        elem_sep = "*"
        comp_sep = ":"
        rep_sep = "^"
        seg_term = "~"
        
        # Element separator is at position 3 (after ISA)
        if len(isa) > 3:
            candidate = isa[3]
            if candidate and candidate != " ":
                elem_sep = candidate
        
        # Component separator is at end of ISA (last char before ~ or end)
        if isa.endswith("~"):
            comp_sep = isa[-2]
        elif len(isa) > 3:
            # Find last element separator and get char after it
            last_sep = isa.rfind(elem_sep)
            if last_sep >= 0 and last_sep + 1 < len(isa):
                potential = isa[last_sep + 1]
                if potential and potential != " ":
                    comp_sep = potential
        
        # Repetition separator (ISA-11) - element 11 (1-indexed)
        try:
            parts = isa.split(elem_sep)
            if len(parts) > 11:
                rep = parts[11].strip()
                if rep and len(rep) == 1:
                    rep_sep = rep
        except Exception:
            pass  # keep default
        
        return elem_sep, comp_sep, rep_sep, seg_term

    def _parse(self) -> None:
        if self._parsed:
            return
        text = self._raw_text
        if not text.strip():
            self._parsed = True
            return

        elem_sep, comp_sep, rep_sep, seg_term = self._detect_delimiters(text)
        tokenizer = X12Tokenizer(seg_term=seg_term, elem_sep=elem_sep)
        raw_segs = tokenizer.tokenize(text)

        # Update segment parser with detected element separator
        self._seg_parser = X12SegmentParser(elem_sep=elem_sep)
        self.segments = [
            self._seg_parser.parse(raw=s, position=i + 1)
            for i, s in enumerate(raw_segs)
        ]

        self.interchanges = self._build_interchanges()

    def _find_segment(self, tag: str, start: int = 0) -> Optional[tuple[Segment, int]]:
        for i in range(start, len(self.segments)):
            if self.segments[i].tag == tag:
                return (self.segments[i], i)
        return None

    def _build_interchanges(self) -> List[Interchange]:
        interchanges: List[Interchange] = []
        if not self.segments:
            return interchanges
        i = 0
        while i < len(self.segments):
            seg = self.segments[i]
            if seg.tag == "ISA":
                isa = seg
                iea_idx = self._find_matching_trailer(i + 1, "IEA", "ISA")
                iea = self.segments[iea_idx] if iea_idx >= 0 else None
                groups = self._build_groups(i + 1, iea_idx - 1 if iea_idx > i else len(self.segments) - 1)

                # ISA-6 = sender ID, ISA-7 = sender qualifier, ISA-8 = receiver qualifier,
                # ISA-9 = receiver ID (fixed-width X12 ISA; qualifiers prefix IDs).
                sender = (self._seg_parser.get(isa, 6) or "").strip()
                receiver = (self._seg_parser.get(isa, 8) or "").strip()

                ic = Interchange(
                    header=isa,
                    groups=groups,
                    trailer=iea if iea else Segment("", [], "", 0),
                    isa06_sender=sender,
                    isa08_receiver=receiver,
                )
                interchanges.append(ic)
                i = iea_idx + 1 if iea_idx > i else i + 1
            else:
                i += 1
        return interchanges

    def _build_groups(self, start: int, end: int) -> List[FunctionalGroup]:
        groups: List[FunctionalGroup] = []
        i = start
        while i <= end and i < len(self.segments):
            seg = self.segments[i]
            if seg.tag == "GS":
                gs = seg
                # Find GE
                ge_idx = self._find_matching_trailer(i + 1, "GE", "GS")
                ge = self.segments[ge_idx] if ge_idx >= 0 else None
                transactions = self._build_transactions(i + 1, ge_idx - 1 if ge_idx > i else end)
                fg = FunctionalGroup(header=gs, transactions=transactions,
                                     trailer=ge if ge else Segment("", [], "", 0))
                groups.append(fg)
                i = ge_idx + 1 if ge_idx > i else i + 1
            else:
                i += 1
        return groups

    def _build_transactions(self, start: int, end: int) -> List[TransactionSet]:
        transactions: List[TransactionSet] = []
        i = start
        while i <= end and i < len(self.segments):
            seg = self.segments[i]
            if seg.tag == "ST":
                st = seg
                set_id = self._seg_parser.get(st, 1) or self._seg_parser.get(st, 2) or "?"
                # Find SE
                se_idx = self._find_matching_trailer(i + 1, "SE", "ST")
                se = self.segments[se_idx] if se_idx >= 0 else None
                body = self.segments[i + 1: se_idx] if se_idx > i else []
                seg_objs = [
                    self._seg_parser.parse(raw=s.raw, position=s.position)
                    for s in body
                ]
                loops = _detect_loops(seg_objs)
                ts = TransactionSet(header=st, loops=loops,
                                    trailer=se if se else Segment("", [], "", 0),
                                    set_id=set_id)
                transactions.append(ts)
                i = se_idx + 1 if se_idx > i else i + 1
            else:
                i += 1
        return transactions

    def _find_matching_trailer(self, start: int, trailer_tag: str, header_tag: str) -> int:
        """Find trailer by counting header/trailer pairs (ST/SE, GS/GE, ISA/IEA)."""
        depth = 0
        for i in range(start, len(self.segments)):
            t = self.segments[i].tag
            if t == header_tag:
                depth += 1
            elif t == trailer_tag:
                if depth == 0:
                    return i
                depth -= 1
        return -1

    # ── Transaction summary helpers ─────────────────────────────────────────────

    def _seg_get(self, seg: Segment, index: int, sub_index: Optional[int] = None) -> Optional[str]:
        """Get element value from a Segment, optionally sub-element."""
        return self._seg_parser.get(seg, index, sub_index)

    def _get_gs_version(self, fg: FunctionalGroup) -> Optional[str]:
        """Return the version string from GS-8 (e.g., '005010X221A1')."""
        return self._seg_get(fg.header, 8)

    def _get_gs_functional_code(self, fg: FunctionalGroup) -> Optional[str]:
        """Return the GS functional code (e.g., 'HP', 'HC', 'HI')."""
        return self._seg_get(fg.header, 1)

    def _detect_837_variant(self, ts: TransactionSet) -> dict:
        """
        Detect whether an 837 transaction is Professional, Institutional, or Dental
        based on segment content.

        Returns a dict with keys: variant, service_line_type, indicator.
        Indicator is a short code: 'P' (professional), 'I' (institutional), 'D' (dental).
        """
        all_tags: set[str] = set()
        has_sv1 = has_sv2 = has_ud = False
        for loop in ts.loops:
            for seg in loop.segments:
                all_tags.add(seg.tag)
                if seg.tag == "SV1":
                    has_sv1 = True
                elif seg.tag == "SV2":
                    has_sv2 = True
                elif seg.tag == "UD":
                    has_ud = True

        # SV2 is institutional-only; UD is dental-only; SV1 is professional-only
        if has_ud and not has_sv1:
            variant = "dental"
            indicator = "D"
            service_type = "dental"
        elif has_sv2 and not has_sv1:
            variant = "institutional"
            indicator = "I"
            service_type = "institutional"
        elif has_sv1:
            variant = "professional"
            indicator = "P"
            service_type = "professional"
        else:
            # Fallback: check for specific NM1 qualifiers that appear in each variant
            nm1_77 = any(
                loop.leader_tag == "NM1" and loop.leader_code == "77"
                for loop in ts.loops
            )
            if nm1_77:
                variant = "institutional"
                indicator = "I"
                service_type = "institutional"
            else:
                variant = "professional"
                indicator = "P"
                service_type = "professional"

        return {
            "variant": variant,
            "indicator": indicator,
            "service_line_type": service_type,
            "has_sv1": has_sv1,
            "has_sv2": has_sv2,
            "has_ud": has_ud,
        }

    def _compute_835_summary(self, ts: TransactionSet) -> dict:
        """
        Compute financial summary for an 835 transaction.

        Financial totals (billed/allowed/paid) are extracted from CLP segment
        element positions per X12 835 specification. Note: some 835 variants
        use non-standard CLP positions; verify against your trading-partner
        implementation if amounts appear unexpectedly zero.

        Includes claim-level rollups and reconciliation helpers:
        - per-claim billed/paid/adjustment totals
        - service-line aggregation per claim
        - discrepancy flags for CLP-vs-SVC amount mismatches
        - PLB-level adjustment summary
        """
        summary = {
            "set_id": ts.set_id,
            "segment_count": len(ts.loops) and sum(len(l.segments) for l in ts.loops) or 0,
            "loop_count": len(ts.loops),
        }

        total_billed = 0.0
        total_allowed = 0.0
        total_paid = 0.0
        total_adjustment = 0.0
        payment_amount = None
        check_trace = None
        payer_name = None
        provider_name = None
        claim_count = 0
        service_line_count = 0
        plb_count = 0
        # Track claim IDs to detect duplicates
        claim_ids: List[str] = []
        duplicate_claim_ids: List[str] = []

        # ── Claim-level rollup (sequential loop walk) ────────────────────
        # In the detected loop structure, CLP, LX, SVC, CAS are separate loop leaders.
        # We walk loops sequentially: CLP starts a claim, SVC/CAS accumulate to it.
        # NM1*QC (patient) may appear between CLP and SVC — capture the name.
        #
        # 835 X12 has two common structures for LX/CLP/SVC grouping:
        #   (a) CLP inside LX loop  → handled by finding CLP in LX loop segments
        #   (b) CLP as own loop     → handled by detecting CLP loop + following SVC
        # Both are supported by scanning loops sequentially.
        claims: list[dict] = []
        discrepancies: list[dict] = []
        current_claim: Optional[dict] = None

        # PLB summary: accumulate by adjustment reason code
        plb_by_code: dict[str, float] = {}

        for loop in ts.loops:
            if loop.leader_tag == "PLB":
                plb_count += 1
                for seg in loop.segments:
                    if seg.tag == "PLB":
                        # PLB e3 = adjustment code:claim reference (e.g. "CV:CLP001")
                        # PLB e4 = adjustment amount
                        ref = self._seg_get(seg, 3) or ""
                        raw_adj = self._seg_get(seg, 4) or ""
                        if ref and raw_adj:
                            try:
                                adj_val = float(raw_adj)
                                code = ref.split(":")[0] if ":" in ref else ref
                                plb_by_code[code] = plb_by_code.get(code, 0.0) + adj_val
                            except ValueError:
                                pass
                continue

            if loop.leader_tag == "CLP":
                # Close previous claim (deferred — CAS may appear after the next CLP
                # but belong to the current claim's service lines)
                if current_claim is not None:
                    claims.append(current_claim)

                clp_seg = loop.segments[0] if loop.segments else None
                clp_id = self._seg_get(clp_seg, 1) or "?"

                def _first_numeric(*indexes: int) -> float:
                    for idx in indexes:
                        raw = self._seg_get(clp_seg, idx)
                        if raw not in (None, ""):
                            try:
                                return float(raw)
                            except ValueError:
                                continue
                    return 0.0

                def _first_value(*indexes: int) -> str:
                    for idx in indexes:
                        raw = self._seg_get(clp_seg, idx)
                        if raw not in (None, ""):
                            return raw
                    return "?"

                # Support both simplified internal fixtures and richer external-style 835 CLP layouts.
                clp_status = _first_value(3, 6)
                clp_billed = _first_numeric(2, 5)
                clp_paid = _first_numeric(4, 7)
                clp_allowed = _first_numeric(5, 7)

                current_claim = {
                    "claim_id": clp_id,
                    "status_code": clp_status,
                    "patient_name": None,
                    "clp_billed": round(clp_billed, 2),
                    "clp_allowed": round(clp_allowed, 2),
                    "clp_paid": round(clp_paid, 2),
                    "clp_adjustment": 0.0,
                    "svc_billed": 0.0,
                    "svc_paid": 0.0,
                    "service_line_count": 0,
                    "has_billed_discrepancy": False,
                    "has_paid_discrepancy": False,
                    "adjustment_group_codes": set(),
                }
                claim_count += 1
                total_billed += clp_billed
                total_paid += clp_paid
                total_allowed += clp_allowed

                if clp_id in claim_ids and clp_id not in duplicate_claim_ids:
                    duplicate_claim_ids.append(clp_id)
                claim_ids.append(clp_id)
                continue

            if loop.leader_tag == "CAS":
                # Accumulate CAS adjustments into current claim.
                # In X12 the CAS group can appear either before or after SVC
                # within the same LX loop. For the sequential walk we assign
                # it to whichever claim is currently open.
                if current_claim is not None:
                    for seg in loop.segments:
                        if seg.tag == "CAS":
                            grp_code = self._seg_get(seg, 2)
                            if grp_code:
                                current_claim["adjustment_group_codes"].add(grp_code)
                            # CAS elements: e1=group_code, e2=reason1, e3=amount1, e4=reason2, e5=amount2...
                            # Amounts are at odd 1-indexed positions: e3, e5, e7...
                            for e_idx in range(3, min(len(seg.elements) + 1, 19), 2):
                                raw = self._seg_get(seg, e_idx)
                                if raw:
                                    try:
                                        adj = float(raw)
                                        current_claim["clp_adjustment"] += adj
                                        total_adjustment += adj
                                    except ValueError:
                                        pass
                continue

            if loop.leader_tag in ("SVC", "SV1", "SV2", "SV3"):
                # SVC-led loop: one service line per such loop
                if current_claim is not None:
                    for seg in loop.segments:
                        if seg.tag in ("SVC", "SV1", "SV2", "SV3"):
                            try:
                                # SVC e2=billed, e3=paid (different from CLP where e4=paid)
                                svc_b = float(self._seg_get(seg, 2) or "0")
                                svc_p = float(self._seg_get(seg, 3) or "0")
                                current_claim["svc_billed"] += svc_b
                                current_claim["svc_paid"] += svc_p
                            except ValueError:
                                pass
                    current_claim["service_line_count"] += 1
                    service_line_count += 1
                continue

            # Other loops (LX, DTM, REF, PER, etc.) — check for embedded SVC
            # SVC can be absorbed into non-SVC loop leaders (e.g. DTM or bare loops)
            # Only count it if it looks like a service-line loop:
            # - SVC present AND loop has ≤ 5 segments (avoids false positives)
            if current_claim is not None:
                svc_segs_in_loop = [s for s in loop.segments
                                    if s.tag in ("SVC", "SV1", "SV2", "SV3")]
                if svc_segs_in_loop and len(loop.segments) <= 5:
                    for seg in svc_segs_in_loop:
                        try:
                            svc_b = float(self._seg_get(seg, 2) or "0")
                            svc_p = float(self._seg_get(seg, 3) or "0")
                            current_claim["svc_billed"] += svc_b
                            current_claim["svc_paid"] += svc_p
                        except ValueError:
                            pass
                    current_claim["service_line_count"] += len(svc_segs_in_loop)
                    service_line_count += len(svc_segs_in_loop)
                continue

            if loop.leader_tag == "NM1" and loop.leader_code == "QC":
                # Patient NM1 — capture name for current claim
                if current_claim is not None and current_claim["patient_name"] is None:
                    for seg in loop.segments:
                        if seg.tag == "NM1":
                            name = " ".join(filter(None, [
                                self._seg_get(seg, 3),
                                self._seg_get(seg, 4),
                            ]))
                            if name:
                                current_claim["patient_name"] = name
                            break
                continue

            # Other loops (BPR, TRN, DTM, N1, REF, PER, LX header, etc.)
            for seg in loop.segments:
                if seg.tag == "BPR":
                    raw_amt = self._seg_get(seg, 2)
                    if raw_amt:
                        try:
                            payment_amount = float(raw_amt)
                        except ValueError:
                            pass
                    check_trace = self._seg_get(seg, 16)
                elif seg.tag == "TRN":
                    check_trace = self._seg_get(seg, 2)
                elif seg.tag == "N1":
                    entity = self._seg_get(seg, 1) or "?"
                    name = self._seg_get(seg, 2) or "?"
                    if entity == "PR":
                        payer_name = name
                    elif entity == "PE":
                        provider_name = name

        if current_claim is not None:
            claims.append(current_claim)

        # ── Post-pass: discrepancy checks ─────────────────────────────────
        # Denied/pended status codes that should normally have zero or minimal payment
        DENIED_OR_PEND_STATUSES = frozenset(("4", "8", "16", "17", "24"))

        for cl in claims:
            # 1. Billed amount mismatch (CLP vs SVC)
            billed_diff = round(abs(cl["clp_billed"] - cl["svc_billed"]), 2)
            if cl["clp_billed"] > 0 and billed_diff > 0.01:
                cl["has_billed_discrepancy"] = True
                disc_meta = _DISCREPANCY_TAXONOMY.get("billed_mismatch", {})
                discrepancies.append({
                    "type": "billed_mismatch",
                    "severity": disc_meta.get("severity", "warning"),
                    "description": disc_meta.get("description", ""),
                    "claim_id": cl["claim_id"],
                    "clp_billed": cl["clp_billed"],
                    "sum_svc_billed": round(cl["svc_billed"], 2),
                    "difference": billed_diff,
                    "note": "CLP billed amount differs from sum of SVC billed amounts; "
                            "verify CLP element 2 matches individual SVC billed amounts",
                })

            # 2. Paid amount mismatch (CLP vs SVC)
            paid_diff = round(abs(cl["clp_paid"] - cl["svc_paid"]), 2)
            if cl["clp_paid"] > 0 and paid_diff > 0.01:
                cl["has_paid_discrepancy"] = True
                disc_meta = _DISCREPANCY_TAXONOMY.get("paid_mismatch", {})
                discrepancies.append({
                    "type": "paid_mismatch",
                    "severity": disc_meta.get("severity", "warning"),
                    "description": disc_meta.get("description", ""),
                    "claim_id": cl["claim_id"],
                    "clp_paid": cl["clp_paid"],
                    "sum_svc_paid": round(cl["svc_paid"], 2),
                    "difference": paid_diff,
                    "note": "CLP paid amount differs from sum of SVC paid amounts; "
                            "verify CLP element 4 matches individual SVC paid amounts",
                })

            # 3. Zero-pay / denied status inconsistency
            # If CLP status is denial/pend but SVC shows non-zero paid, flag it.
            # This is informational — some partial payments exist during pend.
            if cl["status_code"] in DENIED_OR_PEND_STATUSES and cl["svc_paid"] > 0.01:
                disc_meta = _DISCREPANCY_TAXONOMY.get("zero_pay_inconsistency", {})
                discrepancies.append({
                    "type": "zero_pay_inconsistency",
                    "severity": disc_meta.get("severity", "info"),
                    "description": disc_meta.get("description", ""),
                    "claim_id": cl["claim_id"],
                    "status_code": cl["status_code"],
                    "status_label": cl.get("status_label", ""),
                    "clp_paid": cl["clp_paid"],
                    "svc_paid": round(cl["svc_paid"], 2),
                    "difference": round(cl["svc_paid"], 2),
                    "note": f"CLP status {cl['status_code']} ({cl.get('status_label', '')}) "
                            f"suggests denial/pend but service lines show non-zero payment of "
                            f"${round(cl['svc_paid'], 2)}; "
                            f"verify whether payment was actually issued",
                })

            # Save sorted list before enrichment overwrites it
            sorted_codes = sorted(cl["adjustment_group_codes"])
            cl["_adjustment_codes_sorted"] = sorted_codes

        # ── BPR metadata enrichment ─────────────────────────────────────────
        bpr_payment_method = None
        bpr_account_type = None
        for loop in ts.loops:
            for seg in loop.segments:
                if seg.tag == "BPR":
                    bpr_payment_method = self._seg_get(seg, 1)   # C=check, H=ACH, etc.
                    bpr_account_type = self._seg_get(seg, 15)   # checking/savings
                    break

        # ── Enrich claim records with status descriptions ───────────────────
        for cl in claims:
            sc = cl.get("status_code", "?")
            status_info = _CLP_STATUS_CODES.get(sc, {"label": f"Unknown ({sc})", "category": "unknown"})
            cl["status_label"] = status_info["label"]
            cl["status_category"] = status_info["category"]

        # ── Balancing summary ────────────────────────────────────────────────
        # Computes overall reconciliation status at each 835 payment level.
        # These are helpers for review — they do not assert accounting truth.
        #
        # Level 1 — Payment amount vs sum of paid amounts:
        #   In a balanced 835: BPR amount ≈ sum(CLP paid) + PLB adjustments.
        #   Since many payers put paid amounts in SVC rather than CLP e4/e6,
        #   we compute sum_svc_paid as the aggregate of service-line paid amounts.
        #   If CLP paid amounts are also present in the file, they are included
        #   in total_paid and checked in parallel.
        #   The relationship is: sum(paid) + PLB total ≈ BPR payment amount.
        sum_svc_paid = round(sum(cl["svc_paid"] for cl in claims), 2)
        sum_svc_billed = round(sum(cl["svc_billed"] for cl in claims), 2)

        bpr_vs_clp_diff = None
        bpr_vs_clp_balanced = None
        # Prefer SVC-paid sum as the primary reconciliation target since many
        # payers use SVC for payment detail rather than CLP e4/e6.
        reconciliation_target = sum_svc_paid if sum_svc_paid > 0 else total_paid
        if payment_amount is not None and reconciliation_target > 0:
            bpr_vs_clp_diff = round(payment_amount - reconciliation_target, 2)
            # A tolerance of $0.05 accommodates rounding in penny-perfect remits
            bpr_vs_clp_balanced = abs(bpr_vs_clp_diff) <= 0.05

        # Level 2 — PLB total vs expected accounting direction:
        #   PLB adjustments can be positive or negative depending on context.
        #   We track the sign to help reviewers understand direction.
        plb_sign = "positive" if sum(plb_by_code.values()) >= 0 else "negative"

        # Level 3 — Service-line presence:
        #   Claims should have at least one service line unless denied/pended.
        claims_without_svc = [
            cl["claim_id"] for cl in claims
            if cl["service_line_count"] == 0 and cl["status_code"] not in DENIED_OR_PEND_STATUSES
        ]

        balancing_summary = {
            "bpr_payment_amount": payment_amount,
            "sum_clp_paid": round(total_paid, 2),
            "sum_svc_paid": sum_svc_paid,
            "sum_svc_billed": sum_svc_billed,
            "bpr_vs_clp_difference": bpr_vs_clp_diff,
            "bpr_vs_clp_balanced": bpr_vs_clp_balanced,
            "plb_sign": plb_sign,
            "claims_without_service_lines": claims_without_svc,
            "has_claim_discrepancies": any(
                cl["has_billed_discrepancy"] or cl["has_paid_discrepancy"]
                for cl in claims
            ),
            "discrepancy_count": len(discrepancies),
        }

        # Collect claim-level data including status descriptions for top-level summary
        claims_out = []
        for cl in claims:
            # Compute CAS adjustment total by group code for this claim
            cas_by_group: dict[str, float] = {}
            for seg in sum([l.segments for l in ts.loops if l.leader_tag == "CAS"], []):
                if seg.tag == "CAS":
                    grp = self._seg_get(seg, 2) or "?"
                    for e_idx in range(3, min(len(seg.elements) + 1, 19), 2):
                        raw = self._seg_get(seg, e_idx)
                        if raw:
                            try:
                                cas_by_group[grp] = cas_by_group.get(grp, 0.0) + float(raw)
                            except ValueError:
                                pass
            cas_adjustment_sum = round(sum(cas_by_group.values()), 2)

            claims_out.append({
                "claim_id": cl["claim_id"],
                "status_code": cl["status_code"],
                "status_label": cl.get("status_label", ""),
                "status_category": cl.get("status_category", "unknown"),
                "patient_name": cl.get("patient_name"),
                "clp_billed": cl["clp_billed"],
                "clp_allowed": cl["clp_allowed"],
                "clp_paid": cl["clp_paid"],
                "clp_adjustment": round(cl["clp_adjustment"], 2),
                "svc_billed": round(cl["svc_billed"], 2),
                "svc_paid": round(cl["svc_paid"], 2),
                "service_line_count": cl["service_line_count"],
                "has_billed_discrepancy": cl["has_billed_discrepancy"],
                "has_paid_discrepancy": cl["has_paid_discrepancy"],
                "adjustment_group_codes": [
                    {"code": code, "label": _PLB_REASON_CODES.get(code, {"label": code, "category": "other"})["label"]}
                    for code in cl.get("_adjustment_codes_sorted", [])
                ],
                # CAS adjustment totals by group code
                "cas_adjustment_sum": cas_adjustment_sum,
                "cas_adjustments_by_group": {k: round(v, 2) for k, v in cas_by_group.items()},
            })

        summary.update({
            "payment_amount": payment_amount,
            "check_trace": check_trace,
            "total_billed_amount": round(total_billed, 2),
            "total_allowed_amount": round(total_allowed, 2),
            "total_paid_amount": round(total_paid, 2),
            "total_adjustment_amount": round(total_adjustment, 2),
            "net_difference": round(total_billed - total_paid - total_adjustment, 2),
            "claim_count": claim_count,
            "service_line_count": service_line_count,
            "plb_count": plb_count,
            "duplicate_claim_ids": duplicate_claim_ids,
            "payer_name": payer_name,
            "provider_name": provider_name,
            # Enrichment
            "bpr_payment_method": bpr_payment_method,
            "bpr_payment_method_label": {"C": "Check", "H": "ACH"}.get(bpr_payment_method),
            "bpr_account_type": bpr_account_type,
            # Reconciliation helpers
            "balancing_summary": balancing_summary,
            "claims": claims_out,
            "discrepancies": discrepancies,
            "plb_summary": {
                "adjustment_by_code": {k: round(v, 2) for k, v in plb_by_code.items()},
                "adjustment_labels": {
                    k: _PLB_REASON_CODES.get(k, {"label": k, "category": "other"})["label"]
                    for k in plb_by_code
                },
                "total_plb_adjustment": round(sum(plb_by_code.values()), 2),
            },
        })
        return summary

    def _compute_837_summary(self, ts: TransactionSet) -> dict:
        """
        Compute summary for an 837 transaction.

        Includes hierarchy reconstruction (billing provider / subscriber / patient
        levels from HL parent-child structure) and structured claim records
        with service-line aggregation.
        """
        total_billed = 0.0
        claim_count = 0
        service_line_count = 0
        hl_count = 0
        clm_ids: List[str] = []
        duplicate_clm_ids: List[str] = []
        billing_provider = None
        payer_name = None
        submitter_name = None
        subscriber_name = None
        patient_name = None
        bht_id = None
        bht_date = None

        # ── Hierarchy reconstruction ─────────────────────────────────────
        # Build HL parent-child tree.  X12 HL format:
        #   HL*01*parent*level_code*hier_child_code
        #   e1=ID, e2=parent_ID (absent for root), e3=level_code, e4=child_code
        # Level codes: 20=billing provider, 22=subscriber, 23=patient
        hl_by_id: dict[str, dict] = {}
        hl_sequence: list[dict] = []   # preserves file order
        for loop in ts.loops:
            for seg in loop.segments:
                if seg.tag == "HL":
                    hl_id = self._seg_get(seg, 1) or ""
                    hl_parent = self._seg_get(seg, 2) or ""
                    hl_level = self._seg_get(seg, 3) or ""
                    hl_child = self._seg_get(seg, 4) or ""
                    entry = {
                        "id": hl_id,
                        "parent_id": hl_parent,
                        "level_code": hl_level,
                        "child_code": hl_child,
                        "loop": loop,
                    }
                    hl_by_id[hl_id] = entry
                    hl_sequence.append(entry)

        # Identify hierarchy levels
        billing_provider_hl = None
        subscriber_hl = None
        patient_hl = None
        for entry in hl_sequence:
            lc = entry["level_code"]
            if lc == "20" and billing_provider_hl is None:
                billing_provider_hl = entry
            elif lc == "22" and subscriber_hl is None:
                subscriber_hl = entry
            elif lc == "23" and patient_hl is None:
                patient_hl = entry

        # ── Variant detection (837P vs 837I vs 837D) ────────────────────────
        variant_info = self._detect_837_variant(ts)

        # In the detected loop structure, NM1 is often a separate loop leader that
        # immediately follows its associated HL loop. We scan loops sequentially
        # and attach NM1 names to the most recent open HL level.
        # Valid entity qualifiers per level:
        #   level 20 (billing provider): NM1 qualifiers 41, 85
        #   level 22 (subscriber):      NM1 qualifiers IL, QC, PR
        #   level 23 (patient):          NM1 qualifiers QC, IL
        VALID_BP_QUALIFIERS = frozenset(("41", "85"))
        VALID_SUB_QUALIFIERS = frozenset(("IL", "QC", "PR"))

        last_hl_entry: Optional[dict] = None
        for loop in ts.loops:
            if loop.leader_tag == "HL":
                # Find corresponding hl_entry
                for e in hl_sequence:
                    if e["loop"] is loop:
                        last_hl_entry = e
                        break
            elif loop.leader_tag == "NM1":
                if last_hl_entry is not None:
                    seg0 = loop.segments[0] if loop.segments else None
                    if seg0:
                        qual = self._seg_get(seg0, 1) or ""
                        lc = last_hl_entry["level_code"]
                        if lc == "20" and qual in VALID_BP_QUALIFIERS:
                            last_hl_entry["_nm1_name"] = " ".join(filter(None, [
                                self._seg_get(seg0, 3),
                                self._seg_get(seg0, 4),
                            ])) or None
                        elif lc in ("22", "23") and qual in VALID_SUB_QUALIFIERS:
                            last_hl_entry["_nm1_name"] = " ".join(filter(None, [
                                self._seg_get(seg0, 3),
                                self._seg_get(seg0, 4),
                            ])) or None

        def _hl_nm1_name(hl_entry: Optional[dict]) -> Optional[str]:
            if hl_entry is None:
                return None
            return hl_entry.get("_nm1_name")

        hierarchy = {
            "billing_provider_hl_id": billing_provider_hl["id"] if billing_provider_hl else None,
            "subscriber_hl_id": subscriber_hl["id"] if subscriber_hl else None,
            "patient_hl_id": patient_hl["id"] if patient_hl else None,
            "billing_provider_name": _hl_nm1_name(billing_provider_hl),
            "subscriber_name": _hl_nm1_name(subscriber_hl),
            "patient_name": _hl_nm1_name(patient_hl),
            "hl_tree": [
                {
                    "id": e["id"],
                    "parent_id": e["parent_id"] or None,
                    "level_code": e["level_code"],
                    "child_code": e["child_code"],
                    "level_role": (
                        "billing_provider" if e["level_code"] == "20"
                        else "subscriber" if e["level_code"] == "22"
                        else "patient" if e["level_code"] == "23"
                        else "other"
                    ),
                }
                for e in hl_sequence
            ],
        }

        # ── Claim + service-line aggregation ──────────────────────────────
        # Walk loops in order. CLM starts a claim; LX SV1/SV2 are service lines.
        claims: list[dict] = []
        current_claim: Optional[dict] = None
        current_claim_loops: List[Loop] = []
        current_clm_loop: Optional[Loop] = None

        for loop in ts.loops:
            if loop.leader_tag in ("SV1", "SV2", "SV3"):
                # Service line — attach to current claim
                if current_claim is not None:
                    # Accumulate from this service-line loop
                    sv_billed = 0.0
                    sv_paid = 0.0
                    svc_segment = None
                    for seg in loop.segments:
                        if seg.tag in ("SV1", "SV2", "SV3"):
                            svc_segment = seg
                            try:
                                sv_billed += float(self._seg_get(seg, 3) or "0")
                                sv_paid += float(self._seg_get(seg, 4) or "0")
                            except ValueError:
                                pass
                    if current_claim is not None:
                        current_claim["service_lines"].append({
                            "loop_id": loop.id,
                            "billed": round(sv_billed, 2),
                            "paid": round(sv_paid, 2),
                            "service_line_count": 1,
                        })
                        current_claim["total_svc_billed"] += sv_billed
                        current_claim["total_svc_paid"] += sv_paid
                        service_line_count += 1
            elif loop.leader_tag == "CLM":
                # New claim
                if current_claim is not None:
                    claims.append(current_claim)
                clm_seg = loop.segments[0] if loop.segments else None
                clm_id = self._seg_get(clm_seg, 1) if clm_seg else None
                clm_billed = 0.0
                try:
                    clm_billed = float(self._seg_get(clm_seg, 2) or "0")
                except ValueError:
                    pass
                current_claim = {
                    "claim_id": clm_id,
                    "clp_billed": round(clm_billed, 2),
                    "total_svc_billed": 0.0,
                    "total_svc_paid": 0.0,
                    "service_lines": [],
                    "has_discrepancy": False,
                    "discrepancy_reason": None,
                }
                claim_count += 1
            else:
                # Header/entity segments — attach to current claim if any
                if current_claim is not None:
                    current_claim_loops.append(loop)

        if current_claim is not None:
            claims.append(current_claim)

        # Check billed amount discrepancies (CLP vs sum of SVC)
        for cl in claims:
            diff = round(abs(cl["clp_billed"] - cl["total_svc_billed"]), 2)
            if cl["clp_billed"] > 0 and diff > 0.01:
                cl["has_discrepancy"] = True
                cl["discrepancy_reason"] = (
                    f"CLP billed ({cl['clp_billed']}) differs from "
                    f"sum of SVC billed ({round(cl['total_svc_billed'], 2)})"
                )

        # ── Overall totals (scan remaining segments) ─────────────────────
        for loop in ts.loops:
            for seg in loop.segments:
                if seg.tag == "BHT":
                    bht_id = self._seg_get(seg, 3)
                    bht_date = self._seg_get(seg, 4)
                elif seg.tag == "CLM":
                    clm_id = self._seg_get(seg, 1) or "?"
                    if clm_id in clm_ids and clm_id not in duplicate_clm_ids:
                        duplicate_clm_ids.append(clm_id)
                    clm_ids.append(clm_id)
                    try:
                        total_billed += float(self._seg_get(seg, 2) or "0")
                    except ValueError:
                        pass
                elif seg.tag == "HL":
                    hl_count += 1
                elif seg.tag == "NM1":
                    entity = self._seg_get(seg, 1) or "?"
                    name = " ".join(filter(None, [
                        self._seg_get(seg, 3),
                        self._seg_get(seg, 4),
                    ]))
                    if entity == "41":
                        submitter_name = name
                    elif entity == "40":
                        payer_name = name
                    elif entity == "85":
                        billing_provider = name
                    elif entity == "IL":
                        subscriber_name = name
                    elif entity == "QC":
                        patient_name = name

        return {
            "set_id": ts.set_id,
            "segment_count": len(ts.loops) and sum(len(l.segments) for l in ts.loops) or 0,
            "loop_count": len(ts.loops),
            "total_billed_amount": round(total_billed, 2),
            "claim_count": claim_count,
            "service_line_count": service_line_count,
            "hl_count": hl_count,
            "duplicate_claim_ids": duplicate_clm_ids,
            "billing_provider": billing_provider,
            "payer_name": payer_name,
            "submitter_name": submitter_name,
            "subscriber_name": subscriber_name,
            "patient_name": patient_name,
            "bht_id": bht_id,
            "bht_date": bht_date,
            # Variant detection
            "variant": variant_info["variant"],
            "variant_indicator": variant_info["indicator"],
            "service_line_type": variant_info["service_line_type"],
            # Hierarchy and claims fields
            "hierarchy": hierarchy,
            "claims": claims,
        }

    def _parse_summary(self) -> None:
        """Compute and attach summary dict to each TransactionSet."""
        if self._summary_computed:
            return
        for ic in self.interchanges:
            for fg in ic.groups:
                for ts in fg.transactions:
                    if ts.set_id == "835":
                        ts.summary = self._compute_835_summary(ts)
                    elif ts.set_id == "837":
                        ts.summary = self._compute_837_summary(ts)
                    else:
                        ts.summary = {
                            "set_id": ts.set_id,
                            "segment_count": sum(len(l.segments) for l in ts.loops),
                            "loop_count": len(ts.loops),
                        }

    def to_dict(self) -> dict:
        """Return full parsed structure as a plain dict."""
        self._parse()
        self._parse_summary()
        return {
            "version": __version__,
            "schema_version": OUTPUT_SCHEMA_VERSION,
            # Metadata about parsing decisions that may affect downstream consumers
            "metadata": {
                # Loop IDs are derived from the first element of the loop's leader segment
                # (e.g., "PR", "QC", "CLM"). This is a heuristic; verify loop semantics
                # match your expectations for novel transaction types.
                "loop_id_source": "heuristic_first_element",
            },
            "interchanges": [
                {
                    "header": _segment_to_dict(ic.header),
                    "isa06_sender": ic.isa06_sender,
                    "isa08_receiver": ic.isa08_receiver,
                    "functional_groups": [
                        {
                            "header": _segment_to_dict(fg.header),
                            "transactions": [
                                {
                                    "header": _segment_to_dict(ts.header),
                                    "set_id": ts.set_id,
                                    "summary": ts.summary,
                                    "loops": [_loop_to_dict(l) for l in ts.loops],
                                    "trailer": _segment_to_dict(ts.trailer),
                                }
                                for ts in fg.transactions
                            ],
                            "trailer": _segment_to_dict(fg.trailer),
                        }
                        for fg in ic.groups
                    ],
                    "trailer": _segment_to_dict(ic.trailer),
                }
                for ic in self.interchanges
            ],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# ── Public helpers ─────────────────────────────────────────────────────────────

def parse(text: str) -> X12Parser:
    p = X12Parser(text)
    p._parse()
    return p

def parse_file(path: str | pathlib.Path) -> X12Parser:
    p = X12Parser.from_file(path)
    p._parse()
    return p
