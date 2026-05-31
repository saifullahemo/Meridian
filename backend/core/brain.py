"""
backend/core/brain.py
----------------------
AI Brain for Personal OS.


Implements:
- ask(): single prompt
- ask_json(): JSON-only response
- ask_stream(): token streaming
- ask_with_history(): chat with message history

Environment:
- GROQ_API_KEY for Groq
- OLLAMA_BASE_URL / OLLAMA_MODEL for local Ollama fallback

Groq uses the OpenAI-compatible Chat Completions API.
"""

import os
import json
import time
import requests
from dotenv import load_dotenv
from backend.core import observability, safeguards

from pathlib import Path as _Path

load_dotenv(dotenv_path=_Path(__file__).parent.parent.parent / ".env", override=True)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")
MODEL_BACKEND = os.getenv("PERSONAL_OS_MODEL_BACKEND", "auto").lower()


MODEL_RETRIES = int(os.getenv("PERSONAL_OS_MODEL_RETRIES", "2"))
GROQ_TIMEOUT = int(os.getenv("PERSONAL_OS_GROQ_TIMEOUT_SECONDS", "30"))


logger = observability.get_logger(__name__)


def is_groq_available() -> bool:
    return bool(GROQ_API_KEY)


def is_ollama_available() -> bool:
    if MODEL_BACKEND == "groq":
        return False
    try:
        response = requests.get(OLLAMA_BASE_URL.rstrip("/") + "/api/tags", timeout=2)
        return response.ok
    except Exception:
        return False




def get_status() -> dict:
    groq_ok = is_groq_available()
    ollama_ok = is_ollama_available()
    backends = _available_backends()
    active = backends[0] if backends else ""
    return {
        "groq_available": groq_ok,
        "groq_model": GROQ_MODEL,
        "ollama_available": ollama_ok,
        "ollama_model": OLLAMA_MODEL,
        "configured_backend": MODEL_BACKEND,

        "active_backend": active,
        "model": GROQ_MODEL if active == "groq" else OLLAMA_MODEL if active == "ollama" else "",

        "ready": bool(active),
    }




def ask(
    prompt: str,
    system: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 2048,
) -> str:

    """Send a prompt and return the full response as a string."""

    prompt = safeguards.truncate_text(prompt, safeguards.MAX_PROMPT_CHARS, "prompt")
    start = time.perf_counter()
    errors = []
    result = ""
    backend = ""
    for candidate in _available_backends():
        try:
            backend = candidate
            if candidate == "groq":
                result = _ask_groq(prompt=prompt, system=system, temperature=temperature, max_tokens=max_tokens)
            elif candidate == "ollama":
                result = _ask_ollama(prompt=prompt, system=system, temperature=temperature, max_tokens=max_tokens)
            break
        except Exception as exc:
            errors.append(candidate + ": " + str(exc))
            observability.log_event(logger, "model.fallback", backend=candidate, reason=str(exc))
            result = ""
    if not result:
        raise ConnectionError("No model backend available. " + " | ".join(errors))


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
    prompt: str,
    system: str | None = None,
    temperature: float = 0.2,
) -> dict:
    """Ask a question and expect a JSON object back."""

    json_system = (system or "") + (
        "\n\nCRITICAL: Respond with ONLY a valid JSON object. "
        "No explanation. No markdown. No backticks. Raw JSON only."
    )

    raw = ask(prompt, system=json_system, temperature=temperature)

    # Clean up model formatting
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    # Fix truncated JSON (best effort)
    open_braces = raw.count("{")
    close_braces = raw.count("}")
    open_brackets = raw.count("[")
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
    prompt: str,
    system: str | None = None,
    temperature: float = 0.7,
):
    """Stream response token by token."""

    prompt = safeguards.truncate_text(prompt, safeguards.MAX_PROMPT_CHARS, "prompt")
    errors = []
    for candidate in _available_backends():
        try:
            if candidate == "groq":
                yield from _stream_groq(prompt=prompt, system=system, temperature=temperature)
            elif candidate == "ollama":
                yield from _stream_ollama(prompt=prompt, system=system, temperature=temperature)
            return
        except Exception as exc:
            errors.append(candidate + ": " + str(exc))
            observability.log_event(logger, "model.stream_fallback", backend=candidate, reason=str(exc))
    raise ConnectionError("No streaming model backend available. " + " | ".join(errors))




def ask_with_history(
    messages: list,
    system: str | None = None,
    temperature: float = 0.7,
) -> str:
    """Send conversation history and get a response."""

    messages = [
        {
            **message,
            "content": safeguards.truncate_text(
                str(message.get("content", "")), safeguards.MAX_PROMPT_CHARS, "message"
            ),
        }
        for message in messages
    ]

    errors = []
    for candidate in _available_backends():
        try:
            if candidate == "groq":
                return _chat_groq(messages=messages, system=system, temperature=temperature)
            if candidate == "ollama":
                return _chat_ollama(messages=messages, system=system, temperature=temperature)
        except Exception as exc:
            errors.append(candidate + ": " + str(exc))
            observability.log_event(logger, "model.history_fallback", backend=candidate, reason=str(exc))
    raise ConnectionError("No model backend available. " + " | ".join(errors))


# ------------------------------
# Backend selection
# ------------------------------

