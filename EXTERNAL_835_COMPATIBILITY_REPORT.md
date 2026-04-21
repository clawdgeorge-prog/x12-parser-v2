# External 835 / 837 Compatibility Report

_Date: 2026-04-04_

## Purpose

This note summarizes external/public 835 and 837 compatibility testing performed after the initial parser hardening campaign. The goal was to validate the parser against public examples outside the repo's original fixture set and to identify practical gaps that only show up on external samples.

## Tested External/Public Samples

### 835 samples

#### 1. Healthcare Data Insight 835 sample
- Local file: `external-test-files/hdi_835_all_fields.dat`
- Source family: public example linked from Healthcare Data Insight's 835 example page / public GitHub example repository
- Characteristics:
  - fully enveloped 835
  - multiple service lines
  - CAS adjustments
  - includes `TS3` and `MOA`
  - useful as a richer external-style sample

#### 2. Jobisez 835 sample
- Local file: `external-test-files/jobisez_sample_835.edi`
- Source family: public sample content published on Jobisez
- Characteristics:
  - transaction-set-only sample (starts at `ST`)
  - does **not** include a full ISA/GS envelope
  - useful for defensive behavior testing, not for full-envelope validation

### 837 samples

#### 3. Healthcare Data Insight 837P sample
- Local file: `external-test-files/hdi_837p_all_fields.dat`
- Source family: public example linked from Healthcare Data Insight's public 837 example repo/pages
- Characteristics:
  - fully enveloped 837 Professional claim
  - rich field population
  - useful as an external compatibility and summary/demo candidate

#### 4. Healthcare Data Insight 837I sample
- Local file: `external-test-files/hdi_837i_all_fields.dat`
- Source family: public example linked from Healthcare Data Insight's public 837 example repo/pages
- Characteristics:
  - fully enveloped 837 Institutional claim
  - rich field population
  - useful for bounded institutional compatibility testing

## Test Matrix

The following operations were exercised against the available external samples:
- parse to JSON
- CLI summary mode
- validator JSON / verbose output
- NDJSON export
- CSV export (835 pass)
- SQLite bundle export (835 pass)

Machine-generated run summaries:
- `external-test-results/external_835_test_summary.json`
- `external-test-results/external_837_test_summary.json`

## Results

### 835 — HDI sample
**Current status:** compatible in a bounded, practical sense.

What works:
- JSON parsing
- CLI summary mode
- validator execution
- NDJSON export
- CSV export
- SQLite bundle export

Important note:
- The sample includes `TS3` and `MOA` segments. The parser now tolerates these without crashing.
- These segments are currently preserved but not deeply semanticized.

### 835 — Jobisez sample
**Current status:** tolerated gracefully as a partial/bare transaction sample.

What works:
- parser does not crash
- summary mode does not crash
- exports do not crash

Bounded behavior:
- because the file does not contain a full ISA/GS/GE/IEA envelope, the parser returns empty interchanges and the validator correctly treats it as structurally incomplete for full-envelope expectations
- this is expected behavior, not a parser defect

### 837P — HDI sample
**Current status:** good external compatibility sample.

What works:
- JSON parsing
- CLI summary mode
- validator execution
- NDJSON export

Important note:
- After bounded external 837 recognition work, common support segments like `PRV` no longer produce spurious unknown-segment noise.
- This file is currently one of the best external 837P compatibility references in the repo.

### 837I — HDI sample
**Current status:** useful bounded institutional compatibility sample.

What works:
- JSON parsing
- CLI summary mode
- NDJSON export
- validator execution

What remains:
- the file still triggers an `SE_COUNT_MISMATCH`
- based on the current investigation, this appears to be a data-quality issue in the external sample rather than a parser bug

Additional note:
- bounded recognition now covers `PRV`, `CL1`, `PWK`, `OI`, and `SVD`
- CAS validation was adjusted so repeated reason/amount triplets are interpreted more correctly and spurious non-numeric amount warnings are avoided

## External-Facing Fixes Made During This Pass

### Summary-mode crash fixed
An external HDI 835 sample surfaced a real bug in CLI summary rendering:
- discrepancy rendering assumed every discrepancy type carried the same fields
- some discrepancy types provide `clp_paid` rather than `clp_billed`

Fix applied:
- summary rendering is now type-aware and uses safer field access per discrepancy type
- result: external summary mode no longer crashes on this sample

### Bounded 835 optional-segment recognition
Decision:
- classify `TS3`, `MOA`, `MIA`, and `TS2` as tolerated / known-optional 835 segments
- preserve them in parse output / loop structure
- add descriptive loop names for these segments in 835 context
- do **not** claim deep semantic support yet (no dedicated field extraction)

### Bounded 837 support-segment recognition
Decision:
- classify `PRV`, `CL1`, `PWK`, `OI`, and `SVD` as tolerated / recognized support segments in bounded external 837 flows
- prevent misleading unknown-segment warnings where the file is otherwise valid
- do **not** claim deep semantic coverage for all segment elements yet

### CAS repeated-triplet validation fix
The external 837I sample surfaced validator behavior that treated some reason-code positions as though they were amount fields.

Fix applied:
- CAS validation now checks amount positions more carefully in repeated triplets
- result: spurious non-numeric amount warnings from reason-code positions are reduced/removed

## What This Testing Does *Not* Prove

This pass does **not** prove:
- full compatibility with payer-specific 835/837 variants
- support for arbitrary large real-world remits or claims at all scales
- full TR3/SNIP compliance
- deep semantic support for every optional segment encountered in the wild

It *does* prove that the parser is no longer limited to its original internal fixtures and can handle several richer external/public healthcare EDI examples without crashing, including through summary and export flows.

## Current Compatibility Posture

Best honest summary:

> The parser has been validated against internal fixtures plus a small number of public external 835 and 837 samples. Core parsing and summary/export paths work on those samples, including richer files that contain optional/support segments. Optional segments may be tolerated without being deeply semanticized, and compatibility should still be treated as bounded rather than universal.

## Recommended Next Steps

1. Continue searching for additional public/de-identified 835 and 837 examples.
2. Add one or two more representative external-style fixtures if licensing and size are appropriate.
3. Consider a lightweight compatibility matrix in docs by segment family or sample family.
4. If more real-world samples repeatedly include certain optional segments, promote those segments from tolerated to more explicitly modeled.
5. If larger public/de-identified files are found, incorporate one into the demo/benchmark surface with clear source attribution and support-boundary notes.
