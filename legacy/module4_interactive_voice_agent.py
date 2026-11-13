# src/module4_interactive_voice_agent.py
import os
import sys
import time
import queue
import threading
import tempfile
import wave

import numpy as np
import sounddevice as sd
import webrtcvad
from faster_whisper import WhisperModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# --- Make `src/` importable ---
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from src.module1_basic_rag import (
    llm,
    prompt,
    format_docs,
    fast_retriever,
    heavy_retrieve,
    spoken_english_post_process,
)
from src.query_rewrite import ConversationState, rewrite_query

import pyttsx3


# ---------------------------
# Helpers: TTS
# ---------------------------
def speak_once(text: str, rate: int = 150):
    engine = pyttsx3.init()
    engine.setProperty("rate", rate)
    engine.say(text)
    engine.runAndWait()
    engine.stop()
    del engine

def speak_chunks(chunks, pause_s: float = 0.22):
    for line in chunks:
        line = (line or "").strip()
        if not line:
            continue
        speak_once(line)
        time.sleep(pause_s)


# ---------------------------
# ASR config
# ---------------------------
SAMPLE_RATE = 16000
CHANNELS = 1

print("Loading faster-whisper ASR model (GPU)...")
asr_model = WhisperModel("base", device="cuda", compute_type="float16")


# ---------------------------
# VAD config (hands-free)
# ---------------------------
# WebRTC VAD works on 10/20/30 ms frames; we use 30ms. [web:536][web:541]
FRAME_MS = 30
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_MS / 1000)  # 480 at 16kHz
FRAME_BYTES = FRAME_SAMPLES * 2  # int16 mono => 2 bytes/sample

vad = webrtcvad.Vad(2)  # 0 least aggressive, 3 most aggressive


def write_wav_int16(path: str, pcm16: np.ndarray):
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # int16
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm16.tobytes())


def record_utterance_vad(device=None,
                         start_voiced_frames=4,
                         end_silence_frames=14,
                         max_seconds=12):
    """
    Captures mic audio until VAD sees speech then silence.
    Returns: np.ndarray int16 mono at 16kHz, or None if nothing spoken.
    """
    q = queue.Queue()
    voiced = []
    ring = []

    def callback(indata, frames, time_info, status):
        if status:
            pass
        # indata float32 [-1,1], shape (frames, channels)
        mono = indata[:, 0]
        pcm16 = (mono * 32767).astype(np.int16)
        q.put(pcm16.tobytes())

    # state
    triggered = False
    voiced_run = 0
    silence_run = 0

    max_frames = int((max_seconds * 1000) / FRAME_MS)

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32",
        blocksize=FRAME_SAMPLES,
        device=device,
        callback=callback,
    ):
        print("\nListening... (speak now)")
        for _ in range(max_frames):
            frame_bytes = q.get()

            if len(frame_bytes) != FRAME_BYTES:
                # skip weird-sized frames
                continue

            is_speech = vad.is_speech(frame_bytes, SAMPLE_RATE)

            if not triggered:
                ring.append(frame_bytes)
                if is_speech:
                    voiced_run += 1
                else:
                    voiced_run = 0

                # once we see enough consecutive voiced frames, start utterance
                if voiced_run >= start_voiced_frames:
                    triggered = True
                    voiced.extend(ring)
                    ring = []
                    silence_run = 0
            else:
                voiced.append(frame_bytes)
                if is_speech:
                    silence_run = 0
                else:
                    silence_run += 1

                # stop after enough silence frames
                if silence_run >= end_silence_frames:
                    break

    if not voiced:
        return None

    pcm = np.frombuffer(b"".join(voiced), dtype=np.int16)
    return pcm


# ---------------------------
# Dynamic filler
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

# Serialize Ollama generations
llm_lock = threading.Lock()

# Conversation state for query rewriting
state = ConversationState()


# ---------------------------
# Heavy pipeline runner
# ---------------------------
class HeavyResult:
    def __init__(self):
        self.raw = None
        self.spoken_chunks = None
        self.done = False
        self.err = None

def run_heavy(rewritten_query: str, out: HeavyResult):
    try:
        # Heavy retrieval+rERANK first (parallelizable)
        docs = heavy_retrieve(rewritten_query, k=4)
        context = format_docs(docs)

        # LLM generation (serialize)
        with llm_lock:
            msgs = prompt.format_messages(context=context, question=rewritten_query)
            raw = llm.invoke(msgs).content

        out.raw = raw
        spoken = spoken_english_post_process(raw)
        out.spoken_chunks = spoken if isinstance(spoken, list) else [str(spoken)]
        out.done = True
    except Exception as e:
        out.err = e
        out.done = True


# ---------------------------
# Main interactive loop
# ---------------------------
def main():
    print("Interactive voice agent started.")
    print("Press Ctrl+C to exit.")
    device = None  # set to an integer device id if needed

    while True:
        pcm16 = record_utterance_vad(device=device)

        if pcm16 is None or len(pcm16) < SAMPLE_RATE // 3:
            print("No speech detected. Try again.")
            continue

        # Write temp wav for faster-whisper
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = tmp.name

        write_wav_int16(wav_path, pcm16)

        try:
            # ASR
            segments, info = asr_model.transcribe(wav_path, beam_size=2)
            user_text = " ".join(seg.text for seg in segments).strip()
        finally:
            try:
                os.remove(wav_path)
            except OSError:
                pass

        if not user_text:
            print("ASR produced empty transcript. Try again.")
            continue

        print("\nUSER:", user_text)
        state.add_turn("user", user_text)

        # Query rewrite BEFORE retrieval (standalone question)
        rewritten = rewrite_query(user_text, state, llm, llm_lock=llm_lock)
        print("REWRITE:", rewritten)

        # Prefetch (fast hybrid)
        pre_docs = fast_retriever(rewritten[:100], k=2)
        print(f"PREFETCH docs: {len(pre_docs)}")

        # Start heavy in background ASAP
        heavy = HeavyResult()
        t = threading.Thread(target=run_heavy, args=(rewritten, heavy), daemon=True)
        t.start()

        # Build preview snippets for filler context (add THIS right here)
        preview_snippets = "\n".join([doc.page_content[:60].strip() for doc in pre_docs[:2]])
        # Dynamic filler (quick)
        with llm_lock:
            filler = filler_chain.invoke({
                "preview": preview_snippets,
                "question": rewritten
            }).strip()
        print("FILLER:", filler)

        # Speak filler immediately (TTFB)
        speak_once(filler)

        # Wait for heavy result (usually finishes during filler or shortly after)
        while not heavy.done:
            time.sleep(0.05)

        if heavy.err:
            raise heavy.err

        print("ASSISTANT (raw):", heavy.raw)

        # Update state for "second one" etc on next turn
        state.add_turn("assistant", heavy.raw)
        state.set_last_list_items_from_assistant(heavy.raw)

        # Speak final answer as chunks with real pauses (no literal “pause”)
        speak_chunks(heavy.spoken_chunks, pause_s=0.22)


if __name__ == "__main__":
    main()
