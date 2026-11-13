# VoxSupport — Diagram prompts

How to use: paste each prompt into an AI image/diagram generator (e.g. ChatGPT image generation, Gemini, Napkin AI,
Eraser.io "diagram-as-code", or Excalidraw AI). If you would rather draw by hand, the prompts are written as precise
box-and-arrow specifications, so you can follow them in draw.io / PowerPoint / Lucidchart directly.

**Common style line — append this to every prompt:**
> Style: clean, flat, professional technical diagram on a white background, landscape orientation, rectangular boxes
> with rounded corners, thin dark-grey arrows with arrowheads, a restrained palette (blue, orange, green, grey), legible
> sans-serif labels at least 14 pt, no photos, no 3-D, no decorative icons, no gradients, high resolution (suitable for
> print in a Word document). Print exactly the labels given — do not invent extra components.

Each figure below is numbered to match the report exactly (Figures 5.1 – 5.8).

---

## Figure 5.1 — Overall system architecture (layered)

> Draw a layered system architecture diagram titled "VoxSupport – System Architecture". Four horizontal layers stacked
> top to bottom, each a large labelled band:
>
> **Layer 1 – Presentation (Browser):** boxes "Voice Input (Web Speech API – speech-to-text)", "Chat Interface (HTML/JS)",
> "Voice Output (speech synthesis)", "Ticket Viewer / Download".
> **Layer 2 – Application (FastAPI backend):** boxes "REST API  (/api/ask, /api/tickets, /api/health)", "Session Manager
> (conversation memory + diagnosis state)", "Orchestration Pipeline".
> **Layer 3 – Intelligence components** (inside or beside the pipeline): boxes "Input Guardrails", "Guided Diagnosis
> Engine", "Query Rewriter", "Hybrid Retriever (BM25 + Dense, RRF)", "Cross-Encoder Reranker", "Prompt Builder",
> "LLM Client", "Groundedness & Citation Validator", "Escalation Ticket Generator".
> **Layer 4 – Data & external services:** boxes "ChromaDB vector index (4 chunking strategies)", "BM25 chunk index
> (JSONL)", "Manufacturer Manuals (Dell, HP, Lenovo PDFs)", "Tickets store (JSON + Markdown)", and a separate box outside
> the stack on the right: "Groq API – gpt-oss-120b (LLM)".
>
> Arrows: Browser ⇄ REST API; REST API → Pipeline; Pipeline → each intelligence component in flow order; Retriever ⇄
> ChromaDB and BM25 index; LLM Client ⇄ Groq API; Ticket Generator → Tickets store; Manuals → (offline arrow labelled
> "Ingestion & indexing") → ChromaDB and BM25 index.

---

## Figure 5.2 — Document ingestion and indexing pipeline (offline)

> Draw a left-to-right flowchart titled "Offline Ingestion and Indexing Pipeline". Steps as boxes connected by arrows:
> 1. "Manufacturer manuals (PDF) – Dell Latitude 5400 service manual & setup guide, HP ProBook 440 G10 service guide,
>    Lenovo T14/P14s Gen 1 HMM"
> 2. "Text extraction (PyMuPDF) + cleaning (de-hyphenation, whitespace)"
> 3. "Structure mapping – table-of-contents → section and chapter for every page"
> 4. "Metadata tagging – vendor, model, document type, page, section, problem category (boot, overheating, battery/power,
>    RAM, storage, display)"
> 5. A fan-out into four parallel boxes: "Fixed-size (800 chars)", "Overlapping (800 / 150)", "Semantic (embedding-based
>    boundaries)", "Metadata-aware (section-bounded, section prefix)".
> 6. Each of the four → "Embedding – all-MiniLM-L6-v2 (384-dim)".
> 7. Embedding → "ChromaDB collection (HNSW, cosine)" and, in parallel, the chunk text → "BM25 index (rank_bm25)".
> Add small count labels under the four chunkers: 649, 803, 1,021, 860 chunks.

---

## Figure 5.3 — Chunking strategies illustrated

> Draw a four-row comparison diagram titled "Chunking Strategies". Each row shows the same long horizontal bar labelled
> "Manual text (with section headings: 'Removing the battery', 'Removing the fan')". Row 1 "Fixed-size": the bar cut
> into equal blocks. Row 2 "Overlapping": equal blocks with shaded overlapping regions between neighbours. Row 3
> "Semantic": blocks of unequal length, cut where the topic changes (marked with small "similarity drop" markers). Row 4
> "Metadata-aware": blocks never cross a section heading boundary; each block carries a tag "[Dell Latitude 5400 > Removing
> the battery]" above it.

---

## Figure 5.4 — Hybrid retrieval and reranking

> Draw a diagram titled "Hybrid Retrieval with Reciprocal Rank Fusion". On the left a box "Query". Two parallel branches:
> upper branch "Dense retrieval: query embedding → ChromaDB top-20 (cosine)"; lower branch "Keyword retrieval: BM25 top-20".
> Before both branches, a small box "Vendor detection → metadata filter (Dell / HP / Lenovo)" applied to both. The branches
> merge into a box "Reciprocal Rank Fusion: score(d) = Σ 1 / (60 + rank)". Then box "Cross-encoder reranker
> (ms-marco-MiniLM-L-6-v2) — scores each (query, passage) pair". Then box "Top-4 passages with citations (manual,
> section, page)". Under the reranker box add a dashed side-note: "Reranker score also used as retrieval-confidence gate".

---

## Figure 5.5 — Query processing flow with guardrail decision points

