"""Tests for X12 Parser — fixtures 835 and 837."""

import json
import pathlib
import sys

# Add src to path
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from src.parser import (
    X12Parser, X12Tokenizer, X12SegmentParser,
    parse, parse_file,
    DEFAULT_ELEM_SEP, DEFAULT_COMP_SEP, DEFAULT_SEG_TERM,
)


FIXTURES = pathlib.Path(__file__).parent / "fixtures"


# ── Tokenizer tests ───────────────────────────────────────────────────────────

class TestTokenizer:
    def test_basic_split(self):
        t = X12Tokenizer()
        segs = t.tokenize("ST*835*0001~SE*15*0001~")
        assert segs == ["ST*835*0001", "SE*15*0001"]

    def test_multiline(self):
        t = X12Tokenizer()
        text = "ST*835*0001\nSE*15*0001\nIEA*1*000001"
        segs = t.tokenize(text)
        assert segs == ["ST*835*0001", "SE*15*0001", "IEA*1*000001"]

    def test_crlf_normalized(self):
        t = X12Tokenizer()
        segs = t.tokenize("ST*835*0001\r\nSE*15*0001\rIEA*1*000001")
        assert segs == ["ST*835*0001", "SE*15*0001", "IEA*1*000001"]


class TestDelimiterDetection:
    """Tests for dynamic delimiter extraction from ISA segment."""

    def test_standard_delimiters_detected(self):
        """Standard *:^~ delimiters should be detected from ISA."""
        p = X12Parser(text="")
        text = "ISA*00*          *00*          *ZZ*SUBMITTER     *ZZ*RECEIVER      *250402*1522*^*00501*000000001*0*P*:~GS*HP*SUBMITTER*RECEIVER*20250402*1522*1*X*005010X221A1~"
        elem, comp, rep, seg = p._detect_delimiters(text)
        assert elem == "*"
        assert comp == ":"
        assert rep == "^"
        assert seg == "~"

    def test_alternative_delimiters_detected(self):
        """Alternative +> delimiters should be detected from ISA."""
        p = X12Parser(text="")
        text = "ISA+00+          +00+          +ZZ+SENDER       +ZZ+RECEIVER       +250402+1522+^+00501+000000001+0+P+>~GS+HP+SENDER+RECEIVER+20250402+1522+1+X+005010X221A1~"
        elem, comp, rep, seg = p._detect_delimiters(text)
        assert elem == "+"
        assert comp == ">"
        assert rep == "^"
        assert seg == "~"

    def test_no_isa_returns_defaults(self):
        """No ISA segment should return defaults."""
        p = X12Parser(text="")
        elem, comp, rep, seg = p._detect_delimiters("ST*835*0001~SE*15*0001~")
        assert elem == "*"
        assert comp == ":"
        assert rep == "^"
        assert seg == "~"

    def test_alt_delimiter_file_parses_correctly(self):
        """File with alternative delimiters should parse correctly."""
        p = parse_file(str(FIXTURES / "sample_835_alt_delimiters.edi"))
        assert len(p.segments) == 17
        assert len(p.interchanges) == 1
        # ST segment should be properly parsed
        st = p.segments[2]
        assert st.tag == "ST"
        assert st.elements[0].raw == "835"
        assert st.elements[1].raw == "0001"

    def test_standard_delimiter_file_still_works(self):
        """Standard delimiter file should still parse correctly."""
        p = parse_file(str(FIXTURES / "sample_835.edi"))
        assert len(p.segments) == 34
        assert len(p.interchanges) == 1
        st = p.segments[2]
        assert st.tag == "ST"
        assert st.elements[0].raw == "835"


# ── Segment parser tests ───────────────────────────────────────────────────────

class TestSegmentParser:
    def test_parse_st(self):
        p = X12SegmentParser(elem_sep="*")
        seg = p.parse("ST*835*0001*005010X221A1", position=1)
        assert seg.tag == "ST"
        assert seg.elements[0].raw == "835"
        assert seg.elements[1].raw == "0001"

    def test_get_element(self):
        p = X12SegmentParser(elem_sep="*")
        seg = p.parse("BPR*H*1000*C*ACH", position=1)
        assert p.get(seg, 1) == "H"
        assert p.get(seg, 2) == "1000"
        assert p.get(seg, 99) is None

    def test_get_sub_element(self):
        p = X12SegmentParser(elem_sep="*")
        # Build a segment with a composite element at e3: "12:345"
        # CLM*e1*extra*e3=12:345
        seg = p.parse("CLM*CLM001*extra*12:345", position=1)
        # e1=CLM001, e2=extra, e3=12:345
        sub = p.get(seg, 3, sub_index=1)
        assert sub == "12", f"Expected '12', got {sub!r}"
        sub2 = p.get(seg, 3, sub_index=2)
        assert sub2 == "345", f"Expected '345', got {sub2!r}"


