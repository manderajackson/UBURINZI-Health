"""Dependency-free SVG charts (no CDN, works offline and inside sandboxes)."""
from __future__ import annotations

from html import escape


def line_chart(values: list[float | None], *, width=720, height=180, color="#0f766e", fill="#0f766e22", max_value: float | None = None) -> str:
    pts = [v for v in values if v is not None]
    if not pts:
        return '<div class="chart-empty">No data yet</div>'
    hi = max_value or max(max(pts), 0.0001)
    lo = 0.0
    n = len(values)
    step = width / max(n - 1, 1)
    coords = []
    for i, v in enumerate(values):
        if v is None:
            continue
        x = i * step
        y = height - ((v - lo) / (hi - lo)) * (height - 12) - 6
        coords.append((x, y))
    if not coords:
        return '<div class="chart-empty">No data yet</div>'
    path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(coords))
    area = f"{path} L{coords[-1][0]:.1f},{height} L{coords[0][0]:.1f},{height} Z"
    dots = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5" fill="{color}"/>' for x, y in coords[:: max(1, len(coords) // 24)]
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" class="chart" role="img">'
        f'<path d="{area}" fill="{fill}"/>'
        f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round"/>'
        f"{dots}</svg>"
    )


def bar_chart(pairs: list[tuple[str, float]], *, width=720, height=180, color="#2563eb") -> str:
    if not pairs:
        return '<div class="chart-empty">No data yet</div>'
    hi = max((v for _, v in pairs), default=1) or 1
    n = len(pairs)
    gap = 6
    bar_w = (width - gap * (n - 1)) / n
    bars = []
    for i, (label, value) in enumerate(pairs):
        h = max((value / hi) * (height - 26), 2)
        x = i * (bar_w + gap)
        y = height - h - 16
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" rx="3" fill="{color}" opacity="0.9">'
            f"<title>{escape(str(label))}: {value:g}</title></rect>"
        )
    return (
        f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" class="chart" role="img">'
        f'<line x1="0" y1="{height-16}" x2="{width}" y2="{height-16}" stroke="#cbd5e1" stroke-width="1"/>'
        f'{"".join(bars)}</svg>'
    )


def stacked_bar(rows: list[tuple[str, float, str]], *, width=16, height=16) -> str:
    """Tiny horizontal proportion bar for program mix / status split."""
    total = sum(v for _, v, _ in rows) or 1
    x = 0.0
    segs = []
    for label, value, color in rows:
        w = (value / total) * width
        segs.append(
            f'<rect x="{x:.2f}" y="0" width="{w:.2f}" height="{height}" fill="{color}"><title>{escape(str(label))}: {value:g}</title></rect>'
        )
        x += w
    return f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" class="minibar" role="img">{"".join(segs)}</svg>'


def donut(segments: list[tuple[str, float, str]], *, size=140, thickness=18, center_label="", center_value="") -> str:
    import math

    total = sum(v for _, v, _ in segments) or 1
    r = (size - thickness) / 2
    cx = cy = size / 2
    angle = -math.pi / 2
    parts = []
    for label, value, color in segments:
        if value <= 0:
            continue
        sweep = (value / total) * 2 * math.pi
        x1, y1 = cx + r * math.cos(angle), cy + r * math.sin(angle)
        angle2 = angle + sweep
        x2, y2 = cx + r * math.cos(angle2), cy + r * math.sin(angle2)
        large = 1 if sweep > math.pi else 0
        if sweep >= 2 * math.pi - 1e-6:
            d = (
                f"M {cx - r} {cy} a {r} {r} 0 1 1 {2*r} 0 a {r} {r} 0 1 1 {-2*r} 0"
            )
        else:
            d = f"M {x1:.2f} {y1:.2f} A {r} {r} 0 {large} 1 {x2:.2f} {y2:.2f}"
        parts.append(
            f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{thickness}" stroke-linecap="butt">'
            f"<title>{escape(str(label))}: {value:g}</title></path>"
        )
        angle = angle2
    return (
        f'<svg viewBox="0 0 {size} {size}" class="donut" role="img">'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#e2e8f0" stroke-width="{thickness}"/>'
        f'{"".join(parts)}'
        f'<text x="{cx}" y="{cy - 2}" text-anchor="middle" class="donut-value">{escape(center_value)}</text>'
        f'<text x="{cx}" y="{cy + 16}" text-anchor="middle" class="donut-label">{escape(center_label)}</text>'
        f"</svg>"
    )
