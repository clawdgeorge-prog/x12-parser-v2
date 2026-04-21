# X12 Parser — Roadmap & Gap Analysis

**Version:** 0.2.0 (released 2026-04-03)
**Date:** 2026-04-04
**Scope:** This document covers 835 and 837 transaction types only.

---

## Current Capabilities

### Parsing
- ✅ ISA/IEA envelope parsing with sender/receiver extraction
- ✅ GS/GE functional group parsing
- ✅ ST/SE transaction set framing
- ✅ Segment tokenization with element extraction
- ✅ Loop detection (heuristic, keyed by segment leader)
- ✅ Loop metadata: `leader_tag`, `leader_code`, `kind`, `description`
- ✅ **Transaction summaries** (835: financial totals, payer/provider, claim counts; 837: financial totals, billing provider, claim counts, HL counts)
- ✅ Multi-transaction files (multiple ST/SE in one GS/GE)
- ✅ Multi-interchange files (multiple ISA/IEA)
- ✅ Irregular whitespace/CRLF handling

### Validation
- ✅ ISA/IEA count pairing
- ✅ GS/GE count pairing per interchange
- ✅ ST/SE count pairing per functional group
- ✅ Empty transaction detection
- ✅ Empty group warnings
- ✅ Orphan envelope segment detection (ISA/IEA/GS/GE/ST/SE outside valid context)
- ✅ SE segment-count signal validation
- ✅ **ISA date (CCYYMMDD) format warnings**
- ✅ **ISA time (HHMM) format warnings**
- ✅ **Required segment presence per transaction type (835: BPR/TRN/N1/CLP; 837: BHT/NM1/CLM)**
- ✅ **Non-numeric amount field warnings (CLP, SVC, CAS monetary elements)**
- ✅ **Duplicate claim ID detection (CLP for 835, CLM for 837)**
- ✅ **837 variant detection (Professional / Institutional / Dental from SV1/SV2/UD)**
- ✅ **837 Institutional HI absence warning (SV2 without HI)**
- ✅ **835 N1 entity checks (N1*PR and N1*PE presence warnings)**
- ✅ **837 NM1 billing provider absence warning**
- ✅ **CLP status code validation (1–29 range check, non-numeric warning)**
- ✅ **Issue categorization (envelope / segment_structure / semantic / data_quality / content)**
- ✅ **Actionable recommendations in JSON output per issue code**
- ✅ Verbose text report with inline recommendations
- ✅ Unknown segment tag warnings
- ✅ Exit codes: 0 (clean), 1 (errors), 2 (parse failure)

### Test Coverage
- ✅ 158 pytest tests (97 parser + 61 validate)
- ✅ 67 run_tests.py checks
- ✅ 225 total automated checks

---

## Partial Capabilities (working, but limited)

### Composite element decomposition
SVC composite service IDs (e.g., `"HC:99213"`) are returned as raw strings. The qualifier (`HC`) and code (`99213`) are accessible via `segment.get(e, sub_index=1/2)` but not split in the JSON output.

### Loop ID nomenclature
Loop IDs are heuristic (first element of the leader segment, e.g., `CLP001`, `PR`, `IL`). They do not match official X12 loop IDs (`2100`, `2110`, etc.). Useful for grouping but not for spec compliance checking.

### Numeric amount extraction
`total_billed_amount` in 835/837 summaries sums CLP/CLM e2 values. If segments are missing or amounts are in unexpected positions, totals may be inaccurate.

### Cross-segment financial reconciliation (bounded)
The 835 summary provides:
- CLP-vs-SVC billed/paid discrepancy flags (per-claim, with severity + description)
- `zero_pay_inconsistency` detection (denied/pended status with non-zero SVC paid)
- CAS adjustment totals per claim (`cas_adjustment_sum`, `cas_adjustments_by_group`)
- PLB adjustment rollup by reason code (`plb_summary`)
- **Payment-level balancing summary** (`balancing_summary`): BPR vs sum-of-paid comparison (tolerance $0.05), SVC-billed total, claims without service lines, discrepancy counts

These are **flags and helpers for human review**, not full accounting truth. Reconciliation does not modify data or assert equality — it surfaces mismatches for human review.

---

## Missing Capabilities

