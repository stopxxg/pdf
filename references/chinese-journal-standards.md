# Chinese Science Journal Standards Checklist

Use this reference when proofreading Chinese science and technology journal PDFs. Treat it as a practical checklist, not a substitute for the journal's own author guidelines. If a target journal has a stricter house style, follow the house style and note the difference.

## Standards To Consider

- GB/T 3179-2009 `期刊编排格式`: overall journal structure and presentation.
- GB/T 7714-2015 `信息与文献 参考文献著录规则`: references and in-text citation markings.
- GB/T 15834-2011 `标点符号用法`: Chinese punctuation and Chinese/foreign-language mixed punctuation.
- GB/T 15835-2011 `出版物上数字用法`: Arabic numerals, Chinese numerals, dates, ranges, approximations, numbering, and consistency.
- CAJ-CD B/T 1-2006/2007 `中国学术期刊（光盘版）检索与评价数据规范`: Chinese academic journal metadata fields and suggested print positions.
- GB/T 3100, GB/T 3101, GB/T 3102 series and journal-specific rules: SI units, quantities, symbols, and unit typography.

## Front Matter And Metadata

Check:

- Chinese and English titles correspond in meaning; avoid missing geographic qualifiers, object scope, or method words.
- Author names, superscript affiliation markers, and corresponding author markers match affiliation list.
- Affiliations include institution, city, postal code, and country when required; English affiliation order is consistent.
- Abstract structure matches journal style, such as Objective/Methods/Results/Conclusion where required.
- Keywords are semicolon-separated and correspond between Chinese and English.
- CLC number, document code, article ID, DOI, CSTR, received/revised/accepted dates, funding, author biography, and corresponding author information are present when required.
- Dates use consistent format; do not mix full-width and half-width hyphens or ambiguous date notation.

## Text And Logic

Check:

- Avoid repeated sentence frames such as consecutive `基于...基于...`.
- Ensure `分别` has clear one-to-one mapping.
- Avoid dangling or unclear referents such as `这种模式` after switching subject.
- Ensure conclusion statements match result section data.
- Keep technical terms consistent across Chinese title, English title, abstract, figures, tables, and references.

## Punctuation And Mixed Typography

Check:

- Do not use full-width colon inside URLs, such as `http：//` (functional issue). Do NOT flag general full-width/half-width punctuation mixing in body text or references.
- Avoid inappropriate顿号 in predicate-object or clause-level parallel structures.
- Use semicolons carefully in lists; if the next sentence changes subject, use a period.
- Parentheses style should be functionally correct; do NOT annotate purely cosmetic full-width vs half-width mixing.
- Use correct range connectors: Chinese year ranges often use an en dash or full-width dash according to journal style; mathematical ranges and reference pages should be consistent.

## Numerals, Units, And Quantities

Check:

- Use Arabic numerals for measured quantities, years, sample sizes, percentages, figure/table numbers, and statistical values.
- Use a space between number and unit when journal style requires it: `20 m`, `58%` or `58 %` must be consistent with the journal.
- Check ranges such as `30 mm~100 mm`, `3~4 a`, and `2007—2016 年` for journal-preferred connector and spacing.
- Do not break compact units or statistical expressions across lines: `p<0.05`, `MJ·mm/(hm²·h)`, `mm/h`.
- Unit exponents should be real superscripts or clearly raised small glyphs, not plain baseline text.
- Common unit expressions should be consistent: `mm/h`, `MJ·mm/(hm²·h)`, `t`, `km²`, `m²`.

## Formulas, Symbols, Superscripts, And Subscripts

Use character-level PDF inspection before commenting:

- Variables are usually italic, including `p`, `P`, `R`, `I`, `RY`, `SY`, etc., unless journal style defines otherwise.
- Operators, numbers, units, and punctuation are usually upright.
- For `p<0.05`, annotate only if the `p` character font is not italic/oblique and PDF flags do not indicate italic.
- Do not mark extracted `I30` as wrong if rendered digits are smaller and lowered like a subscript.
- Check for formula conversion artifacts: missing glyphs, broken OMath/MathType baselines, overlapping equation components, inconsistent subscript size, misplaced minus signs, and wrong Greek/Latin letters.
- Check expressions split across lines; compact statistical expressions and units should not be broken internally.

## Figures And Tables

Do not rely on extracted text order. Verify visually and by coordinates.

Check:

- Figure/table numbers appear in visual order and match in-text references.
- Captions are below figures and above tables unless journal style says otherwise.
- Chinese and English captions correspond in meaning and numbering.
- Figure legends, axis labels, units, significance letters, and notes are readable.
- Watermarks, placeholder text, overlapping layers, cropped content, or low-resolution images are unacceptable.
- Table headers use consistent variable names, units, superscripts/subscripts, and statistical notes.

## References And Citations

Check against GB/T 7714 style and journal house style:

- Numbering is continuous and in citation order if numeric style is used.
- Every in-text citation has a reference entry and every reference entry is cited, when required.
- Author names, `等/et al.`, year, volume, issue, page range, article number, DOI, URL, access date, and document type markers are complete where applicable.
- **If the original journal has both volume and issue numbers, both must be present in the reference.** Do not omit the volume or issue number when the source journal clearly provides it.
- Chinese references with English translations remain paired and consistent.
- Journal names, capitalization, hyphenation, and translated place names are consistent.
- URLs should not be broken into invalid fragments and must use half-width ASCII punctuation.

## Annotation Discipline

- Mark only evidence-backed problems. For uncertain items, use `建议核查` and explain why.
- If a suspected issue is caused only by text extraction but visual rendering is correct, do not annotate it.
- Prefer precise local comments over broad global comments.
- Never change original PDF content; only add annotations to copies.
