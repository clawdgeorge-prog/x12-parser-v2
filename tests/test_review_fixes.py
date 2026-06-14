import pathlib
import tempfile

from src.batch import discover_input_files
from src.parser import X12SegmentParser
from src.reconcile import _match_reason, read_reference_claims_csv


def test_component_separator_is_respected():
    seg = X12SegmentParser(elem_sep='*', rep_sep='^', comp_sep='>').parse('SVC*HC>99213*100*80', 1)
    parser = X12SegmentParser(elem_sep='*', rep_sep='^', comp_sep='>')
    assert parser.get(seg, 1, 2) == '99213'


def test_match_reason_handles_zero_expected_paid():
    reason = _match_reason({'claim_id': 'ABC', 'expected_paid': '0.00'}, None, None)
    assert 'amount near 0.00' in reason


def test_reference_csv_requires_claim_id_header():
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / 'bad.csv'
        path.write_text('expected_paid\n10.00\n')
        try:
            read_reference_claims_csv(path)
            assert False, 'expected ValueError'
        except ValueError as exc:
            assert 'claim_id' in str(exc)


def test_batch_discovery_defaults_skip_txt():
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        (root / 'a.edi').write_text('ISA*')
        (root / 'notes.txt').write_text('not edi')
        files = discover_input_files(root)
        assert [p.name for p in files] == ['a.edi']
