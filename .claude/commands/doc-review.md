---
name: doc-review
description: Review a .docx file and insert Word comments for typos, errors, formatting issues, and other feedback. Works for dissertations, proposals, reports, or any Word document.
argument-hint: "[file-path] [optional: specific corrections or 'full review']"
---

Review a Word document and insert comments directly into the .docx file using python-docx and lxml XML manipulation.

Target file: $ARGUMENTS

## Modes

### 1. User-provided corrections
If the user provides a list of specific errors/corrections, insert a Word comment at each location in the document.

### 2. Full review (user says "full review" or similar)
Read the document and identify:
- Spelling errors and typos
- Grammar issues
- Inconsistent author name spellings
- Incomplete or malformed citations/references
- Template placeholder text that hasn't been filled in
- Tense inconsistencies
- Missing content (empty sections, placeholder tables)
- Formatting issues (inconsistent hyphenation, capitalization)

Then insert Word comments at each finding.

## How to insert Word comments

Use this Python approach with `python-docx` and `lxml`:

```python
from docx import Document
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from lxml import etree
from docx.opc.part import Part
from docx.opc.packuri import PackURI

# 1. Build the comments XML container
comments_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:comments xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas"
            xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
            xmlns:o="urn:schemas-microsoft-com:office:office"
            xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
            xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"
            xmlns:v="urn:schemas-microsoft-com:vml"
            xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
            xmlns:w10="urn:schemas-microsoft-com:office:word"
            xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
            xmlns:wne="http://schemas.microsoft.com/office/word/2006/wordml">
</w:comments>'''
comments_element = etree.fromstring(comments_xml.encode('utf-8'))

# 2. For each comment, add to the XML and mark the paragraph
def add_comment_to_xml(comments_element, comment_id, author, date_str, text):
    comment = etree.SubElement(comments_element, qn('w:comment'))
    comment.set(qn('w:id'), str(comment_id))
    comment.set(qn('w:author'), author)
    comment.set(qn('w:date'), date_str)
    p = etree.SubElement(comment, qn('w:p'))
    r = etree.SubElement(p, qn('w:r'))
    t = etree.SubElement(r, qn('w:t'))
    t.text = text
    t.set(qn('xml:space'), 'preserve')

def add_comment_markers(paragraph, search_text, comment_id):
    """Add commentRangeStart, commentRangeEnd, and commentReference to a paragraph."""
    # Try to find search_text in individual runs first
    found = False
    for run in paragraph.runs:
        if search_text.lower() in (run.text or "").lower():
            comment_start = OxmlElement('w:commentRangeStart')
            comment_start.set(qn('w:id'), str(comment_id))
            run.element.addprevious(comment_start)

            comment_end = OxmlElement('w:commentRangeEnd')
            comment_end.set(qn('w:id'), str(comment_id))
            run.element.addnext(comment_end)

            ref_run = OxmlElement('w:r')
            ref_rpr = OxmlElement('w:rPr')
            ref_style = OxmlElement('w:rStyle')
            ref_style.set(qn('w:val'), 'CommentReference')
            ref_rpr.append(ref_style)
            ref_run.append(ref_rpr)
            comment_ref = OxmlElement('w:commentReference')
            comment_ref.set(qn('w:id'), str(comment_id))
            ref_run.append(comment_ref)
            comment_end.addnext(ref_run)
            found = True
            break

    if not found:
        # Fallback: mark the whole paragraph
        p_element = paragraph._element
        comment_start = OxmlElement('w:commentRangeStart')
        comment_start.set(qn('w:id'), str(comment_id))
        p_element.insert(0, comment_start)

        comment_end = OxmlElement('w:commentRangeEnd')
        comment_end.set(qn('w:id'), str(comment_id))
        p_element.append(comment_end)

        ref_run = OxmlElement('w:r')
        ref_rpr = OxmlElement('w:rPr')
        ref_style = OxmlElement('w:rStyle')
        ref_style.set(qn('w:val'), 'CommentReference')
        ref_rpr.append(ref_style)
        ref_run.append(ref_rpr)
        comment_ref = OxmlElement('w:commentReference')
        comment_ref.set(qn('w:id'), str(comment_id))
        ref_run.append(comment_ref)
        p_element.append(ref_run)

# 3. After all comments are built, attach the comments part to the document
def attach_comments_part(doc, comments_element):
    comments_bytes = etree.tostring(comments_element, xml_declaration=True, encoding='UTF-8', standalone=True)
    doc_part = doc.part

    # Check for existing comments part
    existing = None
    for rel in doc_part.rels.values():
        if 'comments' in rel.reltype:
            existing = rel
            break

    if existing:
        existing.target_part._blob = comments_bytes
    else:
        comments_part = Part(
            PackURI('/word/comments.xml'),
            'application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml',
            comments_bytes,
            doc_part.package
        )
        doc_part.relate_to(comments_part, 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments')
```

## Agent Teams Strategy (Full Review Mode)

For full document reviews on long documents (50+ pages), use agent teams to parallelize the review:

1. **Create the team**: `TeamCreate` with `team_name: "doc-review"`.
2. **Read the document first** to determine its length and identify logical sections.
3. **Create tasks** via `TaskCreate`, splitting the document by review category:
   - **Spelling/grammar reviewer**: Typos, grammar issues, tense inconsistencies
   - **Citations/references reviewer**: Incomplete or malformed citations, author name consistency, reference formatting
   - **Content reviewer**: Template placeholders, missing content, empty sections, formatting inconsistencies
4. **Spawn 3 teammates** via `Agent` tool with `team_name: "doc-review"`, `subagent_type: "general-purpose"`, named `spelling-reviewer`, `citations-reviewer`, `content-reviewer`. Launch all in a single message.
5. Each teammate reviews the full document for its assigned category and returns comments: `{search_text, comment_text, category}`.
6. **Coordinator merges all comments**, inserts into the document, and saves.
7. **Shut down teammates** and `TeamDelete`.

For short documents or user-provided corrections mode, run as a single agent without teams.

## Steps

1. **Locate the file** — resolve the path, check it exists and is a valid .docx
2. **Read the document** — load with python-docx, scan all paragraphs and tables
3. **Search for each error** — find the paragraph index containing each search term (case-insensitive)
4. **Build comments** — for each finding, create the comment XML and add markers to the paragraph
5. **Attach the comments part** to the document package
6. **Save the file** (overwrite in place unless user requests a copy)
7. **Open in Word** using `open -a "Microsoft Word" "<path>"`
8. **Report** — tell the user how many comments were added and summarize the categories

## Rules

- Author name on all comments: "$AUTHOR_NAME"
- Date on comments: use today's date in ISO format
- Always search both paragraphs AND table cells for error text
- If a search term isn't found, report it to the user rather than silently skipping
- Group comments by category in the summary (typos, citations, template artifacts, etc.)
- For dissertation/proposal reviews, flag tense consistency issues (proposal = future tense, dissertation = past tense)
- Do NOT make direct edits to the text — only insert comments so the author can make their own corrections
- Ensure pdf2docx and python-docx are installed before running (`pip3 install pdf2docx python-docx` if needed)
