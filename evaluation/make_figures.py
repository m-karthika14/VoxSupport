"""Generate report figures from evaluation/results_*.json  ->  report/figures/*.png"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "report" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

# validated categorical slots 1-4 (see dataviz palette); hatches give a non-colour cue for print/CVD
COL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
HATCH = ["", "//", "..", "xx"]
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": MUTED,
                     "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": INK,
                     "axes.spines.top": False, "axes.spines.right": False})

abl = json.load(open(HERE / "results_ablation.json"))
STRATS = ["fixed", "overlap", "semantic", "metadata"]
STRAT_LABEL = {"fixed": "Fixed-size", "overlap": "Overlapping", "semantic": "Semantic", "metadata": "Metadata-aware"}
METHODS = ["dense", "bm25", "hybrid", "hybrid+rerank"]
METH_LABEL = {"dense": "Dense (vector)", "bm25": "BM25 (keyword)", "hybrid": "Hybrid (RRF)",
              "hybrid+rerank": "Hybrid + reranker"}


def val(method, strat, key):
    return next(r[key] for r in abl if r["method"] == method and r["strategy"] == strat)


def grouped(metric, ylabel, fname, title):
    fig, ax = plt.subplots(figsize=(9, 4.6), dpi=200)
    w = 0.2
    for i, m in enumerate(METHODS):
        xs = [j + (i - 1.5) * w for j in range(len(STRATS))]
        ys = [val(m, s, metric) for s in STRATS]
        bars = ax.bar(xs, ys, width=w - 0.02, color=COL[i], hatch=HATCH[i], edgecolor="white",
                      linewidth=1.5, label=METH_LABEL[m])
        for b, y in zip(bars, ys):
            ax.text(b.get_x() + b.get_width() / 2, y + 0.012, f"{y:.2f}", ha="center", va="bottom",
                    fontsize=7.5, color=INK)
    ax.set_xticks(range(len(STRATS)))
    ax.set_xticklabels([STRAT_LABEL[s] for s in STRATS])
    ax.set_ylim(0, 1.12)
    ax.set_ylabel(ylabel)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_title(title, loc="left", fontsize=11, color=INK, pad=24)
    ax.legend(ncol=4, frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0), fontsize=8.5)
    fig.tight_layout()
    fig.savefig(OUT / fname, facecolor="white")
    plt.close(fig)


grouped("hit@4", "Hit@4 (fraction of questions)", "fig6_1_hit4.png",
        "")
grouped("mrr@10", "MRR@10", "fig6_2_mrr.png", "")

# Fig 6.3 retrieval latency by method (metadata-aware chunks)
fig, ax = plt.subplots(figsize=(8, 3.2), dpi=200)
lat = [val(m, "metadata", "latency_ms") for m in METHODS]
bars = ax.barh([METH_LABEL[m] for m in METHODS][::-1], lat[::-1], color=COL[:4][::-1], height=0.55,
               edgecolor="white", linewidth=1.5)
for b, h, v in zip(bars, HATCH[::-1], lat[::-1]):
    b.set_hatch(h)
    ax.text(v + 15, b.get_y() + b.get_height() / 2, f"{v:,.0f} ms", va="center", fontsize=9, color=INK)
ax.set_xlim(0, max(lat) * 1.18)
ax.set_xlabel("Mean retrieval latency per query (ms, CPU)")
ax.xaxis.grid(True, color=GRID, linewidth=0.8)
ax.set_axisbelow(True)
fig.tight_layout()
fig.savefig(OUT / "fig6_3_retrieval_latency.png", facecolor="white")
plt.close(fig)

# Fig 6.4 end-to-end latency breakdown (median per stage; medians add up to the total median)
e2e = json.load(open(HERE / "results_end2end.json"))
bd = {k: {"p50": round(v)} for k, v in e2e["stage_ms_median"].items()}
stages = [("retrieve", "Retrieval + rerank"), ("generate", "LLM generation (Groq)"),
          ("validate", "Groundedness check")]
fig, ax = plt.subplots(figsize=(8.6, 3.0), dpi=200)
left = 0
for i, (k, lab) in enumerate(stages):
    v = bd[k]["p50"]
    ax.barh([0], [v], left=left, color=COL[i], hatch=HATCH[i], edgecolor="white", linewidth=2, height=0.5,
            label=f"{lab}: {v:,} ms")
    left += v
ax.set_yticks([])
ax.set_xlim(0, left * 1.03)
ax.set_xlabel(f"Median end-to-end time per question (ms); total median {bd['total']['p50']:,} ms")
ax.legend(ncol=3, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.45), fontsize=8.5)
ax.spines["left"].set_visible(False)
fig.tight_layout()
fig.savefig(OUT / "fig6_4_latency_breakdown.png", facecolor="white", bbox_inches="tight")
plt.close(fig)
print("figures written to", OUT)
