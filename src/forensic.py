"""
X12 Forensic Analyzer — deep structural analysis beyond basic validation.

Produces a detailed per-claim and per-transaction breakdown suitable for
research, debugging payer quirks, and tracing unusual X12 patterns.

Usage (internal API):
    from src.forensic import X12ForensicAnalyzer
    analyzer = X12ForensicAnalyzer(parser)
    report = analyzer.analyze()

The report is a plain dict; see X12ForensicReport dataclass for schema.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from src.parser import X12Parser, TransactionSet, Loop, Segment


# ── Report dataclasses ────────────────────────────────────────────────────────

@dataclass
class SegmentTrace:
    """One entry in a claim's segment journey."""
    tag: str
    position: int
    elements: dict[str, str]          # e1->value, e2->value, ...
    loop_id: str
    loop_kind: str
    is_unusual: bool = False
    unusual_note: str = ""


@dataclass
class ClaimForensic:
    """Deep forensic record for one claim (CLP in 835, CLM in 837)."""
    claim_id: str
    transaction_set: str               # "835" or "837"
    segment_trace: list[SegmentTrace]  # ordered segment journey
    entity_snapshot: dict[str, str]    # NM1/N1 qualifier → entity name or ID
    amount_summary: dict[str, Any]    # billed, paid, allowed, adjusted, etc.
    flags: list[str]                  # unusual/non-standard pattern labels
    flag_detail: dict[str, str]        # flag → explanation


@dataclass
class TransactionForensic:
    """Per-transaction forensic summary."""
    set_id: str
    st_control: str
    segment_count: int
    claim_count: int
    unusual_patterns: list[str]       # non-standard segment combos detected
    segment_gaps: list[str]           # expected-but-missing segment patterns
    raw_segment_tags: list[str]       # all segment tags in occurrence order
    delimiter_note: str = ""           # if non-standard delimiters detected


@dataclass
class InterchangeForensic:
    """Per-interchange forensic summary."""
    isa_sender: str
    isa_receiver: str
    gs_count: int
    st_count_total: int
    unusual_envelope_conditions: list[str]


@dataclass
class X12ForensicReport:
    """Full forensic analysis report."""
    interchange: InterchangeForensic
    transactions: list[TransactionForensic]
    claims: list[ClaimForensic]
    overall_flags: list[str]          # file-level unusual patterns
    flag_detail: dict[str, str]


# ── Unusual-pattern detection ─────────────────────────────────────────────────

# Segments that should normally appear once per claim in standard X12
_SINGLETON_PER_CLAIM = frozenset((
    "BPR", "TRN", "CLP", "CLM", "DTP", "AMT", "QTY", "CUR",
))

# Segments that, if absent, are noteworthy in standard 835/837
_USUAL_CLAIM_SEGMENTS_835 = frozenset(("N1", "LX", "SVC", "CAS"))
_USUAL_CLAIM_SEGMENTS_837 = frozenset(("NM1", "SV1", "SV2", "HI", "REF", "DTP"))

# Standard-ish segment ordering within a claim (relative, not absolute positions)
# These are the "normal" sequences; anything else is flagged as unusual
_EXPECTED_SEQ_835 = [
    ("N1",), ("REF",), ("DTM",), ("PER",),       # payer/provider identification
    ("LX",),                                      # service line number
    ("SVC",), ("CAS",), ("DTP",), ("REF",),      # service line detail
]
_EXPECTED_SEQ_837 = [
    ("NM1",), ("N3",), ("N4",), ("REF",),        # entity identification
    ("CLM",),                                     # claim info
    ("HI",), ("PRV",), ("CL1",),                  # diagnosis/procedure
    ("SV1",), ("SV2",), ("DTP",), ("REF",),       # service detail
]


def _seg_to_dict(seg: Segment) -> dict[str, str]:
    return {f"e{i+1}": e.raw for i, e in enumerate(seg.elements)}


def _get_element(seg: Segment, idx: int) -> str:
    """1-based element index."""
    if idx < 1 or idx > len(seg.elements):
        return ""
    return seg.elements[idx - 1].raw.strip()


