"""Optional language-model providers, over plain ``urllib``.

A model may *assist* (semantic skill matching, drafting); deterministic code stays the source
of truth. ``semantic_skill_match`` can only raise a skills score, by at most ``MAX_BOOST``,
and what it adds is recorded as ``estimate`` evidence.

Providers: ``anthropic`` (Messages API), ``openai`` (Chat Completions), ``ollama`` (local
``/api/chat``) and ``openai_compatible`` (any endpoint at ``llm.base_url`` that speaks the
Chat Completions format). ``get(cfg)`` returns ``None`` when ``llm.provider`` is ``none``.
With ``llm.anonymize`` (the default) prompts are masked and replies unmasked, so the
candidate's name, e-mail, phone and links never reach the model.
"""
from __future__ import annotations

import json
import os
import re
from typing import Protocol, runtime_checkable
from urllib import error, request

from ..models import Evidence
from . import anonymize

MAX_BOOST = 0.15
MIN_CONFIDENCE = 0.7
DEFAULT_MODELS = {"anthropic": "claude-sonnet-5-5", "openai": "gpt-4o-mini", "ollama": "llama3.1",
                  "openai_compatible": ""}
DEFAULT_KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
OPENAI_BASE = "https://api.openai.com"
OLLAMA_BASE = "http://localhost:11434"


class LLMError(RuntimeError):
    pass


@runtime_checkable
class Provider(Protocol):
    name: str

    def complete(self, system: str, user: str, max_tokens: int = 800) -> str: ...


def _post(url: str, body: dict, headers: dict[str, str], timeout: float = 60.0) -> dict:
    req = request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                          headers={"content-type": "application/json", **headers})
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        raise LLMError(f"{url}: HTTP {e.code} {detail}".strip()) from e
    except (error.URLError, OSError) as e:
        raise LLMError(f"{url}: {getattr(e, 'reason', e)}") from e
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError as e:
        raise LLMError(f"{url}: reply is not JSON") from e


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str, api_key: str, url: str = ANTHROPIC_URL, timeout: float = 60.0):
        self.model, self.api_key, self.url, self.timeout = model, api_key, url, timeout

    def complete(self, system: str, user: str, max_tokens: int = 800) -> str:
        body = {"model": self.model, "max_tokens": max_tokens, "system": system,
                "messages": [{"role": "user", "content": user}]}
        data = _post(self.url, body, {"x-api-key": self.api_key, "anthropic-version": ANTHROPIC_VERSION},
                     self.timeout)
        parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        if not parts:
            raise LLMError("anthropic: no text in reply")
        return "".join(parts)


