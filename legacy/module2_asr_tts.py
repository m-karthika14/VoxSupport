# src/module2_asr_tts.py

import os
from dotenv import load_dotenv
import whisper
import pyttsx3

# 1. Load ASR model
print("Loading Whisper ASR model...")
model = whisper.load_model("tiny")  # or "base" if you want better quality

# 2. Transcribe audio
audio_path = "data/test_question.wav"

print("Transcribing audio...")
result = model.transcribe(audio_path)
transcript = result["text"].strip()

print("Transcript:", transcript)

# 3. Use the same RAG pipeline from Module 1
# (We'll import and reuse the chain logic shortly.)
import sys
import os

# Add the project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.module1_basic_rag import rag_chain

print("Querying RAG...")
response = rag_chain.invoke(transcript)
print("LLM answer:", response)

# 4. TTS: speak the answer
print("Speaking answer...")
engine = pyttsx3.init()

# Optional: set voice and rate
voices = engine.getProperty("voices")
engine.setProperty("voice", voices[0].id)  # pick first voice
engine.setProperty("rate", 150)            # words per minute

engine.say(response)
engine.runAndWait()

print("Done.")
