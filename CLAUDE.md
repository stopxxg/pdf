# PDF Academic Proofreader for Claude Code

This project packages a Chinese science journal PDF proofreading workflow for Claude Code.

## Quick Start

- Preferred entrypoint in Claude Code: `/pdf-academic-proofreader <PDF_FOLDER>`
- Default output folder: `<PDF_FOLDER>/BBB`
- Default filename policy: keep source filenames unchanged

## Core Policy

- Default mode is low-cost deep editorial proofreading with full-text human editorial intensity.
- Cost control may reduce repeated context, terminal output, temporary scripts, permission reviews, and mechanical work, but it must never reduce editorial quality.
- Each paper must still be read in full, word by word, with sentence-by-sentence judgment for typos, missing words, grammar, punctuation, logic, terminology, references, formulas, and layout before final annotated PDFs are delivered.
- Do not rely on candidate scanning alone as the final review.

## Default Execution Entry

- Always use `./scripts/low_cost_pdf_pipeline.py` as the fixed script entrypoint before creating any one-off script.
- Default output folder for this workflow is `<PDF_FOLDER>/BBB`.
- Keep output filenames unchanged unless the user explicitly asks otherwise.
- Process one PDF at a time, checkpoint the log, then continue to the next PDF automatically unless the user asks to stop.

## Default Model Policy

- Use `Claude 5.4`-level equivalent as the default model for full-text proofreading when available in Claude Code.
- Reserve stronger models for small-page escalation passes, borderline language judgments, or final spot checks.
- Do not downgrade the final full-text proofreading pass to a lightweight model.

## Cost-Control Rules

- Do not print full extracted PDF text into the chat unless the user explicitly requests it.
- Read extracted text from disk in small page ranges.
- Use deterministic checks first for p-value italic/upright, superscripts/subscripts, figure and table order, reference sequence, duplicated text, URL punctuation, and missing metadata.
- Use the model for full-text editorial judgment, not for repeated plumbing work.
- Avoid creating a new temporary script per PDF.

## Accuracy Rules

- For `p<0.05`, use font and character-level evidence. Do not judge upright/italic from plain extracted text alone.
- For superscripts and subscripts, inspect character size and baseline position. Do not mark a correct visual subscript wrong because extraction flattened it.
- For figure and table order, use rendered pages or coordinate checks, not object extraction order.
- If uncertain, annotate conservatively with “建议核查”.

## References

- @references/chinese-journal-standards.md
- @references/today-lessons.md
- @references/visual-checklist.md
- @references/journal-house-style-shuibao.md
