"""Structured orchestration:
guard -> (guided diagnosis) -> rewrite -> retrieve -> generate -> validate -> (escalate)."""
import re
import time
from dataclasses import dataclass, field, asdict

from . import config, diagnosis as dg, guardrails as gr, llm
from .retrieval import detect_vendor, retrieve

SYSTEM = f"""You are VoxSupport, a hardware troubleshooting assistant for laptops and desktops.
Answer ONLY from the numbered context passages. Rules:
- Give short, numbered, actionable steps a technician can follow.
- Cite the passage number like [1] after each step or claim that uses it.
- Never invent part numbers, menu names, specifications or steps that are not in the context.
- If the context does not answer the question, reply exactly: "{gr.ABSTAIN}"
- Mention any warning or safety note that appears in the context.
- If "Observations from the customer" are given, tailor the steps to them: start with the check most
  relevant to those observations and skip steps they already rule out."""

FOLLOWUP = re.compile(r"\b(it|that|this|those|them|the (first|second|third|last) one|and what about|"
                      r"what about|same|also)\b", re.I)
HUMAN = re.compile(r"\b(talk|speak|connect|transfer|escalate|hand ?over|pass)\b.{0,30}\b(human|technician|"
                   r"engineer|agent|person|someone|support)\b|\b(human|real) (technician|agent|person)\b", re.I)


@dataclass
class Result:
    question: str
    rewritten: str = ""
    answer: str = ""
    status: str = "ok"          # ok | question | abstained | refused | escalate | error
    escalate: bool = False
    escalation_reason: str = ""
    mode: str = "llm"           # llm | extractive
    citations: list = field(default_factory=list)
    flags: list = field(default_factory=list)
    groundedness: dict = field(default_factory=dict)
    timings_ms: dict = field(default_factory=dict)
    options: list = field(default_factory=list)       # quick replies for diagnostic questions
    diagnosis: dict = field(default_factory=dict)     # {step,total,category} while interviewing
    ticket: dict | None = None

    def dict(self):
        d = asdict(self)
        if d["ticket"]:
            d["ticket"] = {k: d["ticket"][k] for k in ("id", "priority", "device", "markdown")}
        return d


class Session:
    """Conversation memory, guided-diagnosis state and the log used for escalation tickets."""
    def __init__(self):
        self.history: list[tuple[str, str]] = []
        self.vendor: str | None = None
        self.diag: dg.DiagState | None = None
        self.last_diag: dict | None = None
        self.transcript: list[dict] = []
        self.steps_given: list[dict] = []
        self.cites_given: list[dict] = []

    def add(self, q, a):
        self.history = (self.history + [(q, a)])[-4:]


def rewrite_query(q: str, session: Session | None, use_llm=True) -> str:
    if not session or not session.history or not FOLLOWUP.search(q):
        return q
    last_q, last_a = session.history[-1]
    if use_llm and llm.available():
        try:
            out = llm.chat([
                {"role": "system", "content": "Rewrite the follow-up as one standalone hardware "
                 "troubleshooting question, keeping device names. Output only the question."},
                {"role": "user", "content": f"Previous question: {last_q}\nPrevious answer: {last_a[:400]}\n"
                                            f"Follow-up: {q}"}], max_tokens=60)
            return out.strip().strip('"') or q
        except llm.LLMError:
            pass
    return f"{last_q} {q}"          # conservative fallback


def _context(hits) -> str:
    return "\n\n".join(f"[{i}] ({h.meta['vendor']} {h.meta['model']}, {h.meta['section']}, "
                       f"p.{h.meta['page']})\n{h.text}" for i, h in enumerate(hits, 1))


def _cites(hits):
    return [{"n": i, "vendor": h.meta["vendor"], "model": h.meta["model"], "source": h.meta["source"],
             "section": h.meta["section"], "page": h.meta["page"], "score": round(h.score, 2)}
            for i, h in enumerate(hits, 1)]


def _extractive(hits) -> str:
    h = hits[0]
    body = re.sub(r"^\[[^\]]*\]\n", "", h.text).strip()
    return f"{body[:600]} [1]"


def _escalate(res: Result, reason: str, answer: str | None = None, status="escalate"):
    res.status, res.escalate, res.escalation_reason = status, True, reason
    if answer is not None:
        res.answer = answer
    return res


def _ask_next(res: Result, session: Session):
    q = dg.current(session.diag)
    res.status, res.answer, res.options = "question", q["text"], q["options"]
    res.diagnosis = {"step": q["step"], "total": q["total"], "category": session.diag.category}
    return res


