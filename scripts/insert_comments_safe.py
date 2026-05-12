#!/usr/bin/env python3
"""Safely insert review comments into an existing docx with direct ZIP manipulation."""

import zipfile
import shutil
import os
import re
from lxml import etree
from datetime import datetime

DOC_PATH = "/Users/iswcxxg/Desktop/ccc/张宇.docx"
BACKUP = "/Users/iswcxxg/Desktop/ccc/张宇.docx.safe.bak"
AUTHOR = "Editor"
DATE_STR = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NSMAP = {"w": W_NS}

def qn(tag):
    return "{%s}%s" % (W_NS, tag)

def find_max_comment_id(comments_root):
    max_id = 0
    for c in comments_root.iter(qn("comment")):
        cid = c.get(qn("id"))
        if cid and cid.isdigit():
            max_id = max(max_id, int(cid))
    return max_id

def add_comment_to_xml(comments_root, comment_id, author, date_str, text):
    comment = etree.SubElement(comments_root, qn("comment"))
    comment.set(qn("id"), str(comment_id))
    comment.set(qn("author"), author)
    comment.set(qn("date"), date_str)
    # Add para with text, preserving newlines as multiple paragraphs if needed
    for line in text.split("\n"):
        p = etree.SubElement(comment, qn("p"))
        r = etree.SubElement(p, qn("r"))
        t = etree.SubElement(r, qn("t"))
        t.text = line
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

def get_para_text(p_elem):
    """Extract full text from a paragraph element (including runs, tables, etc.)."""
    texts = []
    for t in p_elem.iter(qn("t")):
        texts.append(t.text or "")
    return "".join(texts)

def mark_paragraph(p_elem, comment_id):
    """Insert commentRangeStart, commentRangeEnd, and commentReference in a paragraph."""
    # Insert commentRangeStart after pPr if exists, else at beginning
    pPr = p_elem.find(qn("pPr"))
    start = etree.Element(qn("commentRangeStart"))
    start.set(qn("id"), str(comment_id))
    if pPr is not None:
        idx = list(p_elem).index(pPr) + 1
        p_elem.insert(idx, start)
    else:
        p_elem.insert(0, start)

    # Append commentRangeEnd
    end = etree.Element(qn("commentRangeEnd"))
    end.set(qn("id"), str(comment_id))
    p_elem.append(end)

    # Append reference run
    ref_run = etree.Element(qn("r"))
    ref_rpr = etree.SubElement(ref_run, qn("rPr"))
    ref_style = etree.SubElement(ref_rpr, qn("rStyle"))
    ref_style.set(qn("val"), "CommentReference")
    comment_ref = etree.SubElement(ref_run, qn("commentReference"))
    comment_ref.set(qn("id"), str(comment_id))
    p_elem.append(ref_run)

def add_comment(doc_root, comments_root, search_text, comment_text, max_id_ref):
    """Search in paragraphs and table cells, add comment and markers."""
    max_id_ref[0] += 1
    comment_id = max_id_ref[0]

    # Search all paragraphs in document (including tables)
    for p in doc_root.iter(qn("p")):
        para_text = get_para_text(p)
        if search_text.lower() in para_text.lower():
            add_comment_to_xml(comments_root, comment_id, AUTHOR, DATE_STR, comment_text)
            mark_paragraph(p, comment_id)
            return comment_id, True, "paragraph"

    # Search in table cells (iter all paragraphs in tables already covered by above)
    # The above iter all w:p in document, including those in tables

    return comment_id, False, None

