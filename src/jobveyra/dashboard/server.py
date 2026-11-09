"""Local web dashboard: ``jobveyra dashboard``.

Standard library only (``http.server.ThreadingHTTPServer``). Security model:

- binds 127.0.0.1 by default; a non-loopback address is refused unless the caller passed it
  explicitly (``--host``), and then a warning is printed;
- every request's ``Host`` header must name this server (blocks DNS rebinding);
- every POST needs the per-process CSRF token (header ``X-CSRF-Token`` or form field
  ``csrf``) and, when the browser sends one, an ``Origin``/``Referer`` on this same host;
- ``--read-only`` refuses every POST;
- job ids are checked against the queue; all output is HTML-escaped; a strict
  Content-Security-Policy allows only this server's own script and stylesheet.

No endpoint submits an application, opens a portal or handles credentials: the actions only
record decisions (outcome, hold, release, manual-check result, stage, approve, revoke).
"""
from __future__ import annotations

import hmac
import ipaddress
import json
import secrets
import socket
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from .. import config as cfgmod
from .. import queue as qmod
from . import data, views

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_BODY = 64 * 1024
STATIC = Path(__file__).resolve().parent / "static"
FONTS = Path(__file__).resolve().parent.parent / "fonts"
STATIC_FILES = {"dashboard.css": "text/css; charset=utf-8", "dashboard.js": "text/javascript; charset=utf-8"}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
       "connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
LOOPBACK_NAMES = ("localhost", "127.0.0.1", "::1")


def is_loopback(host: str) -> bool:
    h = (host or "").strip().strip("[]").lower()
    if h == "localhost":
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def check_host(host: str, explicit: bool) -> str:
    """'' for a loopback host; a warning for an explicitly requested other host; ValueError otherwise."""
    if is_loopback(host):
        return ""
    if not explicit:
        raise ValueError(f"refusing to bind the dashboard to non-loopback address {host!r}; "
                         f"pass --host {host} explicitly if you really want that")
    return (f"warning: the dashboard is listening on {host}, reachable from other machines on this network. "
            f"Anyone who can reach it can read your job search; actions still need the page's token. "
            f"Use --read-only or bind 127.0.0.1 unless you need this.")


class Dashboard:
    """Per-process state: workspace, CSRF token, read-only flag, allowed Host names."""

    def __init__(self, workspace: Path, *, read_only: bool = False, host: str = DEFAULT_HOST):
        self.workspace = Path(workspace)
        self.read_only = read_only
        self.host = host
        self.port = 0
        self.csrf = secrets.token_urlsafe(32)
        self.write_lock = threading.Lock()

    @property
    def url(self) -> str:
        h = self.host
        if h in ("0.0.0.0", "::", ""):
            h = "127.0.0.1"
        if ":" in h:
            h = f"[{h}]"
        return f"http://{h}:{self.port}/"

    def host_ok(self, header: str) -> bool:
        if not header:
            return False
        try:
            parts = urlsplit("//" + header)
            name, port = (parts.hostname or "").lower(), parts.port
        except ValueError:
            return False
        if (port or 80) != self.port:
            return False
        if self.host in ("0.0.0.0", "::", ""):
            return True                              # explicit wildcard bind: any name reaching us
        return name in LOOPBACK_NAMES or name == self.host.strip("[]").lower()

    def cfg(self):
        c = cfgmod.load(self.workspace)
        qmod.configure(c)
        return c

    def ctx(self, cfg) -> dict:
        return {"csrf": self.csrf, "read_only": self.read_only, "mode": cfg.policy.submission,
                "workspace": cfg.workspace.name or str(cfg.workspace), "today": data.today(cfg).isoformat()}


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    dashboard: Dashboard


class _Server6(_Server):
    address_family = socket.AF_INET6


