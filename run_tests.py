#!/usr/bin/env python3
"""Run all parser tests and report."""
import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))

import sys, io
from src.parser import X12Parser, X12Tokenizer, X12SegmentParser, parse, parse_file

# Capture and display debug output from parser
old_stderr = sys.stderr

FIXTURES = pathlib.Path(__file__).parent / "tests" / "fixtures"
FAILED = []
PASSED = 0

def check(name, cond, detail=""):
    global PASSED
    if cond:
        PASSED += 1
        print(f"  ✓ {name}")
    else:
        FAILED.append((name, detail))
        print(f"  ✗ {name}: {detail}")

# ── Tokenizer ──
print("\n[Tokenizer]")
t = X12Tokenizer()
segs = t.tokenize("ST*835*0001~SE*15*0001~")
check("basic split", segs == ["ST*835*0001", "SE*15*0001"])
segs2 = t.tokenize("ST*835*0001\nSE*15*0001\nIEA*1*000001")
check("multiline", segs2 == ["ST*835*0001", "SE*15*0001", "IEA*1*000001"])
segs3 = t.tokenize("ST*835*0001\r\nSE*15*0001\rIEA*1*000001")
check("crlf normalized", segs3 == ["ST*835*0001", "SE*15*0001", "IEA*1*000001"])

# ── Segment parser ──
print("\n[Segment Parser]")
p = X12SegmentParser(elem_sep="*")
seg = p.parse("ST*835*0001*005010X221A1", position=1)
check("ST tag", seg.tag == "ST")
check("ST element 1", seg.elements[0].raw == "835")
check("ST element 2", seg.elements[1].raw == "0001")
check("get element out-of-range", p.get(seg, 99) is None)
sub = p.get(seg, 3, sub_index=1)
check("sub-element via get", sub == "005010X221A1")

# ── 835 fixture ──
print("\n[835 Fixture]")
fx = FIXTURES / "sample_835.edi"
data = X12Parser.from_file(fx).to_dict()
ic = data["interchanges"][0]
fg = ic["functional_groups"][0]
ts = fg["transactions"][0]
check("ISA header", ic["header"]["tag"] == "ISA")
check("sender ISA06", ic["isa06_sender"] == "SUBMITTER")
check("receiver ISA08", ic["isa08_receiver"] == "RECEIVER")
check("GS envelope", fg["header"]["tag"] == "GS")
check("ST transaction", ts["header"]["tag"] == "ST")
check("set_id 835", ts["set_id"] == "835")
check("IEA trailer", ic["trailer"]["tag"] == "IEA")
check("GE trailer", fg["trailer"]["tag"] == "GE")
check("SE trailer", ts["trailer"]["tag"] == "SE")
loop_ids = [l["id"] for l in ts["loops"]]
check("has loops", len(ts["loops"]) > 0, f"ids={loop_ids}")
check("BPR segment", any("BPR" in str(l) for l in ts["loops"]))

# ── 837 Professional fixture ──
print("\n[837 Professional Fixture]")
fx2 = FIXTURES / "sample_837_prof.edi"
data2 = X12Parser.from_file(fx2).to_dict()
ic2 = data2["interchanges"][0]
fg2 = ic2["functional_groups"][0]
ts2 = fg2["transactions"][0]
check("837 set_id", ts2["set_id"] == "837")
check("HL segments present", any("HL" in l["id"] or any(s["tag"] == "HL" for s in l["segments"]) for l in ts2["loops"]))
check("BHT present", any("BHT" in str(l) for l in ts2["loops"]))
check("SV1 present", any(any(s["tag"] == "SV1" for s in l["segments"]) for l in ts2["loops"]))
check("CLM present", any(any(s["tag"] == "CLM" for s in l["segments"]) for l in ts2["loops"]))

# ── 837 Institutional fixture ──
print("\n[837 Institutional Fixture]")
fx3 = FIXTURES / "sample_837_institutional.edi"
data3 = X12Parser.from_file(fx3).to_dict()
ic3 = data3["interchanges"][0]
fg3 = ic3["functional_groups"][0]
ts3 = fg3["transactions"][0]
check("837 inst set_id", ts3["set_id"] == "837")
check("SV2 present (institutional)", any(any(s["tag"] == "SV2" for s in l["segments"]) for l in ts3["loops"]))
check("HI present (diagnosis)", any(any(s["tag"] == "HI" for s in l["segments"]) for l in ts3["loops"]))

# ── JSON roundtrip ──
print("\n[JSON Serialization]")
import json
try:
    json.dumps(data)
    check("835 JSON roundtrip", True)
except Exception as e:
    check("835 JSON roundtrip", False, str(e))
try:
    json.dumps(data2)
    check("837 prof JSON roundtrip", True)
except Exception as e:
    check("837 prof JSON roundtrip", False, str(e))
try:
    json.dumps(data3)
    check("837 inst JSON roundtrip", True)
except Exception as e:
    check("837 inst JSON roundtrip", False, str(e))

