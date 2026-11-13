import os
import sys
import time
import threading

# --- Make `src/` importable ---
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from faster_whisper import WhisperModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# Import RAG components from your module1
from src.module1_basic_rag import (
    llm,
    prompt,
    format_docs,
    fast_retriever,
    heavy_retrieve,
    spoken_english_post_process,
)

# Query rewriting module (must exist)
from src.query_rewrite import ConversationState, rewrite_query

# ---------------------------
# Shared state
# ---------------------------
class HeavyResult:
    def __init__(self):
        self.raw_text = None
        self.spoken_chunks = None  # list[str] preferred
        self.done = False
        self.error = None

heavy = HeavyResult()

# Ollama is often happier if you serialize generation calls
llm_lock = threading.Lock()

# Conversation memory for rewriting follow-ups like "the second one"
state = ConversationState()

# ---------------------------
# TTS helper (re-init per call)
# ---------------------------
import pyttsx3

def speak_once(text: str, rate: int = 150):
    engine = pyttsx3.init()
    engine.setProperty("rate", rate)
    engine.say(text)
    engine.runAndWait()
    engine.stop()
    del engine

def speak_chunks(chunks, pause_s: float = 0.25):
    for line in chunks:
        if not line:
            continue
        speak_once(line)
        time.sleep(pause_s)

# ---------------------------
# ASR (GPU)
# ---------------------------
print("Loading faster-whisper ASR model...")
asr_model = WhisperModel("base", device="cuda", compute_type="float16")

audio_path = os.path.join(project_root, "data", "test_question.wav")

print("Transcribing audio with faster-whisper...")
segments, info = asr_model.transcribe(audio_path, beam_size=5)
user_text = " ".join(seg.text for seg in segments).strip()
print("User transcript:", user_text)

# Add user turn to conversation
state.add_turn("user", user_text)

# ---------------------------
# Query rewriting (standalone)
# ---------------------------
# This resolves "the second one" etc. BEFORE hitting vector DB / BM25.
rewritten = rewrite_query(user_text, state, llm, llm_lock=llm_lock)
print("Rewritten query:", rewritten)

# ---------------------------
# Prefetch retrieval (fast hybrid)
# ---------------------------
partial_query = rewritten[:100]
print("Pre-fetch query:", partial_query)

prefetch_docs = fast_retriever(partial_query, k=2)
print(f"Pre-fetch retrieved {len(prefetch_docs)} docs (fast hybrid).")

# Extract preview snippets (first 50 chars each)
preview = "\n".join(doc.page_content[:50] for doc in prefetch_docs[:2])
print("Preview snippets:", preview)

# ---------------------------
# Dynamic filler (LLM)
# ---------------------------
filler_prompt = ChatPromptTemplate.from_messages([
    ("system", 
     """You are a helpful voice agent. ALWAYS respond with a SHORT, CONFIDENT filler like:
     - "Checking that for you..."
     - "Found info on [keyword], let me confirm..."
     - "Looking that up now..."
     - "Got it, one moment..."
     
     I ALWAYS have data. NEVER say "don't know", "no info", "sorry", or "not available".
     Preview docs: {preview}
     User asked: {question}
     
     Respond in 1 sentence only. Be enthusiastic."""),
    ("human", ""),
])
filler_chain = filler_prompt | llm | StrOutputParser()

print("Generating dynamic filler...")
preview_snippets = "\n".join([doc.page_content[:60].strip() for doc in prefetch_docs[:2]])
with llm_lock:
    filler = filler_chain.invoke({
        "preview": preview_snippets,
        "question": rewritten
    }).strip()

print("Filler:", filler)

# ---------------------------
# Heavy pipeline in background
#   - retrieval + rerank starts immediately
#   - LLM generation waits for lock (so it doesn't fight filler generation)
# ---------------------------
def run_heavy():
    try:
        print("Heavy: starting hybrid retrieval + rerank...")
        docs = heavy_retrieve(rewritten, k=4)
        context = format_docs(docs)

        print("Heavy: context ready, waiting for LLM...")
        with llm_lock:
            msgs = prompt.format_messages(context=context, question=rewritten)
            raw = llm.invoke(msgs).content

        heavy.raw_text = raw

        # spoken_english_post_process may return list[str] OR str; handle both
        spoken = spoken_english_post_process(raw)
        if isinstance(spoken, list):
            heavy.spoken_chunks = spoken
        else:
            heavy.spoken_chunks = [str(spoken)]

        heavy.done = True
        print("Heavy: finished.")
    except Exception as e:
        heavy.error = e
        heavy.done = True

heavy_thread = threading.Thread(target=run_heavy, daemon=True)
heavy_thread.start()

# Speak filler immediately (TTFB)
print("Speaking filler...")
speak_once(filler)

# Wait for heavy completion (usually finishes during filler or shortly after)
print("Waiting for heavy result...")
while not heavy.done:
    time.sleep(0.05)

if heavy.error:
    raise heavy.error

print("Final answer (raw):", heavy.raw_text)

# Update conversation state with assistant answer, so "second one" works next turn
state.add_turn("assistant", heavy.raw_text)
state.set_last_list_items_from_assistant(heavy.raw_text)
print("Extracted list items:", state.last_list_items)

# Speak final answer (chunked + real pauses)
print("Speaking final answer...")
speak_chunks(heavy.spoken_chunks, pause_s=0.25)
