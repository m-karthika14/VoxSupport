"""Hybrid retrieval: dense (Chroma) + BM25, fused with RRF, reranked by cross-encoder."""
import json
import re
from dataclasses import dataclass

import chromadb
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

from . import config
from .indexer import chunks_path, get_embedder

_client = None
_reranker = None
_bm25_cache: dict = {}

VENDOR_HINTS = {
    "Dell": ["dell", "latitude"],
    "HP": ["hp ", "hp,", "probook", "hewlett"],
    "Lenovo": ["lenovo", "thinkpad", "t14", "p14s"],
}


@dataclass
class Hit:
    id: str
    text: str
    meta: dict
    score: float = 0.0       # rerank score (higher = better)


def _tok(s: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9\-\.]*", s.lower())


def detect_vendor(query: str) -> str | None:
    q = query.lower() + " "
    found = [v for v, hints in VENDOR_HINTS.items() if any(h in q for h in hints)]
    return found[0] if len(found) == 1 else None


def _chroma():
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
    return _client


def _reranker_model():
    global _reranker
    if _reranker is None:
        _reranker = CrossEncoder(config.RERANK_MODEL, device="cpu")
    return _reranker


def _bm25(strategy: str):
    if strategy not in _bm25_cache:
        rows = [json.loads(l) for l in open(chunks_path(strategy), encoding="utf-8")]
        _bm25_cache[strategy] = (BM25Okapi([_tok(r["text"]) for r in rows]), rows)
    return _bm25_cache[strategy]


def dense_search(query, strategy, k, vendor=None) -> list[Hit]:
    col = _chroma().get_collection(f"chunks_{strategy}")
    vec = get_embedder().encode([query], normalize_embeddings=True).tolist()
    res = col.query(query_embeddings=vec, n_results=k,
                    where={"vendor": vendor} if vendor else None)
    return [Hit(i, d, m) for i, d, m in
            zip(res["ids"][0], res["documents"][0], res["metadatas"][0])]


def bm25_search(query, strategy, k, vendor=None) -> list[Hit]:
    bm, rows = _bm25(strategy)
    scores = bm.get_scores(_tok(query))
    order = sorted(range(len(rows)), key=lambda i: scores[i], reverse=True)
    out = []
    for i in order:
        if vendor and rows[i]["meta"]["vendor"] != vendor:
            continue
        out.append(Hit(rows[i]["id"], rows[i]["text"], rows[i]["meta"]))
        if len(out) >= k:
            break
    return out


def rrf(lists: list[list[Hit]], k: int = 60) -> list[Hit]:
    score, by_id = {}, {}
    for lst in lists:
        for rank, h in enumerate(lst):
            score[h.id] = score.get(h.id, 0) + 1 / (k + rank + 1)
            by_id[h.id] = h
    return [by_id[i] for i in sorted(score, key=score.get, reverse=True)]


def retrieve(query, strategy=None, top_k=4, candidates=20, vendor="auto",
             rerank=True, rerank_query=None) -> list[Hit]:
    """Candidates come from `query`; the cross-encoder scores them against `rerank_query`
    (a shorter natural-language form) when given."""
    strategy = strategy or config.DEFAULT_STRATEGY
    if vendor == "auto":
        vendor = detect_vendor(query)
    fused = rrf([dense_search(query, strategy, candidates, vendor),
                 bm25_search(query, strategy, candidates, vendor)])[:candidates]
    if not rerank or not fused:
        return fused[:top_k]
    scores = _reranker_model().predict([(rerank_query or query, h.text) for h in fused])
    for h, s in zip(fused, scores):
        h.score = float(s)
    fused.sort(key=lambda h: h.score, reverse=True)
    return fused[:top_k]
