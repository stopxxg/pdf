#!/usr/bin/env python3
"""Remove broken comment markers (id 0-17) from document.xml and repack docx."""

import zipfile
import shutil
import os
from lxml import etree

SRC = "/Users/iswcxxg/Desktop/ccc/张宇.docx"
TMP_DIR = "/tmp/docx_fix"
BACKUP = "/Users/iswcxxg/Desktop/ccc/张宇.docx.bak"

# Backup current file
shutil.copy2(SRC, BACKUP)
print(f"Backup saved to {BACKUP}")

# Clean tmp
if os.path.exists(TMP_DIR):
    shutil.rmtree(TMP_DIR)
os.makedirs(TMP_DIR)

# Unzip
with zipfile.ZipFile(SRC, 'r') as z:
    z.extractall(TMP_DIR)

# Fix document.xml: remove comment markers with id 0-17
ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
doc_path = os.path.join(TMP_DIR, 'word', 'document.xml')
tree = etree.parse(doc_path)
root = tree.getroot()

removed = 0
# Remove commentRangeStart and commentRangeEnd with id 0-17
for tag in ['commentRangeStart', 'commentRangeEnd']:
    for elem in root.iter(f'{{{ns["w"]}}}{tag}'):
        cid = elem.get(f'{{{ns["w"]}}}id')
        if cid and cid.isdigit() and 0 <= int(cid) <= 17:
            parent = elem.getparent()
            if parent is not None:
                parent.remove(elem)
                removed += 1

# Remove w:r elements that contain only a commentReference with id 0-17
for run in root.iter(f'{{{ns["w"]}}}r'):
    refs = list(run.iter(f'{{{ns["w"]}}}commentReference'))
    if refs:
        for ref in refs:
            cid = ref.get(f'{{{ns["w"]}}}id')
            if cid and cid.isdigit() and 0 <= int(cid) <= 17:
                parent = run.getparent()
                if parent is not None:
                    parent.remove(run)
                    removed += 1
                break

tree.write(doc_path, xml_declaration=True, encoding='UTF-8', standalone=True)
print(f"Removed {removed} broken comment markers from document.xml")

# Repack docx
os.remove(SRC)
with zipfile.ZipFile(SRC, 'w', zipfile.ZIP_DEFLATED) as zf:
    for root_dir, dirs, files in os.walk(TMP_DIR):
        for file in files:
            full_path = os.path.join(root_dir, file)
            arcname = os.path.relpath(full_path, TMP_DIR)
            zf.write(full_path, arcname)

print(f"Fixed docx saved to {SRC}")

# Verify
from docx import Document
doc = Document(SRC)
print(f"Verified: {len(doc.paragraphs)} paragraphs loaded")
