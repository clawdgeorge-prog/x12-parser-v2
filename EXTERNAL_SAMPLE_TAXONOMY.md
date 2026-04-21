# External Sample Taxonomy

_Date: 2026-04-04_

This document classifies the external test files in `external-test-files/` by their structural characteristics and support boundaries.

## Taxonomy Classification

### Category A: Full Envelope Compatibility Samples

These files include complete ISA/GS envelopes and ST/SE transaction boundaries. They are the most structurally complete and are used for core parser validation.

| File | Transaction | Envelope | ST/SE | Notes |
|------|------------|---------|-------|-------|
| `hdi_835_all_fields.dat` | 835 | ISA→IEA | Yes | Rich 835 with TS3/MOA segments |
| `hdi_837p_all_fields.dat` | 837P | ISA→IEA | Yes | Full 837P with PRV/MEA/PS1/FRM |
| `hdi_837i_all_fields.dat` | 837I | ISA→IEA | Yes | Full 837I with bounded support segments |

### Category B: Partial / Transaction-Fragment Samples

These files start at ST (transaction set) without full envelope headers. They test the parser's ability to handle partial inputs gracefully.

| File | Transaction | Envelope | ST/SE | Notes |
|------|------------|---------|-------|-------|
| `jobisez_sample_835.edi` | 835 | None | Yes | Starts at ST, no ISA/GS |
| `hdi_837_commercial.dat` | 837P | No IEA | Yes | Orphan envelope segments (ISA/IEA mismatch) |
| `hdi_837_prof_encounter.dat` | 837P | No IEA | Yes | Orphan envelope segments |
| `hdi_837_multi_tran.dat` | 837P | Partial | Yes | Multiple transactions, envelope issues |

### Category C: Coverage / Stress Samples

These files contain edge cases, payer-specific formats, or unusual structures that stress the parser's handling of non-standard data.

| File | Transaction | Characteristics | Notes |
|------|-------------|------------------|-------|
| `hdi_835_denial.dat` | 835 | Denial claim (status 4, zero pay) | CLP status 4 (denied) |
| `hdi_835_not_covered_inpatient.dat` | 835 | Zero service lines | CLAIM_WITHOUT_SERVICE_LINES |
| `hdi_835_provider_level_adjustment.dat` | 835 | Provider-level PLB | No patient claims |
| `hdi_837i_inst_claim.dat` | 837I | Orphan ST | Outside envelope |
| `hdi_837i_x299_all_fields.dat` | 837I (X299) | Alternate claim type | Orphan ST |

## Support Boundary Notes

### Segment Recognition

The parser recognizes these segment families for bounded external support:

- **835**: BPR, TRN, DTM, N1, REF, LX, CLP, CAS, NM1, SVC, ADJ, DTP, TS2, TS3, MIA, MOA (tolerated but not deeply semanticized)
- **837**: PRV, CL1, PWK, OI, SVD, MEA, PS1, FRM (bounded support, recognized to prevent spurious warnings)

### CLP Status Codes

The standard X12 835 TR3 defines CLP status codes 1-29. External samples may use payer-specific codes (e.g., 30+) that trigger a `CLP_STATUS_OUT_OF_RANGE` warning. This is expected behavior—a warning indicates the code is non-standard, not invalid.

### SE Count Mismatches

External samples that fail SE segment count validation (`SE_COUNT_MISMATCH`) typically indicate data quality issues in the sample rather than parser defects. Known instances:
- `hdi_837i_all_fields.dat`: SE count mismatch (sample issue)

### Orphan ST Files

Files that trigger `ORPHAN_ST` (e.g., `hdi_837_commercial.dat`, `hdi_837_multi_tran.dat`) are structurally incomplete and should be treated as Category B samples.

## Recommended Test Matrix

| Category | Parse | Validate | Summary | NDJSON | CSV | SQLite |
|----------|-------|---------|---------|--------|------|-----|--------|
| A | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| B | ✓ | ~ (expected warnings) | ✓ | ✓ | - | - |
| C | ✓ | ~ (may have warnings) | ✓ | ✓ | ~ | ~ |

Legend: ✓ = expected pass, ~ = may have issues, - = not applicable