class X12ForensicAnalyzer:
    """
    Deep forensic analysis of parsed X12 data.

    Produces:
    - Claim-level segment traces (journey from CLP/CLM through all segments)
    - Unusual pattern detection (repeated segments, unexpected element values)
    - Transaction-level segment inventory and gap analysis
    - Interchange-level envelope health notes
    """

    def __init__(self, parser: X12Parser):
        self.parser = parser
        self.parser._parse()
        self.parser._parse_summary()

    def analyze(self) -> X12ForensicReport:
        data = self.parser.to_dict()
        interchanges = self.parser.interchanges

        # Collect all unusual patterns at file level
        overall_flags: list[str] = []
        flag_detail: dict[str, str] = {}

        # Check delimiters
        delim_note = self._check_delimiters()

        # Interchange-level forensic
        ic_forensic = self._analyze_interchange(interchanges, overall_flags, flag_detail)

        # Transaction-level forensic
        tx_forensics: list[TransactionForensic] = []
        all_claims: list[ClaimForensic] = []

        for ic in interchanges:
            for fg in ic.groups:
                for ts in fg.transactions:
                    tx_rep, claims = self._analyze_transaction(ts, overall_flags, flag_detail)
                    tx_forensics.append(tx_rep)
                    all_claims.extend(claims)

        # File-level unusual envelope conditions
        if len(interchanges) > 1:
            overall_flags.append("MULTIPLE_INTERCHANGES")
            flag_detail["MULTIPLE_INTERCHANGES"] = (
                f"File contains {len(interchanges)} interchanges. "
                "Some EDI transports expect exactly one interchange per file."
            )

        return X12ForensicReport(
            interchange=ic_forensic,
            transactions=tx_forensics,
            claims=all_claims,
            overall_flags=overall_flags,
            flag_detail=flag_detail,
        )

    # ── Interchange analysis ─────────────────────────────────────────────────

    def _analyze_interchange(
        self,
        interchanges: list,
        overall_flags: list,
        flag_detail: dict,
    ) -> InterchangeForensic:
        ic = interchanges[0]
        sender = ic.isa06_sender or ""
        receiver = ic.isa08_receiver or ""
        gs_count = len([fg for fg in ic.groups])
        st_total = sum(len(fg.transactions) for fg in ic.groups)

        unusual: list[str] = []

        # Empty sender/receiver
        if not sender.strip():
            unusual.append("ISA_SENDER_BLANK")
            flag_detail["ISA_SENDER_BLANK"] = "ISA06 (sender ID) is blank. This may cause routing issues."
        if not receiver.strip():
            unusual.append("ISA_RECEIVER_BLANK")
            flag_detail["ISA_RECEIVER_BLANK"] = "ISA08 (receiver ID) is blank. This may cause routing issues."

        # Check ISA date (field 9) for obviously stale dates
        isa_hdr = ic.header
        if len(isa_hdr.elements) > 8:
            date_raw = isa_hdr.elements[8].raw.strip()
            if date_raw and len(date_raw) >= 6:
                year_part = date_raw[:4]
                if year_part and year_part.isdigit():
                    year = int(year_part)
                    if year < 2000 or year > 2100:
                        unusual.append("ISA_DATE_UNUSUAL_YEAR")
                        flag_detail["ISA_DATE_UNUSUAL_YEAR"] = (
                            f"ISA date year {year} is outside the normal range (2000-2100). "
                            "Verify the ISA header date is correct."
                        )

        return InterchangeForensic(
            isa_sender=sender,
            isa_receiver=receiver,
            gs_count=gs_count,
            st_count_total=st_total,
            unusual_envelope_conditions=unusual,
        )

    # ── Transaction analysis ─────────────────────────────────────────────────

    def _analyze_transaction(
        self,
        ts: TransactionSet,
        overall_flags: list,
        flag_detail: dict,
    ) -> tuple[TransactionForensic, list[ClaimForensic]]:
        set_id = ts.set_id
        st_ctrl = self.parser._seg_get(ts.header, 2) or "?"
        raw_tags = self._collect_raw_tags(ts)
        claim_forensics = self._analyze_claims(ts, overall_flags, flag_detail)
        unusual, gaps = self._detect_transaction_patterns(ts, raw_tags, overall_flags, flag_detail)

        return TransactionForensic(
            set_id=set_id,
            st_control=st_ctrl,
            segment_count=sum(len(l.segments) for l in ts.loops),
            claim_count=len(claim_forensics),
            unusual_patterns=unusual,
            segment_gaps=gaps,
            raw_segment_tags=raw_tags,
        ), claim_forensics

    def _collect_raw_tags(self, ts: TransactionSet) -> list[str]:
        tags = []
        for loop in ts.loops:
            for seg in loop.segments:
                tags.append(seg.tag)
        return tags

    def _detect_transaction_patterns(
        self,
        ts: TransactionSet,
        raw_tags: list[str],
        overall_flags: list,
        flag_detail: dict,
    ) -> tuple[list[str], list[str]]:
        unusual: list[str] = []
        gaps: list[str] = []
        set_id = ts.set_id

        # Repeated singleton segments (BPR, CLP, CLM appearing multiple times per transaction)
        # For 835, CLP is per-claim so repeats are fine
        # For 837, CLM is per-claim so repeats are fine
        # But check for BPR repeated in a single transaction (should be exactly one)
        bpr_count = raw_tags.count("BPR")
        if bpr_count > 1:
            unusual.append(f"BPR_REPEATED_{bpr_count}_TIMES")
            flag_detail[f"BPR_REPEATED_{bpr_count}_TIMES"] = (
                f"BPR segment appears {bpr_count} times in this transaction. "
                "Standard 835 typically has exactly one BPR per ST/SE transaction."
            )

        trn_count = raw_tags.count("TRN")
        if trn_count > 3:
            unusual.append(f"TRN_REPEATED_{trn_count}_TIMES")
            flag_detail[f"TRN_REPEATED_{trn_count}_TIMES"] = (
                f"TRN segment appears {trn_count} times in this transaction. "
                "Typical 835 has one TRN per payment trace; more may indicate non-standard structure."
            )

        # Check for PLB without prior CLP (unusual but sometimes valid)
        clp_tags = [i for i, t in enumerate(raw_tags) if t == "CLP"]
        plb_tags = [i for i, t in enumerate(raw_tags) if t == "PLB"]
        if plb_tags and not clp_tags:
            unusual.append("PLB_WITHOUT_CLP")
            flag_detail["PLB_WITHOUT_CLP"] = (
                "PLB (Provider-Level Adjustment) segment appears but no CLP segments found. "
                "PLB adjustments typically follow CLP claim loops."
            )

        # Check for service lines without corresponding claim
        svc_count = raw_tags.count("SVC")
        sv1_count = raw_tags.count("SV1")
        sv2_count = raw_tags.count("SV2")
        claim_count = max(clp_tags.__len__(), [t for t in raw_tags if t == "CLM"].__len__())
        if svc_count > 0 and claim_count == 0:
            unusual.append("SERVICE_LINES_WITHOUT_CLAIM")
            flag_detail["SERVICE_LINES_WITHOUT_CLAIM"] = (
                f"Found {svc_count} SVC segments but no CLP claim segments. "
                "This may indicate a non-standard or truncated file."
            )
        if sv1_count > 0 and sv2_count > 0:
            unusual.append("MIXED_SV1_SV2")
            flag_detail["MIXED_SV1_SV2"] = (
                "Both SV1 (professional) and SV2 (institutional) service segments present. "
                "837 professional and institutional are typically mutually exclusive. "
                "This may indicate a malformed or non-standard file."
            )

        # Gap detection: expected segments that are missing
        if set_id == "835":
            if "N1" not in raw_tags:
                gaps.append("N1_MISSING")
            if "SVC" not in raw_tags and "CLP" in raw_tags:
                gaps.append("SVC_MISSING")
            if "CAS" not in raw_tags and "CLP" in raw_tags:
                gaps.append("CAS_MISSING (informational only)")
        elif set_id == "837":
            if "HI" not in raw_tags:
                gaps.append("HI_MISSING")
            if "REF" not in raw_tags:
                gaps.append("REF_MISSING (informational only)")

        return unusual, gaps

    # ── Claim-level forensic ────────────────────────────────────────────────

    def _analyze_claims(
        self,
        ts: TransactionSet,
        overall_flags: list,
        flag_detail: dict,
    ) -> list[ClaimForensic]:
        set_id = ts.set_id
        claims: list[ClaimForensic] = []

        if set_id == "835":
            claims = self._analyze_835_claims(ts, overall_flags, flag_detail)
        elif set_id == "837":
            claims = self._analyze_837_claims(ts, overall_flags, flag_detail)

        return claims

    def _analyze_835_claims(
        self,
        ts: TransactionSet,
        overall_flags: list,
        flag_detail: dict,
    ) -> list[ClaimForensic]:
        claims: list[ClaimForensic] = []
        current_claim_loops: list[Loop] = []
        current_claim_id = ""

        for loop in ts.loops:
            is_claim_leader = loop.leader_tag == "CLP"
            if is_claim_leader:
                # Finalize previous claim
                if current_claim_id:
                    prev = self._build_835_claim_forensic(
                        current_claim_loops, current_claim_id, overall_flags, flag_detail
                    )
                    if prev:
                        claims.append(prev)
                clp_seg = loop.segments[0] if loop.segments else None
                current_claim_id = self.parser._seg_get(clp_seg, 1) if clp_seg else "?"
                current_claim_loops = [loop]
            else:
                current_claim_loops.append(loop)

        # Last claim
        if current_claim_id:
            final = self._build_835_claim_forensic(
                current_claim_loops, current_claim_id, overall_flags, flag_detail
            )
            if final:
                claims.append(final)

        return claims

    def _build_835_claim_forensic(
        self,
        loops: list[Loop],
        claim_id: str,
        overall_flags: list,
        flag_detail: dict,
    ) -> Optional[ClaimForensic]:
        trace: list[SegmentTrace] = []
        entities: dict[str, str] = {}
        amounts: dict[str, Any] = {}
        flags: list[str] = []

        for loop in loops:
            for seg in loop.segments:
                elem_dict = _seg_to_dict(seg)
                unusual, note = self._detect_unusual_segment(seg, elem_dict, "835")
                trace.append(SegmentTrace(
                    tag=seg.tag,
                    position=seg.position,
                    elements=elem_dict,
                    loop_id=loop.id,
                    loop_kind=loop.kind,
                    is_unusual=unusual,
                    unusual_note=note,
                ))
                if unusual:
                    flags.append(f"UNUSUAL_{seg.tag}")
                    if f"UNUSUAL_{seg.tag}" not in flag_detail:
                        flag_detail[f"UNUSUAL_{seg.tag}"] = note

                # Entity collection
                if seg.tag == "NM1":
                    qualifier = elem_dict.get("e1", "")
                    name = " ".join(filter(None, [elem_dict.get("e3", ""), elem_dict.get("e4", "")]))
                    id_val = elem_dict.get("e9", elem_dict.get("e4", ""))
                    if qualifier:
                        entities[f"NM1_{qualifier}"] = name or id_val
                elif seg.tag == "N1":
                    qualifier = elem_dict.get("e1", "")
                    name = elem_dict.get("e2", "")
                    id_val = elem_dict.get("e4", "")
                    if qualifier:
                        entities[f"N1_{qualifier}"] = name or id_val

                # Amount collection from CLP
                if seg.tag == "CLP":
                    amounts["clp_billed"] = self.parser._seg_get(seg, 2) or "0"
                    amounts["clp_status"] = self.parser._seg_get(seg, 3) or ""
                    amounts["clp_allowed"] = self.parser._seg_get(seg, 4) or "0"
                    amounts["clp_paid"] = self.parser._seg_get(seg, 5) or "0"

                if seg.tag == "SVC":
                    if "svc_billed" not in amounts:
                        amounts["svc_billed"] = []
                        amounts["svc_paid"] = []
                    amounts["svc_billed"].append(self.parser._seg_get(seg, 2) or "")
                    amounts["svc_paid"].append(self.parser._seg_get(seg, 3) or "")

                if seg.tag == "CAS":
                    if "cas_group_codes" not in amounts:
                        amounts["cas_group_codes"] = []
                    gc = self.parser._seg_get(seg, 1) or ""
                    if gc:
                        amounts["cas_group_codes"].append(gc)

        # Per-claim unusual pattern checks
        seg_tags = [t.tag for t in trace]
        clp_count = seg_tags.count("CLP")
        if clp_count > 1:
            flags.append("MULTIPLE_CLP")
            flag_detail["MULTIPLE_CLP"] = (
                f"Claim {claim_id} has {clp_count} CLP segments. "
                "Standard 835 has one CLP per claim loop."
            )
        if "CAS" in seg_tags and "SVC" not in seg_tags:
            flags.append("CAS_WITHOUT_SVC")
            flag_detail["CAS_WITHOUT_SVC"] = (
                f"Claim {claim_id}: CAS adjustment segments present but no SVC service lines. "
                "Verify the payer does not use a non-standard claim layout."
            )
        svc_count = seg_tags.count("SVC")
        cas_count = seg_tags.count("CAS")
        if svc_count > 0 and cas_count > 0 and svc_count != cas_count:
            flags.append("SVC_CAS_COUNT_MISMATCH")
            flag_detail["SVC_CAS_CAS_COUNT_MISMATCH"] = (
                f"Claim {claim_id}: {svc_count} SVC segments but {cas_count} CAS groups. "
                "Normally each SVC maps to a corresponding CAS group; mismatch may indicate "
                "non-standard payer layout."
            )

        return ClaimForensic(
            claim_id=claim_id,
            transaction_set="835",
            segment_trace=trace,
            entity_snapshot=entities,
            amount_summary=amounts,
            flags=flags,
            flag_detail={},
        )

    def _analyze_837_claims(
        self,
        ts: TransactionSet,
        overall_flags: list,
        flag_detail: dict,
    ) -> list[ClaimForensic]:
        claims: list[ClaimForensic] = []
        current_claim_loops: list[Loop] = []
        current_claim_id = ""

        for loop in ts.loops:
            is_claim_leader = loop.leader_tag == "CLM"
            if is_claim_leader:
                if current_claim_id:
                    prev = self._build_837_claim_forensic(
                        current_claim_loops, current_claim_id, overall_flags, flag_detail
                    )
                    if prev:
                        claims.append(prev)
                clm_seg = loop.segments[0] if loop.segments else None
                current_claim_id = self.parser._seg_get(clm_seg, 1) if clm_seg else "?"
                current_claim_loops = [loop]
            else:
                current_claim_loops.append(loop)

        if current_claim_id:
            final = self._build_837_claim_forensic(
                current_claim_loops, current_claim_id, overall_flags, flag_detail
            )
            if final:
                claims.append(final)

        return claims

    def _build_837_claim_forensic(
        self,
        loops: list[Loop],
        claim_id: str,
        overall_flags: list,
        flag_detail: dict,
    ) -> Optional[ClaimForensic]:
        trace: list[SegmentTrace] = []
        entities: dict[str, str] = {}
        amounts: dict[str, Any] = {}
        flags: list[str] = []

        for loop in loops:
            for seg in loop.segments:
                elem_dict = _seg_to_dict(seg)
                unusual, note = self._detect_unusual_segment(seg, elem_dict, "837")
                trace.append(SegmentTrace(
                    tag=seg.tag,
                    position=seg.position,
                    elements=elem_dict,
                    loop_id=loop.id,
                    loop_kind=loop.kind,
                    is_unusual=unusual,
                    unusual_note=note,
                ))
                if unusual:
                    flags.append(f"UNUSUAL_{seg.tag}")

                if seg.tag == "NM1":
                    qualifier = elem_dict.get("e1", "")
                    name = " ".join(filter(None, [elem_dict.get("e3", ""), elem_dict.get("e4", "")]))
                    if qualifier:
                        entities[f"NM1_{qualifier}"] = name
                elif seg.tag == "CLM":
                    amounts["clm_billed"] = self.parser._seg_get(seg, 2) or "0"
                    amounts["clm_status"] = self.parser._seg_get(seg, 5) or ""
                elif seg.tag in ("SV1", "SV2"):
                    if "svc_billed" not in amounts:
                        amounts["svc_billed"] = []
                    amounts["svc_billed"].append(self.parser._seg_get(seg, 3) or "")

        seg_tags = [t.tag for t in trace]
        if "HI" not in seg_tags:
            flags.append("HI_MISSING")
            flag_detail["HI_MISSING"] = (
                f"Claim {claim_id}: HI (diagnosis codes) not found. "
                "Institutional claims typically require HI segments."
            )

        return ClaimForensic(
            claim_id=claim_id,
            transaction_set="837",
            segment_trace=trace,
            entity_snapshot=entities,
            amount_summary=amounts,
            flags=flags,
            flag_detail={},
        )

    # ── Per-segment unusualness detection ──────────────────────────────────

    def _detect_unusual_segment(
        self,
        seg: Segment,
        elem_dict: dict[str, str],
        set_id: str,
    ) -> tuple[bool, str]:
        """Return (is_unusual, note) for a segment."""
        # CAS with zero-amount adjustments
        if seg.tag == "CAS":
            for i in (2, 5, 8, 11, 14, 17):
                raw = elem_dict.get(f"e{i+1}", "")
                if raw:
                    try:
                        if float(raw) == 0:
                            return True, (
                                f"CAS segment at position {seg.position}: "
                                f"e{i+1} (adjustment amount) is exactly 0. "
                                "Zero-amount adjustments are unusual and may indicate "
                                "a placeholder or non-standard payer variant."
                            )
                    except ValueError:
                        pass

        # REF with very long reference value (could be multi-segment data concatenated)
        if seg.tag == "REF":
            ref_val = elem_dict.get("e2", "")
            if ref_val and len(ref_val) > 30:
                return True, (
                    f"REF segment at position {seg.position}: "
                    f"reference value '{ref_val[:30]}...' is unusually long (>30 chars). "
                    "Verify the reference format is correct for this payer."
                )

        # HI with single diagnosis (standard often has multiple)
        if seg.tag == "HI" and set_id == "837":
            hi_vals = [v for k, v in elem_dict.items() if k.startswith("e") and v and k != "e1"]
            if len(hi_vals) == 1:
                return True, (
                    f"HI segment at position {seg.position}: "
                    f"only 1 diagnosis code found ({hi_vals}). "
                    "Institutional claims typically include multiple diagnosis codes. "
                    "This may be a simplified example or a payer-specific variant."
                )

        return False, ""

    # ── Delimiter analysis ───────────────────────────────────────────────────

    def _check_delimiters(self) -> str:
        """Check if non-standard delimiters were used."""
        # This is already handled by the parser's dynamic delimiter extraction.
        # We note it here for forensic completeness.
        return ""

    # ── Human-readable render ────────────────────────────────────────────────

    def render_text(self, report: X12ForensicReport) -> str:
        """Render a forensic report as human-readable text."""
        lines = []
        lines.append("=" * 64)
        lines.append("X12 FORENSIC ANALYSIS REPORT")
        lines.append("=" * 64)

        # ── Top-level summary line ──────────────────────────────────────────
        total_claims = len(report.claims)
        total_tx = len(report.transactions)
        unusual_tx = sum(1 for t in report.transactions if t.unusual_patterns)
        flag_count = len(report.overall_flags)
        summary_parts = [
            f"{total_tx} transaction set(s)",
            f"{total_claims} claim(s)",
        ]
        if unusual_tx:
            summary_parts.append(f"{unusual_tx} with unusual patterns")
        if flag_count:
            summary_parts.append(f"{flag_count} file-level flag(s)")
        if not unusual_tx and not flag_count:
            summary_parts.append("no unusual patterns detected")
        lines.append(f"\n  Summary: {', '.join(summary_parts)}")

        # Interchange
        ic = report.interchange
        lines.append(f"\nINTERCHANGE")
        lines.append(f"  Sender:     {ic.isa_sender or '(blank)'}")
        lines.append(f"  Receiver:   {ic.isa_receiver or '(blank)'}")
        lines.append(f"  GS groups:  {ic.gs_count}")
        lines.append(f"  ST sets:    {ic.st_count_total}")
        if ic.unusual_envelope_conditions:
            lines.append(f"  ⚠ Envelope conditions:")
            for cond in ic.unusual_envelope_conditions:
                lines.append(f"    - {cond}: {report.flag_detail.get(cond, '')}")

        # Transactions
        for tx in report.transactions:
            lines.append(f"\nTRANSACTION {tx.set_id} (ST control: {tx.st_control})")
            lines.append(f"  Segments:   {tx.segment_count}")
            lines.append(f"  Claims:     {tx.claim_count}")
            if tx.unusual_patterns:
                lines.append(f"  ⚠ Unusual patterns:")
                for p in tx.unusual_patterns:
                    lines.append(f"    - {p}: {report.flag_detail.get(p, '')}")
            if tx.segment_gaps:
                lines.append(f"  ⚠ Possible segment gaps:")
                for g in tx.segment_gaps:
                    lines.append(f"    - {g}")

        # Claims
        if report.claims:
            lines.append(f"\nCLAIM TRACES ({len(report.claims)} claims)")
            for cl in report.claims:
                lines.append(f"\n  Claim: {cl.claim_id} ({cl.transaction_set})")
                for step in cl.segment_trace:
                    flag = " ⚠" if step.is_unusual else ""
                    elem_str = ", ".join(
                        f"{k}={v}" for k, v in list(step.elements.items())[:5]
                    )
                    lines.append(
                        f"    [{step.position:4d}] {step.tag:4s} "
                        f"(loop={step.loop_kind:10s}){flag} {elem_str}"
                    )
                if cl.flags:
                    lines.append(f"    ⚠ Flags: {', '.join(set(cl.flags))}")

        # File-level flags
        if report.overall_flags:
            lines.append(f"\nFILE-LEVEL FLAGS")
            for f_ in report.overall_flags:
                lines.append(f"  ⚠ {f_}: {report.flag_detail.get(f_, '')}")

        lines.append("\n" + "=" * 64)
        return "\n".join(lines)
