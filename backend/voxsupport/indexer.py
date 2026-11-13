"""Build persistent indexes (ChromaDB + chunk JSONL for BM25) per chunking strategy."""
import csv
import json
import sys
import time

import chromadb
from sentence_transformers import SentenceTransformer

from . import config
from .chunkers import build_chunks
from .loader import load_document

_embedder = None


def get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer(config.EMBED_MODEL, device="cpu")
    return _embedder


def chunks_path(strategy: str):
    return config.PROCESSED_DIR / f"chunks_{strategy}.jsonl"


def write_inventory(docs):
    with open(config.INVENTORY_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["filename", "vendor", "model", "doc_type", "pages_with_text",
                    "characters", "toc_sections"])
        for d in docs:
            w.writerow([d.filename, d.meta["vendor"], d.meta["model"], d.meta["doc_type"],
                        len(d.pages), sum(len(p.text) for p in d.pages),
                        len({p.section for p in d.pages})])


def build_index(strategy: str, docs=None):
    t0 = time.time()
    docs = docs or [load_document(f) for f in config.DOCUMENTS]
    emb = get_embedder()
    chunks = []
    for d in docs:
        chunks += build_chunks(d, strategy, embedder=emb)
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    with open(chunks_path(strategy), "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps({"id": c.id, "text": c.text, "meta": c.meta}) + "\n")

    client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
    name = f"chunks_{strategy}"
    try:
        client.delete_collection(name)
    except Exception:
        pass
    col = client.create_collection(name, metadata={"hnsw:space": "cosine"})
    B = 128
    for i in range(0, len(chunks), B):
        batch = chunks[i:i + B]
        vecs = emb.encode([c.text for c in batch], normalize_embeddings=True,
                          show_progress_bar=False).tolist()
        col.add(ids=[c.id for c in batch], embeddings=vecs,
                documents=[c.text for c in batch], metadatas=[c.meta for c in batch])
    print(f"[{strategy}] {len(chunks)} chunks indexed in {time.time() - t0:.1f}s")
    return len(chunks)


if __name__ == "__main__":
    strategies = sys.argv[1:] or config.STRATEGIES
    docs = [load_document(f) for f in config.DOCUMENTS]
    write_inventory(docs)
    for s in strategies:
        build_index(s, docs)
