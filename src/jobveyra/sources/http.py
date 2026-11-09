"""Polite HTTP for sources: one user agent, timeouts, retries with backoff, a per-host minimum
interval between requests, robots.txt checks, and an offline fixture mode for tests.

Fixture mode
  ``Http(fixtures=Path)`` never touches the network. Every request is answered from a file in
  that directory, named by :func:`fixture_name`:

  * take ``host + path`` and, when present, ``"?" + query`` of the URL, lower-cased;
  * replace every run of characters outside ``[a-z0-9.-]`` with ``_`` and strip ``_`` and ``.``
    from both ends;
  * if the result is longer than 120 characters, keep the first 100 and append
    ``-<first 10 hex digits of sha1(url)>``;
  * a POST gets the prefix ``post__``.

  The lookup tries ``<name>``, then ``<name>.json``, ``.html``, ``.txt``, ``.xml``. For a POST it
  first tries ``<name>__<b>`` (``b`` = first 8 hex digits of sha1 of the JSON body with sorted keys
  and compact separators) with the same extensions, so tests can answer different bodies sent to
  one URL. A sibling ``<name>.status`` file holding an integer makes the request fail with that
  HTTP status (``head()`` returns it). A missing fixture behaves like HTTP 404.

  Example: ``https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true`` is answered by
  ``boards-api.greenhouse.io_v1_boards_acme_jobs_content_true.json``.

robots.txt
  Fetched once per scheme+host with urllib and evaluated with the RFC 9309 matcher in
  ``jobveyra.robots_check`` (its pure ``allowed`` and ``has_undecodable_rule`` functions; its
  curl-based fetcher is not used). 4xx means no policy (allowed). 5xx or a network failure means
  the policy is unknown and the request is refused, as RFC 9309 asks. Fixture mode skips robots.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlsplit

from .. import robots_check

USER_AGENT = "jobveyra/0.1 (+https://github.com/jobveyra)"
ROBOTS_AGENT = "jobveyra"
RETRY_STATUS = {429, 500, 502, 503, 504}
FIXTURE_EXTS = ("", ".json", ".html", ".txt", ".xml")


class HttpError(RuntimeError):
    """An HTTP failure. ``status`` is the HTTP status, or 0 for a network error."""

    def __init__(self, url: str, status: int, message: str = ""):
        self.url, self.status = url, status
        super().__init__(f"{message or 'HTTP ' + str(status)} for {url}")


class RobotsDisallowed(HttpError):
    def __init__(self, url: str, why: str):
        super().__init__(url, 0, f"robots.txt: {why}")


def fixture_name(url: str, method: str = "GET") -> str:
    """The fixture file stem that answers ``method url`` (see the module docstring)."""
    u = urlsplit(url)
    s = (u.netloc + u.path + ("?" + u.query if u.query else "")).lower()
    s = re.sub(r"[^a-z0-9.-]+", "_", s).strip("_.")
    if len(s) > 120:
        s = s[:100] + "-" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    return ("post__" if method.upper() == "POST" else "") + s


def body_digest(body: Any) -> str:
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]


class Http:
    def __init__(self, *, fixtures: Path | str | None = None, timeout: float = 25.0, retries: int = 3,
                 backoff: float = 1.0, min_interval: float = 1.0, respect_robots: bool = True,
                 user_agent: str = USER_AGENT, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.fixtures = Path(fixtures) if fixtures else None
        self.timeout, self.retries, self.backoff = timeout, retries, backoff
        self.min_interval, self.respect_robots, self.user_agent = min_interval, respect_robots, user_agent
        self._sleep, self._clock = sleep, clock
        self._last: dict[str, float] = {}
        self._robots: dict[str, str | None] = {}   # origin -> robots body ("" = no policy); None = unknown
        self._lock = threading.Lock()
        self.requests: list[tuple[str, str]] = []  # (method, url) actually sent or answered, for tests

    # public API ---------------------------------------------------------
    def get_json(self, url: str, *, headers: dict | None = None) -> Any:
        return _json(self.request("GET", url, headers=headers)[1], url)

    def get_text(self, url: str, *, headers: dict | None = None) -> str:
        return _decode(*self.request("GET", url, headers=headers)[1:])

    def post_json(self, url: str, body: Any, *, headers: dict | None = None) -> Any:
        return _json(self.request("POST", url, body=body, headers=headers)[1], url)

    def head(self, url: str) -> int:
        """Status of ``url`` (redirects followed); 0 when it cannot be reached. Never raises for
        an HTTP status. Servers that refuse HEAD (405/501) are asked with GET instead."""
        try:
            return self.request("HEAD", url)[0]
        except HttpError as e:
            if e.status in (405, 501):
                try:
                    return self.request("GET", url)[0]
                except HttpError as e2:
                    return e2.status
            return e.status

    # core ---------------------------------------------------------------
    def request(self, method: str, url: str, *, body: Any = None,
                headers: dict | None = None) -> tuple[int, bytes, str]:
        """Return ``(status, body bytes, content type)``; raise HttpError on a 4xx/5xx after retries."""
        method = method.upper()
        if not re.match(r"https?://[^/]+", url or "", re.I):
            raise HttpError(url, 0, "not an http(s) URL")
        self.requests.append((method, url))
        if self.fixtures is not None:
            return self._fixture(method, url, body)
        if self.respect_robots:
            self._robots_gate(url)
        data = None
        hdrs = {"User-Agent": self.user_agent, "Accept": "application/json, text/html;q=0.9, */*;q=0.5"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            hdrs["Content-Type"] = "application/json"
        hdrs.update(headers or {})
        last: HttpError | None = None
        for attempt in range(self.retries + 1):
            self._throttle(url)
            try:
                return self._open(urllib.request.Request(url, data=data, headers=hdrs, method=method))
            except urllib.error.HTTPError as e:
                last = HttpError(url, e.code)
                if e.code not in RETRY_STATUS:
                    raise last from None
                wait = _retry_after(e.headers.get("Retry-After") if e.headers else None)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                last = HttpError(url, 0, f"network error ({getattr(e, 'reason', e)})")
                wait = None
            if attempt < self.retries:
                self._sleep(wait if wait is not None else self.backoff * 2 ** attempt)
        raise last  # type: ignore[misc]

    def _open(self, req: urllib.request.Request) -> tuple[int, bytes, str]:
        """The one place that touches the network (tests replace it)."""
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return r.status, (b"" if req.get_method() == "HEAD" else r.read()), r.headers.get("Content-Type", "")

    def _throttle(self, url: str) -> None:
        host = urlsplit(url).netloc.lower()
        with self._lock:
            now = self._clock()
            wait = self._last.get(host, -1e18) + self.min_interval - now
            if wait > 0:
                self._sleep(wait)
                now += wait
            self._last[host] = now

    # robots -------------------------------------------------------------
    def allowed(self, url: str) -> tuple[bool, str]:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}".lower()
        if origin not in self._robots:
            self._robots[origin] = self._fetch_robots(origin + "/robots.txt")
        body = self._robots[origin]
        if body is None:
            return False, "could not read robots.txt"
        if robots_check.has_undecodable_rule(body):
            return False, "robots.txt has an unreadable rule"
        path = unquote(parts.path) or "/"
        if parts.query:
            path += "?" + unquote(parts.query)
        if not robots_check.allowed(body, ROBOTS_AGENT, path):
            return False, f"disallowed for {ROBOTS_AGENT}"
        return True, ""

    def _robots_gate(self, url: str) -> None:
        ok, why = self.allowed(url)
        if not ok:
            raise RobotsDisallowed(url, why)

    def _fetch_robots(self, robots_url: str) -> str | None:
        req = urllib.request.Request(robots_url, headers={"User-Agent": self.user_agent, "Accept": "text/plain"})
        for attempt in range(2):
            self._throttle(robots_url)
            try:
                _, raw, _ = self._open(req)
                return raw.decode("utf-8", errors="replace")
            except urllib.error.HTTPError as e:
                if 400 <= e.code < 500 and e.code != 429:
                    return ""                       # no published policy: allowed
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
                pass
            if attempt == 0:
                self._sleep(self.backoff)
        return None

    # fixtures -----------------------------------------------------------
    def _fixture(self, method: str, url: str, body: Any) -> tuple[int, bytes, str]:
        assert self.fixtures is not None
        lookup = "GET" if method == "HEAD" else method
        stem = fixture_name(url, lookup)
        stems = ([f"{stem}__{body_digest(body)}"] if lookup == "POST" and body is not None else []) + [stem]
        for s in stems:
            st = self.fixtures / f"{s}.status"
            if st.is_file():
                code = int(st.read_text(encoding="utf-8").strip() or 404)
                if code >= 400:
                    raise HttpError(url, code, f"HTTP {code} (fixture)")
            for ext in FIXTURE_EXTS:
                f = self.fixtures / f"{s}{ext}"
                if f.is_file():
                    ctype = {".json": "application/json", ".html": "text/html", ".xml": "application/xml"}.get(
                        ext, "text/plain")
                    return 200, (b"" if method == "HEAD" else f.read_bytes()), ctype + "; charset=utf-8"
        raise HttpError(url, 404, f"no fixture {stem}")


def _retry_after(value: str | None) -> float | None:
    if value and value.strip().isdigit():
        return min(float(value.strip()), 60.0)
    return None


def _decode(raw: bytes, ctype: str) -> str:
    m = re.search(r"charset=([\w-]+)", ctype or "", re.I)
    try:
        return raw.decode(m.group(1) if m else "utf-8", errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _json(raw: bytes, url: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8-sig", errors="replace"))
    except json.JSONDecodeError as e:
        raise HttpError(url, 0, f"invalid JSON ({e})") from None