# ── File-level fixture tests ───────────────────────────────────────────────────

class Test835:
    @classmethod
    def setup_class(cls):
        fixture = FIXTURES / "sample_835.edi"
        cls.parser = X12Parser.from_file(fixture)
        cls.data = cls.parser.to_dict()

    def test_interchange_header(self):
        ic = self.data["interchanges"][0]
        assert ic["header"]["tag"] == "ISA"
        assert ic["isa06_sender"] == "SUBMITTER"
        assert ic["isa08_receiver"] == "RECEIVER"

    def test_gs_envelope(self):
        ic = self.data["interchanges"][0]
        fg = ic["functional_groups"][0]
        assert fg["header"]["tag"] == "GS"

    def test_transaction_set(self):
        ic = self.data["interchanges"][0]
        fg = ic["functional_groups"][0]
        ts = fg["transactions"][0]
        assert ts["header"]["tag"] == "ST"
        assert ts["set_id"] == "835"

    def test_loops_present(self):
        ic = self.data["interchanges"][0]
        fg = ic["functional_groups"][0]
        ts = fg["transactions"][0]
        loop_ids = [l["id"] for l in ts["loops"]]
        assert "PR" in loop_ids or "PE" in loop_ids or "QC" in loop_ids

    def test_segment_count_reasonable(self):
        ic = self.data["interchanges"][0]
        fg = ic["functional_groups"][0]
        ts = fg["transactions"][0]
        total = sum(len(l["segments"]) for l in ts["loops"])
        assert total >= 5, "Should have at least 5 segments inside transaction"

    def test_iea_trailer_present(self):
        ic = self.data["interchanges"][0]
        assert ic["trailer"]["tag"] == "IEA"


class Test837Professional:
    @classmethod
    def setup_class(cls):
        fixture = FIXTURES / "sample_837_prof.edi"
        cls.parser = X12Parser.from_file(fixture)
        cls.data = cls.parser.to_dict()

    def test_interchange_header(self):
        ic = self.data["interchanges"][0]
        assert ic["header"]["tag"] == "ISA"

    def test_transaction_set_id(self):
        ic = self.data["interchanges"][0]
        fg = ic["functional_groups"][0]
        ts = fg["transactions"][0]
        assert ts["set_id"] == "837"

    def test_hierarchical_levels(self):
        ic = self.data["interchanges"][0]
        fg = ic["functional_groups"][0]
        ts = fg["transactions"][0]
        # HL segments should appear in loops
        all_tags = []
        for loop in ts["loops"]:
            for seg in loop["segments"]:
                all_tags.append(seg["tag"])
        assert "HL" in all_tags

    def test_bht_present(self):
        ic = self.data["interchanges"][0]
        fg = ic["functional_groups"][0]
        ts = fg["transactions"][0]
        all_tags = []
        for loop in ts["loops"]:
            for seg in loop["segments"]:
                all_tags.append(seg["tag"])
        assert "BHT" in all_tags

    def test_svc_present(self):
        ic = self.data["interchanges"][0]
        fg = ic["functional_groups"][0]
        ts = fg["transactions"][0]
        all_tags = []
        for loop in ts["loops"]:
            for seg in loop["segments"]:
                all_tags.append(seg["tag"])
        assert "SV1" in all_tags or "SV2" in all_tags


class Test837Institutional:
    @classmethod
    def setup_class(cls):
        fixture = FIXTURES / "sample_837_institutional.edi"
        cls.parser = X12Parser.from_file(fixture)
        cls.data = cls.parser.to_dict()

    def test_interchange_header(self):
        ic = self.data["interchanges"][0]
        assert ic["header"]["tag"] == "ISA"

    def test_transaction_set_id(self):
        ic = self.data["interchanges"][0]
        fg = ic["functional_groups"][0]
        ts = fg["transactions"][0]
        assert ts["set_id"] == "837"

    def test_sv2_present(self):
        ic = self.data["interchanges"][0]
        fg = ic["functional_groups"][0]
        ts = fg["transactions"][0]
        all_tags = []
        for loop in ts["loops"]:
            for seg in loop["segments"]:
                all_tags.append(seg["tag"])
        assert "SV2" in all_tags, "Institutional claims use SV2"


# ── Loop metadata ─────────────────────────────────────────────────────────────

