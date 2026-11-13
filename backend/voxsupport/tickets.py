"""Escalation tickets: a technician-ready summary saved as JSON + Markdown."""
import json
import re
import secrets
from datetime import datetime

from . import config

TICKETS_DIR = config.ROOT / "datasets" / "tickets"
ID_RE = re.compile(r"^TCK-\d{8}-[0-9A-F]{4}$")


def _steps_from(answer: str) -> list[str]:
    steps = []
    for line in answer.splitlines():
        line = re.sub(r"\[\d+\]", "", line).strip()
        if re.match(r"^(\d+[.)]|[-•*])\s+", line):
            steps.append(re.sub(r"^(\d+[.)]|[-•*])\s+", "", line).strip())
    return steps or ([re.sub(r"\[\d+\]", "", answer).strip()[:300]] if answer.strip() else [])


def _device(session, res) -> str:
    vendor = session.vendor if session else None
    model = None
    for c in res.citations + (list(reversed(session.cites_given)) if session else []):
        if (not vendor or c["vendor"] == vendor):
            vendor, model = c["vendor"], c["model"]
            break
    if not vendor:
        return "Unknown (not stated by user)"
    return f"{vendor} {model}" if model else f"{vendor} (model not stated)"


def create(session, res) -> dict:
    now = datetime.now()
    tid = f"TCK-{now:%Y%m%d}-{secrets.token_hex(2).upper()}"
    safety = "safety" in res.flags
    priority = "HIGH" if safety else "NORMAL"
    diag = getattr(session, "last_diag", None) or {}
    user_msgs = [t for t in (session.transcript if session else []) if t["role"] == "user"]
    reported = diag.get("symptom") or (user_msgs[0]["text"] if user_msgs else res.question)

    steps, seen = [], set()
    for turn in (session.steps_given if session else []):
        for s in _steps_from(turn["answer"]):
            if s not in seen:
                seen.add(s)
                steps.append(s)
    cites, seen_c = [], set()
    for c in (session.cites_given if session else []) + res.citations:
        key = (c["source"], c["page"])
        if key not in seen_c:
            seen_c.add(key)
            cites.append(c)

    ticket = {
        "id": tid, "created": now.isoformat(timespec="seconds"), "priority": priority,
        "status": "open", "device": _device(session, res), "reported_issue": reported,
        "category": diag.get("category"), "diagnostic_answers": diag.get("answers", []),
        "steps_suggested": steps, "manual_references": cites,
        "escalation_reason": res.escalation_reason or "Escalated by assistant",
        "assistant_status": res.status, "flags": res.flags,
        "transcript": list(session.transcript) if session else [{"role": "user", "text": res.question}],
    }
    ticket["markdown"] = render_markdown(ticket)
    TICKETS_DIR.mkdir(parents=True, exist_ok=True)
    (TICKETS_DIR / f"{tid}.json").write_text(json.dumps(ticket, indent=2), encoding="utf-8")
    (TICKETS_DIR / f"{tid}.md").write_text(ticket["markdown"], encoding="utf-8")
    return ticket


def render_markdown(t: dict) -> str:
    L = [f"# Escalation ticket {t['id']}", "",
         f"- **Priority:** {t['priority']}", f"- **Created:** {t['created']}",
         f"- **Device:** {t['device']}", f"- **Problem category:** {t['category'] or 'not classified'}",
         f"- **Reason for escalation:** {t['escalation_reason']}", "",
         "## Reported issue", t["reported_issue"], ""]
    if t["diagnostic_answers"]:
        L += ["## Diagnostic answers from the customer"]
        L += [f"- {a['label']}: **{a['answer']}**" for a in t["diagnostic_answers"] if a["label"] != "Device"]
        L.append("")
    L += ["## Steps already suggested by the assistant"]
    L += [f"{i}. {s}" for i, s in enumerate(t["steps_suggested"], 1)] or ["_None — escalated before any steps were given._"]
    L += ["", "## Manual references"]
    L += [f"- {c['vendor']} {c['model']} — {c['section'] or 'General'}, p.{c['page']} ({c['source']})"
          for c in t["manual_references"]] or ["_None retrieved._"]
    L += ["", "## Conversation"]
    L += [f"- **{m['role'].title()}:** {m['text'][:300]}" for m in t["transcript"]]
    return "\n".join(L) + "\n"


def get(tid: str) -> dict | None:
    if not ID_RE.match(tid):
        return None
    p = TICKETS_DIR / f"{tid}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def list_tickets() -> list[dict]:
    out = []
    for p in sorted(TICKETS_DIR.glob("TCK-*.json"), reverse=True):
        t = json.loads(p.read_text(encoding="utf-8"))
        out.append({k: t[k] for k in ("id", "created", "priority", "status", "device",
                                      "reported_issue", "escalation_reason")})
    return out
