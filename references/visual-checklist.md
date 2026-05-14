# Visual Review Checklist for AI

Use this checklist when reading rendered page PNGs during PDF proofreading. Read only the pages that contain figures, tables, formulas, or suspicious layout based on the text review.

## Figures

- Caption is below the figure (unless journal style says otherwise).
- Chinese and English captions correspond in meaning and numbering.
- Figure legend, axis labels, and units are readable.
- No watermarks, placeholder text, overlapping layers, or low-resolution images.
- Figure numbers appear in visual order and match in-text references.

## Tables

- Caption is above the table (unless journal style says otherwise).
- Table headers use consistent variable names, units, superscripts/subscripts.
- No misaligned cells or broken borders.
- Statistical notes and significance letters are readable.

## Formulas and Symbols

- Variables (p, P, R, I, etc.) are visually italic/oblique.
- Operators, numbers, units, and punctuation are upright.
- For p<0.05: inspect the rendered image to confirm the p character is slanted.
- For I30-style subscripts: check if the digit is smaller and lowered relative to the baseline. Do not mark as wrong if the image shows a correct visual subscript.
- Check for formula conversion artifacts: missing glyphs, broken OMath/MathType baselines, overlapping equation components, inconsistent subscript size, misplaced minus signs, wrong Greek/Latin letters.
- Compact statistical expressions and units should not be broken internally across lines.

## Layout and Typography

- No cropped content at page edges.
- No unexpected blank pages.
- Header/footer consistency across pages.
- Do not mark an issue if the extracted text is flattened but the rendered image is correct.
- Do NOT flag general full-width/half-width punctuation mixing as an error.

## Cost Control

- Do not open every page image. Open only the pages where text review flagged a figure, table, formula, or layout concern.
- If uncertain, annotate conservatively with "建议核查" and explain why.
