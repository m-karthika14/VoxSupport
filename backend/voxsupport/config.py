"""Central configuration for VoxSupport."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

ROOT = Path(__file__).resolve().parents[2]
MANUALS_DIR = ROOT / "datasets" / "manuals"
PROCESSED_DIR = ROOT / "datasets" / "processed"
CHROMA_DIR = PROCESSED_DIR / "chroma"
INVENTORY_CSV = ROOT / "datasets" / "document_inventory.csv"
EVAL_DIR = ROOT / "evaluation"

# Document registry: filename -> metadata. Extend when adding manuals.
DOCUMENTS = {
    "hp_probook_440_g10_service_guide.pdf": dict(
        vendor="HP", model="ProBook 440 G10", doc_type="service_guide"),
    "dell_latitude_5400_service_manual.pdf": dict(
        vendor="Dell", model="Latitude 5400", doc_type="service_manual"),
    "dell_latitude_5400_setup_specs.pdf": dict(
        vendor="Dell", model="Latitude 5400", doc_type="setup_specs"),
    "lenovo_t14_p14s_gen1_hmm.pdf": dict(
        vendor="Lenovo", model="ThinkPad T14/P14s Gen 1", doc_type="hardware_maintenance_manual"),
}

# Problem categories in scope, with keywords used for metadata tagging.
CATEGORIES = {
    "boot": ["boot", "post", "bios", "power-on", "won't start", "startup", "no power", "beep"],
    "overheating": ["thermal", "fan", "heat sink", "heatsink", "overheat", "temperature", "cooling"],
    "battery_power": ["battery", "ac adapter", "power adapter", "charging", "charger", "coin-cell", "rtc"],
    "ram": ["memory module", "memory", "dimm", "sodimm", "ram"],
    "storage": ["hard drive", "ssd", "m.2", "solid-state", "storage", "nvme", "hdd"],
    "display": ["display", "lcd", "screen", "panel", "backlight", "camera", "hinge"],
}

EMBED_MODEL = os.getenv("VOX_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
RERANK_MODEL = os.getenv("VOX_RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
LLM_PROVIDER = os.getenv("VOX_LLM_PROVIDER", "ollama")   # groq | ollama
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_URL = "https://api.groq.com/openai/v1"
LLM_MODEL = os.getenv("VOX_LLM_MODEL", "openai/gpt-oss-120b" if LLM_PROVIDER == "groq" else "llama3.2:3b")
LLM_TIMEOUT = float(os.getenv("VOX_LLM_TIMEOUT", "120"))

STRATEGIES = ["fixed", "overlap", "semantic", "metadata"]
DEFAULT_STRATEGY = os.getenv("VOX_STRATEGY", "metadata")

# Guardrail thresholds (tuned in evaluation)
MIN_RERANK_SCORE = float(os.getenv("VOX_MIN_RERANK", "2.0"))
# Guided answers: symptom-style queries match procedural manual text less well, and the interview has
# already narrowed the category, so the gate is relaxed (LLM abstention + groundedness still apply).
GUIDED_MIN_RERANK = float(os.getenv("VOX_GUIDED_MIN_RERANK", "-6.0"))
MIN_GROUNDED = float(os.getenv("VOX_MIN_GROUNDED", "0.35"))