def answer(question: str, session: Session | None = None, strategy: str | None = None,
           vendor="auto", use_llm=True, top_k=4, guided: bool = True) -> Result:
    """Guided diagnosis only runs when a `session` is supplied (stateless callers get plain RAG)."""
    res = Result(question)
    t = {}
    t0 = time.perf_counter()
    observations = None
    query = question
    rq = None
    try:
        in_dialog = bool(session and session.diag)
        # a reply that is clearly a brand-new procedural question abandons the interview
        if in_dialog and (dg.CANCEL.match(question.strip()) or dg.is_new_request(question)):
            session.diag, in_dialog = None, False
            if dg.CANCEL.match(question.strip()):
                res.status, res.answer = "ok", "Okay, I've stopped the diagnosis. What else can I help with?"
                return res

        if HUMAN.search(question):
            if session:
                session.diag = None
            return _escalate(res, "Customer asked to speak to a human technician",
                             "Understood. I'm escalating this to a human technician and I've written up "
                             "a summary so you won't need to repeat yourself.")

        chk = gr.check_input(question, in_dialog=in_dialog)
        res.flags += chk.flags
        if not chk.ok:
            res.status, res.answer = "refused", chk.message
            return res
        if session and not session.vendor:
            session.vendor = detect_vendor(question)

        if chk.safety_alert:      # hazards are escalated immediately, no troubleshooting advice
            if session:
                session.diag = None
            return _escalate(res, "Safety hazard reported (battery swelling, smoke, liquid, shock)",
                             gr.SAFETY_NOTICE)

        # ---------- guided diagnosis ----------
        if guided and session:
            if session.diag:                                   # answering an interview question
                state = dg.consume(session.diag, question)
                if session.diag.vendor:
                    session.vendor = session.diag.vendor
                if state == "safety":
                    session.last_diag = dg.summary(session.diag)
                    session.diag = None
                    res.flags.append("safety")
                    return _escalate(res, "Safety hazard reported during diagnosis", gr.SAFETY_NOTICE)
                if state == "more":
                    return _ask_next(res, session)
                # interview finished: retrieve using what we learned
                observations = dg.observations(session.diag)
                query = dg.retrieval_query(session.diag)
                rq = dg.rerank_query(session.diag)
                session.last_diag = dg.summary(session.diag)
                res.diagnosis = {"category": session.diag.category, "complete": True}
                session.diag = None
            elif dg.is_vague_symptom(question):                # vague symptom: start interviewing
                session.diag = dg.start(question, session.vendor)
                session.last_diag = None
                return _ask_next(res, session)

        ts = time.perf_counter()
        res.rewritten = query if observations else rewrite_query(query, session, use_llm)
        t["rewrite"] = (time.perf_counter() - ts) * 1000

        ts = time.perf_counter()
        v = vendor
        if v == "auto" and session and session.vendor:
            v = session.vendor
        hits = retrieve(res.rewritten, strategy, top_k=top_k, vendor=v, rerank_query=rq)
        t["retrieve"] = (time.perf_counter() - ts) * 1000
        res.citations = _cites(hits)

        if not gr.retrieval_confident(hits, guided=bool(observations)):
            res.flags.append("low_retrieval_confidence")
            return _escalate(res, "No sufficiently relevant manual content found",
                             gr.ABSTAIN, status="abstained")

        ts = time.perf_counter()
        if use_llm and llm.available():
            user_msg = f"Context:\n{_context(hits)}\n\n"
            if observations:
                user_msg += f"Observations from the customer:\n{observations}\n\n"
            user_msg += f"Question: {question if observations else res.rewritten}"
            text = llm.chat([{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": user_msg}])
            text = re.sub(r"[【\[](\d+)[^】\]]*[】\]]", r"[\g<1>]", text)   # 4-dagger-L1 style -> [4]
            if not gr.valid_citations(text, len(hits)):
                res.flags.append("invalid_citation")
                text = re.sub(r"\[\d+\]", "", text)
            res.answer = text
        else:
            res.mode, res.answer = "extractive", _extractive(hits)
        t["generate"] = (time.perf_counter() - ts) * 1000

        ts = time.perf_counter()
        res.groundedness = gr.groundedness(res.answer, hits)
        t["validate"] = (time.perf_counter() - ts) * 1000
        if gr.ABSTAIN.lower() in res.answer.lower():
            _escalate(res, "Model found no answer in retrieved manuals", status="abstained")
        elif res.groundedness["supported_frac"] < 0.5:
            res.flags.append("possible_hallucination")
            _escalate(res, "Answer not sufficiently grounded in manuals",
                      gr.ABSTAIN + " A technician should review this.")
    except llm.LLMError as e:
        _escalate(res, str(e), "The assistant is temporarily unavailable.", status="error")
    finally:
        t["total"] = (time.perf_counter() - t0) * 1000
        res.timings_ms = {k: round(v, 1) for k, v in t.items()}
        if session is not None:
            session.transcript.append({"role": "user", "text": question})
            if res.answer:
                session.transcript.append({"role": "assistant", "text": res.answer, "status": res.status})
            if res.status == "ok":
                session.add(question, res.answer)
                session.steps_given.append({"question": question, "answer": res.answer})
                session.cites_given += res.citations
    return res
