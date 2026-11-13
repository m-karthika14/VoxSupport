"""Guided diagnosis: turn a vague symptom into a short, one-question-at-a-time interview.

The answers become (a) observations passed to the LLM and (b) extra retrieval terms,
so the manual passages that get retrieved match the symptoms actually observed.
"""
import difflib
import re
from dataclasses import dataclass, field

from .retrieval import detect_vendor

# A message is a "vague symptom" if it describes a fault but doesn't ask for a specific procedure.
SYMPTOM = re.compile(
    r"won'?t|doesn'?t|didn'?t|can'?t|cannot|can not|never|does not|did not|is not|isn'?t|not (turn|power|start|boot|work|charg|show|detect|respond)"
    r"|no power|dead|stuck|freez|crash|shut(s|ting)? (down|off)|restart|reboot|blue screen|flicker|black|blank"
    r"|overheat|too hot|very hot|\bhot\b|loud fan|noisy|beep|slow|drain|not charging|broken|problem|issue|fault|fix|troubleshoot",
    re.I)
PROCEDURE = re.compile(
    r"\b(remove|replace|install|disassembl\w*|take out|swap|upgrade|run|clear|restore|download|specification"
    r"s?|part number|mean|means|check|test|diagnostics?|update|change|reset|enter|access|open|drain residual|hard reset|residual)\b", re.I)

CATEGORY_RULES = [  # order matters: first match wins
    ("boot", r"(won'?t|doesn'?t|didn'?t|can'?t|cannot|not|isn'?t|never).{0,20}(turn(s|ing)? on|power|start|boot|switch(es|ing)? on)|no power|\bdead\b|boot (loop|fail)|stuck on|power button|restart|reboot"),
    ("battery_power", r"charg|battery|adapter|ac power|drain"),
    ("overheating", r"overheat|too hot|very hot|\bhot\b|\bfan\b|thermal|shuts?(ting)? (down|off)"),
    ("ram", r"blue screen|memory|\bram\b|random restart|beep"),
    ("storage", r"hard (drive|disk)|\bssd\b|\bdisk\b|no boot device|clicking|slow|freez"),
    ("display", r"screen|display|flicker|lines|black|blank|lcd|panel"),
]
# retrieval hints appended to the composed query so manual passages about the likely checks surface
HINTS = {
    "boot": "power button LED behavior beep error codes diagnostics drain residual power",
    "battery_power": "battery AC power adapter charging coin-cell battery",
    "overheating": "thermal fan heat sink vents",
    "ram": "memory module beep codes diagnostics",
    "storage": "hard disk solid-state drive boot device diagnostics",
    "display": "display LCD self test no display symptoms",
}

DEVICE_Q = dict(id="device", label="Device", safety=False,
                text="Which laptop is it — Dell, HP or Lenovo — and do you know the model?",
                options=["Dell", "HP", "Lenovo"])

QUESTIONS = {
    "boot": [
        dict(id="led", label="Power LED lights up", safety=False,
             text="When you press the power button, does any power or charging light come on?",
             options=["Yes", "No", "It blinks"]),
        dict(id="beeps", label="Beeps or error codes", safety=False,
             text="Do you hear any beeps, or see an error message or code on screen?",
             options=["No", "Beeps", "Error message"]),
        dict(id="reset", label="Tried power reset / other charger", safety=False,
             text="Have you tried a different charger, or removing the battery and holding the power button for thirty seconds?",
             options=["Yes", "No"]),
    ],
    "battery_power": [
        dict(id="charge_led", label="Charging light when plugged in", safety=False,
             text="When you plug in the charger, does the charging light come on?",
             options=["Yes", "No", "Blinks"]),
        dict(id="battery_only", label="Runs on battery alone", safety=False,
             text="Does the laptop run on battery alone, and for roughly how long?",
             options=["No, dies immediately", "A short while", "Normal"]),
        dict(id="hazard", label="Battery bulging / burning smell", safety=True,
             text="Have you noticed the battery bulging, or a burning smell or heat from the charger?",
             options=["No", "Yes"]),
    ],
    "overheating": [
        dict(id="fan", label="Fan behaviour", safety=False,
             text="Is the fan spinning — and is it loud, or completely silent?",
             options=["Loud", "Silent", "Normal"]),
        dict(id="load", label="Hot when idle or under load", safety=False,
             text="Does it get hot when idle, or only under heavy load?",
             options=["Idle", "Heavy load only"]),
        dict(id="shutdown", label="Shuts down by itself / blocked vents", safety=False,
             text="Does it shut down by itself, and are the vents dusty or blocked?",
             options=["Shuts down", "Vents blocked", "Neither"]),
    ],
    "ram": [
        dict(id="symptoms", label="Beeps / blue screens / restarts", safety=False,
             text="Do you get beeps at startup, blue screens, or random restarts?",
             options=["Beeps", "Blue screens", "Random restarts"]),
        dict(id="change", label="Memory recently changed", safety=False,
             text="Have you added or replaced any memory recently?",
             options=["Yes", "No"]),
        dict(id="single", label="Boots with a single module", safety=False,
             text="Does it still start if only one memory module is installed?",
             options=["Yes", "No", "Not tried"]),
    ],
    "storage": [
        dict(id="msg", label="No boot device / drive not found message", safety=False,
             text="Do you see a 'no boot device' or 'drive not found' message?",
             options=["Yes", "No"]),
        dict(id="noise", label="Clicking or slow / freezing", safety=False,
             text="Do you hear clicking or grinding, or is it very slow or freezing?",
             options=["Clicking", "Slow or freezing", "Neither"]),
        dict(id="bios", label="Drive visible in BIOS", safety=False,
             text="Does the drive show up in the BIOS or setup screen?",
             options=["Yes", "No", "Not sure"]),
    ],
    "display": [
        dict(id="kind", label="Screen symptom", safety=False,
             text="Is the screen completely black, flickering, or showing lines?",
             options=["Black", "Flickering", "Lines"]),
        dict(id="external", label="External monitor works", safety=False,
             text="Does an external monitor work when you connect one?",
             options=["Yes", "No", "Not tried"]),
        dict(id="running", label="Laptop appears to be running", safety=False,
             text="Is the laptop actually running — do the lights come on and the fan spin?",
             options=["Yes", "No"]),
    ],
}

