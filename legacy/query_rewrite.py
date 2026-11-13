# src/query_rewrite.py
import re
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser


@dataclass
class ConversationState:
    # (role, text) where role in {"user", "assistant"}
    history: List[Tuple[str, str]] = field(default_factory=list)

    # Last assistant answer’s enumerated items, e.g. ["Check power", "Reseat RAM"]
    last_list_items: List[str] = field(default_factory=list)

    def add_turn(self, role: str, text: str):
        self.history.append((role, text))

    def set_last_list_items_from_assistant(self, assistant_text: str):
        self.last_list_items = extract_numbered_items(assistant_text)


def extract_numbered_items(text: str) -> List[str]:
    """
    Extract items from patterns like:
      1) ...
      2. ...
      3 - ...
    """
    items = []
    for m in re.finditer(r"(?m)^\s*(\d+)\s*[\)\.\-:]\s+(.*)$", text):
        item = m.group(2).strip()
        if item:
            items.append(item)
    return items


def resolve_ordinal_reference(user_text: str, state: ConversationState) -> Optional[str]:
    """
    If user says "second one"/"2nd one"/"step 2", expand it using last_list_items.
    Returns rewritten text or None if no change.
    """
    if not state.last_list_items:
        return None

    t = user_text.lower()

    ordinal_map = {
        "first": 1, "1st": 1, "one": 1,
        "second": 2, "2nd": 2, "two": 2,
        "third": 3, "3rd": 3, "three": 3,
        "fourth": 4, "4th": 4, "four": 4,
    }

    hit = None
    for k, idx in ordinal_map.items():
        if re.search(rf"\b{k}\b", t) and ("one" in t or "option" in t or "step" in t or "item" in t or k in ["1st","2nd","3rd","4th"]):
            hit = idx
            break

    if not hit:
        # also handle "step 2" / "option 2"
        m = re.search(r"\b(step|option|item)\s*(\d+)\b", t)
        if m:
            hit = int(m.group(2))

    if not hit:
        return None

    if hit <= 0 or hit > len(state.last_list_items):
        return None

    chosen = state.last_list_items[hit - 1]
    return f"{user_text.strip()} (Refers to: '{chosen}')"


def should_llm_rewrite(user_text: str) -> bool:
    """Only rewrite for CLEAR pronouns/ordinals. Pass everything else through."""
    t = user_text.lower().strip()
    
    # Pronouns + strong context signals only
    patterns = [
        r"\b(?:the|that|this|those|these)\s+(?:second|first|third|one|step|option|item)\b",
        r"\b(?:it|that|this)\s+(?:one|step|option|thing)\b",
        r"\b(?:do|try)\s+(?:that|this)\b",
    ]
    
    return any(re.search(p, t) for p in patterns)



def rewrite_with_llm(user_text: str, state: ConversationState, llm, llm_lock=None) -> str:
    """
    LLM rewrite: make last user utterance standalone using conversation history.
    Output must be a single sentence question/instruction, no preamble.
    """
    # Keep history short to reduce latency.
    history_tail = state.history[-4:]  # SHORTEN history to avoid hallucination

    history_str = "\n".join([f"{r.upper()}: {txt}" for r, txt in history_tail])
    #items_str = "\n".join([f"{i+1}) {x}" for i, x in enumerate(state.last_list_items)]) if state.last_list_items else "(none)"

    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "Rewrite ONLY IF needed: resolve pronouns using LAST assistant message. "
         "If standalone, return unchanged. "
         "Output ONLY the query (no quotes)."),
        ("human",
         "LAST ASSISTANT:\n{history}\n\n"
         "USER: {msg}\n\n"
         "QUERY: ")
    ])

    chain = prompt | llm | StrOutputParser()

    payload = {"history": history_str, "items": items_str, "msg": user_text}

    if llm_lock:
        with llm_lock:
            return chain.invoke(payload).strip()
    return chain.invoke(payload).strip()


def rewrite_query(user_text: str, state: ConversationState, llm, llm_lock=None) -> str:
    """
    Full rewrite pipeline:
      1) ordinal/coref shortcut (fast, deterministic)
      2) if still referential, do LLM rewrite
    """
    # 1) deterministic ordinal resolution
    ordinal = resolve_ordinal_reference(user_text, state)
    if ordinal:
        return ordinal

    # 2) LLM rewrite only if needed
    if should_llm_rewrite(user_text):
        return rewrite_with_llm(user_text, state, llm, llm_lock=llm_lock)

    return user_text
