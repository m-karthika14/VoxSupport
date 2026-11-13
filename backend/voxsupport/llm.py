"""LLM client (Groq or Ollama) with timeout, retries and clear errors."""
import time

import requests

from . import config


class LLMError(RuntimeError):
    pass


_avail = {"t": 0.0, "v": False}


def available() -> bool:
    """Cheap, cached check that the configured provider can be used."""
    if time.time() - _avail["t"] < 30:
        return _avail["v"]
    try:
        if config.LLM_PROVIDER == "groq":
            ok = bool(config.GROQ_API_KEY)
        else:
            r = requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=2)
            names = [m["name"] for m in r.json().get("models", [])]
            ok = any(n.split(":")[0] == config.LLM_MODEL.split(":")[0] for n in names)
    except Exception:
        ok = False
    _avail.update(t=time.time(), v=ok)
    return ok


def chat(messages: list[dict], temperature: float = 0.1, max_tokens: int = 900,
         retries: int = 2) -> str:
    groq = config.LLM_PROVIDER == "groq"
    url = f"{config.GROQ_URL}/chat/completions" if groq else f"{config.OLLAMA_URL}/api/chat"
    headers = {"Authorization": f"Bearer {config.GROQ_API_KEY}"} if groq else {}
    payload = ({"model": config.LLM_MODEL, "messages": messages, "temperature": temperature,
                "max_tokens": max_tokens, **({"reasoning_effort": "low"} if "gpt-oss" in config.LLM_MODEL else {})} if groq else
               {"model": config.LLM_MODEL, "messages": messages, "stream": False,
                "options": {"temperature": temperature, "num_predict": max_tokens}})
    last = None
    for attempt in range(retries + 1):
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=config.LLM_TIMEOUT)
            if r.status_code == 429:                      # rate limited: back off, retry
                time.sleep(float(r.headers.get("retry-after", 2)))
                last = RuntimeError("rate limited (429)")
                continue
            r.raise_for_status()
            j = r.json()
            return (j["choices"][0]["message"]["content"] if groq else j["message"]["content"]).strip()
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise LLMError(f"LLM call failed after {retries + 1} attempts: {last}")