> Draw a vertical flowchart titled "Online Query Processing and Guardrails". Use rectangles for processes, diamonds
> for decisions, rounded "terminator" boxes for outcomes (colour outcomes: green = answer, orange = escalate, grey =
> refuse).
> Start: "User question (voice or text)".
> → Diamond "Input guardrails: empty / prompt-injection / off-topic?" — Yes → grey terminator "Refuse politely".
> → Diamond "Safety hazard (swollen battery, smoke, liquid, shock)?" — Yes → orange terminator "Immediate safety advice +
>    escalate + ticket".
> → Diamond "Customer asks for a human?" — Yes → orange "Escalate + ticket".
> → Diamond "Vague symptom and no diagnosis in progress?" — Yes → box "Guided diagnosis interview (Figure 5.6)" which later
>    rejoins at the next step with "observations".
> → Box "Query rewriting (resolve follow-ups using conversation memory)".
> → Box "Hybrid retrieval + reranking (Figure 5.4)".
> → Diamond "Top reranker score ≥ threshold?" — No → orange "Abstain + escalate + ticket".
> → Box "Prompt construction: numbered context, citation rules, abstention rule, customer observations".
> → Box "LLM generation (Groq gpt-oss-120b)".
> → Box "Validation: citation check, sentence-level groundedness".
> → Diamond "Model abstained or answer not grounded?" — Yes → orange "Escalate + ticket". No → green terminator "Answer
>    with citations (read aloud)".

---

## Figure 5.6 — Guided diagnosis state machine

> Draw a state-machine diagram titled "Guided Diagnosis Flow". States (rounded boxes): "Idle", "Symptom detected",
> "Ask device (if unknown)", "Question 1", "Question 2", "Question 3", "Compose query + observations", "Answer".
> Transitions: Idle → Symptom detected (label "vague symptom, e.g. 'laptop won't turn on'"); Symptom detected → Ask device
> (label "vendor unknown") or → Question 1 (label "vendor known"); Ask device → Question 1; Question 1 → Question 2 →
> Question 3 (label "customer reply"); Question 3 → Compose query + observations → Answer; Answer → Idle.
> Exit transitions drawn in orange from the question states: → "Safety escalation + ticket" (label "'yes' to bulging /
> burning smell"), → "Idle" (label "cancel / new specific question").
> Add a side panel "Question sets by category" listing: Boot, Battery/Power, Overheating, RAM, Storage, Display (3
> questions each).

---

## Figure 5.7 — Escalation ticket generation

> Draw a flowchart titled "Escalation Ticket Generation". Left: four orange trigger boxes stacked — "Safety hazard
> detected", "No relevant manual content (low retrieval confidence)", "Model abstained / answer not grounded", "Customer
> requests a human technician" (also include "LLM service error"). All arrows converge into a box "Ticket generator".
> Inputs feeding the generator from the left-bottom: "Session transcript", "Diagnostic answers", "Steps already
> suggested", "Manual references (manual, section, page)", "Detected device". Output on the right: a document icon-less
> box "Ticket TCK-YYYYMMDD-XXXX" with fields listed inside: "Priority (HIGH for safety)", "Device", "Reported issue",
> "Diagnostic answers", "Steps already suggested", "Manual references", "Escalation reason", "Conversation". Two arrows
> from the ticket: "Saved as JSON + Markdown (datasets/tickets/)" and "Shown in the UI with download link / API
> endpoints".

---

## Figure 5.8 — Voice interaction sequence diagram

> Draw a UML sequence diagram titled "Voice Interaction Sequence". Lifelines left to right: "User", "Browser (Web Speech
> API + UI)", "FastAPI /api/ask", "Pipeline", "Hybrid Retriever", "Groq LLM", "Ticket Store".
> Messages in order: 1 User → Browser: "speaks question"; 2 Browser → Browser: "speech-to-text; waits 1.6 s of silence";
> 3 Browser → FastAPI: "POST /api/ask {question, session_id}"; 4 FastAPI → Pipeline: "answer(question, session)";
> 5 Pipeline → Pipeline: "input guardrails"; 6 Pipeline → Hybrid Retriever: "retrieve(query, vendor)"; 7 Retriever →
> Pipeline: "top-4 passages + scores"; 8 Pipeline → Groq LLM: "prompt (context + question)"; 9 Groq LLM → Pipeline:
> "cited answer"; 10 Pipeline → Pipeline: "groundedness + citation validation"; 11 (optional frame "if escalate")
> Pipeline → Ticket Store: "create ticket"; 12 Pipeline → FastAPI → Browser: "JSON {answer, citations, status,
> ticket}"; 13 Browser → User: "displays answer and speaks it sentence by sentence".

---

## Screenshots to capture yourself (Figures 6.5 – 6.9)

Run the app (`python -m uvicorn voxsupport.api:app --app-dir backend --port 8000`, open http://localhost:8000), use a
fresh page for each, and take a full-window screenshot (Win + Shift + S):

| Figure | What to ask | What the screenshot must show |
|---|---|---|
| 6.5 | "How do I replace the thermal fan on a ThinkPad T14 Gen 1?" | Numbered steps, [1] citations, the reference list (manual, section, page), and the status line (status · mode · ms · grounded score) |
| 6.6 | "my laptop won't turn on" → answer the questions by tapping the option buttons | A diagnostic question with its buttons and "question 2 of 4" label; then the final tailored answer |
| 6.7 | "my battery is swollen" | The safety message, the orange "Escalate to a human technician" banner and the HIGH-priority ticket card |
| 6.8 | After any answer, say "I want to talk to a human technician" and click "View technician summary" | The expanded ticket summary |
| 6.9 | "What's the best pizza recipe?" and "How do I replace the turbocharger on a Dell Latitude 5400?" | The refusal and the abstention message |
