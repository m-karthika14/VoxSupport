"""PDF loading with page-level text and TOC-derived section metadata."""
import re
from dataclasses import dataclass, field

import pymupdf

from . import config


@dataclass
class Page:
    number: int          # 1-based
    text: str
    section: str         # nearest TOC heading at/before this page
    chapter: str         # top-level TOC heading


@dataclass
class Document:
    filename: str
    meta: dict
    pages: list[Page] = field(default_factory=list)


def _clean(text: str) -> str:
    text = text.replace(" ", " ")
    text = re.sub(r"-\n(?=[a-z])", "", text)          # de-hyphenate line wraps
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_document(filename: str) -> Document:
    path = config.MANUALS_DIR / filename
    meta = config.DOCUMENTS[filename]
    pdf = pymupdf.open(path)
    toc = pdf.get_toc()  # [level, title, page]
    # Map page -> (section, chapter), carrying the last heading forward.
    section_at, chapter_at = {}, {}
    cur_sec, cur_ch = "", ""
    by_page: dict[int, list] = {}
    for lvl, title, pg in toc:
        by_page.setdefault(max(pg, 1), []).append((lvl, title.strip()))
    for p in range(1, len(pdf) + 1):
        for lvl, title in by_page.get(p, []):
            cur_sec = title
            if lvl == 1:
                cur_ch = title
        section_at[p], chapter_at[p] = cur_sec, cur_ch
    doc = Document(filename, meta)
    for i, page in enumerate(pdf, start=1):
        text = _clean(page.get_text())
        if text:
            doc.pages.append(Page(i, text, section_at[i], chapter_at[i]))
    pdf.close()
    return doc


def tag_categories(text: str) -> list[str]:
    low = text.lower()
    return [c for c, kws in config.CATEGORIES.items()
            if any(re.search(rf"\b{re.escape(k)}", low) for k in kws)]
