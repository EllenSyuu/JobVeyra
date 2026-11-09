"""Reports built from one digest: newsletter email, status Markdown, notifications, calendar.

Submodules are imported on use (``from jobveyra.report import newsletter``) so that Pillow,
needed only by ``chart``, is never imported unless a chart is drawn.
"""
__all__ = ["digest", "newsletter", "chart", "notify", "status", "calendar"]
