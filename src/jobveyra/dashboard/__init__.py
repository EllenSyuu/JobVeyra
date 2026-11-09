"""Local web dashboard (`jobveyra dashboard`): overview, queue, job detail, review and insights.

Standard library only. It records decisions (outcomes, holds, manual-check results, batch
approvals); it never submits an application or enters credentials. See ``server.py``.
"""
from .server import DEFAULT_HOST, DEFAULT_PORT, check_host, is_loopback, make_server, run

__all__ = ["DEFAULT_HOST", "DEFAULT_PORT", "check_host", "is_loopback", "make_server", "run"]
