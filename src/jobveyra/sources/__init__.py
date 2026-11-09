"""Job sources: one adapter per board or feed, all returning ``list[Posting]``.

``get(type_name)`` returns an adapter instance; ``REGISTRY`` maps type names to classes.
Every adapter fetches through :class:`Http`, which tests run offline against fixtures.
"""
from __future__ import annotations

from . import (ashby, greenhouse, jsonld, lever, linkedin_alert, recruitee, remotive,  # noqa: F401  (register)
               smartrecruiters, un_careers, usajobs, workable)
from .base import ADAPTERS, REGISTRY, Source, SourceError, get
from .http import Http, HttpError, RobotsDisallowed

__all__ = ["ADAPTERS", "REGISTRY", "Source", "SourceError", "get", "Http", "HttpError", "RobotsDisallowed"]
