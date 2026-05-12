---
description: Chinese journal PDF/Word proofreading with high-precision deep full-text review
---

Use the packaged Chinese journal proofreading workflow on `$ARGUMENTS`.

If `$ARGUMENTS` is empty, ask for one source folder path and do not guess.

Requirements:

- Support both `.pdf` and `.docx` files in the source folder.
- Use `python3 scripts/pdf_pipeline.py` as the fixed entrypoint for PDFs.
- Use `python3 scripts/word_pipeline.py` as the fixed entrypoint for Word documents.
- Treat `$ARGUMENTS` as the source folder unless the user already provided a different target in the current session.
- Output annotated files to `<source-folder>/BBB` with unchanged filenames.
- Process one file at a time.
- For PDFs, run high-quality extraction with page rendering (PNG artifacts saved to `_artifacts/<stem>/pages/`).
- For Word documents, run text extraction without page rendering (text artifacts saved to `_artifacts/<stem>/page_paras/`).
- After extraction, read the **entire** `review_context.md` from disk (use up to 3 `Read` calls if it exceeds 2000 lines). Also read `_artifacts/<stem>/fulltext.md` for the raw text with markup.
- In parallel, for PDFs only, read **all page PNGs that contain figures, tables, formulas, or suspicious layout** (not just a selective subset). Read them in parallel batches to avoid timeout.
- For Word documents, do **not** read rendered page PNGs. Rely on extracted text and OOXML format markup (`<i>`, `<sub>`, `<sup>`) for formula/symbol checks.
- Use rendered pages, coordinates, and character-level font checks for p values, superscripts/subscripts, and figure/table order **only for PDFs**.
- Cross-check text extractions against rendered images (PDF only): if extracted text suggests a subscript error but the image shows a correct visual subscript, do not annotate it.
- Do not print full extracted text into the chat.
- Write detailed artifacts and logs to disk, and keep chat output compact.
- Skip abnormal files safely and continue.

**Auto-review policy:**
- After extraction, do **NOT** ask the user to confirm before proceeding. Automatically continue to review, compile findings, annotate, and report.
- The user wants **one-shot execution**: run prepare → AI review → generate reviewed findings JSON → annotate → summarize results, all in one go, within a single turn.

**File type detection:**

1. Scan `$ARGUMENTS` folder for `.pdf` and `.docx` files.
2. Process one file at a time in sorted order.
3. For each file:
   - If `.pdf`: follow the **PDF workflow** below.
   - If `.docx`: follow the **Word workflow** below.

**PDF one-shot execution sequence:**

1. Run `python3 scripts/pdf_pipeline.py --root "$ARGUMENTS" --output "$ARGUMENTS/BBB" --mode prepare --same-name --limit 1 --render-dpi 200`.
   This produces extracted text, `review_context.md`, candidate JSON, and rendered page PNGs under `_artifacts/`.
2. Read `_artifacts/<stem>/review_context.md` **completely** (up to 3 `Read` calls; merge contents mentally). This file contains the full text, auto-detected rule findings, and a visual inspection checklist.
3. Read `_artifacts/<stem>/fulltext.md` if additional text detail is needed.
4. Read `_candidates/<stem>.findings.json` to see local rule candidates.
5. Run automated pre-checks in parallel:
   - `./scripts/pdf_module/reference_checker.py <first-pdf>` → save output to `_candidates/<stem>.reference_findings.json`
   - `./scripts/pdf_module/term_checker.py <first-pdf>` → save output to `_candidates/<stem>.term_findings.json`
   Read both JSON outputs; treat them as candidate lists to be verified or dismissed during editorial review.
6. Read **all** `pages/page_XXX.png` files that correspond to pages mentioned in the visual inspection checklist (pages containing figures, tables, formulas, or layout anomalies). Read them in parallel.
7. Perform **systematic deep editorial review** with the checklist below. Read the extracted text first; then open rendered page PNGs for every page containing figures, tables, or formulas to verify visual rendering. Do not skip visual verification for cost reasons.
8. Compile the final reviewed findings JSON and write it to disk.
   - **Merge policy**: The final JSON must include ALL of the following, after deduplication:
     a) Confirmed valid items from the local rule `_candidates/<stem>.findings.json` (e.g., p-value style, caption order, text rule hits). Do **not** drop a local-rule finding unless you have explicitly verified it is a false positive and noted the reason.
     b) Confirmed valid items from `reference_findings.json` and `term_findings.json`.
     c) New issues discovered during your own sentence-by-sentence editorial review.
   - If a local-rule candidate and your own finding target the same location, keep the more precise one and merge their suggestions.
9. Annotate with:
   `python3 scripts/pdf_pipeline.py --root "$ARGUMENTS" --output "$ARGUMENTS/BBB" --mode annotate --same-name --limit 1 --findings-json <path-to-reviewed-findings.json>`
10. Verify annotated output. Report a concise summary to the user:
    - Total findings, annotated count, missed count.
    - List of high-severity issues.
    - Output path of the annotated PDF.
