---
description: Chinese journal PDF proofreading with low-cost deep full-text review
---

Use the packaged Chinese journal PDF proofreading workflow on `$ARGUMENTS`.

If `$ARGUMENTS` is empty, ask for one source PDF folder path and do not guess.

Requirements:

- Use `python3 scripts/low_cost_pdf_pipeline.py` as the fixed execution entrypoint.
- Treat `$ARGUMENTS` as the source PDF folder unless the user already provided a different target in the current session.
- Output annotated PDFs to `<source-folder>/BBB` with unchanged filenames.
- Process one PDF at a time.
- First run low-output candidate scanning with page rendering (PNG artifacts saved to `_artifacts/<stem>/pages/`).
- After scan, read the **entire** `fulltext.md` from disk in one go (use up to 2 `Read` calls if it exceeds 2000 lines). Do **not** read in small chunks or ask the user to continue.
- In parallel, read only the **suspicious page PNGs** identified from text (pages mentioning figures, tables, formulas, or layout anomalies). Do not read all page images at once; read selectively to control cost.
- Use rendered pages, coordinates, and character-level font checks for p values, superscripts/subscripts, and figure/table order.
- Cross-check text extractions against rendered images: if extracted text suggests a subscript error but the image shows a correct visual subscript, do not annotate it.
- Do not print full extracted text into the chat.
- Write detailed artifacts and logs to disk, and keep chat output compact.
- Skip abnormal PDFs safely and continue.

**Auto-review policy:**
- After scan, do **NOT** ask the user to confirm before proceeding. Automatically continue to review, compile findings, annotate, and report.
- The user wants **one-shot execution**: run scan → AI review → generate reviewed findings JSON → annotate → summarize results, all in one go, within a single turn.

**One-shot execution sequence:**

1. Run `python3 scripts/low_cost_pdf_pipeline.py --root "$ARGUMENTS" --output "$ARGUMENTS/BBB" --mode scan --same-name --limit 1 --render-dpi 144`.
   This produces extracted text, candidate JSON, and rendered page PNGs under `_artifacts/`.
2. Read `_artifacts/<stem>/fulltext.md` **completely** (up to 2 `Read` calls; merge contents mentally).
3. Read `_candidates/<stem>.findings.json` to see local rule candidates.
4. Run automated pre-checks in parallel:
   - `./scripts/pdf_module/reference_checker.py <first-pdf>` → save output to `_candidates/<stem>.reference_findings.json`
   - `./scripts/pdf_module/term_checker.py <first-pdf>` → save output to `_candidates/<stem>.term_findings.json`
   Read both JSON outputs; treat them as candidate lists to be verified or dismissed during editorial review.
