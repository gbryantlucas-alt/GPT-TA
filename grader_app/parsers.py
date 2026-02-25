from __future__ import annotations

import json
import os
import re
from pathlib import Path

from docx import Document
from pypdf import PdfReader


def read_text_from_docx(path: str) -> str:
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def read_text_from_pdf(path: str) -> str:
    reader = PdfReader(path)
    chunks: list[str] = []
    for page in reader.pages:
        chunks.append(page.extract_text() or "")
    return "\n".join(chunks)


def read_text(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix == ".docx":
        return read_text_from_docx(path)
    if suffix == ".pdf":
        return read_text_from_pdf(path)
    raise ValueError(f"Unsupported file type: {suffix}")


def infer_student_id(path: str, text: str) -> str:
    filename = Path(path).stem
    filename_guess = re.sub(r"[_-]+", " ", filename).strip()

    lines = [l.strip() for l in text.splitlines()[:20] if l.strip()]
    id_pattern = re.compile(r"\b(?:id|student\s*id)[:\s#-]*([A-Za-z0-9-]{4,})\b", re.I)
    name_pattern = re.compile(r"\b(?:name|student)[:\s-]*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b")

    for line in lines:
        match = id_pattern.search(line)
        if match:
            return match.group(1)
    for line in lines:
        match = name_pattern.search(line)
        if match:
            return match.group(1)

    return filename_guess


def safe_json_extract(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        first = raw.find("{")
        last = raw.rfind("}")
        if first >= 0 and last > first:
            return json.loads(raw[first : last + 1])
        raise
