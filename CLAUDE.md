# PDF/Word Academic Proofreader for Claude Code

This project packages a Chinese science journal proofreading workflow for Claude Code, supporting both PDF and Word (.docx) submissions.

## Quick Start

- Preferred entrypoint in Claude Code: `/pdf-academic-proofreader <FOLDER>`
- Default output folder: `<FOLDER>/BBB`
- Default filename policy: keep source filenames unchanged
- The skill auto-detects file type (`.pdf` or `.docx`) and routes to the appropriate pipeline.

## Core Policy

- Default mode is **high-precision deep editorial proofreading** with full-text human editorial intensity.
- Each paper must be read in full, word by word, with sentence-by-sentence judgment for typos, missing words, grammar, punctuation, logic, terminology, references, formulas, and layout before final annotated files are delivered.
- Do not rely on candidate scanning alone as the final review.
- Accuracy is the top priority. Use deterministic checks as supplements, not replacements, for editorial judgment.

## Default Execution Entry

- For **PDFs**: always use `./scripts/pdf_pipeline.py` as the fixed script entrypoint.
- For **Word documents**: always use `./scripts/word_pipeline.py` as the fixed script entrypoint.
- Default output folder for both workflows is `<SOURCE_FOLDER>/BBB`.
- Keep output filenames unchanged unless the user explicitly asks otherwise.
- Process one file at a time, checkpoint the log, then continue to the next file automatically unless the user asks to stop.

## Default Model Policy

- Use the strongest available model for full-text proofreading.
- Reserve stronger models for small-page escalation passes, borderline language judgments, or final spot checks.
- Do not downgrade the final full-text proofreading pass to a lightweight model.

## Efficiency Guidelines

- Do not print full extracted PDF text into the chat unless the user explicitly requests it.
- Read extracted text from disk in small page ranges.
- Use deterministic checks first for p-value italic/upright, superscripts/subscripts, figure and table order, reference sequence, duplicated text, URL punctuation, and missing metadata.
- Use the model for full-text editorial judgment, not for repeated plumbing work.
- Avoid creating a new temporary script per PDF.

## Accuracy Rules

### PDF-specific
- For `p<0.05`, use font and character-level evidence. Do not judge upright/italic from plain extracted text alone.
- For superscripts and subscripts, inspect character size and baseline position. Do not mark a correct visual subscript wrong because extraction flattened it.
- For figure and table order, use rendered pages or coordinate checks, not object extraction order.
- If uncertain, annotate conservatively with "建议核查".

### Word-specific
- For `p<0.05`, rely on OOXML italic markup (`<i>`) from `fulltext.md`. Word run properties are usually accurate.
- For superscripts and subscripts, rely on OOXML `<sub>` / `<sup>` markup.
- Chart and table layout checks (three-line table, figure resolution, watermark) are deferred to the PDF stage; flag only textual issues in Word.

## References

- @references/chinese-journal-standards.md
- @references/today-lessons.md
- @references/visual-checklist.md
- @references/journal-house-style-shuibao.md
