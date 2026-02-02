# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List
from docx import Document

def extract_pages_text_docx(docx_path: str) -> List[str]:
    """Extract text from a DOCX (single 'page' string)."""
    doc = Document(docx_path)
    text = "\n".join(p.text for p in doc.paragraphs)
    return [text]