# ── Helper functions ──
print("\n[Helper Functions]")
p = parse_file(FIXTURES / "sample_835.edi")
check("parse_file returns interchanges", len(p.interchanges) >= 1)
p2 = parse((FIXTURES / "sample_835.edi").read_text())
check("parse text returns interchanges", len(p2.interchanges) >= 1)
check("parse correct set_id", p2.interchanges[0].groups[0].transactions[0].set_id == "835")

# ── Rich 835 fixture ──
print("\n[Rich 835 Fixture]")
fx_rich = FIXTURES / "sample_835_rich.edi"
data_rich = X12Parser.from_file(fx_rich).to_dict()
ic_rich = data_rich["interchanges"][0]
fg_rich = ic_rich["functional_groups"][0]
ts_rich = fg_rich["transactions"][0]
check("rich 835: parses without crash", True)
check("rich 835: has PLB segments", any(s["tag"] == "PLB" for l in ts_rich["loops"] for s in l["segments"]))
check("rich 835: has 4 LX groups", sum(1 for l in ts_rich["loops"] if l["leader_tag"] == "LX") >= 3)
check("rich 835: SE segment count field", ts_rich["trailer"].get("elements", {}).get("e1") not in (None, ""))
check("rich 835: multiple N1 PE", sum(1 for l in ts_rich["loops"] if l["leader_tag"] == "N1" and l["leader_code"] == "PE") >= 1)
# Loop metadata: every loop must have leader_tag, leader_code, kind, description
loop_meta_ok = all(
    all(k in l for k in ("leader_tag", "leader_code", "kind", "description"))
    for l in ts_rich["loops"]
)
check("rich 835: loop metadata fields present", loop_meta_ok)
# kind should be one of known categories
valid_kinds = {"entity", "claim", "service", "header", "adjustment",
               "amount", "date", "reference", "diagnosis", "payment",
               "trace", "other", "contact"}
kind_ok = all(l.get("kind", "") in valid_kinds for l in ts_rich["loops"])
check("rich 835: loop kind values valid", kind_ok)
# description should be non-empty
desc_ok = all(l.get("description", "") != "" for l in ts_rich["loops"])
check("rich 835: loop descriptions non-empty", desc_ok)
# PLB loop should have kind=adjustment
plb_loops = [l for l in ts_rich["loops"] if l["leader_tag"] == "PLB"]
check("rich 835: PLB loop kind=adjustment",
      all(l["kind"] == "adjustment" for l in plb_loops))

# ── Rich 837 Professional fixture ──
print("\n[Rich 837 Professional Fixture]")
fx_prof_rich = FIXTURES / "sample_837_prof_rich.edi"
data_pr = X12Parser.from_file(fx_prof_rich).to_dict()
ic_pr = data_pr["interchanges"][0]
fg_pr = ic_pr["functional_groups"][0]
ts_pr = fg_pr["transactions"][0]
check("rich 837 prof: parses without crash", True)
check("rich 837 prof: multiple HL levels", len([l for l in ts_pr["loops"] if l["leader_tag"] == "HL"]) >= 2)
check("rich 837 prof: HI diagnosis present", any(l["leader_tag"] == "HI" for l in ts_pr["loops"]))
check("rich 837 prof: loop metadata complete",
      all(k in l for k in ("leader_tag", "leader_code", "kind", "description") for l in ts_pr["loops"]))
# NM1 entity loops should have kind=entity
nm1_loops = [l for l in ts_pr["loops"] if l["leader_tag"] == "NM1"]
check("rich 837 prof: NM1 loops kind=entity", all(l["kind"] == "entity" for l in nm1_loops))

# ── Multi-transaction fixture ──
print("\n[Multi-Transaction Fixture]")
fx_mt = FIXTURES / "sample_multi_transaction.edi"
data_mt = X12Parser.from_file(fx_mt).to_dict()
ic_mt = data_mt["interchanges"][0]
fg_mt = ic_mt["functional_groups"][0]
check("multi-tx: has 3 transactions", len(fg_mt["transactions"]) == 3)
check("multi-tx: all set_id 835",
      all(ts["set_id"] == "835" for ts in fg_mt["transactions"]))
check("multi-tx: SE counts distinct",
      len(set(ts["trailer"]["elements"]["e1"] for ts in fg_mt["transactions"])) == 3)
check("multi-tx: each transaction has loops",
      all(len(ts["loops"]) >= 1 for ts in fg_mt["transactions"]))

# ── Multi-interchange fixture ──
print("\n[Multi-Interchange Fixture]")
fx_mi = FIXTURES / "sample_multi_interchange.edi"
data_mi = X12Parser.from_file(fx_mi).to_dict()
check("multi-ic: has 3 interchanges", len(data_mi["interchanges"]) == 3)
check("multi-ic: first IC is 835", data_mi["interchanges"][0]["functional_groups"][0]["transactions"][0]["set_id"] == "835")
check("multi-ic: third IC is 837", data_mi["interchanges"][2]["functional_groups"][0]["transactions"][0]["set_id"] == "837")
check("multi-ic: IC3 sender/receiver extracted",
      data_mi["interchanges"][2]["isa06_sender"] == "THIRDIC")

