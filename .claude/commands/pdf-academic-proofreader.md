---
description: Chinese journal PDF proofreading with low-cost deep full-text review
---

Use the packaged Chinese journal PDF proofreading workflow on `$ARGUMENTS`.

If `$ARGUMENTS` is empty, ask for one source PDF folder path and do not guess.

Requirements:

- Use `./scripts/run_pdf_academic_proofreader.sh` as the shortest terminal entrypoint.
- Use `./scripts/low_cost_pdf_pipeline.py` as the fixed execution entrypoint behind the wrapper.
- Treat `$ARGUMENTS` as the source PDF folder unless the user already provided a different target in the current session.
- Output annotated PDFs to `<source-folder>/BBB` with unchanged filenames.
- Process one PDF at a time.
- First run low-output candidate scanning with page rendering (PNG artifacts saved to `_artifacts/<stem>/pages/`).
- Then read the complete extracted text page by page from disk, word by word, and judge sentences one by one.
- Use rendered pages, coordinates, and character-level font checks for p values, superscripts/subscripts, and figure/table order.
- For visual review, read the rendered page PNGs for pages that contain figures, tables, formulas, or suspicious layout. Do not read all page images at once; read selectively to control cost.
- Cross-check text extractions against rendered images: if extracted text suggests a subscript error but the image shows a correct visual subscript, do not annotate it.
- Do not print full extracted text into the chat.
- Write detailed artifacts and logs to disk, and keep chat output compact.
- Skip abnormal PDFs safely and continue.

**Auto-review policy:**
- After scan, do NOT ask the user to confirm before proceeding. Automatically continue to review, compile findings, annotate, and report.
- The user wants one-shot execution: run scan → AI review → generate reviewed findings JSON → annotate → summarize results, all in one go.

Default sequence:

1. Run `./scripts/run_pdf_academic_proofreader.sh "$ARGUMENTS" scan`.
   This produces extracted text, candidate JSON, and rendered page PNGs under `_artifacts/`.
2. Automatically review one paper's candidate JSON and its extracted page text from disk.
3. Perform systematic editorial review with the following checklist. For every item, inspect the extracted text first; only read the rendered page PNG when text alone is insufficient.

   **Front matter and metadata (page 1)**
   - Chinese title: ≤20 Chinese characters, no subtitle unless necessary.
   - Chinese and English titles: must correspond in meaning; no full-width commas in English title.
   - Author names: ≤6 authors; corresponding author must be marked.
   - Affiliations: accurate Chinese and English names, city, and postal code required.
   - Abstract: research articles must use structured abstract ([Objective]/[Methods]/[Results]/[Conclusion] or [目的]/[方法]/[结果]/[结论]); review articles may use indicative abstract.
   - Keywords: 3–8 keywords; Chinese and English must correspond and be in the same order.
   - Header/footer: check page headers (e.g., Vol.33， No.5) for full-width commas in English text.
   - DOI/CSTR/funding: check for full-width colons, inconsistent spacing in grant numbers, missing fields.
   - Author biography: first author and corresponding author biographies must be present on the first page (name, birth year, gender, origin, degree, title, research direction, E-mail, phone).
   - Check "摘要" is not written as "摘 要" with an extra space.

   **Text and logic (all pages)**
   - Read sentence by sentence. Flag repeated phrasing, dangling referents, mismatched conclusion/data, inconsistent terminology.
   - Punctuation: no full-width colons in URLs; no consecutive commas/periods (，。/。。); English prose uses half-width punctuation.
   - Numerals and units: consistent spacing around %; no broken ranges; check for extra spaces in decimals (e.g., 0. 05, 0. 1).
   - Statistical symbols: p, P, z, q, I in statistical expressions should be italic. Flag "P 值", "z 得分", "q 值" with extra spaces.
   - Biological names: the first appearance of a biological name must include the Latin scientific name in italics.
   - **Units:** In the main text, use conventional forms (e.g., 1.5 m/s). In figure axes and table headers, use negative exponent form (e.g., 速度/(m·s⁻¹)).

   **Figures and tables (visual review)**
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
   - If extracted text suggests a subscript error but the image shows a correct visual subscript, do not annotate it.

   **Formulas and symbols (visual review)**
   - **Italic rules:** Single-letter variables italic (e.g., T in Tmax). Multi-letter variables upright (e.g., WUE, ET). Subscripts that are variables italic; subscripts that are descriptive text upright (e.g., max in Tmax is upright).
   - Formula annotations must begin with **"式中："**. Every variable must have an annotation; units go in parentheses after the annotation.
   - Check p<0.05 visually for italic p.
   - Check I30-style subscripts by image: digit must be smaller and lower than baseline.
   - Look for OMath/MathType artifacts: broken baselines, overlapping components, missing glyphs.

   **References**
   - Numbering continuous and in citation order. **Total references ≤30.**
   - Every in-text citation has a reference entry and vice versa.
   - Author names, et al., year, volume, issue, page range, DOI/URL complete.
   - **Volume/issue completeness:** If the original journal clearly has both volume and issue numbers, the reference must include both.
   - **Foreign authors:** surname first in full, given name abbreviated without a period (e.g., Mao Z D). **≥3 authors:** list first 3 only, then "等" or "et al".
   - **Bilingual references (Chinese only):** English translation starts on a new paragraph, no serial number, no extra symbols. Surname in full pinyin with initial capital, given name abbreviated.
   - English references: check for missing periods after "et al", full-width colons in page numbers, missing [J] markers.
   - Bilingual references: Chinese and English paired and consistent.

4. Compile all findings into the reviewed findings JSON.
5. Annotate with:
   `./scripts/run_pdf_academic_proofreader.sh "$ARGUMENTS" annotate <path-to-reviewed-findings.json>`
6. Verify annotated output, report summary to user, then continue to the next PDF unless the user asked to stop.