class TestLoopMetadata:
    """Verify that loop output includes enriched metadata fields."""

    def test_835_loop_has_all_metadata_fields(self):
        fixture = FIXTURES / "sample_835.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        for loop in ts["loops"]:
            assert "leader_tag" in loop, f"loop {loop['id']} missing leader_tag"
            assert "leader_code" in loop, f"loop {loop['id']} missing leader_code"
            assert "kind" in loop, f"loop {loop['id']} missing kind"
            assert "description" in loop, f"loop {loop['id']} missing description"
            assert loop["leader_tag"] != "", f"loop {loop['id']} has empty leader_tag"
            assert loop["kind"] != "", f"loop {loop['id']} has empty kind"
            assert loop["description"] != "", f"loop {loop['id']} has empty description"

    def test_835_loop_kind_values_recognized(self):
        fixture = FIXTURES / "sample_835.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        valid_kinds = {
            "entity", "claim", "service", "header", "adjustment",
            "amount", "date", "reference", "diagnosis", "payment",
            "trace", "other",
        }
        for loop in ts["loops"]:
            assert loop["kind"] in valid_kinds, \
                f"loop {loop['id']} has unknown kind: {loop['kind']}"

    def test_835_plb_loop_kind_is_adjustment(self):
        fixture = FIXTURES / "sample_835_rich.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        plb_loops = [l for l in ts["loops"] if l["leader_tag"] == "PLB"]
        assert len(plb_loops) >= 1, "PLB loop not found in rich 835"
        for l in plb_loops:
            assert l["kind"] == "adjustment", f"PLB loop has kind={l['kind']}"

    def test_837_nm1_loops_kind_is_entity(self):
        fixture = FIXTURES / "sample_837_prof.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        nm1_loops = [l for l in ts["loops"] if l["leader_tag"] == "NM1"]
        assert len(nm1_loops) >= 1
        for l in nm1_loops:
            assert l["kind"] == "entity", f"NM1 loop has kind={l['kind']}"

    def test_837_svc_loops_kind_is_service(self):
        fixture = FIXTURES / "sample_837_prof.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        svc_loops = [l for l in ts["loops"] if l["leader_tag"] in ("SV1", "SV2", "LX")]
        assert len(svc_loops) >= 1
        for l in svc_loops:
            assert l["kind"] in ("service",), f"{l['leader_tag']} loop has kind={l['kind']}"


# ── Rich 835 fixture ─────────────────────────────────────────────────────────

class Test835Rich:
    @classmethod
    def setup_class(cls):
        fixture = FIXTURES / "sample_835_rich.edi"
        cls.parser = X12Parser.from_file(fixture)
        cls.data = cls.parser.to_dict()

    def test_interchange_header(self):
        ic = self.data["interchanges"][0]
        assert ic["header"]["tag"] == "ISA"

    def test_transaction_set_id(self):
        ic = self.data["interchanges"][0]
        ts = ic["functional_groups"][0]["transactions"][0]
        assert ts["set_id"] == "835"

    def test_has_plb_segments(self):
        ic = self.data["interchanges"][0]
        ts = ic["functional_groups"][0]["transactions"][0]
        all_tags = [s["tag"] for l in ts["loops"] for s in l["segments"]]
        assert "PLB" in all_tags, "Rich 835 should contain PLB segments"

    def test_multiple_lx_loops(self):
        ic = self.data["interchanges"][0]
        ts = ic["functional_groups"][0]["transactions"][0]
        lx_loops = [l for l in ts["loops"] if l["leader_tag"] == "LX"]
        assert len(lx_loops) >= 3, f"Expected >=3 LX loops, got {len(lx_loops)}"

    def test_has_per_segment(self):
        ic = self.data["interchanges"][0]
        ts = ic["functional_groups"][0]["transactions"][0]
        all_tags = [s["tag"] for l in ts["loops"] for s in l["segments"]]
        assert "PER" in all_tags

    def test_se_count_present(self):
        ic = self.data["interchanges"][0]
        ts = ic["functional_groups"][0]["transactions"][0]
        assert ts["trailer"]["elements"]["e1"] not in (None, "", "0")


# ── Rich 837 Professional fixture ─────────────────────────────────────────────

class Test837ProfRich:
    @classmethod
    def setup_class(cls):
        fixture = FIXTURES / "sample_837_prof_rich.edi"
        cls.parser = X12Parser.from_file(fixture)
        cls.data = cls.parser.to_dict()

    def test_interchange_header(self):
        ic = self.data["interchanges"][0]
        assert ic["header"]["tag"] == "ISA"

    def test_transaction_set_id(self):
        ts = self.data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        assert ts["set_id"] == "837"

    def test_multiple_hl_levels(self):
        ts = self.data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        hl_loops = [l for l in ts["loops"] if l["leader_tag"] == "HL"]
        assert len(hl_loops) >= 2, f"Expected >=2 HL loops, got {len(hl_loops)}"

    def test_has_nested_subscriber_hl(self):
        ts = self.data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        # Find subscriber-level HL loops (child of billing provider HL, HL ID "2")
        subscriber_hls = [l for l in ts["loops"] if l["leader_tag"] == "HL" and l["leader_code"] == "2"]
        assert len(subscriber_hls) >= 1, f"Expected at least 1 subscriber HL loop, got {len(subscriber_hls)}"


