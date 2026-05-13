"""
core/brain.py
-------------
AI Brain for Personal OS — powered by Groq.
Uses Llama 3.3 70B via Groq API.
Fast, free, and much more capable than local Ollama.
Falls back to local Ollama if Groq is unavailable.
"""

import os
import json
import time
import requests
from dotenv import load_dotenv
from backend.core import observability, safeguards

from pathlib import Path as _Path
load_dotenv(dotenv_path=_Path(__file__).parent.parent.parent / ".env", override=True)

GROQ_API_KEY    = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL   = "https://api.groq.com/openai/v1"
GROQ_MODEL      = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "llama3.2")
MODEL_RETRIES   = int(os.getenv("PERSONAL_OS_MODEL_RETRIES", "2"))
GROQ_TIMEOUT    = int(os.getenv("PERSONAL_OS_GROQ_TIMEOUT_SECONDS", "30"))
OLLAMA_TIMEOUT  = int(os.getenv("PERSONAL_OS_OLLAMA_TIMEOUT_SECONDS", "120"))

logger = observability.get_logger(__name__)


# ─────────────────────────────────────────────
#  Status checks
# ─────────────────────────────────────────────

def is_groq_available() -> bool:
    return bool(GROQ_API_KEY)


def is_ollama_running() -> bool:
    try:
        r = requests.get(OLLAMA_BASE_URL + "/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def is_model_available() -> bool:
    try:
        r      = requests.get(OLLAMA_BASE_URL + "/api/tags", timeout=3)
        models = [m["name"] for m in r.json().get("models", [])]
        return any(OLLAMA_MODEL in m for m in models)
    except Exception:
        return False


def get_status() -> dict:
    groq_ok   = is_groq_available()
    ollama_ok = is_ollama_running()
    model_ok  = is_model_available() if ollama_ok else False
    return {
        "groq_available":  groq_ok,
        "groq_model":      GROQ_MODEL,
        "ollama_running":  ollama_ok,
        "model_available": model_ok,
        "ollama_model":    OLLAMA_MODEL,
        "active_backend":  "groq" if groq_ok else "ollama",
        "model":           GROQ_MODEL if groq_ok else OLLAMA_MODEL,
        "ready":           groq_ok or (ollama_ok and model_ok)
    }


# ─────────────────────────────────────────────
#  Core ask — Groq first, Ollama fallback
# ─────────────────────────────────────────────

def ask(
    prompt:      str,
    system:      str   = None,
    temperature: float = 0.7,
    max_tokens:  int   = 2048
) -> str:
    """
    Send a prompt and return the full response as a string.
    Uses Groq if available, falls back to local Ollama.
    """
    prompt = safeguards.truncate_text(prompt, safeguards.MAX_PROMPT_CHARS, "prompt")
    start = time.perf_counter()
    if is_groq_available():
        backend = "groq"
        result = _ask_groq(prompt, system, temperature, max_tokens)
    elif is_ollama_running():
        backend = "ollama"
        result = _ask_ollama(prompt, system, temperature, max_tokens)
    else:
        raise ConnectionError(
            "No AI backend available.\n"
            "Option 1: Add GROQ_API_KEY to your .env file\n"
            "Option 2: Run 'ollama serve' for local AI"
        )
    observability.log_event(
        logger,
        "model.request",
        backend=backend,
        model=GROQ_MODEL if backend == "groq" else OLLAMA_MODEL,
        latency_ms=round((time.perf_counter() - start) * 1000, 2),
        prompt_chars=len(prompt),
        output_chars=len(result),
        tokens=None,
    )
    return safeguards.trim_output(result)


def ask_json(
    prompt:      str,
    system:      str   = None,
    temperature: float = 0.2
) -> dict:
    """
    Ask a question and expect a JSON object back.
    Used by the router and schema engine.
    """
    json_system = (system or "") + (
        "\n\nCRITICAL: Respond with ONLY a valid JSON object. "
        "No explanation. No markdown. No backticks. Raw JSON only."
    )

    try:
        raw = ask(prompt, system=json_system, temperature=temperature)
    except Exception as e:
        raise RuntimeError("Brain request failed: " + str(e))

    # Clean up model formatting
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw   = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    # Fix truncated JSON
    open_braces    = raw.count("{")
    close_braces   = raw.count("}")
    open_brackets  = raw.count("[")
    close_brackets = raw.count("]")
    if open_brackets > close_brackets:
        raw += "]" * (open_brackets - close_brackets)
    if open_braces > close_braces:
        raw += "}" * (open_braces - close_braces)

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(
            "Model did not return valid JSON.\n"
            "Error: " + str(e) + "\n"
            "Raw: " + raw[:300]
        )


def ask_stream(
    prompt:      str,
    system:      str   = None,
    temperature: float = 0.7
):
    """
    Stream response token by token.
    Use in Streamlit UI for live typing effect.
    """
    if is_groq_available():
        yield from _stream_groq(prompt, system, temperature)
    elif is_ollama_running():
        yield from _stream_ollama(prompt, system, temperature)
    else:
        raise ConnectionError("No AI backend available.")


def ask_with_history(
    messages:    list,
    system:      str   = None,
    temperature: float = 0.7
) -> str:
    """
    Send conversation history and get a response.
    Used for multi-turn chat with memory.
    """
    messages = [
        {**message, "content": safeguards.truncate_text(str(message.get("content", "")), safeguards.MAX_PROMPT_CHARS, "message")}
        for message in messages
    ]
    if is_groq_available():
        return _chat_groq(messages, system, temperature)
    elif is_ollama_running():
        return _chat_ollama(messages, system, temperature)
    else:
        raise ConnectionError("No AI backend available.")


# ─────────────────────────────────────────────
#  Groq implementation
# ─────────────────────────────────────────────

def _ask_groq(prompt, system, temperature, max_tokens) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    headers = {
        "Authorization": "Bearer " + GROQ_API_KEY,
        "Content-Type":  "application/json"
    }
    payload = {
        "model":       GROQ_MODEL,
        "messages":    messages,
        "temperature": temperature,
        "max_tokens":  max_tokens,
        "stream":      False
    }

    def request():
        r = requests.post(
            GROQ_BASE_URL + "/chat/completions",
            headers=headers,
            json=payload,
            timeout=GROQ_TIMEOUT
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

    try:
        return _with_retries(request, "groq")
    except requests.exceptions.Timeout:
        raise RuntimeError("Groq timed out. Try again.")
    except requests.exceptions.HTTPError as e:
        raise RuntimeError("Groq API error: " + str(e))
    except Exception as e:
        raise RuntimeError("Groq request failed: " + str(e))


def _chat_groq(messages, system, temperature) -> str:
    full_messages = []
    if system:
        full_messages.append({"role": "system", "content": system})
    full_messages.extend(messages)

    headers = {
        "Authorization": "Bearer " + GROQ_API_KEY,
        "Content-Type":  "application/json"
    }
    payload = {
        "model":       GROQ_MODEL,
        "messages":    full_messages,
        "temperature": temperature,
        "max_tokens":  2048,
        "stream":      False
    }

    def request():
        r = requests.post(
            GROQ_BASE_URL + "/chat/completions",
            headers=headers,
            json=payload,
            timeout=GROQ_TIMEOUT
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

    try:
        return _with_retries(request, "groq_chat")
    except Exception as e:
        raise RuntimeError("Groq chat failed: " + str(e))


def _stream_groq(prompt, system, temperature):
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    headers = {
        "Authorization": "Bearer " + GROQ_API_KEY,
        "Content-Type":  "application/json"
    }
    payload = {
        "model":       GROQ_MODEL,
        "messages":    messages,
        "temperature": temperature,
        "max_tokens":  2048,
        "stream":      True
    }

    with requests.post(
        GROQ_BASE_URL + "/chat/completions",
        headers=headers,
        json=payload,
        stream=True,
        timeout=GROQ_TIMEOUT
    ) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if line:
                line = line.decode("utf-8")
                if line.startswith("data: "):
                    line = line[6:]
                if line == "[DONE]":
                    break
                try:
                    chunk   = json.loads(line)
                    content = chunk["choices"][0]["delta"].get("content", "")
                    if content:
                        yield content
                except Exception:
                    continue


# ─────────────────────────────────────────────
#  Ollama fallback
# ─────────────────────────────────────────────

def _ask_ollama(prompt, system, temperature, max_tokens) -> str:
    payload = {
        "model":   OLLAMA_MODEL,
        "prompt":  prompt,
        "stream":  False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens
        }
    }
    if system:
        payload["system"] = system

    def request():
        r = requests.post(
            OLLAMA_BASE_URL + "/api/generate",
            json=payload,
            timeout=OLLAMA_TIMEOUT
        )
        r.raise_for_status()
        return r.json().get("response", "").strip()

    try:
        return _with_retries(request, "ollama")
    except requests.exceptions.Timeout:
        raise RuntimeError("Ollama timed out. Try a shorter prompt.")
    except Exception as e:
        raise RuntimeError("Ollama error: " + str(e))


def _chat_ollama(messages, system, temperature) -> str:
    payload = {
        "model":    OLLAMA_MODEL,
        "messages": messages,
        "stream":   False,
        "options":  {"temperature": temperature}
    }
    if system:
        payload["system"] = system

    def request():
        r = requests.post(
            OLLAMA_BASE_URL + "/api/chat",
            json=payload,
            timeout=OLLAMA_TIMEOUT
        )
        r.raise_for_status()
        return r.json()["message"]["content"].strip()

    try:
        return _with_retries(request, "ollama_chat")
    except Exception as e:
        raise RuntimeError("Ollama chat error: " + str(e))


def _stream_ollama(prompt, system, temperature):
    payload = {
        "model":   OLLAMA_MODEL,
        "prompt":  prompt,
        "stream":  True,
        "options": {"temperature": temperature}
    }
    if system:
        payload["system"] = system

    with requests.post(
        OLLAMA_BASE_URL + "/api/generate",
        json=payload,
        stream=True,
        timeout=OLLAMA_TIMEOUT
    ) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if line:
                chunk = json.loads(line)
                token = chunk.get("response", "")
                if token:
                    yield token
                if chunk.get("done"):
                    break


def _with_retries(fn, backend: str):
    last_error = None
    for attempt in range(MODEL_RETRIES + 1):
        try:
            return fn()
        except requests.exceptions.RequestException as exc:
            last_error = exc
            if attempt >= MODEL_RETRIES:
                break
            delay = 0.25 * (2 ** attempt)
            observability.log_event(
                logger,
                "model.retry",
                backend=backend,
                attempt=attempt + 1,
                delay_seconds=delay,
                reason=str(exc),
            )
            time.sleep(delay)
    raise last_error


# ─────────────────────────────────────────────
#  Test
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("Checking brain status...\n")
    status = get_status()
    print("  Active backend : " + status["active_backend"])
    print("  Model          : " + status["model"])
    print("  Groq available : " + str(status["groq_available"]))
    print("  Ollama running : " + str(status["ollama_running"]))
    print("  Ready          : " + str(status["ready"]))

    if status["ready"]:
        print("\nTest 1: Simple question")
        print("-" * 40)
        r = ask("What is the capital of Japan? One sentence.")
        print("  " + r)

        print("\nTest 2: Math")
        print("-" * 40)
        r2 = ask("What is the derivative of e^(x^2)? Show steps briefly.")
        print("  " + r2)

        print("\nTest 3: JSON output")
        print("-" * 40)
        r3 = ask_json(
            "Return a JSON object with fields: name, capital, population "
            "for Japan."
        )
        print("  " + str(r3))

        print("\nTest 4: Conversation memory")
        print("-" * 40)
        r4 = ask_with_history([
            {"role": "user",      "content": "My name is Alex."},
            {"role": "assistant", "content": "Nice to meet you Alex!"},
            {"role": "user",      "content": "What is my name?"}
        ])
        print("  " + r4)
    else:
        print("\nBrain not ready.")
        print("Add GROQ_API_KEY to your .env file.")