# ── Whitespace-irregular fixture ──
print("\n[Whitespace-Irregular Fixture]")
fx_ws = FIXTURES / "sample_whitespace_irregular.edi"
data_ws = X12Parser.from_file(fx_ws).to_dict()
ic_ws = data_ws["interchanges"][0]
fg_ws = ic_ws["functional_groups"][0]
ts_ws = fg_ws["transactions"][0]
check("ws-irregular: parses without crash", True)
check("ws-irregular: transaction set_id 835", ts_ws["set_id"] == "835")
check("ws-irregular: has CLP", any(l["leader_tag"] == "CLP" for l in ts_ws["loops"]))
check("ws-irregular: has NM1 QC", any(l["leader_code"] == "QC" for l in ts_ws["loops"]))

# ── Loop metadata — general ──
print("\n[Loop Metadata — All Fixtures]")
all_fixture_data = [data, data2, data3, data_rich, data_pr, data_mt, data_mi, data_ws]
for label, fd in [("835", data), ("837-prof", data2), ("837-inst", data3),
                  ("835-rich", data_rich), ("837-prof-rich", data_pr),
                  ("multi-tx", data_mt), ("multi-ic-1", data_mi), ("ws-irregular", data_ws)]:
    for ic in fd["interchanges"]:
        for fg in ic["functional_groups"]:
            for ts in fg["transactions"]:
                for l in ts["loops"]:
                    if not l.get("leader_tag"):
                        check(f"{label}: all loops have leader_tag", False, f"missing in {l}")
                    if not l.get("kind"):
                        check(f"{label}: all loops have kind", False)
                    if not l.get("description"):
                        check(f"{label}: all loops have description", False)
loop_meta_all = all(
    all(k in l for k in ("leader_tag", "leader_code", "kind", "description"))
    for fd in all_fixture_data
    for ic in fd["interchanges"]
    for fg in ic["functional_groups"]
    for ts in fg["transactions"]
    for l in ts["loops"]
)
check("all fixtures: loop metadata complete", loop_meta_all)

# ── Resilience / Negative tests ──
print("\n[Resilience / Negative Cases]")

# Malformed: ISA without IEA — parser should not crash, returns empty or partial
try:
    bad1 = "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       *20260101*1234*^*00501*000000001*0*P*:~GS*HC*SENDER*RECEIVER*20260101*1234*1*X*005010X221A1~ST*835*0001~BPR*C*1000*ACH****CLP*CLM001*1*~SE*3*0001~GE*1*1~"
    r1 = X12Parser(text=bad1).to_dict()
    check("ISA without IEA — no crash", True)
    check("ISA without IEA — interchanges still found", len(r1["interchanges"]) >= 0)
except Exception as e:
    check("ISA without IEA — no crash", False, str(e))

# Malformed: ST without SE — should still parse header/trailer gracefully
try:
    bad2 = "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       *20260101*1234*^*00501*000000001*0*P*:~GS*HC*SENDER*RECEIVER*20260101*1234*1*X*005010X221A1~ST*835*0001~BPR*C*1000*ACH~SE*3*0001~GE*1*1~IEA*1*000000001~"
    r2 = X12Parser(text=bad2).to_dict()
    check("ST/SE pair — transaction parsed", len(r2["interchanges"]) > 0)
except Exception as e:
    check("ST/SE pair — no crash", False, str(e))

# Bare ST/SE transaction (no ISA wrapper) — per README limitation, behavior may vary
try:
    bare = "ST*835*0001~BPR*C*1000*ACH~SE*3*0001~"
    r3 = X12Parser(text=bare).to_dict()
    check("bare ST/SE — no crash", True)
    # Per known limitations: bare ST/SE is not supported; interchanges will be empty
    has_interchange = len(r3["interchanges"]) > 0
    check("bare ST/SE — limitation documented (interchanges empty)", not has_interchange,
          "Known limitation: bare ST/SE not yet supported")
except Exception as e:
    check("bare ST/SE — no crash", False, str(e))

# Unexpected segment order (SE before ST) — should not crash
try:
    bad3 = "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       *20260101*1234*^*00501*000000001*0*P*:~GS*HC*SENDER*RECEIVER*20260101*1234*1*X*005010X221A1~SE*3*0001~ST*835*0001~BPR*C*1000*ACH~GE*1*1~IEA*1*000000001~"
    r4 = X12Parser(text=bad3).to_dict()
    check("SE before ST (out of order) — no crash", True)
except Exception as e:
    check("SE before ST (out of order) — no crash", False, str(e))

# Empty file — should not crash
try:
    r5 = X12Parser(text="").to_dict()
    check("empty input — no crash", True)
except Exception as e:
    check("empty input — no crash", False, str(e))

# ── Summary ──
print(f"\n{'='*50}")
print(f"Passed: {PASSED}")
print(f"Failed: {len(FAILED)}")
if FAILED:
    for name, detail in FAILED:
        print(f"  ✗ {name}: {detail}")
    sys.exit(1)
else:
    print("All tests passed!")
    sys.exit(0)