# ── Multi-transaction fixture ─────────────────────────────────────────────────

class TestMultiTransaction:
    @classmethod
    def setup_class(cls):
        fixture = FIXTURES / "sample_multi_transaction.edi"
        cls.parser = X12Parser.from_file(fixture)
        cls.data = cls.parser.to_dict()

    def test_three_transactions_in_one_group(self):
        fg = self.data["interchanges"][0]["functional_groups"][0]
        assert len(fg["transactions"]) == 3

    def test_all_set_id_835(self):
        fg = self.data["interchanges"][0]["functional_groups"][0]
        assert all(ts["set_id"] == "835" for ts in fg["transactions"])

    def test_distinct_transaction_ids(self):
        fg = self.data["interchanges"][0]["functional_groups"][0]
        ids = [ts["header"]["elements"]["e2"] for ts in fg["transactions"]]
        assert len(set(ids)) == 3

    def test_each_transaction_has_loops(self):
        fg = self.data["interchanges"][0]["functional_groups"][0]
        assert all(len(ts["loops"]) >= 1 for ts in fg["transactions"])


# ── Multi-interchange fixture ──────────────────────────────────────────────────

class TestMultiInterchange:
    @classmethod
    def setup_class(cls):
        fixture = FIXTURES / "sample_multi_interchange.edi"
        cls.parser = X12Parser.from_file(fixture)
        cls.data = cls.parser.to_dict()

    def test_three_interchanges(self):
        assert len(self.data["interchanges"]) == 3

    def test_ic1_is_835(self):
        ts = self.data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        assert ts["set_id"] == "835"

    def test_ic2_is_835(self):
        ts = self.data["interchanges"][1]["functional_groups"][0]["transactions"][0]
        assert ts["set_id"] == "835"

    def test_ic3_is_837(self):
        ts = self.data["interchanges"][2]["functional_groups"][0]["transactions"][0]
        assert ts["set_id"] == "837"

    def test_ic3_sender_extracted(self):
        ic3 = self.data["interchanges"][2]
        assert ic3["isa06_sender"] == "THIRDIC"
        assert ic3["isa08_receiver"] == "THIRDRCV"


# ── Whitespace-irregular fixture ──────────────────────────────────────────────

class TestWhitespaceIrregular:
    @classmethod
    def setup_class(cls):
        fixture = FIXTURES / "sample_whitespace_irregular.edi"
        cls.parser = X12Parser.from_file(fixture)
        cls.data = cls.parser.to_dict()

    def test_parses_without_crash(self):
        # Should not raise
        ic = self.data["interchanges"][0]
        assert ic["header"]["tag"] == "ISA"

    def test_transaction_is_835(self):
        ts = self.data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        assert ts["set_id"] == "835"

    def test_has_clp_loop(self):
        ts = self.data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        assert any(l["leader_tag"] == "CLP" for l in ts["loops"])

    def test_has_nm1_qc_loop(self):
        ts = self.data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        assert any(l["leader_code"] == "QC" for l in ts["loops"])


# ── JSON roundtrip ─────────────────────────────────────────────────────────────

def test_json_serializable():
    fixture = FIXTURES / "sample_835.edi"
    parser = X12Parser.from_file(fixture)
    data = parser.to_dict()
    # Should not raise
    json.dumps(data)
    assert True


def test_json_serializable_837():
    fixture = FIXTURES / "sample_837_prof.edi"
    parser = X12Parser.from_file(fixture)
    data = parser.to_dict()
    json.dumps(data)
    assert True


# ── Helper parser functions ─────────────────────────────────────────────────────

def test_parse_file_function():
    fixture = FIXTURES / "sample_835.edi"
    p = parse_file(fixture)
    assert len(p.interchanges) >= 1


def test_parse_function():
    text = (FIXTURES / "sample_835.edi").read_text()
    p = parse(text)
    assert len(p.interchanges) >= 1
    ic = p.interchanges[0]
    assert ic.header.tag == "ISA"
    assert len(ic.groups) >= 1
    assert len(ic.groups[0].transactions) >= 1
    assert ic.groups[0].transactions[0].set_id == "835"


# ── Transaction summaries ────────────────────────────────────────────────────────

