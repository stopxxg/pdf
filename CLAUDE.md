# PDF Academic Proofreader for Claude Code

Chinese science journal PDF proofreading workflow. PDF is the core focus; Word (.docx) support exists but is secondary and not under active development.

## Quick Start

- Preferred entrypoint: `/pdf-academic-proofreader` (no arguments needed)
- Input folder: `~/Desktop/CCC/` (hardwired)
- Output folder: `~/Desktop/CCC/AAAAA/` (auto-created)
- Concurrency: 8 sub-agent workers process files in parallel batches
- Default filename policy: keep source filenames unchanged

## Architecture

Master-worker batch processing:
- **Master agent**: scans input folder, creates output directory, dispatches sub-agents in batches of 8, collects results.
- **Worker sub-agent**: processes exactly one document through the three-phase PDF review pipeline.
- Each worker receives a self-contained prompt with the full editorial review checklist.
- Workers run in parallel (`run_in_background: true`); the master waits for a batch to complete before dispatching the next.
- The master agent only orchestrates — all proofreading is done by sub-agent workers.

## PDF Review: Three Core Phases

### Phase 1 — Dual-Dimension Content Extraction

**Text extraction**: preserve italic/bold, super/subscript, document structure, and original word order. Handle dual-column and multi-column layouts correctly — no content serialization errors or logical misordering.

**Image extraction**: render each PDF page to PNG for:
- Cross-verification of AI text-review annotations against rendered output
- Visual compliance review of charts, formulas, and other content that cannot be meaningfully reviewed from plain text extraction alone

**Layout structure recognition**: auto-differentiate title, abstract, keywords, body text, references, footnotes, and headers/footers. Apply zone-targeted review so non-body content (headers, footers, footnotes) is not mis-flagged. Handle scanned PDFs, encrypted PDFs, and irregular layouts gracefully.

### Phase 2 — Comprehensive Rule-Based Review

Review every sentence and every item against Chinese science journal general standards + journal-specific house style. Check these dimensions:

- **Layout**: heading hierarchy, numbering format, paragraph indentation, line spacing, page margins.
- **Text formatting**: full-width/half-width usage, punctuation, special characters, numeral usage, technical terminology, variable/unit italic-upright conventions, symbol standards.
- **Formulas, figures & tables**: formula numbering, symbol case, super/subscript correctness; figure/table captions (Chinese + English), notes, numbering continuity, cross-reference matching between text and figures/tables.
- **Academic citations**: reference format compliance, punctuation standards, one-to-one in-text citation ↔ reference entry matching, missing or erroneous citations.
- **Logic & content**: contextual coherence, duplicate expressions, conceptual contradictions, logical conflicts.

Custom journal-specific exemption rules must be respected — automatically filter and skip issues the journal explicitly exempts to avoid over-annotation.

### Phase 3 — Sub-Agent Annotation Verification (Anti-Hallucination)

Before annotations are finalized, a hook-based verification step runs:

- **Multi-layer review**: identify AI hallucinations, forced/strained annotations, and unreasonable false positives.
- **Multi-model collaboration**: text models handle language standards and logic checks; vision (VL) models handle layout, formula, and figure/table visual review. Each model type stays in its lane.
- **Standardized annotation granularity** — three tiers:
  1. **Must annotate** (必须批注): clear, evidence-backed errors.
  2. **Suggest annotate** (建议批注): uncertain items, use "建议核查" with explanation.
  3. **Exempt / no annotate** (豁免不批注): issues the journal explicitly exempts, or items caused only by text extraction artifacts.
- **Precise positioning**: every annotation is located to page number, paragraph, or figure/table position.
- **Output**: standardized classified review report alongside the annotated PDF.

Goal: minimize false annotation rate while maintaining the rigor and professionalism expected of journal editorial review.

## Default Execution Entry

- The master agent scans `~/Desktop/CCC/` for `.pdf` and `.docx` files.
- For each file, a sub-agent worker runs the appropriate pipeline:
  - **PDFs**: `python3 scripts/pdf_pipeline.py --file <path> --output ~/Desktop/CCC/AAAAA/`
  - **Word documents**: `python3 scripts/word_pipeline.py --file <path> --output ~/Desktop/CCC/AAAAA/`
- Default output folder: `~/Desktop/CCC/AAAAA/`.

## Default Model Policy

- Use the strongest available model for full-text proofreading.
- Multi-model split: text models for language/logic review; VL models for layout, formula, and figure/table visual review.
- Reserve stronger models for borderline judgments, escalation passes, or final spot checks.
- Do not downgrade the final full-text proofreading pass to a lightweight model.

## Efficiency Guidelines

- Do not print full extracted PDF text into the chat unless explicitly requested.
- Read extracted text from disk in small page ranges.
- Use deterministic checks first for p-value italic/upright, superscripts/subscripts, figure/table order, reference sequence, duplicated text, URL punctuation, and missing metadata.
- Use models for full-text editorial judgment, not for repeated plumbing work.
- Avoid creating a new temporary script per PDF.

## Accuracy Rules

### PDF-specific
- For `p<0.05`, use font and character-level evidence. Do not judge upright/italic from plain extracted text alone.
- For superscripts and subscripts, inspect character size and baseline position. Do not mark a correct visual subscript wrong because extraction flattened it.
- For figure and table order, use rendered pages or coordinate checks, not object extraction order.
- If uncertain, annotate conservatively with "建议核查".

### Word-specific (secondary, not under active development)
- For `p<0.05`, rely on OOXML italic markup (`<i>`) from `fulltext.md`.
- For superscripts and subscripts, rely on OOXML `<sub>` / `<sup>` markup.
- Chart and table layout checks are deferred to the PDF stage; flag only textual issues in Word.

## Annotation Discipline

- Mark only evidence-backed problems. For uncertain items, use `建议核查` and explain why.
- If a suspected issue is caused only by text extraction but visual rendering is correct, do not annotate it.
- Do not flag full-width/half-width punctuation mixing as an error — this is explicitly exempted.
- Prefer precise local comments over broad global comments.
- Never change original PDF content; only add annotations to copies.

## References

- @references/chinese-journal-standards.md
- @references/today-lessons.md
- @references/visual-checklist.md
- @references/journal-house-style-shuibao.md