def main():
    # Backup
    shutil.copy2(DOC_PATH, BACKUP)
    print(f"Backup saved to {BACKUP}")

    TMP_DIR = "/tmp/docx_insert_safe"
    if os.path.exists(TMP_DIR):
        shutil.rmtree(TMP_DIR)
    os.makedirs(TMP_DIR)

    with zipfile.ZipFile(DOC_PATH, "r") as z:
        z.extractall(TMP_DIR)

    # Parse comments.xml
    comments_path = os.path.join(TMP_DIR, "word", "comments.xml")
    comments_tree = etree.parse(comments_path)
    comments_root = comments_tree.getroot()
    max_id = find_max_comment_id(comments_root)
    print(f"Existing max comment ID: {max_id}")
    max_id_ref = [max_id]

    # Parse document.xml
    doc_path_xml = os.path.join(TMP_DIR, "word", "document.xml")
    doc_tree = etree.parse(doc_path_xml)
    doc_root = doc_tree.getroot()

    findings = [
        ("文章编号:", "文章编号为空，请补充文章编号。", "格式规范"),
        ("Using a representative mine ecological restoration area as an empirical case",
         "英文摘要内容明显短于中文摘要，且未完整对应中文摘要的四部分结构（目的、方法、结果、结论），疑似截断。建议对照中文摘要补充完整，并确保包含[Methods]、[Results]、[Conclusion]部分。", "摘要"),
        ("Gaozhi Peng",
         "英文作者姓名格式不规范。按照本刊要求，姓前名后，姓用全拼，名缩写。建议改为 Gao Z P。", "作者信息"),
        ("a case study of jungar banner",
         "英文题名中地名拼写为 Jungar Banner，但正文及关键词中统一使用 Zhunge′er Banner，请统一拼写。此外，题名中 trade-off-synergy 建议改为 trade-off and synergy 或 Trade-off/Synergy 以与中文对应。", "题名"),
        ("式中:为流域内每个栅格单元的年产水量",
         "公式注解中变量符号缺失（“式中：”后直接接“为”）。公式中的变量符号可能以公式对象插入，但未在文字注解中显示。请检查并补全每个变量的符号说明。", "公式"),
        ("式中:为总碳储量(t/hm2)",
         "公式注解中变量符号缺失。请补全变量符号。", "公式"),
        ("式中:为栅格x的土壤保持量(t)",
         "公式注解中变量符号缺失。请补全变量符号。", "公式"),
        ("式中:为土地利用i类中x栅格的生境质量",
         "公式注解中变量符号缺失。请补全变量符号。", "公式"),
        ("式中:为皮尔逊相关系数",
         "公式注解中变量符号缺失。请补全变量符号。", "公式"),
        ("式中:为第𝑖个空间单元中的因变量",
         "公式注解中变量符号缺失。请补全变量符号。", "公式"),
        ("4.讨 论",
         "节标题“4.讨 论”中间有空格，与其他节标题（如“3.结果与分析”）格式不一致。建议改为“4.讨论”。", "格式规范"),
        ("5.结 论",
         "节标题“5.结 论”中间有空格，与其他节标题格式不一致。建议改为“5.结论”。", "格式规范"),
        ("Acta Ecologica Sinica, 2023(16):1-14",
         "英文参考文献卷号缺失。应为 Acta Ecologica Sinica, 2023, 43(16):1-14。", "参考文献"),
        ("358-36",
         "英文参考文献页码不完整（358-36），请核实并补全。", "参考文献"),
        ("China mining Magazine",
         "期刊名大小写不规范。建议改为 China Mining Magazine。", "参考文献"),
        ("Fig. 3Spatial distribution",
         "图题中英文缩写 Fig. 3 与正文之间缺少空格，与其他图题格式不一致。建议改为 Fig. 3 Spatial distribution。", "图表格式"),
        ("四项具有代表性的生态系统服务",
         "前文使用汉字数字“四项”，后文出现“4类生态系统服务”（阿拉伯数字）。全文数字用法请保持一致，建议统一使用阿拉伯数字。", "文字规范"),
        ("https:∥",
         "表格中URL使用了特殊字符“∥”，应使用半角斜杠“//”。请检查并修正所有网址格式。", "图表格式"),
        ("ArcGIS Pro 3.1.5中构建",
         "英文软件名与中文之间缺少空格。建议改为“ArcGIS Pro 3.1.5 中构建”。", "文字规范"),
        ("CS—HQ",
         "服务对符号混用：此处使用破折号“CS—HQ”，而正文中其他地方使用连字符“CS-HQ”。请统一符号用法。", "文字规范"),
    ]

    inserted = []
    not_found = []

    for search_text, comment_text, category in findings:
        cid, ok, loc = add_comment(doc_root, comments_root, search_text, comment_text, max_id_ref)
        if ok:
            inserted.append((search_text[:50], comment_text, category))
            print(f"[OK] Comment {cid}: {category}")
        else:
            not_found.append((search_text, comment_text, category))
            print(f"[NOT FOUND] Comment {cid}: {search_text[:60]}")

    # Save modified XMLs
    comments_tree.write(comments_path, xml_declaration=True, encoding="UTF-8", standalone=True)
    doc_tree.write(doc_path_xml, xml_declaration=True, encoding="UTF-8", standalone=True)

    # Repack docx
    os.remove(DOC_PATH)
    with zipfile.ZipFile(DOC_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for root_dir, dirs, files in os.walk(TMP_DIR):
            for file in files:
                full_path = os.path.join(root_dir, file)
                arcname = os.path.relpath(full_path, TMP_DIR)
                zf.write(full_path, arcname)

    print(f"\nInserted {len(inserted)} comments.")
    if not_found:
        print(f"Not found ({len(not_found)}):")
        for s, c, cat in not_found:
            print(f"  - [{cat}] {s[:60]}")

    from collections import defaultdict
    cats = defaultdict(list)
    for s, c, cat in inserted:
        cats[cat].append(c)
    print("\n--- Summary ---")
    for cat, items in cats.items():
        print(f"{cat}: {len(items)} comments")

if __name__ == "__main__":
    main()