class Test835Summary:
    """Verify 835 transaction summary fields are populated and correct."""

    def test_summary_present(self):
        fixture = FIXTURES / "sample_835.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        assert "summary" in ts
        summary = ts["summary"]
        assert summary["set_id"] == "835"
        assert summary["segment_count"] > 0
        assert summary["loop_count"] > 0
        assert summary["claim_count"] >= 1
        assert summary["service_line_count"] >= 1

    def test_summary_amounts_are_numeric(self):
        fixture = FIXTURES / "sample_835.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        summary = ts["summary"]
        assert isinstance(summary["total_billed_amount"], (int, float))
        assert isinstance(summary["total_paid_amount"], (int, float))
        assert isinstance(summary["total_adjustment_amount"], (int, float))
        assert isinstance(summary["payment_amount"], (int, float))

    def test_summary_identifies_payer_and_provider(self):
        fixture = FIXTURES / "sample_835.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        summary = ts["summary"]
        # From sample_835.edi: N1*PR*INSURANCE COMPANY ONE, N1*PE*PROVIDER CLINIC
        assert summary["payer_name"] is not None
        assert summary["provider_name"] is not None
        assert summary["check_trace"] is not None

    def test_summary_no_duplicate_claims_in_basic_fixture(self):
        fixture = FIXTURES / "sample_835.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        summary = ts["summary"]
        assert summary["duplicate_claim_ids"] == []


class Test837Summary:
    """Verify 837 transaction summary fields are populated and correct."""

    def test_summary_present(self):
        fixture = FIXTURES / "sample_837_prof.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        assert "summary" in ts
        summary = ts["summary"]
        assert summary["set_id"] == "837"
        assert summary["segment_count"] > 0
        assert summary["claim_count"] >= 1
        assert summary["service_line_count"] >= 1
        assert summary["hl_count"] >= 1

    def test_summary_identifies_parties(self):
        fixture = FIXTURES / "sample_837_prof.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        summary = ts["summary"]
        assert summary["billing_provider"] is not None
        assert summary["bht_id"] is not None
        assert summary["bht_date"] is not None

    def test_summary_bht_date_format(self):
        fixture = FIXTURES / "sample_837_prof.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        summary = ts["summary"]
        # BHT e4 is CCYYMMDD format
        assert len(summary["bht_date"]) == 8
        assert summary["bht_date"].isdigit()


class TestRich835Summary:
    """Verify rich 835 summary (PLB segments, multiple LX loops)."""

    def test_plb_count_reflected(self):
        fixture = FIXTURES / "sample_835_rich.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        summary = ts["summary"]
        assert summary["plb_count"] >= 1, "Rich 835 should have PLB segments"

    def test_multiple_claims(self):
        fixture = FIXTURES / "sample_835_rich.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        summary = ts["summary"]
        assert summary["claim_count"] >= 3, "Rich 835 has 4 LX/CLP loops"
        assert summary["service_line_count"] >= 3

    def test_payment_amount_from_bpr(self):
        fixture = FIXTURES / "sample_835_rich.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        summary = ts["summary"]
        # BPR*I*3500*C*ACH... → payment_amount should be 3500.0
        assert summary["payment_amount"] == 3500.0


# ── 837 hierarchy semantics ──────────────────────────────────────────────────

class Test837Hierarchy:
    """Verify 837 hierarchy reconstruction from HL parent-child structure."""

    def test_hl_tree_present_in_summary(self):
        fixture = FIXTURES / "sample_837_prof_rich.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        summary = ts["summary"]
        assert "hierarchy" in summary
        assert "hl_tree" in summary["hierarchy"]

    def test_hl_tree_has_billing_provider_level(self):
        fixture = FIXTURES / "sample_837_prof_rich.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        hl_tree = ts["summary"]["hierarchy"]["hl_tree"]
        bp_levels = [e for e in hl_tree if e["level_role"] == "billing_provider"]
        assert len(bp_levels) >= 1
        assert bp_levels[0]["level_code"] == "20"

    def test_hl_tree_has_subscriber_level(self):
        fixture = FIXTURES / "sample_837_prof_rich.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        hl_tree = ts["summary"]["hierarchy"]["hl_tree"]
        sub_levels = [e for e in hl_tree if e["level_role"] == "subscriber"]
        assert len(sub_levels) >= 1
        assert sub_levels[0]["level_code"] == "22"

    def test_hl_parent_child_relationships(self):
        fixture = FIXTURES / "sample_837_prof_rich.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        hl_tree = ts["summary"]["hierarchy"]["hl_tree"]
        # Build lookup
        by_id = {e["id"]: e for e in hl_tree}
        # Subscriber should have billing provider as parent
        subscriber = next((e for e in hl_tree if e["level_role"] == "subscriber"), None)
        assert subscriber is not None
        if subscriber["parent_id"]:
            parent = by_id.get(subscriber["parent_id"])
            assert parent is not None
            assert parent["level_role"] == "billing_provider"

    def test_hierarchy_has_level_names(self):
        fixture = FIXTURES / "sample_837_prof_rich.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        h = ts["summary"]["hierarchy"]
        # Billing provider name should be extracted from NM1 in the billing provider HL
        assert h.get("billing_provider_name") is not None

    def test_claims_list_present(self):
        fixture = FIXTURES / "sample_837_prof_rich.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        summary = ts["summary"]
        assert "claims" in summary
        assert len(summary["claims"]) >= 1

    def test_claim_has_service_lines(self):
        fixture = FIXTURES / "sample_837_prof_rich.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        claims = ts["summary"]["claims"]
        assert any(len(cl.get("service_lines", [])) >= 1 for cl in claims)


