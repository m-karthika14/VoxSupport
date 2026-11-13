"""End-to-end evaluation: guardrail accuracy, groundedness, hallucination rate, latency.

Usage: python evaluation/eval_end2end.py [--no-llm] [--strategy metadata]
--no-llm runs in extractive mode (no Ollama) - useful for guardrails/latency of retrieval only.
Hallucination rate = share of answered questions whose answer has <50% sentences supported by context.
"""
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))

from voxsupport import guardrails as gr, llm   # noqa: E402
from voxsupport.pipeline import answer          # noqa: E402
from eval_retrieval import is_hit               # noqa: E402


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))]


def main():
    use_llm = "--no-llm" not in sys.argv
    strategy = sys.argv[sys.argv.index("--strategy") + 1] if "--strategy" in sys.argv else None
    if use_llm and not llm.available():
        print("Ollama/model not available -> falling back to extractive mode (--no-llm)")
        use_llm = False
    qs = [json.loads(l) for l in open(HERE / "questions.jsonl", encoding="utf-8") if l.strip()]
    pos = [q for q in qs if q["answerable"]]
    neg = [q for q in qs if not q["answerable"]]

    rows, lat, grounded, halluc, cite_ok, answered = [], [], [], 0, 0, 0
    stages = {}
    for q in pos:
        r = answer(q["question"], strategy=strategy, use_llm=use_llm)
        lat.append(r.timings_ms.get("total", 0))
        for k, v in r.timings_ms.items():
            stages.setdefault(k, []).append(v)
        top_ok = bool(r.citations) and any(
            is_hit(type("H", (), {"meta": {"section": c["section"]}}), q["expect_section"])
            for c in r.citations)
        cite_ok += top_ok
        if r.status == "ok":
            answered += 1
            grounded.append(r.groundedness.get("score", 0))
        if "possible_hallucination" in r.flags:
            halluc += 1
        rows.append((q["id"], r.status, top_ok, round(r.groundedness.get("score", 0), 2)))

    correct_neg = 0
    for q in neg:
        r = answer(q["question"], strategy=strategy, use_llm=use_llm)
        correct_neg += r.status in ("refused", "abstained", "escalate")

    out = {
        "mode": "llm" if use_llm else "extractive",
        "answerable_n": len(pos), "negative_n": len(neg),
        "answered_rate": answered / len(pos),
        "citation_correct_rate": cite_ok / len(pos),
        "mean_groundedness": statistics.mean(grounded) if grounded else None,
        "hallucination_rate": halluc / len(pos),
        "negative_handled_rate": correct_neg / len(neg),
        "latency_ms_p50": pct(lat, 0.5), "latency_ms_p95": pct(lat, 0.95),
        "latency_ms_mean": statistics.mean(lat),
        "stage_ms_median": {k: statistics.median(v) for k, v in stages.items()},
        "stage_ms_mean": {k: statistics.mean(v) for k, v in stages.items()},
        "statuses": {st: sum(1 for r in rows if r[1] == st) for st in {r[1] for r in rows}},
    }
    print(json.dumps(out, indent=2))
    json.dump(out, open(HERE / "results_end2end.json", "w"), indent=2)


if __name__ == "__main__":
    main()
