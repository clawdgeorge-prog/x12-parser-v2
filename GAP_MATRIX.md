# X12 Parser — Gap Matrix & Execution Plan

_Date: 2026-04-04_

## Current Top 5 Priorities

| Priority | Workstream | Why it matters | Current state | Target outcome today | Status |
|---|---|---|---|---|---|
| 1 | Dynamic ISA delimiter extraction | Biggest parser-hardening gap; required for real-world non-default X12 robustness | Dynamic extraction now implemented | Parse delimiters directly from ISA reliably, add tests/fixtures/docs, keep existing behavior stable | **DONE** |
| 2 | Large 835 stress testing | Real remits can be much larger than current fixtures; parser not stress-tested | Synthetic large-file benchmark/generation tooling, fixtures, and stress tests now implemented | Add generated large-835 fixture strategy/benchmark tooling/tests and document safe limits/observations | **DONE** |
| 3 | Additional output modes | JSON-only is limiting for real ops/analytics | JSON + summary + validation only | CSV extracts, NDJSON, and SQLite-ready normalized exports | ✅ DONE (v0.2.1) |
| 4 | Deeper 835 balancing checks | Important for remits/reconciliation credibility | Balancing checks deepened in bounded, honest way | BPR vs CLP/SVC reconciliation, zero_pay_inconsistency, PLB ref format, balancing_summary block, discrepancy severity taxonomy, bounded tests/fixtures/docs | **DONE** |
| 5 | Companion-guide / payer rules framework | Needed for real-world payer-specific evolution | Small JSON rule-pack foundation now implemented | Added bounded `--rules` support, JSON rule-pack loader/validation, two sample packs, docs, and tests | DONE |

## Secondary / Additional Gaps

| Gap | Current state | Notes |
|---|---|---|
| Formal TR3 loop IDs | Heuristic loop grouping only | Useful, but not canonical spec modeling |
| 837 dental semantics | Scaffolded / bounded | Needs clear support boundary |
| Composite element auto-decomposition | Raw strings only | Useful follow-on after delimiter work |
| Repetition separator handling | Extracted from ISA (v0.2.1) | Should improve with ISA parsing work — now extracted but not used for segment parsing |
| Streaming parser for very large files | Not implemented | May become necessary after large-file benchmark pass |
| Transport/security pipeline (AS2/SFTP/HIPAA ops) | Out of scope for parser repo | Separate concern unless product expands |
| Outbound/generation support | Not implemented | Lower priority than parsing/validation/export |

## Execution Method

This push is being run as a coordinated multi-agent development campaign with:
- a dedicated gap matrix,
- parallel implementation workstreams,
- frequent George QA/check-in passes,
- comprehensive tests before push,
- regular GitHub commits as each workstream lands,
- README / ROADMAP / DEMO / PROGRESS updates with each meaningful change.

## Definition of Done for this campaign

For each top-5 item:
1. code lands cleanly,
2. tests are added and pass,
3. docs are updated,
4. demo/examples are updated if relevant,
5. repo is committed and pushed,
6. support boundaries remain honest.

## Push Cadence

- Prefer one clean commit per completed workstream or sub-workstream.
- Push to GitHub after each completed priority item if quality bar is met.
- If a workstream is only partially ready, do not push noisy half-work unless it is behind a clearly bounded/documented interface.

## Oversight cadence

George should review progress at least every ~15 minutes during the active campaign and give concrete next-step steering where needed.