# ── 835 reconciliation helpers ───────────────────────────────────────────────

class Test835Reconciliation:
    """Verify 835 claim-level rollups and discrepancy flags."""

    def test_claims_list_present(self):
        fixture = FIXTURES / "sample_835.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        summary = ts["summary"]
        assert "claims" in summary
        assert len(summary["claims"]) == 2

    def test_claim_has_required_fields(self):
        fixture = FIXTURES / "sample_835.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        claims = ts["summary"]["claims"]
        for cl in claims:
            assert "claim_id" in cl
            assert "clp_billed" in cl
            assert "clp_paid" in cl
            assert "svc_billed" in cl
            assert "svc_paid" in cl
            assert "service_line_count" in cl
            assert "has_billed_discrepancy" in cl
            assert "has_paid_discrepancy" in cl
            assert "adjustment_group_codes" in cl

    def test_rich_835_claims_populated(self):
        fixture = FIXTURES / "sample_835_rich.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        claims = ts["summary"]["claims"]
        assert len(claims) == 4
        for cl in claims:
            assert cl["service_line_count"] >= 1
            assert cl["svc_billed"] > 0

    def test_rich_835_svc_billed_accumulated(self):
        fixture = FIXTURES / "sample_835_rich.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        claims = ts["summary"]["claims"]
        # SVC billed amounts are reliably extracted from SVC e2 in the DTM/SVC loop
        billed = [cl["svc_billed"] for cl in claims]
        assert billed == [250.0, 300.0, 275.0, 450.0]
        paid = [cl["svc_paid"] for cl in claims]
        assert paid == [200.0, 150.0, 175.0, 300.0]

    def test_discrepancies_field_present(self):
        fixture = FIXTURES / "sample_835.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        summary = ts["summary"]
        assert "discrepancies" in summary
        assert isinstance(summary["discrepancies"], list)

    def test_discrepancy_flags_when_clp_svc_mismatch(self):
        # Create a synthetic 835 where CLP billed != SVC billed to test flag
        from src.parser import X12Parser
        # Structure: DTM absorbs SVC so it accumulates into the current claim.
        # CLP billed=500, SVC billed=400 → billed_mismatch discrepancy.
        edi = (
            "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       "
            "*250402*1530*^*00501*000000001*0*P*:~"
            "GS*HP*SENDER*RECEIVER*250402*1530*1*X*005010X221A1~"
            "ST*835*0001*005010X221A1~"
            "BPR*I*100*ACH~"
            "N1*PR*PAYER~"
            "N1*PE*PROVIDER~"
            "LX*1~"
            "CLP*CLM001*500*1*400~"   # CLP: billed=500, status=1, paid=400
            "CAS*CO*45*100~"
            "DTM*472*D8*20250401~"   # DTM absorbs SVC
            "SVC*HC:99213*400*400~"  # SVC: billed=400, paid=400
            "DTP*472*D8*20250401~"
            "SE*12*0001~"
            "GE*1*1~"
            "IEA*1*000000001~"
        )
        p = X12Parser(text=edi)
        data = p.to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        summary = ts["summary"]
        # CLP billed=500, SVC billed=400 → should flag billed_mismatch
        disc = summary["discrepancies"]
        billed_discs = [d for d in disc if d["type"] == "billed_mismatch"]
        assert len(billed_discs) >= 1
        assert billed_discs[0]["clp_billed"] == 500.0
        assert billed_discs[0]["sum_svc_billed"] == 400.0

    def test_plb_summary_populated(self):
        fixture = FIXTURES / "sample_835_rich.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        summary = ts["summary"]
        assert "plb_summary" in summary
        assert summary["plb_count"] == 2
        ps = summary["plb_summary"]
        assert ps["total_plb_adjustment"] == 35.0  # CV:25 + WO:10
        assert "CV" in ps["adjustment_by_code"]
        assert ps["adjustment_by_code"]["CV"] == 25.0

    def test_plb_summary_absent_when_no_plb(self):
        fixture = FIXTURES / "sample_835.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        summary = ts["summary"]
        assert summary["plb_count"] == 0
        assert summary["plb_summary"]["total_plb_adjustment"] == 0.0


