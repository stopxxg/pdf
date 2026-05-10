# Claude Code PDF Academic Proofreader

This package is the Claude Code version of the Chinese science journal PDF proofreading workflow.

## Quick Start

1. Open Claude Code in this folder.
2. Put source PDFs in a folder such as `/Users/yourname/Desktop/AAA`.
3. Run:

```text
/pdf-academic-proofreader /Users/yourname/Desktop/AAA
```

Default behavior:

- Source folder: the path you pass to the slash command
- Output folder: `<source-folder>/BBB`
- Output filenames: unchanged
- Processing mode: one PDF at a time
- Review mode: low-cost deep review with full-text sentence-by-sentence proofreading

## Package Contents

- `CLAUDE.md`: project memory loaded by Claude Code
- `.claude/commands/pdf-academic-proofreader.md`: slash command entry (one-shot scan→review→annotate)
- `scripts/low_cost_pdf_pipeline.py`: fixed entrypoint (scan mode for extraction/candidates, annotate mode for writing annotations)
- `scripts/pdf_module/`: supporting modules
  - `pdf_text_converter.py`: dual-column PDF → Markdown with italic markup
  - `reference_checker.py`: GB/T 7714 reference format checker
  - `term_checker.py`: terminology consistency checker
  - `pdf_annotator.py`: PDF annotation writer
- `references/`: Chinese journal standards (`chinese-journal-standards.md`), visual checklist (`visual-checklist.md`), journal house style (`journal-house-style-shuibao.md`), and session lessons (`today-lessons.md`)
- `requirements.txt`: Python dependencies (only PyMuPDF)

## Quality Rules

- Full text must still be read page by page.
- Candidate scanning is only a helper.
- p values, superscripts/subscripts, and figure/table order must use font, coordinate, or rendered evidence.
- Abnormal PDFs must be skipped safely and logged without stopping the batch.