def _available_backends() -> list[str]:
    if MODEL_BACKEND == "groq":
        return ["groq"] if is_groq_available() else []
    if MODEL_BACKEND == "ollama":
        return ["ollama"] if is_ollama_available() else []
    backends = []
    if is_groq_available():
        backends.append("groq")
    if is_ollama_available():
        backends.append("ollama")
    return backends


# ------------------------------
# Groq implementation
# ------------------------------

def _build_messages(prompt: str, system: str | None):
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return messages


def _headers() -> dict:
    return {
        "Authorization": "Bearer " + GROQ_API_KEY,
        "Content-Type": "application/json",
    }



def _ask_groq(prompt: str, system: str | None, temperature: float, max_tokens: int) -> str:
    messages = _build_messages(prompt, system)

    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }

    def request():
        r = requests.post(
            GROQ_BASE_URL + "/chat/completions",
            headers=_headers(),
            json=payload,
            timeout=GROQ_TIMEOUT,
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


def _chat_groq(messages: list, system: str | None, temperature: float) -> str:
    full_messages = []
    if system:
        full_messages.append({"role": "system", "content": system})
    full_messages.extend(messages)

    payload = {
        "model": GROQ_MODEL,
        "messages": full_messages,
        "temperature": temperature,
        "max_tokens": 2048,
        "stream": False,
    }

    def request():
        r = requests.post(
            GROQ_BASE_URL + "/chat/completions",
            headers=_headers(),
            json=payload,
            timeout=GROQ_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

    try:
        return _with_retries(request, "groq_chat")
    except Exception as e:
        raise RuntimeError("Groq chat failed: " + str(e))


def _stream_groq(prompt: str, system: str | None, temperature: float):

    messages = _build_messages(prompt, system)

    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 2048,
        "stream": True,
    }

    with requests.post(
        GROQ_BASE_URL + "/chat/completions",
        headers=_headers(),
        json=payload,
        stream=True,
        timeout=GROQ_TIMEOUT,
    ) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            decoded = line.decode("utf-8")
            if decoded.startswith("data: "):
                decoded = decoded[6:]
            if decoded == "[DONE]":
                break
            try:
                chunk = json.loads(decoded)
                content = chunk["choices"][0]["delta"].get("content", "")
                if content:
                    yield content
            except Exception:
                continue


# ------------------------------
# Ollama implementation
# ------------------------------

def _ollama_url(path: str) -> str:
    return OLLAMA_BASE_URL.rstrip("/") + path


def _ollama_messages(prompt: str, system: str | None) -> list[dict]:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return messages


def _ask_ollama(prompt: str, system: str | None, temperature: float, max_tokens: int) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": _ollama_messages(prompt, system),
        "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }

    def request():
        response = requests.post(_ollama_url("/api/chat"), json=payload, timeout=GROQ_TIMEOUT)
        response.raise_for_status()
        return response.json().get("message", {}).get("content", "").strip()

    return _with_retries(request, "ollama")


def _chat_ollama(messages: list, system: str | None, temperature: float) -> str:
    full_messages = []
    if system:
        full_messages.append({"role": "system", "content": system})
    full_messages.extend(messages)
    payload = {
        "model": OLLAMA_MODEL,
        "messages": full_messages,
        "stream": False,
        "options": {"temperature": temperature},
    }

    def request():
        response = requests.post(_ollama_url("/api/chat"), json=payload, timeout=GROQ_TIMEOUT)
        response.raise_for_status()
        return response.json().get("message", {}).get("content", "").strip()

    return _with_retries(request, "ollama_chat")


def _stream_ollama(prompt: str, system: str | None, temperature: float):
    payload = {
        "model": OLLAMA_MODEL,
        "messages": _ollama_messages(prompt, system),
        "stream": True,
        "options": {"temperature": temperature},
    }
    with requests.post(_ollama_url("/api/chat"), json=payload, stream=True, timeout=GROQ_TIMEOUT) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line:
                continue
            try:
                chunk = json.loads(line.decode("utf-8"))
                content = chunk.get("message", {}).get("content", "")
                if content:
                    yield content
                if chunk.get("done"):
                    break
            except Exception:
                continue


def _with_retries(fn, backend: str):
    last_error = None
    for attempt in range(MODEL_RETRIES + 1):
        try:
            return fn()
        except requests.exceptions.RequestException as exc:
            last_error = exc
            if attempt >= MODEL_RETRIES:
                break
            delay = 0.25 * (2**attempt)
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


if __name__ == "__main__":
    print("Checking brain status...\n")
    status = get_status()
    print("  Active backend : " + status["active_backend"])
    print("  Model          : " + status["model"])
    print("  Groq available : " + str(status["groq_available"]))

    print("  Ready          : " + str(status["ready"]))

    if status["ready"]:
        print("\nTest 1: Simple question")
        print("-" * 40)
        r = ask("What is the capital of Japan? One sentence.")
        print("  " + r)

        print("\nTest 2: JSON output")
        print("-" * 40)
        r3 = ask_json(
            "Return a JSON object with fields: name, capital, population for Japan."
        )
        print("  " + str(r3))
    else:
        print("\nBrain not ready.")
        print("Add GROK_API_KEY to your .env file.")
