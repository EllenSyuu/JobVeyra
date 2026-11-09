"""Short notifications: Telegram and a generic incoming webhook (Slack, Discord, Teams-style).

Both are no-ops without settings and never raise on network failure. They return a
``Result`` that is truthy only when the message was delivered and carries ``error`` otherwise
(``Result == False`` holds for a failed or skipped send).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

TELEGRAM_API = "https://api.telegram.org"
TELEGRAM_LIMIT = 4096
TIMEOUT = 15


class Result:
    __slots__ = ("ok", "error")

    def __init__(self, ok: bool, error: str = ""):
        self.ok, self.error = ok, error

    def __bool__(self) -> bool:
        return self.ok

    def __eq__(self, other) -> bool:
        if isinstance(other, bool):
            return self.ok is other
        if isinstance(other, Result):
            return (self.ok, self.error) == (other.ok, other.error)
        return NotImplemented

    __hash__ = None

    def __repr__(self) -> str:
        return f"Result(ok={self.ok}{', error=' + repr(self.error) if self.error else ''})"


def _post(url: str, body: dict, check_ok: bool = False) -> Result:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "jobveyra"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            status = getattr(r, "status", None) or r.getcode()
            raw = r.read() or b""
    except urllib.error.HTTPError as e:
        return Result(False, f"HTTP {e.code}")
    except Exception as e:  # noqa: BLE001 - a notification must never break a run
        return Result(False, f"{type(e).__name__}: {e}")
    if not 200 <= int(status or 0) < 300:
        return Result(False, f"HTTP {status}")
    if check_ok:                                   # Telegram answers {"ok": true|false, ...}
        try:
            if json.loads(raw.decode("utf-8") or "{}").get("ok") is False:
                return Result(False, "Telegram answered ok=false")
        except (ValueError, AttributeError):
            pass
    return Result(True)


def telegram(text: str, env=os.environ) -> Result:
    token, chat = env.get("TELEGRAM_BOT_TOKEN"), env.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return Result(False, "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are not set")
    if len(text) > TELEGRAM_LIMIT:
        text = text[: TELEGRAM_LIMIT - 3] + "..."
    res = _post(f"{TELEGRAM_API}/bot{token}/sendMessage",
                {"chat_id": chat, "text": text, "disable_web_page_preview": True}, check_ok=True)
    if not res and token in res.error:
        res.error = res.error.replace(token, "***")     # never echo the token
    return res


def webhook(text: str, url: str | None = None, env=os.environ, var: str = "JOBVEYRA_WEBHOOK") -> Result:
    """POST ``{"text": text, "content": text}``: Slack reads ``text``, Discord reads ``content``.
    ``url`` defaults to the environment variable ``var`` (``notify.webhook_env`` in the config)."""
    url = url or env.get(var) or ""
    if not url:
        return Result(False, f"no webhook URL ({var} is not set)")
    if not url.lower().startswith(("https://", "http://")):
        return Result(False, "webhook URL must start with https://")
    return _post(url, {"text": text, "content": text[:2000]})


def summary(digest: dict) -> str:
    """A few lines for a chat message, built from a digest."""
    from .newsletter import coming_lines, needs_lines, subject
    lines = [subject(digest)]
    needs, soon = needs_lines(digest), coming_lines(digest)
    if needs:
        lines += ["", "Needs attention:"] + [f"- {x}" for x in needs[:5]]
    if soon:
        lines += ["", "Coming up:"] + [f"- {x}" for x in soon[:5]]
    return "\n".join(lines)