5. Identify suspicious pages from the text (mentions of 图/表/公式/占位符/异常排版).
6. Read those `pages/page_XXX.png` files **in parallel**.
7. Perform systematic editorial review with the following checklist. For every item, inspect the extracted text first; only read the rendered page PNG when text alone is insufficient.

   **Front matter and metadata (page 1)**
   - Chinese title: ≤20 Chinese characters, no subtitle unless necessary.
   - Chinese and English titles: must correspond in meaning; no full-width commas in English title.
   - Author names: ≤6 authors; corresponding author must be marked.
   - Affiliations: accurate Chinese and English names, city, and postal code required.
   - Abstract: research articles must use structured abstract ([Objective]/[Methods]/[Results]/[Conclusion] or [目的]/[方法]/[结果]/[结论]); review articles may use indicative abstract.
   - Keywords: 3–8 keywords; Chinese and English must correspond and be in the same order.
   - Header/footer: check page headers (e.g., Vol.33， No.5) for full-width commas in English text.
   - DOI/CSTR/funding: check for full-width colons, inconsistent spacing in grant numbers, missing fields.
   - Author biography: check whether first author and corresponding author biographies are present (usually on the first page or in footnotes; fields include name, birth year, gender, origin, degree, title, research direction, E-mail, phone).
   - Check "摘要" is not written as "摘 要" with an extra space.

   **Text and logic (all pages)**
   - Read sentence by sentence. Flag repeated phrasing, dangling referents, mismatched conclusion/data, inconsistent terminology.
   - Cross-check the `term_findings.json` output: if it flagged any term variants, verify whether those variants are intentional abbreviations or actual inconsistencies, and annotate accordingly.
   - Punctuation: no full-width colons in URLs; no consecutive commas/periods (，。/。。); English prose uses half-width punctuation.
   - Numerals and units: consistent spacing around %; no broken ranges; check for extra spaces in decimals (e.g., 0. 05, 0. 1).
   - **Number-unit spacing:** Check that the spacing between numbers and units is consistent throughout the paper (e.g., either always "20 m" or always "20m", according to the journal style). Flag mixed usage.
   - Statistical symbols: p, P, z, q, I, R, F, t in statistical expressions should be italic. Flag "P 值", "z 得分", "q 值" with extra spaces.
   - Biological names: the first appearance of a biological name must include the Latin scientific name in italics.
   - **Units:** In the main text, use conventional forms (e.g., 1.5 m/s). In figure axes and table headers, use negative exponent form (e.g., 速度/(m·s⁻¹)).
   - **Parentheses consistency:** Chinese prose uses full-width parentheses （）; English prose and formula contexts use half-width parentheses (). Flag mixed or incorrect usage.
   - **Figure/table citation order:** The first in-text citation of each figure and table must appear in sequential order (图1 before 图2, 表1 before 表2). Cross-check against `_candidates/<stem>.findings.json` for any auto-detected order gaps.

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
   - **Role split:** The `fulltext.md` italic markup helps identify slanted text, but it does **not** encode superscripts or subscripts. Do **not** rely on the md text alone to judge subscript/superscript correctness. For strict italic/subscript/superscript rules, follow this order:
     1. Trust local-rule `_candidates/<stem>.findings.json` first (it uses character-level font/position evidence).
     2. If the text or the local-rule finding is ambiguous, read the rendered `pages/page_XXX.png` to verify visually.
   - **Italic rules:** Single-letter variables italic (e.g., T in Tmax). Multi-letter variables upright (e.g., WUE, ET). Subscripts that are variables italic; subscripts that are descriptive text upright (e.g., max in Tmax is upright).
   - Formula annotations must begin with **"式中："**. Every variable must have an annotation; units go in parentheses after the annotation.
   - Check p<0.05: rely on the local-rule char-font finding; only open the PNG if the local rule is inconclusive.
   - Check I30-style subscripts: rely on local-rule position evidence first; verify by image only when needed (digit must be smaller and lower than baseline).
   - Look for OMath/MathType artifacts: broken baselines, overlapping components, missing glyphs.

   **References**
   - Start from the `reference_findings.json` output: verify each candidate (et al. punctuation, volume/issue completeness, numbering continuity) visually on the reference pages, and keep confirmed issues while dismissing false positives.
   - Numbering continuous and in citation order. **Total references ≤30** (if the target journal imposes this limit).
   - Every in-text citation has a reference entry and vice versa.
   - Author names, et al., year, volume, issue, page range, DOI/URL complete.
   - **Volume/issue completeness:** If the original journal clearly has both volume and issue numbers, the reference must include both.
   - **Foreign authors:** surname first in full, given name abbreviated without a period (e.g., Mao Z D). **≥3 authors:** list first 3 only, then "等" or "et al".
   - **Bilingual references (Chinese only):** English translation starts on a new paragraph, no serial number, no extra symbols. Surname in full pinyin with initial capital, given name abbreviated.
   - English references: check for missing periods after "et al", full-width colons in page numbers, missing [J] markers.
   - Bilingual references: Chinese and English paired and consistent.

8. Compile the final reviewed findings JSON and write it to disk.
   - **Merge policy**: The final JSON must include ALL of the following, after deduplication:
     a) Confirmed valid items from the local rule `_candidates/<stem>.findings.json` (e.g., p-value style, caption order, text rule hits). Do **not** drop a local-rule finding unless you have explicitly verified it is a false positive and noted the reason.
     b) Confirmed valid items from `reference_findings.json` and `term_findings.json`.
     c) New issues discovered during your own sentence-by-sentence editorial review.
   - If a local-rule candidate and your own finding target the same location, keep the more precise one and merge their suggestions.
9. Annotate with:
   `python3 scripts/low_cost_pdf_pipeline.py --root "$ARGUMENTS" --output "$ARGUMENTS/BBB" --mode annotate --same-name --limit 1 --findings-json <path-to-reviewed-findings.json>`
10. Verify annotated output. Report a concise summary to the user:
    - Total findings, annotated count, missed count.
    - List of high-severity issues.
    - Output path of the annotated PDF.
11. If more PDFs remain in the folder, loop back to step 1 automatically. Stop only if the user explicitly asks to stop.
