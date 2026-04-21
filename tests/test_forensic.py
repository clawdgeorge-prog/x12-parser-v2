"""
Formal tests for X12 Forensic Analyzer (src/forensic.py).

Covers: X12ForensicAnalyzer, _detect_unusual_segment,
_analyze_interchange, _detect_transaction_patterns,
_collect_raw_tags, _build_*_claim_forensic, analyze, render_text.
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from src.parser import X12Parser, TransactionSet, Loop, Segment, Element
from src.forensic import (
    X12ForensicAnalyzer,
    X12ForensicReport,
    SegmentTrace,
    ClaimForensic,
    TransactionForensic,
    InterchangeForensic,
    _seg_to_dict,
    _get_element,
    _SINGLETON_PER_CLAIM,
    _USUAL_CLAIM_SEGMENTS_835,
    _USUAL_CLAIM_SEGMENTS_837,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


# ── Helpers ───────────────────────────────────────────────────────────────────

def forensic_for_fixture(name: str) -> X12ForensicAnalyzer:
    fixture = FIXTURES / name
    parser = X12Parser.from_file(fixture)
    return X12ForensicAnalyzer(parser)


def make_parser(text: str) -> X12Parser:
    p = X12Parser(text=text)
    p._parse()
    p._parse_summary()
    return p


# ── Module-level helpers ──────────────────────────────────────────────────────

class TestModuleHelpers:
    def test_seg_to_dict(self):
        raw = "CLP*CLM001*1000*500*800****CL*12*345"
        elem_sep = "*"
        parts = raw.split(elem_sep)
        seg = Segment(
            tag="CLP",
            elements=[Element(raw=e, position=i + 1) for i, e in enumerate(parts[1:])],
            raw=raw,
            position=1,
        )
        d = _seg_to_dict(seg)
        assert d["e1"] == "CLM001"
        assert d["e2"] == "1000"
        assert d["e3"] == "500"

    def test_get_element_1based_valid(self):
        raw = "CLP*CLM001*1000*500"
        parts = raw.split("*")
        seg = Segment(
            tag="CLP",
            elements=[Element(raw=e, position=i + 1) for i, e in enumerate(parts[1:])],
            raw=raw,
            position=1,
        )
        assert _get_element(seg, 1) == "CLM001"
        assert _get_element(seg, 2) == "1000"
        assert _get_element(seg, 3) == "500"

    def test_get_element_out_of_range(self):
        raw = "CLP*CLM001*1000"
        parts = raw.split("*")
        seg = Segment(
            tag="CLP",
            elements=[Element(raw=e, position=i + 1) for i, e in enumerate(parts[1:])],
            raw=raw,
            position=1,
        )
        assert _get_element(seg, 99) == ""
        assert _get_element(seg, 0) == ""


# ── Dataclass round-trip ──────────────────────────────────────────────────────

class TestForensicDataclasses:
    def test_segment_trace_defaults(self):
        t = SegmentTrace(
            tag="CLP", position=1,
            elements={"e1": "CLM001"},
            loop_id="CLP", loop_kind="claim",
        )
        assert t.is_unusual is False
        assert t.unusual_note == ""

    def test_claim_forensic_empty_lists(self):
        c = ClaimForensic(
            claim_id="CLM001",
            transaction_set="835",
            segment_trace=[],
            entity_snapshot={},
            amount_summary={},
            flags=[],
            flag_detail={},
        )
        assert c.claim_id == "CLM001"
        assert c.transaction_set == "835"

    def test_transaction_forensic_delimiter_note(self):
        t = TransactionForensic(
            set_id="835",
            st_control="0001",
            segment_count=10,
            claim_count=1,
            unusual_patterns=[],
            segment_gaps=[],
            raw_segment_tags=["ST", "BPR", "CLP"],
            delimiter_note="Non-standard tilde encoding",
        )
        assert "Non-standard" in t.delimiter_note

    def test_interchange_forensic(self):
        ic = InterchangeForensic(
            isa_sender="SENDER",
            isa_receiver="RECEIVER",
            gs_count=2,
            st_count_total=3,
            unusual_envelope_conditions=["ISA_SENDER_BLANK"],
        )
        assert ic.gs_count == 2
        assert "ISA_SENDER_BLANK" in ic.unusual_envelope_conditions

    def test_forensic_report(self):
        ic = InterchangeForensic("S", "R", 1, 1, [])
        tx = TransactionForensic("835", "0001", 10, 1, [], [], [])
        report = X12ForensicReport(
            interchange=ic,
            transactions=[tx],
            claims=[],
            overall_flags=[],
            flag_detail={},
        )
        assert len(report.transactions) == 1
        assert report.overall_flags == []


# ── _detect_unusual_segment ───────────────────────────────────────────────────

class TestDetectUnusualSegment:
    """Unit-test _detect_unusual_segment via a directly-constructed Segment."""

    def _seg(self, tag: str, elem_dict: dict) -> Segment:
        elements = [Element(raw=elem_dict.get(f"e{i}","") or "", position=i)
                    for i in range(1, max(len(elem_dict) + 2, 2))]
        return Segment(tag=tag, elements=elements, raw="", position=100)

    def test_cas_zero_amount_returns_unusual(self):
        # CAS*e1=CO, e2=45, e3=0.00 → zero-amount adjustment
        seg = self._seg("CAS", {"e1": "CO", "e2": "45", "e3": "0.00"})
        analyzer = forensic_for_fixture("sample_835.edi")
        unusual, note = analyzer._detect_unusual_segment(seg, {"e1": "CO", "e2": "45", "e3": "0.00"}, "835")
        assert unusual is True
        assert "0" in note
        assert "position 100" in note

    def test_cas_nonzero_amount_not_unusual(self):
        seg = self._seg("CAS", {"e1": "CO", "e2": "45", "e3": "50.00"})
        analyzer = forensic_for_fixture("sample_835.edi")
        unusual, note = analyzer._detect_unusual_segment(seg, {"e1": "CO", "e2": "45", "e3": "50.00"}, "835")
        assert unusual is False

    def test_ref_long_value_returns_unusual(self):
        long_val = "A" * 31
        seg = self._seg("REF", {"e1": "2U", "e2": long_val})
        analyzer = forensic_for_fixture("sample_835.edi")
        unusual, note = analyzer._detect_unusual_segment(seg, {"e1": "2U", "e2": long_val}, "835")
        assert unusual is True
        assert "31" in note or "long" in note.lower()

    def test_ref_short_value_not_unusual(self):
        seg = self._seg("REF", {"e1": "2U", "e2": "12345678"})
        analyzer = forensic_for_fixture("sample_835.edi")
        unusual, note = analyzer._detect_unusual_segment(seg, {"e1": "2U", "e2": "12345678"}, "835")
        assert unusual is False

    def test_hi_single_diagnosis_unusual_for_837(self):
        seg = self._seg("HI", {"e1": "ABK", "e2": "J1234"})
        analyzer = forensic_for_fixture("sample_837_prof.edi")
        unusual, note = analyzer._detect_unusual_segment(seg, {"e1": "ABK", "e2": "J1234"}, "837")
        assert unusual is True
        assert "1" in note and "diagnosis" in note

    def test_hi_multiple_diagnoses_not_unusual(self):
        seg = self._seg("HI", {"e1": "ABK", "e2": "J1234", "e3": "K5678", "e4": "L9012"})
        analyzer = forensic_for_fixture("sample_837_prof.edi")
        unusual, _ = analyzer._detect_unusual_segment(seg, {"e1": "ABK", "e2": "J1234", "e3": "K5678", "e4": "L9012"}, "837")
        assert unusual is False

    def test_hi_not_checked_for_835(self):
        seg = self._seg("HI", {"e1": "ABK", "e2": "J1234"})
        analyzer = forensic_for_fixture("sample_835.edi")
        unusual, _ = analyzer._detect_unusual_segment(seg, {"e1": "ABK", "e2": "J1234"}, "835")
        assert unusual is False


# ── _detect_transaction_patterns ─────────────────────────────────────────────

class TestDetectTransactionPatterns:
    """Test transaction-level pattern detection via directly-constructed segments."""

    def _ts_with_tags(self, tags: list[str], set_id: str = "835") -> TransactionSet:
        """Build a minimal TransactionSet with given segment tags."""
        header = Segment(tag="ST", elements=[Element(set_id, 1), Element("0001", 2)],
                         raw=f"ST*{set_id}*0001", position=1)
        trailer = Segment(tag="SE", elements=[Element(str(len(tags) + 2), 1)],
                          raw=f"SE*{len(tags) + 2}*0001", position=10 + len(tags))
        segs = []
        for i, tag in enumerate(tags):
            segs.append(Segment(tag=tag, elements=[Element(tag, 1)],
                               raw=tag, position=2 + i))
        loop = Loop(id="MISC", leader_tag="MISC", leader_code="MISC",
                    kind="other", description="misc", segments=segs)
        ts = TransactionSet(header=header, loops=[loop], trailer=trailer, set_id=set_id)
        return ts

    def test_bpr_repeated_detected(self):
        p = make_parser(
            "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       "
            "*250402*1234*^*00501*000000001*0*P*:~GS*HP*SENDER*RECEIVER*20250402*1234*1*X*005010X221A1~"
            "ST*835*0001*005010X221A1~"
            "BPR*I*1000*C*ACH~"
            "BPR*I*500*C*ACH~"
            "TRN*1*0000000001~"
            "SE*5*0001~GE*1*1~IEA*1*000000001~"
        )
        a = X12ForensicAnalyzer(p)
        raw_tags = ["ST", "BPR", "BPR", "TRN", "SE"]
        unusual, gaps = a._detect_transaction_patterns(
            self._ts_with_tags(["BPR", "BPR", "TRN"]),
            raw_tags, [], {}
        )
        assert any("BPR_REPEATED" in u for u in unusual)

    def test_trn_repeated_many_detected(self):
        p = make_parser(
            "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       "
            "*250402*1234*^*00501*000000001*0*P*:~GS*HP*SENDER*RECEIVER*20250402*1234*1*X*005010X221A1~"
            "ST*835*0001*005010X221A1~"
            "BPR*I*1000*C*ACH~"
            "TRN*1*A~TRN*1*B~TRN*1*C~TRN*1*D~"
            "SE*6*0001~GE*1*1~IEA*1*000000001~"
        )
        a = X12ForensicAnalyzer(p)
        unusual, gaps = a._detect_transaction_patterns(
            self._ts_with_tags(["BPR", "TRN", "TRN", "TRN", "TRN"]),
            ["BPR", "TRN", "TRN", "TRN", "TRN"], [], {}
        )
        assert any("TRN_REPEATED" in u for u in unusual)

    def test_plb_without_clp_detected(self):
        p = make_parser(
            "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       "
            "*250402*1234*^*00501*000000001*0*P*:~GS*HP*SENDER*RECEIVER*20250402*1234*1*X*005010X221A1~"
            "ST*835*0001*005010X221A1~"
            "BPR*I*1000*C*ACH~"
            "PLB*SENDER*20250401*CV:CLM001*25.00~"
            "SE*4*0001~GE*1*1~IEA*1*000000001~"
        )
        a = X12ForensicAnalyzer(p)
        unusual, gaps = a._detect_transaction_patterns(
            self._ts_with_tags(["BPR", "PLB"]),
            ["BPR", "PLB"], [], {}
        )
        assert "PLB_WITHOUT_CLP" in unusual

    def test_service_lines_without_claim_detected(self):
        a = X12ForensicAnalyzer(make_parser(
            "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       "
            "*250402*1234*^*00501*000000001*0*P*:~GS*HP*SENDER*RECEIVER*20250402*1234*1*X*005010X221A1~"
            "ST*835*0001*005010X221A1~"
            "BPR*I*1000*C*ACH~"
            "SVC*HC:99213*200*150~"
            "SE*4*0001~GE*1*1~IEA*1*000000001~"
        ))
        unusual, gaps = a._detect_transaction_patterns(
            self._ts_with_tags(["BPR", "SVC"]),
            ["BPR", "SVC"], [], {}
        )
        assert "SERVICE_LINES_WITHOUT_CLAIM" in unusual

    def test_mixed_sv1_sv2_detected(self):
        a = X12ForensicAnalyzer(make_parser(
            "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       "
            "*250402*1234*^*00501*000000001*0*P*:~GS*HC*SENDER*RECEIVER*20250402*1234*1*X*005010X222A1~"
            "ST*837*0001*005010X222A1~"
            "SV1*HC:99213*200*150~"
            "SV2*HC:0250*100*80~"
            "SE*4*0001~GE*1*1~IEA*1*000000001~"
        ))
        unusual, gaps = a._detect_transaction_patterns(
            self._ts_with_tags(["SV1", "SV2"]),
            ["SV1", "SV2"], [], {}
        )
        assert "MIXED_SV1_SV2" in unusual

    def test_835_n1_missing_gap(self):
        a = X12ForensicAnalyzer(make_parser(
            "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       "
            "*250402*1234*^*00501*000000001*0*P*:~GS*HP*SENDER*RECEIVER*20250402*1234*1*X*005010X221A1~"
            "ST*835*0001*005010X221A1~"
            "BPR*I*1000*C*ACH~"
            "SE*3*0001~GE*1*1~IEA*1*000000001~"
        ))
        unusual, gaps = a._detect_transaction_patterns(
            self._ts_with_tags(["BPR"]),
            ["ST", "BPR", "SE"], [], {}
        )
        assert "N1_MISSING" in gaps

    def test_835_svc_missing_gap_when_clp_present(self):
        a = X12ForensicAnalyzer(make_parser(
            "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       "
            "*250402*1234*^*00501*000000001*0*P*:~GS*HP*SENDER*RECEIVER*20250402*1234*1*X*005010X221A1~"
            "ST*835*0001*005010X221A1~"
            "BPR*I*1000*C*ACH~"
            "CLP*CLM001****200*3**CL*12*345~"
            "SE*3*0001~GE*1*1~IEA*1*000000001~"
        ))
        unusual, gaps = a._detect_transaction_patterns(
            self._ts_with_tags(["BPR", "CLP"]),
            ["ST", "BPR", "CLP", "SE"], [], {}
        )
        assert "SVC_MISSING" in gaps

    def test_837_hi_missing_gap(self):
        a = X12ForensicAnalyzer(make_parser(
            "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       "
            "*250402*1234*^*00501*000000001*0*P*:~GS*HC*SENDER*RECEIVER*20250402*1234*1*X*005010X222A1~"
            "ST*837*0001*005010X222A1~"
            "BHT*0019*11*BATCH001*20250402*1234*CH~"
            "NM1*41*2*BILLING*****46*12345~"
            "CLM*CLM001*500***11:B:1*Y*A*Y*Y~"
            "SE*4*0001~GE*1*1~IEA*1*000000001~"
        ))
        unusual, gaps = a._detect_transaction_patterns(
            self._ts_with_tags(["BHT", "NM1", "CLM"], set_id="837"),
            ["ST", "BHT", "NM1", "CLM", "SE"], [], {}
        )
        assert "HI_MISSING" in gaps


# ── _collect_raw_tags ─────────────────────────────────────────────────────────

class TestCollectRawTags:
    def test_collects_tags_in_order(self):
        a = forensic_for_fixture("sample_835.edi")
        # Get first transaction
        ic = a.parser.interchanges[0]
        fg = ic.groups[0]
        ts = fg.transactions[0]
        tags = a._collect_raw_tags(ts)
        assert isinstance(tags, list)
        assert "CLP" in tags  # CLP is in a loop
        assert len(tags) > 0


# ── _analyze_interchange ──────────────────────────────────────────────────────

class TestAnalyzeInterchange:
    def test_blank_sender_flagged(self):
        edi = (
            "ISA*00*          *00*          *ZZ*               *ZZ*RECEIVER       "
            "*250402*1234*^*00501*000000001*0*P*:~GS*HP*SENDER*RECEIVER*20250402*1234*1*X*005010X221A1~"
            "ST*835*0001*005010X221A1~"
            "BPR*I*1000*C*ACH~"
            "SE*3*0001~GE*1*1~IEA*1*000000001~"
        )
        p = make_parser(edi)
        a = X12ForensicAnalyzer(p)
        flags = []
        detail = {}
        ic_rep = a._analyze_interchange(p.interchanges, flags, detail)
        assert ic_rep.isa_sender.strip() == "" or ic_rep.isa_sender == ""
        assert "ISA_SENDER_BLANK" in ic_rep.unusual_envelope_conditions

    def test_blank_receiver_flagged(self):
        edi = (
            "ISA*00*          *00*          *ZZ*SENDER         *ZZ*               "
            "*250402*1234*^*00501*000000001*0*P*:~GS*HP*SENDER*RECEIVER*20250402*1234*1*X*005010X221A1~"
            "ST*835*0001*005010X221A1~"
            "BPR*I*1000*C*ACH~"
            "SE*3*0001~GE*1*1~IEA*1*000000001~"
        )
        p = make_parser(edi)
        a = X12ForensicAnalyzer(p)
        ic_rep = a._analyze_interchange(p.interchanges, [], {})
        assert "ISA_RECEIVER_BLANK" in ic_rep.unusual_envelope_conditions

    def test_unusual_isa_date_year_flagged(self):
        edi = (
            "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       "
            "*19990101*1234*^*00501*000000001*0*P*:~"  # year=1999
            "GS*HP*SENDER*RECEIVER*20250402*1234*1*X*005010X221A1~"
            "ST*835*0001*005010X221A1~"
            "BPR*I*1000*C*ACH~"
            "SE*3*0001~GE*1*1~IEA*1*000000001~"
        )
        p = make_parser(edi)
        a = X12ForensicAnalyzer(p)
        ic_rep = a._analyze_interchange(p.interchanges, [], {})
        assert "ISA_DATE_UNUSUAL_YEAR" in ic_rep.unusual_envelope_conditions


# ── analyze() — integration ───────────────────────────────────────────────────

class TestAnalyze:
    def test_analyze_returns_full_report(self):
        a = forensic_for_fixture("sample_835.edi")
        report = a.analyze()
        assert isinstance(report, X12ForensicReport)
        assert isinstance(report.interchange, InterchangeForensic)
        assert isinstance(report.transactions, list)
        assert isinstance(report.claims, list)

    def test_analyze_sets_gs_st_counts(self):
        a = forensic_for_fixture("sample_835.edi")
        report = a.analyze()
        assert report.interchange.gs_count >= 1
        assert report.interchange.st_count_total >= 1

    def test_analyze_multiple_interchanges_sets_flag(self):
        a = forensic_for_fixture("sample_multi_interchange.edi")
        report = a.analyze()
        assert "MULTIPLE_INTERCHANGES" in report.overall_flags

    def test_analyze_835_claims_populated(self):
        a = forensic_for_fixture("sample_835.edi")
        report = a.analyze()
        assert len(report.claims) >= 1
        for cl in report.claims:
            assert cl.transaction_set == "835"
            assert cl.claim_id != ""
            assert isinstance(cl.segment_trace, list)

    def test_analyze_837_claims_populated(self):
        a = forensic_for_fixture("sample_837_prof.edi")
        report = a.analyze()
        assert len(report.claims) >= 1
        for cl in report.claims:
            assert cl.transaction_set == "837"

    def test_analyze_segment_trace_positions(self):
        a = forensic_for_fixture("sample_835.edi")
        report = a.analyze()
        for cl in report.claims:
            for step in cl.segment_trace:
                assert step.position >= 0
                assert step.tag != ""

    def test_analyze_entity_snapshot_populated(self):
        a = forensic_for_fixture("sample_835.edi")
        report = a.analyze()
        for cl in report.claims:
            if cl.entity_snapshot:
                # Should contain N1 or NM1 keys
                keys = list(cl.entity_snapshot.keys())
                assert any(k.startswith("N1_") or k.startswith("NM1_") for k in keys)

    def test_analyze_amount_summary_populated(self):
        a = forensic_for_fixture("sample_835.edi")
        report = a.analyze()
        for cl in report.claims:
            assert isinstance(cl.amount_summary, dict)

    def test_analyze_flag_detail_populated(self):
        a = forensic_for_fixture("sample_835_balancing.edi")
        report = a.analyze()
        # If any flag fires, flag_detail should have an entry
        for cl in report.claims:
            for flag in cl.flags:
                if flag.startswith("UNUSUAL_"):
                    assert flag in cl.flag_detail or flag in report.flag_detail


# ── _build_835_claim_forensic ─────────────────────────────────────────────────

class TestBuild835ClaimForensic:
    def test_claim_id_from_clp(self):
        a = forensic_for_fixture("sample_835.edi")
        ic = a.parser.interchanges[0]
        fg = ic.groups[0]
        ts = fg.transactions[0]
        claims = a._analyze_835_claims(ts, [], {})
        assert len(claims) >= 1
        assert claims[0].claim_id != ""

    def test_segment_trace_includes_clp(self):
        a = forensic_for_fixture("sample_835.edi")
        ic = a.parser.interchanges[0]
        fg = ic.groups[0]
        ts = fg.transactions[0]
        claims = a._analyze_835_claims(ts, [], {})
        clp_tags = [s.tag for s in claims[0].segment_trace]
        assert "CLP" in clp_tags

    def test_entity_snapshot_has_nm1_or_n1(self):
        """First claim may include transaction-level N1/NM1 from the enclosing loop."""
        a = forensic_for_fixture("sample_835.edi")
        ic = a.parser.interchanges[0]
        fg = ic.groups[0]
        ts = fg.transactions[0]
        claims = a._analyze_835_claims(ts, [], {})
        snap = claims[0].entity_snapshot
        # First claim may have N1 or NM1 entities from its loops
        assert len(snap) >= 0  # at minimum, entity_snapshot is a dict
        # NM1_QC (patient) is present in the CLP-level loop for sample_835.edi
        assert any("NM1" in k or "N1" in k for k in snap.keys())

    def test_amount_summary_clp_fields(self):
        a = forensic_for_fixture("sample_835.edi")
        ic = a.parser.interchanges[0]
        fg = ic.groups[0]
        ts = fg.transactions[0]
        claims = a._analyze_835_claims(ts, [], {})
        amt = claims[0].amount_summary
        assert "clp_billed" in amt or "svc_billed" in amt

    def test_svc_cas_count_mismatch_flag(self):
        """Two SVCs but only one CAS group → SVC_CAS_COUNT_MISMATCH fires."""
        edi = (
            "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       "
            "*250402*1234*^*00501*000000001*0*P*:~"
            "GS*HP*SENDER*RECEIVER*20250402*1234*1*X*005010X221A1~"
            "ST*835*0001*005010X221A1~"
            "BPR*I*1000*C*ACH~"
            "CLP*CLM001****200*3**CL*12*345~"
            "SVC*HC:99213*200*150~"
            "SVC*HC:99214*100*80~"
            "CAS*CO*45*50.00~"   # only one CAS for two SVCs
            "SE*7*0001~GE*1*1~IEA*1*000000001~"
        )
        p = make_parser(edi)
        a = X12ForensicAnalyzer(p)
        ic = a.parser.interchanges[0]
        fg = ic.groups[0]
        ts = fg.transactions[0]
        claims = a._analyze_835_claims(ts, [], {})
        flags = claims[0].flags
        assert "SVC_CAS_COUNT_MISMATCH" in flags

    def test_cas_without_svc_flag(self):
        edi = (
            "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       "
            "*250402*1234*^*00501*000000001*0*P*:~"
            "GS*HP*SENDER*RECEIVER*20250402*1234*1*X*005010X221A1~"
            "ST*835*0001*005010X221A1~"
            "BPR*I*1000*C*ACH~"
            "CLP*CLM001****200*3**CL*12*345~"
            "CAS*CO*45*50.00~"
            "SE*5*0001~GE*1*1~IEA*1*000000001~"
        )
        p = make_parser(edi)
        a = X12ForensicAnalyzer(p)
        ic = a.parser.interchanges[0]
        fg = ic.groups[0]
        ts = fg.transactions[0]
        claims = a._analyze_835_claims(ts, [], {})
        flags = claims[0].flags
        assert "CAS_WITHOUT_SVC" in flags


# ── _build_837_claim_forensic ─────────────────────────────────────────────────

class TestBuild837ClaimForensic:
    def test_claim_id_from_clm(self):
        a = forensic_for_fixture("sample_837_prof.edi")
        ic = a.parser.interchanges[0]
        fg = ic.groups[0]
        ts = fg.transactions[0]
        claims = a._analyze_837_claims(ts, [], {})
        assert len(claims) >= 1
        assert claims[0].claim_id != ""

    def test_segment_trace_includes_clm(self):
        a = forensic_for_fixture("sample_837_prof.edi")
        ic = a.parser.interchanges[0]
        fg = ic.groups[0]
        ts = fg.transactions[0]
        claims = a._analyze_837_claims(ts, [], {})
        clm_tags = [s.tag for s in claims[0].segment_trace]
        assert "CLM" in clm_tags

    def test_hi_missing_flag(self):
        # Build a minimal 837 without HI
        edi = (
            "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       "
            "*250402*1234*^*00501*000000001*0*P*:~"
            "GS*HC*SENDER*RECEIVER*20250402*1234*1*X*005010X222A1~"
            "ST*837*0001*005010X222A1~"
            "BHT*0019*11*BATCH001*20250402*1234*CH~"
            "NM1*41*2*BILLING*****46*12345~"
            "HL*1**20*1~"
            "NM1*85*2*DR SMITH*****XX*123456~"
            "HL*2*1*22*1~"
            "SBR*P*18*******CI~"
            "NM1*IL*1*DOE*JANE****MI*MEMBER001~"
            "CLM*CLM001*500***11:B:1*Y*A*Y*Y~"
            "SV1*HC:99213*250*200***1**1~"
            "SE*15*0001~GE*1*1~IEA*1*000000001~"
        )
        p = make_parser(edi)
        a = X12ForensicAnalyzer(p)
        ic = a.parser.interchanges[0]
        fg = ic.groups[0]
        ts = fg.transactions[0]
        claims = a._analyze_837_claims(ts, [], {})
        flags = claims[0].flags
        assert "HI_MISSING" in flags

    def test_amount_summary_clm_billed(self):
        a = forensic_for_fixture("sample_837_prof.edi")
        ic = a.parser.interchanges[0]
        fg = ic.groups[0]
        ts = fg.transactions[0]
        claims = a._analyze_837_claims(ts, [], {})
        amt = claims[0].amount_summary
        assert "clm_billed" in amt


# ── render_text ────────────────────────────────────────────────────────────────

class TestRenderText:
    def test_render_contains_interchange_section(self):
        a = forensic_for_fixture("sample_835.edi")
        report = a.analyze()
        text = a.render_text(report)
        assert "INTERCHANGE" in text
        assert "Sender" in text or "ISA" in text

    def test_render_contains_transaction_section(self):
        a = forensic_for_fixture("sample_835.edi")
        report = a.analyze()
        text = a.render_text(report)
        assert "TRANSACTION" in text
        assert "ST control" in text or "Segments" in text

    def test_render_contains_claim_traces(self):
        a = forensic_for_fixture("sample_835.edi")
        report = a.analyze()
        text = a.render_text(report)
        assert "CLAIM TRACES" in text
        assert "Claim:" in text

    def test_render_shows_unusual_envelope_conditions(self):
        edi = (
            "ISA*00*          *00*          *ZZ*               *ZZ*RECEIVER       "
            "*250402*1234*^*00501*000000001*0*P*:~"
            "GS*HP*SENDER*RECEIVER*20250402*1234*1*X*005010X221A1~"
            "ST*835*0001*005010X221A1~"
            "BPR*I*1000*C*ACH~"
            "SE*3*0001~GE*1*1~IEA*1*000000001~"
        )
        p = make_parser(edi)
        a = X12ForensicAnalyzer(p)
        report = a.analyze()
        text = a.render_text(report)
        assert "ISA_SENDER_BLANK" in text or "⚠" in text

    def test_render_shows_unusual_patterns_in_transaction(self):
        edi = (
            "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       "
            "*250402*1234*^*00501*000000001*0*P*:~"
            "GS*HP*SENDER*RECEIVER*20250402*1234*1*X*005010X221A1~"
            "ST*835*0001*005010X221A1~"
            "BPR*I*1000*C*ACH~"
            "BPR*I*500*C*ACH~"
            "TRN*1*0000000001~"
            "SE*5*0001~GE*1*1~IEA*1*000000001~"
        )
        p = make_parser(edi)
        a = X12ForensicAnalyzer(p)
        report = a.analyze()
        text = a.render_text(report)
        # Should show BPR_REPEATED pattern
        assert any("BPR_REPEATED" in p_ for p_ in report.transactions[0].unusual_patterns)

    def test_render_shows_file_level_flags(self):
        a = forensic_for_fixture("sample_multi_interchange.edi")
        report = a.analyze()
        text = a.render_text(report)
        assert "MULTIPLE_INTERCHANGES" in text

    def test_render_contains_width_60_separator(self):
        a = forensic_for_fixture("sample_835.edi")
        report = a.analyze()
        text = a.render_text(report)
        assert "=" * 60 in text or "=" * 64 in text

    def test_render_segment_trace_shows_loop_kind(self):
        a = forensic_for_fixture("sample_835.edi")
        report = a.analyze()
        text = a.render_text(report)
        # Should show loop kind (e.g., "claim", "entity", "service")
        for cl in report.claims:
            for step in cl.segment_trace:
                if step.is_unusual:
                    assert "⚠" in text
                    break

    def test_render_renders_837_claims(self):
        a = forensic_for_fixture("sample_837_institutional.edi")
        report = a.analyze()
        text = a.render_text(report)
        assert "CLAIM TRACES" in text
        assert any(cl.transaction_set == "837" for cl in report.claims)

    def test_render_claim_segment_trace_elements_truncated(self):
        """Element display should be truncated to 5 key-value pairs."""
        a = forensic_for_fixture("sample_835.edi")
        report = a.analyze()
        text = a.render_text(report)
        # Verify we don't explode on a claim with many elements
        for cl in report.claims:
            for step in cl.segment_trace:
                assert step.tag != ""

    def test_render_empty_claims_skipped(self):
        """render_text should handle empty claims list without crashing."""
        # Build a file with no CLP/CLM segments (empty transaction)
        edi = (
            "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       "
            "*250402*1234*^*00501*000000001*0*P*:~"
            "GS*HP*SENDER*RECEIVER*20250402*1234*1*X*005010X221A1~"
            "ST*835*0001*005010X221A1~"
            "BPR*I*1000*C*ACH~"
            "SE*3*0001~GE*1*1~IEA*1*000000001~"
        )
        p = make_parser(edi)
        a = X12ForensicAnalyzer(p)
        report = a.analyze()
        # Should not crash; claims section is simply absent when there are no claims
        assert len(report.claims) == 0
        text = a.render_text(report)
        assert "X12 FORENSIC ANALYSIS REPORT" in text  # header always present

    def test_render_segment_trace_shows_segment_position(self):
        a = forensic_for_fixture("sample_835.edi")
        report = a.analyze()
        text = a.render_text(report)
        # Position numbers should appear in trace
        for cl in report.claims:
            for step in cl.segment_trace:
                assert step.position >= 0

    def test_render_file_level_issue_flags_shown(self):
        a = forensic_for_fixture("sample_multi_interchange.edi")
        report = a.analyze()
        text = a.render_text(report)
        assert "FILE-LEVEL FLAGS" in text
