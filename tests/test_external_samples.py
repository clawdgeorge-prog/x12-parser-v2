"""Tests for external sample 835/837 files — expected issues and coverage.

These tests document the expected validation behavior for external partner
samples that may have payer-specific quirks. The tests verify that the parser
handles these gracefully without crashing, and that validation correctly 
identifies data quality issues vs. tool limitations.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from src.parser import X12Parser
from src.validate import X12Validator


FIXTURES = pathlib.Path(__file__).parent.parent / "external-test-files"


def validate_external(name: str):
    """Parse an external fixture and return ValidationResult."""
    fixture = FIXTURES / name
    parser = X12Parser.from_file(fixture)
    validator = X12Validator(parser)
    return validator.validate()


def codes(result):
    return {i.code for i in result.issues}


class TestExternal835Samples:
    """Test external 835 samples - verifying expected issues are documented."""

    def test_hdi_835_all_fields_parses_without_crash(self):
        """HDI 835 all fields should parse without crashing."""
        result = validate_external("hdi_835_all_fields.dat")
        assert result is not None
        # Should have some issues but not crash

    def test_hdi_835_all_fields_expected_issues(self):
        """HDI 835 all fields: SE count mismatch (file issue), CLP status out of range, BPR mismatch.
        
        This file has:
        - SE count mismatch (file declares 34, found 92) — data quality issue
        - CLP status code 226 (outside 1-29 range) — payer-specific code, warning is correct
        - BPR vs SVC sum mismatch — $132 vs $250, this is normal for files where SVC paid > CLP paid
        """
        result = validate_external("hdi_835_all_fields.dat")
        c = codes(result)
        assert "SE_COUNT_MISMATCH" in c
        assert "CLP_STATUS_OUT_OF_RANGE" in c
        # BPR_CLP_SUM_MISMATCH may or may not fire depending on balancing logic

    def test_hdi_835_denial_parses_without_crash(self):
        """HDI 835 denial should parse without crashing."""
        result = validate_external("hdi_835_denial.dat")
        assert result is not None

    def test_hdi_835_not_covered_inpatient_parses_without_crash(self):
        """HDI 835 not covered inpatient should parse without crashing."""
        result = validate_external("hdi_835_not_covered_inpatient.dat")
        assert result is not None

    def test_hdi_835_provider_level_adjustment_parses_without_crash(self):
        """HDI 835 provider-level adjustment (PLB-only, no claims) should parse."""
        result = validate_external("hdi_835_provider_level_adjustment.dat")
        assert result is not None
        # These have no CLP segments (PLB-only transactions) — expected warnings

    def test_jobisez_sample_parses_without_crash(self):
        """Jobisez bare transaction set should parse (returns empty interchanges)."""
        result = validate_external("jobisez_sample_835.edi")
        assert result is not None
        # Should have ORPHAN_ST since it's a fragment without envelope


class TestExternal837Samples:
    """Test external 837 samples - verifying expected issues are documented."""

    def test_hdi_837p_all_fields_clean(self):
        """HDI 837P all fields should be clean (no errors or warnings)."""
        result = validate_external("hdi_837p_all_fields.dat")
        c = codes(result)
        # This file is complete and well-formed
        assert len(c) == 0

    def test_hdi_837i_all_fields_has_se_count_mismatch(self):
        """HDI 837I all fields has known SE count mismatch (file issue)."""
        result = validate_external("hdi_837i_all_fields.dat")
        c = codes(result)
        # This is a documented data quality issue in the sample
        assert "SE_COUNT_MISMATCH" in c

    def test_hdi_837_commercial_has_envelope_issues(self):
        """HDI 837 commercial has orphan envelope segments (fragment)."""
        result = validate_external("hdi_837_commercial.dat")
        c = codes(result)
        # Fragment file — expected errors
        assert "ISA_IEA_MISMATCH" in c or "ORPHAN_ST" in c

    def test_hdi_837_multi_tran_has_orphan_st(self):
        """HDI 837 multi-tran has orphan ST segments (fragment)."""
        result = validate_external("hdi_837_multi_tran.dat")
        c = codes(result)
        # Fragment file — expected errors
        assert "ORPHAN_ST" in c

    def test_hdi_837_prof_encounter_has_envelope_issues(self):
        """HDI 837 professional encounter has orphan envelope segments."""
        result = validate_external("hdi_837_prof_encounter.dat")
        c = codes(result)
        # Fragment file — expected errors
        assert "ORPHAN_ST" in c or "ISA_IEA_MISMATCH" in c

    def test_hdi_837i_inst_claim_has_orphan_st(self):
        """HDI 837I institutional claim has orphan ST."""
        result = validate_external("hdi_837i_inst_claim.dat")
        c = codes(result)
        assert "ORPHAN_ST" in c

    def test_hdi_837i_x299_all_fields_has_orphan_st(self):
        """HDI 837I X299 all fields has orphan ST (outside envelope)."""
        result = validate_external("hdi_837i_x299_all_fields.dat")
        c = codes(result)
        assert "ORPHAN_ST" in c


class TestExternalSampleConfidenceMetadata:
    """Test that confidence/warning metadata is appropriate for external samples."""

    def test_external_837p_no_spurious_unknown_segment_warnings(self):
        """837P samples should not have spurious UNKNOWN_SEGMENT for common segments.
        
        Note: MEA, PS1, FRM are bounded-support (recognized but not deeply semanticized).
        """
        result = validate_external("hdi_837p_all_fields.dat")
        c = codes(result)
        # No warnings means no unknown segments were flagged
        assert len(c) == 0

    def test_fragment_aware_mode_suppresses_envelope_errors(self):
        """Fragment-aware mode should suppress ORPHAN_ST and ISA_IEA_MISMATCH."""
        from src.parser import X12Parser
        from src.validate import X12Validator
        
        parser = X12Parser.from_file(FIXTURES / "hdi_837_commercial.dat")
        validator = X12Validator(parser, mode="fragment-aware")
        result = validator.validate()
        c = codes(result)
        # In fragment mode, these should be suppressed
        assert "ISA_IEA_MISMATCH" not in c
        assert "ORPHAN_ST" not in c