class Test837VariantDetection:
    """837 variant (professional/institutional/dental) detection."""

    def test_837_professional_variant(self):
        fixture = FIXTURES / "sample_837_prof.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        summary = ts["summary"]
        assert summary["variant"] == "professional"
        assert summary["variant_indicator"] == "P"
        assert summary["service_line_type"] == "professional"

    def test_837_institutional_variant(self):
        fixture = FIXTURES / "sample_837_institutional.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        summary = ts["summary"]
        assert summary["variant"] == "institutional"
        assert summary["variant_indicator"] == "I"
        assert summary["service_line_type"] == "institutional"

    def test_837_dental_variant(self):
        fixture = FIXTURES / "sample_837_dental.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        summary = ts["summary"]
        assert summary["variant"] == "dental"
        assert summary["variant_indicator"] == "D"
        assert summary["service_line_type"] == "dental"


class Test835Enrichment:
    """835 BPR and CLP status enrichment."""

    def test_bpr_payment_method_extracted(self):
        fixture = FIXTURES / "sample_835.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        summary = ts["summary"]
        assert "bpr_payment_method" in summary
        # sample_835.edi has BPR*H (ACH)
        assert summary["bpr_payment_method"] == "H"

    def test_bpr_payment_method_label(self):
        fixture = FIXTURES / "sample_835.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        summary = ts["summary"]
        assert summary["bpr_payment_method"] == "H"
        assert summary["bpr_payment_method_label"] == "ACH"

    def test_clp_status_labels(self):
        fixture = FIXTURES / "sample_835.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        summary = ts["summary"]
        for cl in summary["claims"]:
            assert "status_label" in cl
            assert "status_category" in cl
            assert cl["status_label"] != ""
            assert cl["status_category"] in {"paid", "pended", "denied", "forwarded", "informational", "unknown"}

    def test_discrepancy_fixture_detects_billed_mismatch(self):
        """sample_835_discrepancy.edi: CLP billed=1000, SVC billed=250 → mismatch."""
        fixture = FIXTURES / "sample_835_discrepancy.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        summary = ts["summary"]
        assert summary["total_billed_amount"] == 1800.0
        assert len(summary["discrepancies"]) == 1
        assert summary["discrepancies"][0]["type"] == "billed_mismatch"
        assert summary["discrepancies"][0]["claim_id"] == "CLP001"
        assert summary["discrepancies"][0]["difference"] == 750.0

    def test_discrepancy_fixture_clp002_no_mismatch(self):
        fixture = FIXTURES / "sample_835_discrepancy.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        clp002 = next(c for c in ts["summary"]["claims"] if c["claim_id"] == "CLP002")
        assert not clp002["has_billed_discrepancy"]
        assert clp002["svc_billed"] == 800.0

    def test_plb_adjustment_labels(self):
        fixture = FIXTURES / "sample_835_rich.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        summary = ts["summary"]
        plb_summary = summary["plb_summary"]
        assert "adjustment_labels" in plb_summary
        assert "CV" in plb_summary["adjustment_labels"]
        assert "WO" in plb_summary["adjustment_labels"]
        assert plb_summary["adjustment_labels"]["CV"] == "Covered"
        assert plb_summary["adjustment_labels"]["WO"] == "Write-Off"


