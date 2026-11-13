"""FastAPI app: POST /api/ask, GET /api/health, serves the frontend."""
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, llm, tickets
from .pipeline import Session, answer

app = FastAPI(title="VoxSupport")
SESSIONS: dict[str, Session] = {}
FRONTEND = config.ROOT / "frontend"


class Ask(BaseModel):
    question: str
    session_id: str | None = None
    strategy: str | None = None


@app.get("/api/health")
def health():
    return {"status": "ok", "llm_available": llm.available(), "model": config.LLM_MODEL,
            "strategy": config.DEFAULT_STRATEGY}


@app.post("/api/ask")
def ask(body: Ask):
    sid = body.session_id or uuid.uuid4().hex
    sess = SESSIONS.setdefault(sid, Session())
    res = answer(body.question, sess, strategy=body.strategy)
    if res.escalate:
        res.ticket = tickets.create(sess, res)
    return {"session_id": sid, **res.dict()}


@app.get("/api/tickets")
def list_tickets():
    return tickets.list_tickets()


@app.get("/api/tickets/{tid}")
def get_ticket(tid: str, format: str = "json"):
    t = tickets.get(tid)
    if not t:
        raise HTTPException(404, "ticket not found")
    if format == "md":
        return PlainTextResponse(t["markdown"], headers={"Content-Disposition": f'attachment; filename="{tid}.md"'})
    return t


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