SKIP = re.compile(r"^(skip|don'?t know|do not know|not sure|no idea|unsure|idk)\b", re.I)
AFFIRM = re.compile(r"\b(yes|yeah|yep|yup|bulg\w*|swell\w*|swoll\w*|smell\w*|smoke|smoking|burn\w*|hot)\b", re.I)
NEGATE = re.compile(r"^\s*(no|nope|nah|not)\b", re.I)
CANCEL = re.compile(r"^(cancel|stop|never ?mind|forget it|start over)\b", re.I)


@dataclass
class DiagState:
    category: str
    symptom: str
    vendor: str | None
    queue: list = field(default_factory=list)   # remaining questions
    asked: list = field(default_factory=list)   # (question dict, reply)
    device_retry: bool = False
    safety_hit: bool = False

    @property
    def total(self):
        return len(self.asked) + len(self.queue)


_VOCAB = ["turn", "turns", "power", "start", "boot", "charge", "charging", "battery", "screen", "display",
          "laptop", "computer", "overheating", "freezing", "restart", "black", "blank", "flickering",
          "working", "work", "didnt", "doesnt", "wont", "cant", "isnt", "dead", "turning", "beep", "beeping", "blue", "shutting", "shuts", "noisy", "slow", "heating", "hot"]


_TYPOS = {"tuen": "turn", "trun": "turn", "tunr": "turn", "wont": "won't", "dosent": "doesnt", "dosnt": "doesnt", "ndidnt": "didnt", "didnt": "didn't", "doesnt": "doesn't", "cant": "can't",
          "stat": "start", "satrt": "start", "bot": "boot"}


def normalize(text: str) -> str:
    """Lower-case and repair typos ("tuen" -> "turn") so symptom detection survives voice/typing errors."""
    out = []
    for tok in re.findall(r"[a-z']+|[0-9]+|\S", text.lower()):
        if tok in _TYPOS:
            tok = _TYPOS[tok]
        elif tok.isalpha() and len(tok) >= 5 and tok not in _VOCAB:
            m = difflib.get_close_matches(tok, _VOCAB, n=1, cutoff=0.85)
            tok = m[0] if m else tok
        out.append(tok)
    return " ".join(out)


def classify(text: str) -> str | None:
    low = normalize(text)
    for cat, pat in CATEGORY_RULES:
        if re.search(pat, low):
            return cat
    return None


def is_vague_symptom(text: str) -> bool:
    t = normalize(text)
    return bool(SYMPTOM.search(t)) and not PROCEDURE.search(t) and classify(text) is not None


def is_new_request(text: str) -> bool:
    """While interviewing, a reply that is clearly a fresh procedural question breaks out of it."""
    return bool(PROCEDURE.search(text)) and len(text.split()) >= 5


def start(text: str, session_vendor: str | None) -> DiagState:
    vendor = detect_vendor(text) or session_vendor
    cat = classify(text)
    st = DiagState(category=cat, symptom=text.strip(), vendor=vendor)
    st.queue = ([] if vendor else [DEVICE_Q]) + list(QUESTIONS[cat])
    return st


def current(st: DiagState) -> dict | None:
    q = st.queue[0] if st.queue else None
    if not q:
        return None
    n = len(st.asked) + 1
    return {"text": q["text"], "options": q["options"], "step": n, "total": st.total}


def consume(st: DiagState, reply: str) -> str:
    """Record the reply to the current question. Returns 'safety', 'more' or 'done'."""
    q = st.queue[0]
    reply = reply.strip()
    if q["id"] == "device":
        v = detect_vendor(reply)
        if v:
            st.vendor = v
        elif not st.device_retry and not SKIP.search(reply):
            st.device_retry = True
            return "more"                      # re-ask once, keeping the question at the head
        st.queue.pop(0)
        st.asked.append((q, reply))
    else:
        st.queue.pop(0)
        st.asked.append((q, "Not sure" if SKIP.search(reply) else reply))
        if q.get("safety") and AFFIRM.search(reply) and not NEGATE.search(reply):
            st.safety_hit = True
            return "safety"
    return "done" if not st.queue else "more"


def observations(st: DiagState) -> str:
    return "\n".join(f"- {q['label']}: {a}" for q, a in st.asked if q["id"] != "device")


def retrieval_query(st: DiagState) -> str:
    obs = "; ".join(f"{q['label']}: {a[:60]}" for q, a in st.asked
                    if q["id"] != "device" and a.lower() != "not sure")
    parts = [st.symptom, HINTS[st.category], obs]
    return ". ".join(p for p in parts if p)[:420]


def rerank_query(st: DiagState) -> str:
    """Short natural-language form used by the cross-encoder (long keyword strings score poorly)."""
    return f"{st.symptom}, {' '.join(HINTS[st.category].split()[:4])}"


def summary(st: DiagState) -> dict:
    return {"category": st.category, "symptom": st.symptom, "vendor": st.vendor,
            "answers": [{"question": q["text"], "label": q["label"], "answer": a}
                        for q, a in st.asked]}
