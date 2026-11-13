"""Ablation: retrieval method x chunking strategy, plus per-vendor / per-category breakdown.

Usage: python evaluation/eval_ablation.py
Writes evaluation/results_ablation.json
"""
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))

from voxsupport import config                                   # noqa: E402
from voxsupport.retrieval import (bm25_search, dense_search,   # noqa: E402
                                  detect_vendor, retrieve, rrf)
from eval_retrieval import is_hit, load_questions               # noqa: E402

K = 10


def run(method, strategy, q):
    v = detect_vendor(q["question"])
    text = q["question"]
    if method == "dense":
        return dense_search(text, strategy, K, v)
    if method == "bm25":
        return bm25_search(text, strategy, K, v)
    if method == "hybrid":
        return rrf([dense_search(text, strategy, 20, v), bm25_search(text, strategy, 20, v)])[:K]
    if method == "hybrid+rerank":
        return retrieve(text, strategy, top_k=K, rerank=True)
    raise ValueError(method)


def score(method, strategy, qs):
    ranks, lat = [], []
    by_vendor, by_cat = defaultdict(list), defaultdict(list)
    for q in qs:
        t = time.perf_counter()
        hits = run(method, strategy, q)
        lat.append((time.perf_counter() - t) * 1000)
        r = next((i for i, h in enumerate(hits, 1) if is_hit(h, q["expect_section"])), None)
        ranks.append(r)
        ok4 = 1 if (r and r <= 4) else 0
        by_vendor[q["vendor"]].append(ok4)
        by_cat[q["category"]].append(ok4)
    n = len(qs)
    return {
        "method": method, "strategy": strategy,
        "hit@1": sum(1 for r in ranks if r == 1) / n,
        "hit@4": sum(1 for r in ranks if r and r <= 4) / n,
        "mrr@10": sum(1 / r for r in ranks if r) / n,
        "latency_ms": statistics.mean(lat),
        "hit@4_by_vendor": {k: sum(v) / len(v) for k, v in by_vendor.items()},
        "hit@4_by_category": {k: sum(v) / len(v) for k, v in by_cat.items()},
    }


if __name__ == "__main__":
    qs = load_questions()
    rows = []
    for method in ["dense", "bm25", "hybrid", "hybrid+rerank"]:
        for s in config.STRATEGIES:
            rows.append(score(method, s, qs))
            r = rows[-1]
            print(f"{method:14} {s:9} Hit@1 {r['hit@1']:.2f}  Hit@4 {r['hit@4']:.2f}  "
                  f"MRR {r['mrr@10']:.2f}  {r['latency_ms']:.0f} ms")
    json.dump(rows, open(HERE / "results_ablation.json", "w"), indent=2)
    best = [r for r in rows if r["method"] == "hybrid+rerank" and r["strategy"] == "metadata"][0]
    print("\nmetadata + hybrid+rerank by vendor:", best["hit@4_by_vendor"])
    print("by category:", best["hit@4_by_category"])