### Schema-level validation (high value, medium complexity)
1. **Segment required/conditional rules** — X12 TR3 specs define which segments are required vs. optional per transaction type and context. A rule engine could validate these without full schema parsing.
2. **Element data type validation** — e.g., numeric fields should be numeric, date fields should match CCYYMMDD format.
3. **Element length/count limits** — X12 specifies minimum and maximum uses for each element.
4. **Code value validation** — e.g., NM1 e2 (entity identifier code) should be one of the valid values.
5. **Repeatable element count limits** — Some elements can repeat up to N times.

**Recommendation:** Phase this in as a rule table keyed by segment tag, with `(required, type, min_uses, max_uses, codes)` tuples. Do not attempt full regex-based schema parsing in v0.2.

### Other transaction types (medium value, low complexity for parsing)
- **270/271** — Eligibility inquiry/response
- **276/277** — Claims status inquiry/response
- **278** — Prior authorization
- **834** — Enrollment/disenrollment
- **277s** — For multiple transaction types

These parse at the loop level but have no transaction-specific summaries.

**Recommendation:** Add parsing support as fixtures become available. No schema changes needed — just new `_compute_{TYPE}_summary` methods.

### Composite element auto-decomposition
- Return composite sub-fields as `e1_sub1`, `e1_sub2` in JSON output
- Or add a `composite_elements` dict alongside `elements`

**Recommendation:** Low-risk, add after v0.2.

### Repetition separator (ISA-11) support
- [x] Extraction from ISA segment (v0.2.1)
- [ ] Usage for repeating element parsing (future)

Currently ISA-11 is extracted from ISA but not yet used for segment parsing. If present and non-standard, the parser should use it to split repeated elements within segments.

**Recommendation:** Implement when a fixture requiring it is available.

### CLI — additional output modes
- [x] `--summary` flag to print only the transaction summary (human-readable)
- [x] `--format ndjson` — newline-delimited JSON (one record per line)
- [x] `--format csv` — flat CSV files (claims, service lines, entities)
- [x] `--format sqlite` — normalized CSV bundle + schema.sql for SQLite import

---

## Recommended Phased Roadmap

### v0.2 — Semantic Hardening (current focus)
**Goal:** Make parsed 835/837 data immediately useful for business logic while keeping support-boundary claims conservative.

1. [x] Transaction summaries (financial totals, claim counts, party names)
2. [x] Non-numeric amount warnings
3. [x] Required segment checks
4. [x] Duplicate claim ID detection
5. [x] Recommendations in JSON output
6. [x] **HL hierarchy tree reconstruction for 837** (parent/child, billing_provider/subscriber/patient levels)
7. [x] **837 claim-level rollups** with service-line aggregation and discrepancy flags
8. [x] **835 claim-level rollups** (billed/paid/adjustment per CLP, SVC aggregation, discrepancy flags, PLB summary)
9. [x] **Deeper 835 balancing checks** (BPR vs CLP/SVC paid reconciliation, `zero_pay_inconsistency`, PLB reference format, `balancing_summary` block, discrepancy severity taxonomy)
10. [ ] SVC composite decomposition in JSON output
11. [ ] `extract_claims()` helper returning structured claim records with adjustments
12. [ ] Bounded dental-specific semantics beyond variant detection (only after fixtures/tests justify the claim)

### v0.3 — Rule-based Validation
**Goal:** Catch more data quality issues without full TR3 parsing.

1. [x] Small JSON companion-guide / payer-rule foundation (`--rules` packs with bounded presence/value assertions)
2. Element data type table (segment → {element_index → type})
3. Numeric/date/an/string field validation via type table
4. Required element presence per transaction type (a lightweight TR3 approximation)
5. Segment min/max occurrence checks

### v0.4 — Additional Transaction Types
**Goal:** Expand platform to 270/271, 276/277, 278.

1. Fixture collection for each new type
2. `_compute_{TYPE}_summary` implementation
3. `REQUIRED_SEGMENT_MISSING` check extended to new types

### v1.0 — Production Hardening
**Goal:** Ready for real-world use at scale.

1. Performance benchmarking and optimization for large files (>10MB)
2. Composite element auto-decomposition
3. ISA-11 repetition separator support
4. Code value lookup tables for common elements
5. Structured error/warning output for downstream pipeline integration

---

## Not Planned (Known Non-Goals)

- Full X12 schema parser (regex-based TR3 interpretation) — use a dedicated schema validator if needed
- Auto-correction of malformed data — the parser is read-only
- Support for non-healthcare X12 (automotive, supply chain, etc.) — out of scope
- Graphical UI — CLI and Python API only

---

*Last updated: 2026-04-04*
