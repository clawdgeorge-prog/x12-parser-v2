# X12 Parser — Push / Merge Gate

Use this checklist before any GitHub push during the 2026-04-04 top-5 hardening campaign.

## Release bar

A workstream is only push-ready when all applicable boxes are true.

### 1. Code quality
- [ ] Changes are scoped and understandable
- [ ] No obvious dead code / placeholder comments left behind
- [ ] Support boundaries remain honest in code comments and CLI wording
- [ ] No regressions visible in adjacent parser/validator behavior

### 2. Tests
- [ ] New behavior has direct tests
- [ ] Existing parser tests pass
- [ ] Existing validator tests pass
- [ ] Any benchmark/stress scripts run cleanly enough to support claimed findings
- [ ] Test names and fixtures clearly match what the feature actually does

### 3. Documentation
- [ ] README updated if user-facing behavior changed
- [ ] ROADMAP updated to reflect new state
- [ ] PROGRESS updated with what changed and what remains limited
- [ ] DEMO updated when output shape or workflow changed
- [ ] GAP_MATRIX updated for the workstream status

### 4. CLI / output surface
- [ ] CLI help/examples still make sense
- [ ] Output labels do not overstate semantic certainty
- [ ] New output modes are documented and demonstrated
- [ ] Errors/warnings remain understandable to operators

### 5. Boundaries / honesty
- [ ] No implied TR3/SNIP-complete claims unless truly implemented
- [ ] No implied production-scale claims unless benchmarked and documented
- [ ] No payer/companion-guide claims beyond what config/tests truly support
- [ ] Dental / heuristic / helper features remain clearly framed if still partial

### 6. Git hygiene
- [ ] `git status` is clean except for intentionally included files
- [ ] Commit message is specific and professional
- [ ] Commit groups one coherent workstream or sub-workstream
- [ ] Ready to push without immediate follow-up cleanup

## Push cadence for this campaign

Preferred order:
1. Validate locally
2. Update docs/demo/progress/gap matrix
3. Commit one coherent workstream
4. Re-run tests
5. Push to GitHub
6. Record in PROGRESS.md what shipped and what still remains

## Suggested commit style
- `feat: add ISA-driven delimiter extraction`
- `test: add large 835 benchmark and stress fixtures`
- `feat: add CSV and NDJSON output modes`
- `feat: deepen 835 balancing validation`
- `feat: add config-driven companion rule hooks`
- `docs: align README/demo/roadmap for x12 hardening pass`

## Campaign goal

Ship the top 5 improvements with a high bar, one clean increment at a time, without letting support-boundary language drift ahead of reality.
