"""Retrieval evaluation across chunking strategies.

Usage: python evaluation/eval_retrieval.py [--rerank/--no-rerank] [strategies...]
A retrieved chunk is correct if its TOC section matches the question's expected regex.
Metrics: Hit@1, Hit@4, MRR@10, mean retrieval latency.
"""
import json
import re
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))

from voxsupport import config          # noqa: E402
from voxsupport.retrieval import retrieve  # noqa: E402


def load_questions():
    return [json.loads(l) for l in open(HERE / "questions.jsonl", encoding="utf-8")
            if l.strip() and json.loads(l)["answerable"]]


def is_hit(h, pattern):
    return bool(re.search(pattern, h.meta["section"].replace("\xa0", " "), re.I))


def evaluate(strategy, rerank=True, vendor="auto", qs=None, verbose=False):
    qs = qs or load_questions()
    ranks, lat, misses = [], [], []
    for q in qs:
        t = time.perf_counter()
        hits = retrieve(q["question"], strategy, top_k=10, vendor=vendor, rerank=rerank)
        lat.append((time.perf_counter() - t) * 1000)
        r = next((i for i, h in enumerate(hits, 1) if is_hit(h, q["expect_section"])), None)
        ranks.append(r)
        if r is None or r > 4:
            misses.append((q["id"], q["question"], r))
    n = len(qs)
    out = {
        "strategy": strategy, "rerank": rerank, "n": n,
        "hit@1": sum(1 for r in ranks if r == 1) / n,
        "hit@4": sum(1 for r in ranks if r and r <= 4) / n,
        "mrr@10": sum(1 / r for r in ranks if r) / n,
        "latency_ms": statistics.mean(lat),
    }
    if verbose:
        for m in misses:
            print("   miss:", m)
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    strategies = args or config.STRATEGIES
    rerank = "--no-rerank" not in sys.argv
    rows = [evaluate(s, rerank, verbose="--verbose" in sys.argv) for s in strategies]
    print(f"\n{'strategy':10} {'rerank':6} {'Hit@1':>6} {'Hit@4':>6} {'MRR':>6} {'ms/q':>7}")
    for r in rows:
        print(f"{r['strategy']:10} {str(r['rerank']):6} {r['hit@1']:6.2f} {r['hit@4']:6.2f} "
              f"{r['mrr@10']:6.2f} {r['latency_ms']:7.0f}")
    with open(HERE / "results_retrieval.json", "w") as f:
        json.dump(rows, f, indent=2)