class Handler(BaseHTTPRequestHandler):
    server_version = "jobveyra-dashboard"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    @property
    def dash(self) -> Dashboard:
        return self.server.dashboard  # type: ignore[attr-defined]

    def log_message(self, fmt, *args) -> None:       # quiet: the terminal shows only the URL
        return

    # ------------------------------------------------------------ responses
    def _send(self, status: int, body: bytes, ctype: str, *, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Security-Policy", CSP)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _html(self, status: int, text: str) -> None:
        self._send(status, text.encode("utf-8"), "text/html; charset=utf-8")

    def _json(self, status: int, obj) -> None:
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, status: int, message: str, *, api: bool, back: str = "/") -> None:
        if api:
            self._json(status, {"ok": False, "error": message})
            return
        try:
            ctx = self.dash.ctx(self.dash.cfg())
        except Exception:                            # noqa: BLE001 - a broken config still gets an error page
            ctx = {"csrf": "", "read_only": True, "mode": "", "workspace": "", "today": ""}
        self._html(status, views.error_page(ctx, status, message, back))

    # ------------------------------------------------------------ GET
    def do_HEAD(self) -> None:                       # noqa: N802
        self.do_GET()

    def do_GET(self) -> None:                        # noqa: N802
        parts = urlsplit(self.path)
        path = parts.path
        api = path.startswith("/api/")
        if not self.dash.host_ok(self.headers.get("Host", "")):
            self._error(HTTPStatus.MISDIRECTED_REQUEST, "unexpected Host header", api=True)
            return
        try:
            if path.startswith("/static/"):
                self._static(path[len("/static/"):])
                return
            cfg = self.dash.cfg()
            q = qmod.Queue(cfg.state_dir)
            try:
                self._route_get(cfg, q, path, parse_qs(parts.query))
            finally:
                q.close()
        except cfgmod.ConfigError as e:
            self._error(500, f"config: {e}", api=api)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:                       # noqa: BLE001 - show the error instead of a dropped connection
            self._error(500, f"internal error: {type(e).__name__}: {e}", api=api)

    def _route_get(self, cfg, q, path: str, params: dict) -> None:
        ctx = self.dash.ctx(cfg)
        if path == "/":
            self._html(200, views.overview(ctx, data.digest_view(cfg, q)))
        elif path == "/queue":
            self._html(200, views.queue_page(ctx, data.jobs(cfg, q), params))
        elif path.startswith("/job/"):
            d = self._detail(cfg, q, path[len("/job/"):])
            if d is None:
                self._error(404, "unknown job", api=False, back="/queue")
            else:
                self._html(200, views.job_page(ctx, d))
        elif path == "/review":
            self._html(200, views.review_page(ctx, data.review(cfg, q)))
        elif path == "/insights":
            self._html(200, views.insights_page(ctx, data.insights(cfg, q)))
        elif path == "/api/digest":
            self._json(200, data.digest_view(cfg, q))
        elif path == "/api/jobs":
            self._json(200, {"jobs": data.jobs(cfg, q)})
        elif path.startswith("/api/job/"):
            d = self._detail(cfg, q, path[len("/api/job/"):])
            if d is None:
                self._error(404, "unknown job", api=True)
            else:
                self._json(200, d)
        elif path == "/api/insights":
            self._json(200, data.insights(cfg, q))
        elif path == "/api/review":
            self._json(200, data.review(cfg, q))
        else:
            self._error(404, "not found", api=path.startswith("/api/"))

    def _detail(self, cfg, q, raw: str) -> dict | None:
        jid = unquote(raw)
        if not jid or len(jid) > data.MAX_ID or data.CONTROL.search(jid):
            return None
        return data.job_detail(cfg, q, jid)          # None unless the id is in the queue

    def _static(self, name: str) -> None:
        if name in STATIC_FILES:
            self._send(200, (STATIC / name).read_bytes(), STATIC_FILES[name])
            return
        if name.startswith("fonts/"):
            fn = name[len("fonts/"):]
            if fn.endswith(".woff2") and "/" not in fn and (FONTS / fn).is_file() and not fn.startswith("."):
                self._send(200, (FONTS / fn).read_bytes(), "font/woff2")
                return
        self._error(404, "not found", api=True)

    # ------------------------------------------------------------ POST
    def do_POST(self) -> None:                       # noqa: N802
        path = urlsplit(self.path).path
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        as_form = ctype == "application/x-www-form-urlencoded"
        if not self.dash.host_ok(self.headers.get("Host", "")):
            self.close_connection = True
            self._error(HTTPStatus.MISDIRECTED_REQUEST, "unexpected Host header", api=True)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            self.close_connection = True
            self._error(413 if length > 0 else 400, "request body too large or malformed", api=not as_form)
            return
        raw = self.rfile.read(length) if length else b""
        if self.dash.read_only:
            self._error(403, "the dashboard is read-only", api=not as_form)
            return
        if not self._same_origin():
            self._error(403, "cross-origin request refused", api=not as_form)
            return
        body = self._body(raw, ctype)
        if body is None:
            self._error(400, "expected a JSON object or a form", api=not as_form)
            return
        token = self.headers.get("X-CSRF-Token") or (body.get("csrf") if isinstance(body.get("csrf"), str) else "")
        if not token or not hmac.compare_digest(token.encode(), self.dash.csrf.encode()):
            self._error(403, "missing or wrong CSRF token; reload the page", api=not as_form)
            return
        name = path[len("/api/"):] if path.startswith("/api/") else ""
        fn = data.ACTIONS.get(name)
        if fn is None:
            self._error(404, "unknown action", api=not as_form)
            return
        nxt = body.get("next") if isinstance(body.get("next"), str) else ""
        nxt = nxt if nxt.startswith("/") and not nxt.startswith("//") and "\\" not in nxt else "/"
        try:
            cfg = self.dash.cfg()
            with self.dash.write_lock:
                q = qmod.Queue(cfg.state_dir)
                try:
                    result = fn(cfg, q, body)
                finally:
                    q.close()
        except data.ActionError as e:
            self._error(e.status, e.message, api=not as_form, back=nxt)
            return
        except cfgmod.ConfigError as e:
            self._error(500, f"config: {e}", api=not as_form, back=nxt)
            return
        if as_form:
            self._send(303, b"", "text/plain; charset=utf-8", extra={"Location": nxt})
        else:
            self._json(200, {"ok": True, **result})

    def _same_origin(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        origin = self.headers.get("Origin")
        if origin is not None:
            if origin == "null":
                return False
            o = urlsplit(origin)
            return o.scheme == "http" and o.netloc.lower() == host
        ref = self.headers.get("Referer")
        if ref:
            r = urlsplit(ref)
            return r.scheme == "http" and r.netloc.lower() == host
        return True                                  # non-browser client: the CSRF token still applies

    @staticmethod
    def _body(raw: bytes, ctype: str) -> dict | None:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
        if ctype == "application/x-www-form-urlencoded":
            qs = parse_qs(text, keep_blank_values=True)
            body = {k: (v if k == "exclude" else v[-1]) for k, v in qs.items()}
            return body
        if ctype in ("application/json", ""):
            if not text.strip():
                return {}
            try:
                obj = json.loads(text)
            except ValueError:
                return None
            return obj if isinstance(obj, dict) else None
        return None


def make_server(workspace: Path, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, *, explicit_host: bool = False,
                read_only: bool = False) -> _Server:
    """Bind (port 0 picks a free port) and return the server; ``server.dashboard`` holds the token."""
    check_host(host, explicit_host)
    cls = _Server6 if ":" in host.strip("[]") else _Server
    srv = cls((host.strip("[]"), port), Handler)
    dash = Dashboard(workspace, read_only=read_only, host=host.strip("[]"))
    dash.port = srv.server_address[1]
    srv.dashboard = dash
    return srv


def run(cfg, *, host: str | None = None, port: int = DEFAULT_PORT, read_only: bool = False,
        open_browser: bool = True) -> int:
    explicit = host is not None
    host = host or DEFAULT_HOST
    warning = check_host(host, explicit)
    if warning:
        print(warning, file=sys.stderr)
    try:
        srv = make_server(cfg.workspace, host, port, explicit_host=explicit, read_only=read_only)
    except OSError as e:
        print(f"jobveyra: cannot listen on {host}:{port}: {e.strerror or e}", file=sys.stderr)
        return 1
    url = srv.dashboard.url
    print(f"dashboard: {url}" + ("  (read-only)" if read_only else ""))
    print("press Ctrl+C to stop")
    sys.stdout.flush()
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:                            # noqa: BLE001 - no browser is fine
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0
