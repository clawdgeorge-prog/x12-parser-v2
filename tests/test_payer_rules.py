import json
import pathlib
import sys
import subprocess

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from src.parser import X12Parser
from src.payer_rules import load_rule_pack, RulePackError, CompanionRuleEngine

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
EXAMPLES = pathlib.Path(__file__).parent.parent / "examples" / "rules"


def test_load_sample_rule_pack():
    pack = load_rule_pack(EXAMPLES / "premier-835-companion.sample.json")
    assert pack.name.startswith("Premier Insurance")
    assert len(pack.rules) == 2


def test_all_example_rule_packs_load():
    packs = sorted(EXAMPLES.glob("*.json"))
    assert len(packs) >= 7
    loaded = [load_rule_pack(path) for path in packs]
    assert all(pack.rules for pack in loaded)
    assert any("Aetna" in pack.name for pack in loaded)
    assert any("UnitedHealthcare" in pack.name for pack in loaded)


def test_invalid_rule_pack_rejected(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"name": "bad", "rules": [{"id": "x"}]}))
    try:
        load_rule_pack(bad)
        assert False, "Expected RulePackError"
    except RulePackError as exc:
        assert "segment" in str(exc)


def test_companion_rule_pack_matches_and_emits_warning():
    parser = X12Parser.from_file(FIXTURES / "sample_835_rich.edi")
    pack = load_rule_pack(EXAMPLES / "premier-835-companion.sample.json")
    result = CompanionRuleEngine(parser).apply_pack(pack)
    codes = {i.code for i in result.issues}
    assert "PAYER_RULE_VALUE_MISMATCH" in codes
    assert result.clean is True


def test_companion_rule_pack_does_not_match_other_payer():
    parser = X12Parser.from_file(FIXTURES / "sample_835.edi")
    pack = load_rule_pack(EXAMPLES / "premier-835-companion.sample.json")
    result = CompanionRuleEngine(parser).apply_pack(pack)
    assert result.issues == []


def test_validate_cli_applies_rule_pack():
    fixture = FIXTURES / "sample_835_rich.edi"
    rules = EXAMPLES / "premier-835-companion.sample.json"
    result = subprocess.run(
        [sys.executable, "-m", "src.validate", str(fixture), "--json", "--rules", str(rules)],
        capture_output=True,
        text=True,
        cwd=pathlib.Path(__file__).parent.parent,
    )
    parsed = json.loads(result.stdout)
    codes = {issue["code"] for issue in parsed["issues"]}
    assert "PAYER_RULE_VALUE_MISMATCH" in codes


def test_validate_cli_bad_rule_pack_exits_2(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not-json")
    fixture = FIXTURES / "sample_835.edi"
    result = subprocess.run(
        [sys.executable, "-m", "src.validate", str(fixture), "--rules", str(bad)],
        capture_output=True,
        text=True,
        cwd=pathlib.Path(__file__).parent.parent,
    )
    assert result.returncode == 2
    assert "could not load rule pack" in result.stderr
