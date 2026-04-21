# Root Cause Analysis — External Sample Validation Findings

_Date: 2026-04-04_

## Purpose

This note records the root-cause analysis for current validator/output issues seen while exercising the curated external sample set under `external-test-files/`.

The goal is to distinguish among:
1. actual parser/validator defects,
2. sample data-quality issues,
3. expected fragment / partial-file behavior,
4. valid unsupported structures that may deserve future support.

## Issue Table

| Issue code | Affected files | Root cause | Confidence | Recommendation |
|---|---|---|---|---|
| `ORPHAN_ST` | `jobisez_sample_835.edi`, `hdi_837_multi_tran.dat`, `hdi_837i_inst_claim.dat`, `hdi_837i_x299_all_fields.dat` | These are transaction fragments or ST/SE-only samples with no enclosing GS and/or ISA envelope. Validator is correctly flagging ST segments that appear outside a functional group. | High | Document, not fix |
| `ISA_IEA_MISMATCH` | `hdi_837_commercial.dat`, `hdi_837_prof_encounter.dat` | These files contain partial envelopes (e.g. ISA present, but no matching IEA and no complete GS/GE structure). The mismatch is in the sample structure, not the parser. | High | Document as partial-envelope samples |
| `SE_COUNT_MISMATCH` | `hdi_837i_all_fields.dat`, `hdi_835_all_fields.dat`, `hdi_835_not_covered_inpatient.dat`, `hdi_835_provider_level_adjustment.dat` | Raw segment counts exceed declared `SE01` values in these external/public examples. At least some of these appear to be genuine sample-quality/count issues rather than parser counting defects. | Medium-High | Document as sample-quality issue; do not mask |
| `CLAIM_WITHOUT_SERVICE_LINES` | `hdi_835_not_covered_inpatient.dat` | File contains a claim-level record with zero `SVC` service lines. Warning is justified under the current validator rule. | High | Document as expected bounded warning |
| `REQUIRED_SEGMENT_MISSING` (`CLP`) | `hdi_835_provider_level_adjustment.dat` | The provider-level adjustment sample contains unusual multi-transaction / PLB-heavy structure in which some transactions do not include a normal claim-level `CLP`. Current validator behavior is consistent with its normal 835 assumptions. | Medium | Document; consider future richer PLB-only support |
| `CLP_STATUS_OUT_OF_RANGE` | `hdi_835_all_fields.dat`, `hdi_835_denial.dat`, `hdi_835_not_covered_inpatient.dat`, `hdi_835_provider_level_adjustment.dat` | These external samples use non-standard or payer-specific status-code values outside the standard X12 1–29 range. Validator warning is correct. | High | Document, not fix |
| `BPR_CLP_SUM_MISMATCH` | `hdi_835_all_fields.dat` | Review flag only. Indicates the public sample's payment/reconciliation data does not line up cleanly with the validator's bounded balancing assumptions. Not enough evidence here to call this a parser bug. | Medium | Document as reconciliation warning; future deeper review optional |
| `UNKNOWN_SEGMENT` | Remaining major 837P noise has been reduced/removed after bounded recognition work | Prior warnings were genuine bounded-support gaps and were addressed where safe. | High | Mostly fixed already |

## Structural Findings by Sample Class

### Category A — Full-envelope compatibility samples
These are the strongest external compatibility references.

- `hdi_835_all_fields.dat`
- `hdi_837p_all_fields.dat`
- `hdi_837i_all_fields.dat`

These files contain full ISA/GS/ST envelopes and are the best basis for parser/output trust discussions. Even here, a public sample may still carry count or value anomalies.

### Category B — Partial / transaction-fragment samples
These are not suitable as clean validator fixtures.

- `jobisez_sample_835.edi`
- `hdi_837_commercial.dat`
- `hdi_837_prof_encounter.dat`
- `hdi_837_multi_tran.dat`

These files are useful for parser resilience and bounded behavior checks, but warnings like `ORPHAN_ST` or `ISA_IEA_MISMATCH` are expected.

### Category C — Coverage / stress samples
These exercise unusual but useful shapes.

- `hdi_835_denial.dat`
- `hdi_835_not_covered_inpatient.dat`
- `hdi_835_provider_level_adjustment.dat`
- `hdi_837i_inst_claim.dat`
- `hdi_837i_x299_all_fields.dat`

These are helpful for edge-case coverage, but not all are clean validator exemplars.

## Conclusions

### What the RCA confirms
- The fragment/partial-sample hypothesis is correct for several of the current 837 and Jobisez sample issues.
- Several remaining warnings/errors are sample-quality problems rather than parser defects.
- Current external validator noise is **not** strong evidence of a major hidden parser failure.

### What should be fixed now
No additional obvious parser fix fell out of this RCA beyond the bounded support already added earlier.

### What should be documented
- fragment/partial sample behavior
- sample-side `SE_COUNT_MISMATCH`
- non-standard public `CLP` status values
- unusual provider-level adjustment / PLB-heavy 835 sample behavior

### What may deserve future support
1. richer support for unusual 835 provider-level-adjustment-only structures
2. deeper 835 reconciliation logic for public payer examples
3. possibly an explicit fragment-aware validation mode for ST/SE-only sample files

## Recommended Next Engineering Move

Prefer documentation/product framing over speculative parser changes unless a new clean raw sample demonstrates a genuine parser defect.

If more work is desired, the most valuable next step is likely one of:
- add a fragment-aware validation mode or clearer validator mode distinctions,
- or continue expanding the curated external sample set with stronger full-envelope institutional examples.