11. If more files remain in the folder, loop back to step 1 automatically. Stop only if the user explicitly asks to stop.

**Word one-shot execution sequence:**

1. Run `python3 scripts/word_pipeline.py --root "$ARGUMENTS" --output "$ARGUMENTS/BBB" --mode prepare --same-name --limit 1`.
   This produces extracted text, `review_context.md`, and candidate JSON under `_artifacts/` and `_candidates/`.
2. Read `_artifacts/<stem>/review_context.md` **completely** (up to 3 `Read` calls; merge contents mentally). This file contains the full text with markup, auto-detected rule findings, and a review checklist.
3. Read `_artifacts/<stem>/fulltext.md` if additional text detail is needed.
4. Read `_candidates/<stem>.findings.json` to see local rule candidates.
4. Run automated pre-checks in parallel using the text interfaces:
   - `python3 scripts/pdf_module/reference_checker.py --text _artifacts/<stem>/fulltext.txt <stem>` → save output to `_candidates/<stem>.reference_findings.json`
   - `python3 scripts/pdf_module/term_checker.py --text _artifacts/<stem>/fulltext.txt <stem>` → save output to `_candidates/<stem>.term_findings.json`
   Read both JSON outputs; treat them as candidate lists to be verified or dismissed during editorial review.
5. Perform systematic editorial review with the checklist below. For Word documents, do **not** read rendered page PNGs. Rely on extracted text and OOXML format markup (`<i>`, `<sub>`, `<sup>`) for formula/symbol checks. Chart and table layout issues (three-line table, axis units, etc.) are not mechanically verified in Word; flag them if noticed in text but note that layout verification belongs to the PDF stage.
6. Compile the final reviewed findings JSON and write it to disk.
   - **Merge policy**: Same as PDF — include confirmed local rules, confirmed pre-checks, and new AI findings after deduplication.
7. Annotate with:
   `python3 scripts/word_pipeline.py --root "$ARGUMENTS" --output "$ARGUMENTS/BBB" --mode annotate --same-name --limit 1 --findings-json <path-to-reviewed-findings.json>`
8. Verify annotated output. Report a concise summary to the user:
    - Total findings, annotated comment count, missed count.
    - List of high-severity issues.
    - Output path of the annotated .docx.
9. If more files remain in the folder, loop back to step 1 automatically. Stop only if the user explicitly asks to stop.

**Editorial review checklist (applies to both PDF and Word):**

**Front matter and metadata (page 1 / first block)**
- Chinese title: ≤20 Chinese characters, no subtitle unless necessary.
- Chinese and English titles: must correspond in meaning; no full-width commas in English title.
- Author names: ≤6 authors; corresponding author must be marked.
- Affiliations: accurate Chinese and English names, city, and postal code required.
- Abstract: research articles must use structured abstract ([Objective]/[Methods]/[Results]/[Conclusion] or [目的]/[方法]/[结果]/[结论]); review articles may use indicative abstract.
- Keywords: 3–8 keywords; Chinese and English must correspond and be in the same order.
- Header/footer: check page headers (e.g., Vol.33， No.5) for full-width commas in English text. For Word documents, also verify consistent page numbers, correct journal names in running heads, and mixed full-width/half-width punctuation in headers/footers.
- DOI/CSTR/funding: check for full-width colons, inconsistent spacing in grant numbers, missing fields.
- Author biography: check whether first author and corresponding author biographies are present (usually on the first page or in footnotes; fields include name, birth year, gender, origin, degree, title, research direction, E-mail, phone).
- Check "摘要" is not written as "摘 要" with an extra space.

**Text and logic (all pages / all paragraphs)**
- Read sentence by sentence. Flag repeated phrasing, dangling referents, mismatched conclusion/data, inconsistent terminology.
- Cross-check the `term_findings.json` output: if it flagged any term variants, verify whether those variants are intentional abbreviations or actual inconsistencies, and annotate accordingly.
- Punctuation: no full-width colons in URLs; no consecutive commas/periods（，。/。。); English prose uses half-width punctuation.
- Numerals and units: consistent spacing around %; no broken ranges; check for extra spaces in decimals (e.g., 0. 05, 0. 1).
- **Number-unit spacing:** Check that the spacing between numbers and units is consistent throughout the paper (e.g., either always "20 m" or always "20m", according to the journal style). Flag mixed usage.
- Statistical symbols: p, P, z, q, I, R, F, t in statistical expressions should be italic. Flag "P 值", "z 得分", "q 值" with extra spaces.
- Biological names: the first appearance of a biological name must include the Latin scientific name in italics.
- **Units:** In the main text, use conventional forms (e.g., 1.5 m/s). In figure axes and table headers, use negative exponent form (e.g., 速度/(m·s⁻¹)).
- **Parentheses consistency:** Chinese prose uses full-width parentheses （）; English prose and formula contexts use half-width parentheses (). Flag mixed or incorrect usage.
- **Figure/table citation order:** The first in-text citation of each figure and table must appear in sequential order (图1 before 图2, 表1 before 表2). Cross-check against `_candidates/<stem>.findings.json` for any auto-detected order gaps.

