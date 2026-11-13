# VoxSupport

Voice-enabled hardware troubleshooting assistant. Retrieval-Augmented Generation over Dell, HP and
Lenovo service manuals, with guardrails, citations, and a measured evaluation.

```
Voice/text -> input guardrails -> query rewrite -> hybrid retrieval (BM25 + dense, RRF)
           -> cross-encoder rerank -> confidence gate -> LLM (cited, grounded prompt)
           -> groundedness / citation validation -> answer or escalate to technician
```

## Layout
```
backend/voxsupport/   config, loader, chunkers, indexer, retrieval, guardrails, llm, pipeline, api
frontend/index.html   browser UI (Web Speech API for mic + read-aloud)
datasets/manuals/     PDFs (not committed)      datasets/processed/   chunk files + Chroma index
datasets/document_inventory.csv                 evaluation/           questions + eval scripts
legacy/               original proof-of-concept (Whisper/VAD/pyttsx3 CLI agent)
```

## Setup
```
pip install -r backend/requirements.txt
# create .env with GROQ_API_KEY=...  (VOX_LLM_PROVIDER=groq, VOX_LLM_MODEL=openai/gpt-oss-120b)
# or use local Ollama: VOX_LLM_PROVIDER=ollama + ollama pull llama3.2:3b
# with no LLM at all the app answers extractively
python -m voxsupport.indexer     # run from backend/ ; builds all 4 chunking indexes
uvicorn voxsupport.api:app --app-dir backend --port 8000     # open http://localhost:8000
```
Config via env vars: `VOX_LLM_MODEL`, `VOX_STRATEGY` (fixed|overlap|semantic|metadata), `VOX_MIN_RERANK`.

## Chunking strategies
fixed (800 chars) · overlap (800/150) · semantic (embedding-similarity splits) · metadata (TOC-section aware,
each chunk prefixed with vendor/model/section; default).

## Guardrails
- Input: empty, prompt-injection, off-topic, safety hazards (swollen battery, smoke, liquid) -> immediate escalation.
- Retrieval: reranker-score gate -> abstain + escalate.
- Output: citation validity, sentence-level groundedness vs. retrieved context, abstention phrase detection.
- Orchestration: LLM retries/timeouts, errors escalate instead of crashing.

## Evaluation
```
python evaluation/eval_retrieval.py            # Hit@1, Hit@4, MRR per chunking strategy
python evaluation/eval_end2end.py [--no-llm]   # guardrails, groundedness, hallucination rate, latency
```
Questions are in `evaluation/questions.jsonl` (40 answerable + 6 negative). Correctness = the retrieved chunk's
manual section matches the expected section.

## Guided diagnosis and escalation tickets
- **Guided diagnosis** (`diagnosis.py`): a vague symptom ("it won't turn on") starts a short interview, one question at a
  time (device first if unknown, then 3 category-specific checks). The answers become retrieval terms and
  "observations" the LLM tailors its steps to. A specific question, "cancel", or a safety answer breaks out of it.
- **Escalation tickets** (`tickets.py`): any escalation (safety, no manual evidence, ungrounded answer, LLM failure, or
  "talk to a human") writes `datasets/tickets/TCK-*.json/.md` with device, issue, diagnostic answers, steps already
  suggested, manual page references and the conversation. API: `GET /api/tickets`, `GET /api/tickets/{id}?format=md`.
