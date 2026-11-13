"""Four chunking strategies, all returning list[Chunk].

fixed     - fixed-size windows, no overlap
overlap   - fixed-size windows with overlap
semantic  - split where adjacent-sentence embedding similarity drops
metadata  - section-aware: never crosses TOC section boundaries; each chunk is
            prefixed with "Vendor Model > Section" so context travels with it
"""
import re
from dataclasses import dataclass, field

import numpy as np

from .loader import Document, tag_categories

CHUNK_CHARS = 800
OVERLAP_CHARS = 150


@dataclass
class Chunk:
    id: str
    text: str
    meta: dict = field(default_factory=dict)


def _meta(doc: Document, page, strategy, section=None):
    m = dict(doc.meta)
    m.update(source=doc.filename, page=page.number, strategy=strategy,
             section=section if section is not None else page.section,
             chapter=page.chapter)
    return m


def _finish(chunks: list[Chunk]) -> list[Chunk]:
    for c in chunks:
        c.meta["categories"] = ",".join(tag_categories(c.text))
    return chunks


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n{2,}|\n(?=\s*(?:\d+\.|[-•]))", text)
    return [p.strip() for p in parts if p and p.strip()]


def _window(text: str, size: int, overlap: int) -> list[str]:
    """Split text into <=size windows, preferring to break on whitespace."""
    out, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            brk = text.rfind(" ", start + size // 2, end)
            end = brk if brk != -1 else end
        piece = text[start:end].strip()
        if piece:
            out.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return out


def _doc_stream(doc: Document):
    """Concatenate pages; return full text and (offset, page) markers."""
    full, marks = "", []
    for p in doc.pages:
        marks.append((len(full), p))
        full += p.text + "\n\n"
    return full, marks


def _page_at(marks, pos):
    page = marks[0][1]
    for off, p in marks:
        if off <= pos:
            page = p
        else:
            break
    return page


def _windowed(doc: Document, strategy: str, size: int, overlap: int) -> list[Chunk]:
    full, marks = _doc_stream(doc)
    chunks, cursor = [], 0
    for i, piece in enumerate(_window(full, size, overlap)):
        pos = full.find(piece[:60], max(cursor - size, 0))
        pos = pos if pos != -1 else cursor
        cursor = pos
        chunks.append(Chunk(f"{doc.filename}:{strategy}:{i}", piece,
                            _meta(doc, _page_at(marks, pos), strategy)))
    return chunks


def chunk_fixed(doc: Document) -> list[Chunk]:
    return _finish(_windowed(doc, "fixed", CHUNK_CHARS, 0))


def chunk_overlap(doc: Document) -> list[Chunk]:
    return _finish(_windowed(doc, "overlap", CHUNK_CHARS, OVERLAP_CHARS))


def chunk_semantic(doc: Document, embedder, threshold: float = 0.45) -> list[Chunk]:
    """Greedy semantic splitting per page-stream using sentence embeddings."""
    full, marks = _doc_stream(doc)
    sents = _split_sentences(full)
    if not sents:
        return []
    vecs = embedder.encode(sents, batch_size=64, normalize_embeddings=True,
                           show_progress_bar=False)
    groups, cur = [], [0]
    for i in range(1, len(sents)):
        size = sum(len(sents[j]) for j in cur)
        sim = float(np.dot(vecs[i], vecs[i - 1]))
        if (sim < threshold and size >= 300) or size + len(sents[i]) > CHUNK_CHARS * 1.5:
            groups.append(cur)
            cur = [i]
        else:
            cur.append(i)
    groups.append(cur)
    chunks, cursor = [], 0
    for n, g in enumerate(groups):
        text = " ".join(sents[j] for j in g)
        pos = full.find(sents[g[0]][:60], max(cursor - 500, 0))
        pos = pos if pos != -1 else cursor
        cursor = pos
        chunks.append(Chunk(f"{doc.filename}:semantic:{n}", text,
                            _meta(doc, _page_at(marks, pos), "semantic")))
    return _finish(chunks)


def chunk_metadata(doc: Document) -> list[Chunk]:
    """Section-aware: group pages by TOC section, window inside each section."""
    chunks, n = [], 0
    sections: list[tuple[str, list]] = []
    for p in doc.pages:
        if sections and sections[-1][0] == p.section:
            sections[-1][1].append(p)
        else:
            sections.append((p.section, [p]))
    for section, pages in sections:
        text, marks = "", []
        for p in pages:
            marks.append((len(text), p))
            text += p.text + "\n\n"
        prefix = f"[{doc.meta['vendor']} {doc.meta['model']} > {section or 'General'}]\n"
        cursor = 0
        for piece in _window(text, CHUNK_CHARS, OVERLAP_CHARS):
            pos = text.find(piece[:60], max(cursor - CHUNK_CHARS, 0))
            pos = pos if pos != -1 else cursor
            cursor = pos
            chunks.append(Chunk(f"{doc.filename}:metadata:{n}", prefix + piece,
                                _meta(doc, _page_at(marks, pos), "metadata", section)))
            n += 1
    return _finish(chunks)


def build_chunks(doc: Document, strategy: str, embedder=None) -> list[Chunk]:
    if strategy == "fixed":
        return chunk_fixed(doc)
    if strategy == "overlap":
        return chunk_overlap(doc)
    if strategy == "semantic":
        return chunk_semantic(doc, embedder)
    if strategy == "metadata":
        return chunk_metadata(doc)
    raise ValueError(f"unknown strategy {strategy}")
