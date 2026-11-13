"""Guardrails: input screening, retrieval-confidence, and output groundedness."""
import re
from dataclasses import dataclass, field

import numpy as np

from . import config
from .indexer import get_embedder

SAFETY = [
    r"swollen|bulging|puffed|ballooning", r"\bsmoke|smoking|burning smell|burnt|\bfire\b|caught fire",
    r"\bsparks?\b|electric(al)? shock|electrocut", r"liquid|spill|water damage|wet",
    r"battery .*(leak|hot|explod)", r"\bexplod",
]
INJECTION = [r"ignore (all |any |previous |the )*(instructions|rules)", r"system prompt",
             r"you are now", r"jailbreak", r"pretend (to be|you are)"]
DOMAIN = ["laptop", "desktop", "computer", "pc", "notebook", "boot", "bios", "battery", "ram", "memory",
          "ssd", "drive", "storage", "screen", "display", "lcd", "fan", "overheat", "heat", "thermal",
          "power", "charger", "adapter", "keyboard", "touchpad", "wifi", "wi-fi", "dell", "hp", "lenovo",
          "thinkpad", "latitude", "probook", "post", "beep", "error", "fail", "replace", "remove",
          "install", "disassembl", "motherboard", "cpu", "usb", "port", "camera", "speaker", "hinge",
          "diagnos", "troubleshoot", "won't", "doesn't", "not working", "black screen", "shut"]
ABSTAIN = "I could not find that in the available manuals."


@dataclass
class InputCheck:
    ok: bool
    flags: list[str] = field(default_factory=list)
    safety_alert: bool = False
    message: str = ""


def check_input(query: str, in_dialog: bool = False) -> InputCheck:
    """in_dialog: the user is answering a diagnostic question ("yes", "no"), so skip the topic checks."""
    q = query.strip().lower()
    if in_dialog:
        if any(re.search(p, q) for p in INJECTION):
            return InputCheck(False, ["prompt_injection"],
                              message="I can only help with laptop and desktop hardware troubleshooting.")
        safety = any(re.search(p, q) for p in SAFETY)
        return InputCheck(bool(q), (["safety"] if safety else []) + ([] if q else ["empty"]),
                          safety_alert=safety)
    if len(q) < 3 or not re.search(r"[a-z]", q):
        return InputCheck(False, ["empty"], message="I didn't catch that. Please describe the hardware problem.")
    if any(re.search(p, q) for p in INJECTION):
        return InputCheck(False, ["prompt_injection"],
                          message="I can only help with laptop and desktop hardware troubleshooting.")
    safety = any(re.search(p, q) for p in SAFETY)
    on_topic = any(k in q for k in DOMAIN)
    if not on_topic and not safety:
        return InputCheck(False, ["off_topic"],
                          message="That doesn't look like a hardware issue. I can help with boot, "
                                  "overheating, battery, memory, storage and display problems.")
    flags = ["safety"] if safety else []
    return InputCheck(True, flags, safety_alert=safety)


SAFETY_NOTICE = ("Safety first: unplug the charger, power the device off, and do not charge or use it. "
                 "Do not open a swollen or damaged battery yourself. This case should be escalated to a "
                 "human technician.")


def retrieval_confident(hits, guided: bool = False) -> bool:
    floor = config.GUIDED_MIN_RERANK if guided else config.MIN_RERANK_SCORE
    return bool(hits) and hits[0].score >= floor


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip(" -•*\t") for p in parts if len(p.strip()) > 12]


def groundedness(answer: str, hits) -> dict:
    """Fraction of answer sentences supported by retrieved context (embedding similarity)."""
    sents = [s for s in _sentences(answer) if ABSTAIN.lower() not in s.lower()]
    ctx = [s for h in hits for s in _sentences(h.text)]
    if not sents:
        return {"score": 1.0, "unsupported": [], "supported_frac": 1.0}
    if not ctx:
        return {"score": 0.0, "unsupported": sents, "supported_frac": 0.0}
    emb = get_embedder()
    a = emb.encode(sents, normalize_embeddings=True, show_progress_bar=False)
    c = emb.encode(ctx, normalize_embeddings=True, show_progress_bar=False)
    best = (a @ c.T).max(axis=1)
    unsupported = [s for s, b in zip(sents, best) if b < config.MIN_GROUNDED + 0.2]
    return {"score": float(np.mean(best)), "unsupported": unsupported,
            "supported_frac": 1 - len(unsupported) / len(sents)}


def valid_citations(answer: str, n_sources: int) -> bool:
    cites = {int(x) for x in re.findall(r"\[(\d+)\]", answer)}
    return all(1 <= c <= n_sources for c in cites)
