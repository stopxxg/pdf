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
- `.claude/commands/pdf-academic-proofreader.md`: slash command entry
- `scripts/low_cost_pdf_pipeline.py`: fixed low-output pipeline
- `scripts/run_pdf_academic_proofreader.sh`: shortest terminal entrypoint
- `references/`: Chinese journal standards and workflow lessons

## Terminal Fallback

If you want to run the pipeline directly instead of using the slash command:

```bash
# Scan one PDF and write candidates to disk
./scripts/run_pdf_academic_proofreader.sh /Users/yourname/Desktop/AAA scan

# Annotate one PDF after human review
./scripts/run_pdf_academic_proofreader.sh /Users/yourname/Desktop/AAA annotate /path/to/reviewed_findings.json
```

## Quality Rules

- Full text must still be read page by page.
- Candidate scanning is only a helper.
- p values, superscripts/subscripts, and figure/table order must use font, coordinate, or rendered evidence.
- Abnormal PDFs must be skipped safely and logged without stopping the batch.

