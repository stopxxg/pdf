# PDF/Word Academic Proofreader — Quality Review & Bug Hunt

## Goal
Systematically inspect the PDF/Word academic proofreader project for bugs, code smells, logical inconsistencies, and rule-accuracy issues. Focus on uncommitted changes first, then broaden to cross-pipeline consistency and rule precision.

## Scope

### Phase A: Diff Review (11 uncommitted files)
File-by-file review of pending changes.

| File | Key Concerns |
|------|--------------|
| `scripts/pdf_module/reference_checker.py` | Volume/issue regex relaxation introducing false negatives; bilingual ref serial-number heuristic too broad; page-range regex compatibility |
| `scripts/pdf_module/term_checker.py` | Term-variant threshold合理性; stop-word filtering sufficiency |
| `scripts/word_module/word_rule_detectors.py` | Robustness of new detectors (typos, placeholders, superscripts, inconsistent compounds); safe OOXML run-property access |
| `scripts/pdf_pipeline.py` / `scripts/word_pipeline.py` | Review-context builder performance and edge-case handling |
| `references/*.md`, `CLAUDE.md` | Documentation consistency with code behavior |

### Phase B: Cross-Pipeline Consistency
Verify equivalent rules produce equivalent results in PDF and Word pipelines.

| Rule | PDF Implementation | Word Implementation | Check |
|------|-------------------|---------------------|-------|
| Reference sequence | `detect_reference_sequence` | `detect_word_reference_sequence` | Regex, bracket styles, duplicate/continuity logic |
| Caption order | `detect_caption_order` | `detect_word_caption_order` | Coordinate vs paragraph ordering, prefix matching |
| Stat symbol italic | `detect_stat_symbol_style` (char-level font flags) | `detect_word_stat_symbol_style` (OOXML italic) | Pattern list sync, severity alignment |
| Subscript detection | `detect_script_style` (bbox/size heuristic) | `detect_word_script_style` (OOXML vertAlign) | Prefix set sync, skip conditions (year, citation) |
| Text rules | `detect_text_rules` | `detect_word_text_rules` | Target list, regex rules, duplicate-line detection |
| Deduplication | `dedupe_findings` (pdf_pipeline) | `dedupe_findings` (word_rule_detectors) | Key tuple fields identical |

### Phase C: Rule Precision Review
Business-logic review of false-positive / false-negative risk.

- `p<0.05` italic check — special fonts (e.g. `NEU-BZ-S92-Italic`) handling
- `subscript_prefixes` set coverage for domain variables
- Placeholder regexes — risk of over-matching normal content
- `detect_inconsistent_compounds` — confirmed intentional no-output design; verify downstream consumers respect this
- Superscript regexes (`cm2`, `m2`, etc.) — risk of matching non-unit contexts in body text
- `_check_ref_format` Chinese-author "等" heuristic — comma-count threshold validity

## Success Criteria
- All obvious bugs and regressions in uncommitted changes identified
- At least one cross-pipeline inconsistency found and documented
- Every rule receives a keep / modify / remove recommendation
- Actionable fix list produced

## Outputs
- This design document
- Implementation plan (per-file fix checklist)
- Code changes (executed after user approval)
