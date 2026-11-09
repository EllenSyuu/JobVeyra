"""Animated GIF bar chart of submissions per day (Pillow, optional).

Drawn at 2x so it stays sharp on high-density screens. Frame 0 is the finished chart, so
email clients and previews that show only the first frame still show the real numbers; then
the bars grow left to right and the last frame holds. Light and dark palettes use neutral
greys and a single blue accent (today's bar in full, earlier days in a tint of it).
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

FONTS = Path(__file__).resolve().parent.parent / "fonts"
FALLBACK_FONTS = ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans.ttf")
FALLBACK_BOLD = ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "DejaVuSans-Bold.ttf")

LIGHT = {"bg": "#ffffff", "ink": "#1f2328", "muted": "#656d76", "rule": "#d0d7de",
         "bar": "#9cc2f5", "today": "#0969da"}
DARK = {"bg": "#0d1117", "ink": "#e6edf3", "muted": "#9198a1", "rule": "#30363d",
        "bar": "#1f4f8f", "today": "#4493f8"}
PALETTES = {"light": LIGHT, "dark": DARK}


def _pil():
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as e:  # pragma: no cover - exercised only without pillow
        raise ImportError("Charts need Pillow, which is optional. Install it with "
                          "`pip install 'jobveyra[charts]'` or `pip install pillow`.") from e
    return Image, ImageDraw, ImageFont


def font(weight: int, size: int):
    _, _, ImageFont = _pil()
    name = "inter-latin-600-normal.woff2" if weight >= 600 else "inter-latin-400-normal.woff2"
    for p in (str(FONTS / name), *(FALLBACK_BOLD if weight >= 600 else ()), *FALLBACK_FONTS):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def render(series: list[dict], path, *, palette="light", scale: int = 2, steps: int = 14,
           title: str | None = None) -> Path:
    """Write the GIF and return its path. ``series``: ``[{"date": "YYYY-MM-DD", "sent": n}, ...]``."""
    Image, ImageDraw, _ = _pil()
    pal = PALETTES[palette] if isinstance(palette, str) else palette
    series = list(series) or [{"date": dt.date.today().isoformat(), "sent": 0}]
    W, H = 600 * scale, 200 * scale
    left, right, top, bottom = 8 * scale, 8 * scale, 28 * scale, 30 * scale
    n = len(series)
    peak = max(1, max(int(s.get("sent") or 0) for s in series))
    gap = 6 * scale
    bw = (W - left - right - gap * (n - 1)) / n
    f_lab, f_num, f_head = font(400, 11 * scale), font(600, 11 * scale), font(600, 12 * scale)
    head = title or f"Applications submitted per day, last {n} days"

    def frame(progress: float):
        im = Image.new("RGB", (W, H), pal["bg"])
        d = ImageDraw.Draw(im)
        d.text((left, 4 * scale), head, font=f_head, fill=pal["ink"])
        base = H - bottom
        d.line([(left, base), (W - right, base)], fill=pal["rule"], width=scale)
        for i, s in enumerate(series):
            v = int(s.get("sent") or 0)
            local = max(0.0, min(1.0, progress * 1.6 - i / n * 0.6))
            h = (base - top - 14 * scale) * v / peak * local
            x0 = left + i * (bw + gap)
            if v:
                d.rectangle([x0, base - max(h, scale), x0 + bw, base], fill=pal["today"] if i == n - 1 else pal["bar"])
            if local >= 1 and v:
                txt = str(v)
                tw = d.textlength(txt, font=f_num)
                d.text((x0 + (bw - tw) / 2, base - h - 15 * scale), txt, font=f_num, fill=pal["ink"])
            try:
                day = dt.date.fromisoformat(str(s.get("date"))[:10])
            except ValueError:
                continue
            if i in (0, n - 1) or day.weekday() == 0:
                lab = f"{day.strftime('%b')} {day.day}"
                tw = d.textlength(lab, font=f_lab)
                d.text((min(max(x0 + (bw - tw) / 2, left), W - right - tw), base + 8 * scale), lab,
                       font=f_lab, fill=pal["muted"])
        return im

    frames = [frame(1.0)] + [frame(k / steps) for k in range(steps + 1)]
    durations = [20] + [55] * steps + [6000]
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)
    return out


def render_pair(series: list[dict], out_dir, *, scale: int = 2) -> tuple[Path, Path]:
    """chart.gif (light) and chart-dark.gif in ``out_dir``."""
    out_dir = Path(out_dir)
    return (render(series, out_dir / "chart.gif", palette="light", scale=scale),
            render(series, out_dir / "chart-dark.gif", palette="dark", scale=scale))