class OpenAIProvider:
    name = "openai"

    def __init__(self, model: str, api_key: str = "", base_url: str = OPENAI_BASE, timeout: float = 60.0):
        self.model, self.api_key, self.timeout = model, api_key, timeout
        base = (base_url or OPENAI_BASE).rstrip("/")
        self.url = base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions")

    def complete(self, system: str, user: str, max_tokens: int = 800) -> str:
        body = {"model": self.model, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        headers = {"authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        data = _post(self.url, body, headers, self.timeout)
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"{self.name}: unexpected reply shape") from e


class OpenAICompatibleProvider(OpenAIProvider):
    name = "openai_compatible"


class OllamaProvider:
    name = "ollama"

    def __init__(self, model: str, base_url: str = OLLAMA_BASE, timeout: float = 120.0):
        self.model, self.timeout = model, timeout
        self.url = (base_url or OLLAMA_BASE).rstrip("/") + "/api/chat"

    def complete(self, system: str, user: str, max_tokens: int = 800) -> str:
        body = {"model": self.model, "stream": False, "options": {"num_predict": max_tokens},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        data = _post(self.url, body, {}, self.timeout)
        try:
            return data["message"]["content"]
        except (KeyError, TypeError) as e:
            raise LLMError("ollama: unexpected reply shape") from e


class MaskedProvider:
    """Masks personal data in both prompts and unmasks the reply."""

    _SEP = "\n␞␞␞\n"

    def __init__(self, inner: Provider, candidate):
        self.inner, self.candidate = inner, candidate
        self.name = getattr(inner, "name", "provider")
        self.last_mapping: dict[str, str] = {}

    def complete(self, system: str, user: str, max_tokens: int = 800) -> str:
        masked, mapping = anonymize.mask(f"{system}{self._SEP}{user}", self.candidate)
        s, _, u = masked.partition(self._SEP)
        self.last_mapping = mapping
        return anonymize.unmask(self.inner.complete(s, u, max_tokens), mapping)


def get(cfg) -> Provider | None:
    """The configured provider, masked when ``llm.anonymize`` is on; None for provider ``none``."""
    llm = cfg.llm
    kind = llm.provider
    if kind in ("", "none", None):
        return None
    model = llm.model or DEFAULT_MODELS.get(kind, "")
    key_env = llm.api_key_env or DEFAULT_KEY_ENV.get(kind, "")
    key = os.environ.get(key_env, "") if key_env else ""
    if kind == "anthropic":
        if not key:
            raise LLMError(f"llm.provider is anthropic but ${key_env} is not set")
        p: Provider = AnthropicProvider(model, key, url=(llm.base_url.rstrip("/") + "/v1/messages")
                                        if llm.base_url else ANTHROPIC_URL)
    elif kind == "openai":
        if not key:
            raise LLMError(f"llm.provider is openai but ${key_env} is not set")
        p = OpenAIProvider(model, key, llm.base_url or OPENAI_BASE)
    elif kind == "ollama":
        p = OllamaProvider(model, llm.base_url or OLLAMA_BASE)
    elif kind == "openai_compatible":
        if not llm.base_url:
            raise LLMError("llm.provider is openai_compatible but llm.base_url is empty")
        if not model:
            raise LLMError("llm.provider is openai_compatible but llm.model is empty")
        p = OpenAICompatibleProvider(model, key, llm.base_url)
    else:
        raise LLMError(f"unknown llm.provider {kind!r}")
    return MaskedProvider(p, cfg.candidate) if llm.anonymize else p


# ---------------------------------------------------------------- semantic skill matching

_SYSTEM = ("You compare job requirements with a candidate's evidenced skills. A skill covers a "
           "requirement only when someone holding that skill clearly meets it. Reply with JSON only.")


def _fold(s: str) -> str:
    return re.sub(r"\s+", " ", anonymize._fold(s)).strip()


def _parse_json(reply: str):
    reply = (reply or "").strip()
    reply = re.sub(r"^```(?:json)?|```$", "", reply, flags=re.M).strip()
    for opener, closer in (("[", "]"), ("{", "}")):
        i, j = reply.find(opener), reply.rfind(closer)
        if i != -1 and j > i:
            try:
                return json.loads(reply[i:j + 1])
            except ValueError:
                continue
    return None


def semantic_skill_match(provider: Provider | None, requirements, candidate_skills) -> dict:
    """Ask the model which *unmet* requirements a candidate skill covers.

    ``requirements``: strings or objects with ``.text``. Returns
    ``{"matches": [(requirement, skill, confidence)], "boost": float <= MAX_BOOST,
    "evidence": [Evidence(basis="estimate")], "error": str}``. Only skills from
    ``candidate_skills`` and requirements from ``requirements`` are accepted, at confidence
    >= MIN_CONFIDENCE; anything else in the reply is ignored.
    """
    reqs = [getattr(r, "text", r) for r in requirements or []]
    reqs = [str(r).strip() for r in reqs if str(r).strip()]
    skills = [str(s).strip() for s in candidate_skills or [] if str(s).strip()]
    out = {"matches": [], "boost": 0.0, "evidence": [], "error": ""}
    if provider is None or not reqs or not skills:
        return out
    user = ("Requirements:\n" + "\n".join(f"- {r}" for r in reqs) + "\n\nCandidate skills:\n" +
            "\n".join(f"- {s}" for s in skills) +
            '\n\nReturn a JSON array of {"requirement": <copied exactly>, "skill": <copied exactly>, '
            '"confidence": <0..1>} for requirements a listed skill covers. Return [] if none.')
    try:
        data = _parse_json(provider.complete(_SYSTEM, user, max_tokens=800))
    except Exception as e:                                # a model failure never breaks scoring
        out["error"] = str(e)[:200]
        return out
    if isinstance(data, dict):
        data = data.get("matches", [])
    if not isinstance(data, list):
        out["error"] = "reply was not a JSON list"
        return out
    req_by = {_fold(r): r for r in reqs}
    skill_by = {_fold(s): s for s in skills}
    got: dict[str, tuple[str, str, float]] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        r = req_by.get(_fold(str(item.get("requirement", ""))))
        s = skill_by.get(_fold(str(item.get("skill", ""))))
        try:
            c = float(item.get("confidence", 0))
        except (TypeError, ValueError):
            continue
        if r and s and c >= MIN_CONFIDENCE and (r not in got or got[r][2] < c):
            got[r] = (r, s, min(c, 1.0))
    out["matches"] = list(got.values())
    out["boost"] = round(MAX_BOOST * len(got) / len(reqs), 4)
    out["evidence"] = [Evidence(f"model suggests '{s}' covers '{r[:80]}' (confidence {c:.2f})", "estimate")
                       for r, s, c in out["matches"]]
    return out
