# Lessons From 2026-05-08 PDF Proofreading Session

## Original User Goal

Batch traverse all academic PDF papers in a folder; proofread page by page; check typos, grammar, punctuation, unclear wording, messy layout, OMath/MathType/formula abnormalities, superscript/subscript errors, and formula layout problems; circle/box issues and insert comments at corresponding PDF positions; do not change original content; preserve references, figure/table numbering, section order, images, layers, and links; skip abnormal documents without crashing.

## Conversation Corrections To Preserve

- Do not add both rectangle comments and duplicate sticky-note comments. Use red rectangle annotations with comment content only.
- Do not mark every visible `p<0.05` as wrong. Some `p` characters are already italic. Inspect character-level font metadata.
- In the tested PDF, character-level inspection showed most `p` values were `NEU-BZ-S92-Italic`; only page 4 one instance and page 5 one instance had `p` as `NEU-BZ-S92-Regular`.
- Detect `p<0.05` split across lines by comparing character y-coordinates within the same expression.
- Do not mark `I30` as a subscript error solely because text extraction returns `I30`. In the tested PDF, many instances used smaller lowered digits even when text extracted as plain digits.
- Do not judge figure/table order from extracted text. In the tested PDF, extracted text suggested figure 4 before figure 3, but visual coordinates showed figure 3 at y≈395 and figure 4 at y≈677, so the page order was correct.
- Always verify suspicious layout comments with rendered page images or coordinates.
- In batch proofreading, discover all PDFs at once but review them one by one. Do not emit multiple PDFs' full extracted text in one terminal response; long output can be truncated and can hide issues. Save each PDF's full text to its own temporary file and inspect page ranges incrementally.
- Do not default to conservative batch-only rule scanning. The user's editorial workflow requires deep per-paper proofreading: read each article at full-text human editorial intensity, generate a paper-specific findings list, then write annotations. Automatic rules are supplements only.
- For true deep proofreading, process only one PDF per run. Finish full-text review, annotated output, verification, and report for that one paper; stop and wait before starting the next paper. Running 10+ PDFs in one pass tends to collapse into rule scanning and loses editorial depth.

## Recommended Implementation Pattern

1. Extract text for language and reference review.
2. Use `page.get_text("rawdict")` for font/style/position checks.
3. Use `page.search_for()` coordinates and rendered thumbnails for visual order.
4. Build a manual findings JSON for language/content issues after review.
5. Let the reusable script add those manual findings plus automatic character-level formula/statistical findings.
6. Re-run verification: page count, annotation count, annotation type, renderability.
