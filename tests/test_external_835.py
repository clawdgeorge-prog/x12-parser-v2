"""
Tests for external/public 835 samples.
These tests ensure compatibility with real-world 835 files that may contain
segments like TS3, MOA that are not fully semanticized but should be tolerated.
"""

import pytest
from src.parser import parse


class TestHDIExternal835:
    """Test external HDI 835 sample with TS3 and MOA segments."""

    @pytest.fixture
    def hdi_835_path(self):
        return "external-test-files/hdi_835_all_fields.dat"

    def test_parse_completes_without_error(self, hdi_835_path):
        """Parser should complete without crashing on HDI sample."""
        with open(hdi_835_path) as f:
            content = f.read()
        result = parse(content)
        d = result.to_dict()
        # Should have 1 interchange
        assert len(d["interchanges"]) == 1

    def test_summary_computation_no_crash(self, hdi_835_path):
        """Summary mode should not crash on discrepancies."""
        with open(hdi_835_path) as f:
            content = f.read()
        result = parse(content)
        d = result.to_dict()
        trans = d["interchanges"][0]["functional_groups"][0]["transactions"][0]
        summary = trans.get("summary", {})
        # Should have discrepancies
        assert "discrepancies" in summary
        assert len(summary["discrepancies"]) == 2
        # Each discrepancy should have proper fields
        for disc in summary["discrepancies"]:
            assert "type" in disc
            assert "claim_id" in disc

    def test_ts3_and_moa_tolerated(self, hdi_835_path):
        """TS3 and MOA segments should be parsed without error."""
        with open(hdi_835_path) as f:
            content = f.read()
        result = parse(content)
        d = result.to_dict()
        trans = d["interchanges"][0]["functional_groups"][0]["transactions"][0]
        # Collect all segment tags
        tags = []
        for loop in trans.get("loops", []):
            for seg in loop.get("segments", []):
                tags.append(seg.get("tag"))
        # TS3 and MOA should be present and not cause crash
        assert "TS3" in tags
        assert "MOA" in tags


class TestJobisezExternal835:
    """Test jobsez 835 sample (bare transaction set without envelope)."""

    @pytest.fixture
    def jobisez_835_path(self):
        return "external-test-files/jobisez_sample_835.edi"

    def test_bare_transaction_set_handled(self, jobisez_835_path):
        """Bare transaction set without ISA/GS should return empty interchanges."""
        with open(jobisez_835_path) as f:
            content = f.read()
        result = parse(content)
        d = result.to_dict()
        # No envelope means no interchanges - this is expected behavior
        assert len(d["interchanges"]) == 0
