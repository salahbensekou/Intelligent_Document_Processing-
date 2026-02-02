# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import List
import os

import PyPDF2


def _normalize_ocr_lang(lang: str) -> str:
    """
    Normalize OCR language string for Tesseract.
    Accepts common separators like comma/space and converts to "+".
    """
    if not lang:
        return "eng"

    # Allow values like "fra, eng" or "fra eng" or "fra+eng"
    cleaned = (
        lang.replace(",", " ")
        .replace(";", " ")
        .replace("|", " ")
        .strip()
    )
    parts = [p for p in cleaned.split() if p]
    return "+".join(parts) if parts else "eng"


def _ocr_pdf_pages(pdf_path: str, lang: str = "fra+eng", dpi: int = 300) -> List[str]:
    """
    OCR each PDF page by rendering it to an image with PyMuPDF (fitz),
    then running pytesseract on it.
    Requires:
      - pip install pymupdf pillow pytesseract
      - Tesseract installed on Windows
    """
    import fitz  # PyMuPDF
    from PIL import Image
    import pytesseract

    # Optional: set tesseract path from env
    tcmd = os.getenv("TESSERACT_CMD")
    if tcmd:
        pytesseract.pytesseract.tesseract_cmd = tcmd

    texts: List[str] = []

    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)

    lang = _normalize_ocr_lang(lang)

    with fitz.open(pdf_path) as doc:
        for page in doc:
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

            # OCR config (tu peux ajuster psm si besoin)
            config = "--oem 3 --psm 6"
            text = pytesseract.image_to_string(img, lang=lang, config=config)
            texts.append(text or "")

    return texts


def extract_pages_text(pdf_path: str) -> List[str]:
    """
    Extract text per page from a PDF.
    - First tries embedded text (PyPDF2)
    - If almost empty, falls back to OCR for scanned PDFs
    """
    pages: List[str] = []
    with open(pdf_path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            pages.append(page.extract_text() or "")

    # If PDF is scanned, extracted text is usually empty
    total_chars = sum(len(p.strip()) for p in pages)

    # Threshold: if too small => OCR
    if total_chars < 50:
        lang = os.getenv("OCR_LANG", "eng")  # ex: "fra+eng"
        return _ocr_pdf_pages(pdf_path, lang=lang, dpi=300)

    return pages