**General writing quality (all paragraphs, tables, headers, footers — Word especially)**
- Spelling errors: check Chinese homophones (的/地/得, 在/再, 做/作, 象/像, 帐号/账号, 其它/其他), English typos, and OCR artifacts.
- Grammar issues: subject-verb disagreement, missing articles in English, incorrect measure words in Chinese, redundant words.
- Tense consistency: results sections should use past tense; general facts and conclusions may use present tense. Flag mixing within the same section.
- Template placeholders: scan for unfilled text such as `请输入标题`, `XXX`, `待补充`, `TBD`, `placeholder`, `图注待补`, `数据待更新`, `Lorem ipsum`, `此处插入`, `（待填）`, `<待补充>`. Also flag empty sections or placeholder tables.
- Inconsistent hyphenation and compound words: flag if the same concept is written differently (e.g., `co-operation` vs `cooperation`, `e-mail` vs `email`, `land use` vs `land-use` vs `landuse`).
- Inconsistent capitalization of technical terms: e.g., `GIS` vs `Gis` vs `gis`, `NDVI` vs `Ndvi`, `RUSLE` vs `Rusle`.
- Missing definitions for abbreviations on first use: flag if an abbreviation like `RUSLE`, `NDVI`, `WUE` appears without being defined on its first occurrence.
- Empty sections or placeholder tables: flag sections with only a heading and no body text, or tables with placeholder rows/cells.

**Figures and tables (visual review — PDF only)**
- Identify every page that mentions a figure, table, or formula from the text.
- Read the corresponding `pages/page_XXX.png`.
- **Figures:**
  - Caption below, bilingual match, axis labels readable, no watermark/overlap/placeholder text.
  - **Axes must show physical quantity and unit**; must have a **legend**.
  - Data lines must be distinguished by **markers/symbols**.
  - Maps must use standard base maps with an **approval number (审图号)** and include the standard-map note below the figure.
- **Tables:**
  - Caption above; must be a **three-line table**.
  - Header units use negative exponent form (e.g., 速度/(m·s⁻¹)).
  - Zero values marked "0", unmeasured values marked "—".
  - For **Word documents**: check table cells for empty placeholders, inconsistent decimal places, and incorrect units. Verify that table data in the text matches the values shown in the table.
- If extracted text suggests a subscript error but the image shows a correct visual subscript, do not annotate it.
- For **Word documents**, layout checks (three-line table, figure resolution, watermark) are deferred to the PDF stage. Still flag obvious textual issues (missing caption, wrong numbering).

**Formulas and symbols**
- **Role split:**
  - For **PDF**: Trust local-rule `_candidates/<stem>.findings.json` first (character-level font/position evidence). If ambiguous, read rendered `pages/page_XXX.png`.
  - For **Word**: Rely on `fulltext.md` italic markup (`<i>`) and subscript/superscript markup (`<sub>`, `<sup>`) from OOXML run properties. These are usually accurate because they reflect the author's explicit formatting choices.
- **Italic rules:** Single-letter variables italic (e.g., T in Tmax). Multi-letter variables upright (e.g., WUE, ET). Subscripts that are variables italic; subscripts that are descriptive text upright (e.g., max in Tmax is upright).
- Formula annotations must begin with **"式中："**. Every variable must have an annotation; units go in parentheses after the annotation.
- Check p<0.05: for PDF rely on local-rule char-font finding; for Word rely on `<i>` markup.
- Check I30-style subscripts: for PDF rely on local-rule position evidence; for Word rely on `<sub>` markup.
- Look for OMath/MathType artifacts: broken baselines, overlapping components, missing glyphs (relevant for both formats, but verify by image only for PDF).

**References**
- Start from the `reference_findings.json` output: verify each candidate (et al. punctuation, volume/issue completeness, numbering continuity) visually on the reference pages (PDF) or in the text (Word), and keep confirmed issues while dismissing false positives.
- Numbering continuous and in citation order. **Total references ≤30** (if the target journal imposes this limit).
- Every in-text citation has a reference entry and vice versa.
- Author names, et al., year, volume, issue, page range, DOI/URL complete.
- **Volume/issue completeness:** If the original journal clearly has both volume and issue numbers, the reference must include both.
- **Foreign authors:** surname first in full, given name abbreviated without a period (e.g., Mao Z D). **≥3 authors:** list first 3 only, then "等" or "et al".
- **Bilingual references (Chinese only):** English translation starts on a new paragraph, no serial number, no extra symbols. Surname in full pinyin with initial capital, given name abbreviated.
- English references: check for missing periods after "et al", full-width colons in page numbers, missing [J] markers.
- Bilingual references: Chinese and English paired and consistent.