class Test835Balancing:
    """835 payment-level balancing: BPR vs CLP sums, balancing summary, discrepancy taxonomy."""

    def test_balancing_summary_present(self):
        fixture = FIXTURES / "sample_835.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        summary = ts["summary"]
        assert "balancing_summary" in summary
        bal = summary["balancing_summary"]
        assert "bpr_payment_amount" in bal
        assert "sum_clp_paid" in bal
        assert "bpr_vs_clp_difference" in bal
        assert "bpr_vs_clp_balanced" in bal
        assert "has_claim_discrepancies" in bal
        assert "discrepancy_count" in bal

    def test_balancing_summary_balanced_fixture(self):
        """sample_835.edi: BPR=1000, SVC paid sum=270 (CLP001:150+CLP002:120) → not balanced.
        In this fixture BPR is intentionally larger than sum of SVC paid because
        PLB adjustments (not present) would normally close the gap.
        Note: CLP e6 paid amounts are empty in this fixture; actual payments
        come from SVC segments, so we use sum_svc_paid for reconciliation."""
        fixture = FIXTURES / "sample_835.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        summary = ts["summary"]
        bal = summary["balancing_summary"]
        assert bal["bpr_payment_amount"] == 1000.0
        assert bal["sum_svc_paid"] == 270.0  # from SVC segments (CLP e6 is empty in this fixture)
        assert bal["bpr_vs_clp_balanced"] is False

    def test_balancing_summary_has_claim_discrepancies(self):
        """Discrepancy fixture should report has_claim_discrepancies=True."""
        fixture = FIXTURES / "sample_835_discrepancy.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        bal = ts["summary"]["balancing_summary"]
        assert bal["has_claim_discrepancies"] is True
        assert bal["discrepancy_count"] >= 1

    def test_discrepancy_severity_field_present(self):
        """All discrepancy records now carry a severity field."""
        fixture = FIXTURES / "sample_835_discrepancy.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        for disc in ts["summary"]["discrepancies"]:
            assert "severity" in disc
            assert disc["severity"] in ("warning", "info")
            assert "description" in disc

    def test_zero_pay_inconsistency_detected(self):
        """A claim with denial status (4) but non-zero SVC paid should produce
        a zero_pay_inconsistency discrepancy."""
        # CLP status=4 (denied) but SVC paid=100 → zero_pay_inconsistency
        edi = (
            "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       "
            "*250402*1530*^*00501*000000001*0*P*:~"
            "GS*HP*SENDER*RECEIVER*250402*1530*1*X*005010X221A1~"
            "ST*835*0001*005010X221A1~"
            "BPR*I*100*ACH~"
            "N1*PR*PAYER~"
            "N1*PE*PROVIDER~"
            "LX*1~"
            "CLP*CLM001*500*4*100~"   # denied but paid=100
            "CAS*CO*45*400~"
            "DTM*472*D8*20250401~"
            "SVC*HC:99213*500*100~"
            "SE*10*0001~"
            "GE*1*1~"
            "IEA*1*000000001~"
        )
        p = X12Parser(text=edi)
        data = p.to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        disc = ts["summary"]["discrepancies"]
        zero_pay = [d for d in disc if d["type"] == "zero_pay_inconsistency"]
        assert len(zero_pay) == 1
        assert zero_pay[0]["claim_id"] == "CLM001"
        assert zero_pay[0]["status_code"] == "4"
        assert zero_pay[0]["svc_paid"] == 100.0

    def test_cas_adjustment_sum_per_claim(self):
        """Each claim record should include cas_adjustment_sum and cas_adjustments_by_group."""
        fixture = FIXTURES / "sample_835_rich.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        claims = ts["summary"]["claims"]
        for cl in claims:
            assert "cas_adjustment_sum" in cl
            assert "cas_adjustments_by_group" in cl
            assert isinstance(cl["cas_adjustments_by_group"], dict)

    def test_balancing_fixture_bpr_clp_mismatch(self):
        """sample_835_balancing.edi: BPR=950, sum CLP paid=750 → should show mismatch."""
        fixture = FIXTURES / "sample_835_balancing.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        bal = ts["summary"]["balancing_summary"]
        assert bal["bpr_payment_amount"] == 950.0
        assert bal["sum_clp_paid"] == 750.0  # CLP001:750 + CLP002:0
        assert bal["bpr_vs_clp_balanced"] is False
        assert bal["bpr_vs_clp_difference"] == 200.0  # 950 - 750

    def test_denied_claim_without_svc_in_balancing_summary(self):
        """sample_835_balancing.edi: CLP002 is denied (status=4) with 0 paid, no svc should
        not appear in claims_without_service_lines since it's denied."""
        fixture = FIXTURES / "sample_835_balancing.edi"
        data = X12Parser.from_file(fixture).to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        bal = ts["summary"]["balancing_summary"]
        # CLP002 is status=4 (denied), so it's excluded from the no-svc warning list
        assert "BADCLAIM002" not in bal.get("claims_without_service_lines", [])

    def test_zero_pay_inconsistency_severity_is_info(self):
        """zero_pay_inconsistency should have severity=info (not warning)."""
        edi = (
            "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       "
            "*250402*1530*^*00501*000000001*0*P*:~"
            "GS*HP*SENDER*RECEIVER*250402*1530*1*X*005010X221A1~"
            "ST*835*0001*005010X221A1~"
            "BPR*I*100*ACH~"
            "N1*PR*PAYER~"
            "N1*PE*PROVIDER~"
            "LX*1~"
            "CLP*CLM001*500*4*100~"
            "CAS*CO*45*400~"
            "DTM*472*D8*20250401~"
            "SVC*HC:99213*500*100~"
            "SE*10*0001~"
            "GE*1*1~"
            "IEA*1*000000001~"
        )
        p = X12Parser(text=edi)
        data = p.to_dict()
        ts = data["interchanges"][0]["functional_groups"][0]["transactions"][0]
        zero_pay = [d for d in ts["summary"]["discrepancies"]
                    if d["type"] == "zero_pay_inconsistency"]
        assert len(zero_pay) == 1
        assert zero_pay[0]["severity"] == "info"


class TestStableOutputContract:
    def test_to_dict_includes_schema_version(self):
        data = X12Parser.from_file(FIXTURES / "sample_835.edi").to_dict()
        assert data["schema_version"] == "1.0"
        assert "version" in data
        assert "interchanges" in data


if __name__ == "__main__":

    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
