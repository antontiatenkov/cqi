"""Генерация отчетов в стиле Google Lighthouse (SVG и standalone HTML)."""

import html
import math
from typing import Tuple

from cqi.models import AuditReport, DimensionScore

_SHORT_DIM_LABELS = {
    "maintainability": "Maintainability",
    "readability": "Readability",
    "resilience": "Resilience",
    "security": "Security",
    "testability": "Testability",
}


def _score_color(score: float) -> Tuple[str, str]:
    """Возвращает пару (основной цвет, фоновый цвет кольца) по шкале Lighthouse."""
    if score >= 90.0:
        return "#0cce6b", "#e6faf0"
    if score >= 50.0:
        return "#ffa400", "#fff5e0"
    return "#ff4e42", "#ffe8e6"


def _gate_colors(gate: str) -> Tuple[str, str]:
    """Возвращает пару (цвет текста, цвет фона) для бейджа Quality Gate."""
    mapping = {
        "PASSED": ("#065f46", "#d1fae5"),
        "WARN": ("#92400e", "#fef3c7"),
        "BLOCKED": ("#991b1b", "#fee2e2"),
    }
    return mapping.get(gate, ("#1e293b", "#e2e8f0"))


def _svg_gauge(
    cx: float,
    cy: float,
    radius: float,
    score: float,
    stroke_width: float = 8.0,
    font_size: int = 22,
    label: str = "",
) -> str:
    """Строит SVG-фрагмент кругового индикатора (gauge) в стиле Lighthouse."""
    fg, bg = _score_color(score)
    circumference = 2.0 * math.pi * radius
    clamped = max(0.0, min(100.0, score))
    dash = (clamped / 100.0) * circumference
    score_text = f"{score:.1f}" if score < 100.0 else "100"

    parts = [
        f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="{bg}" fill-opacity="0.35" '
        f'stroke="{bg}" stroke-width="{stroke_width}" />',
        f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" stroke="{fg}" '
        f'stroke-width="{stroke_width}" stroke-linecap="round" '
        f'stroke-dasharray="{dash:.2f} {circumference:.2f}" '
        f'transform="rotate(-90 {cx} {cy})" />',
        f'<text x="{cx}" y="{cy}" text-anchor="middle" dominant-baseline="central" '
        f'font-family="ui-monospace, SFMono-Regular, Menlo, monospace" '
        f'font-size="{font_size}" font-weight="700" fill="{fg}">{score_text}</text>',
    ]
    if label:
        parts.append(
            f'<text x="{cx}" y="{cy + radius + 22}" text-anchor="middle" '
            f'font-family="-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif" '
            f'font-size="12" font-weight="600" fill="#334155">{html.escape(label)}</text>'
        )
    return "\n  ".join(parts)


def render_svg_report(report: AuditReport) -> str:
    """Рендерит компактный SVG-отчет CQI в стиле Google Lighthouse."""
    gate_fg, gate_bg = _gate_colors(report.quality_gate)
    safe_path = html.escape(report.project_path)
    if len(safe_path) > 48:
        safe_path = "..." + safe_path[-45:]

    hero_gauge = _svg_gauge(120, 175, 58, report.final_cqi, stroke_width=11.0, font_size=30)

    dim_gauges: list[str] = []
    start_x = 290
    step_x = 135
    for idx, (key, dim) in enumerate(report.dimensions.items()):
        cx = start_x + idx * step_x
        short_name = _SHORT_DIM_LABELS.get(key, key.title())
        dim_gauges.append(_svg_gauge(cx, 165, 36, dim.score, stroke_width=7.0, font_size=18, label=short_name))
        w_pct = int(dim.weight * 100)
        dim_gauges.append(
            f'<text x="{cx}" y="242" text-anchor="middle" '
            f'font-family="-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif" '
            f'font-size="11" fill="#64748b">weight {w_pct}%</text>'
        )

    dim_block = "\n  ".join(dim_gauges)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 920 330" width="920" height="330" role="img" aria-label="CQI Lighthouse Report">
  <rect x="1" y="1" width="918" height="328" rx="16" fill="#ffffff" stroke="#e2e8f0" stroke-width="2" />
  <rect x="1" y="1" width="918" height="64" rx="16" fill="#f8fafc" />
  <rect x="1" y="48" width="918" height="17" fill="#f8fafc" />
  <line x1="1" y1="65" x2="919" y2="65" stroke="#e2e8f0" stroke-width="1" />

  <text x="28" y="31" font-family="-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif" font-size="18" font-weight="700" fill="#0f172a">Code Quality Index (CQI)</text>
  <text x="28" y="51" font-family="ui-monospace, SFMono-Regular, Menlo, monospace" font-size="12" fill="#64748b">{safe_path}</text>

  <rect x="650" y="19" width="84" height="28" rx="14" fill="#e2e8f0" />
  <text x="692" y="37" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif" font-size="12" font-weight="700" fill="#1e293b">{html.escape(report.profile.upper())}</text>

  <rect x="748" y="19" width="144" height="28" rx="14" fill="{gate_bg}" />
  <text x="820" y="37" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif" font-size="12" font-weight="700" fill="{gate_fg}">GATE: {html.escape(report.quality_gate)}</text>

  {hero_gauge}
  <text x="120" y="256" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif" font-size="13" font-weight="700" fill="#0f172a">{html.escape(report.grade)}</text>
  <text x="120" y="274" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif" font-size="11" fill="#64748b">Raw {report.raw_cqi:.1f} | Veto x{report.penalty_multiplier:.2f}</text>

  <line x1="220" y1="90" x2="220" y2="275" stroke="#e2e8f0" stroke-width="1" />
  {dim_block}

  <line x1="28" y1="292" x2="892" y2="292" stroke="#f1f5f9" stroke-width="1" />
  <text x="28" y="314" font-family="-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif" font-size="12" fill="#64748b">Files: {report.files_scanned}  |  Prod SLOC: {report.total_sloc}  |  Test SLOC: {report.test_sloc}</text>
  <text x="892" y="314" text-anchor="end" font-family="-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif" font-size="11" fill="#94a3b8">90-100 Good  |  50-89 Needs Improvement  |  0-49 Critical</text>
</svg>
"""


def _render_dimension_card(key: str, dim: DimensionScore) -> str:
    """Формирует HTML-карточку одного измерения CQI."""
    gauge_svg = (
        f'<svg viewBox="0 0 100 100" width="76" height="76" aria-hidden="true">'
        f"{_svg_gauge(50, 50, 40, dim.score, stroke_width=8.0, font_size=22)}"
        f"</svg>"
    )
    metrics_html = "".join(
        f'<span class="pill">{html.escape(k)}: <strong>{v}</strong></span>'
        for k, v in dim.metrics_summary.items()
    )
    if dim.penalties:
        penalties_html = "<ul class='penalties'>" + "".join(
            f"<li>{html.escape(p)}</li>" for p in dim.penalties
        ) + "</ul>"
    else:
        penalties_html = '<div class="ok-note">Нарушений по порогам не обнаружено</div>'

    return f"""
    <article class="card" id="dim-{html.escape(key)}">
      <div class="card-head">
        {gauge_svg}
        <div>
          <h3>{html.escape(dim.name)}</h3>
          <div class="sub">Вес: {int(dim.weight * 100)}% &middot; Вклад в Raw CQI: <strong>{dim.weighted_score:.2f}</strong></div>
        </div>
      </div>
      <div class="pills">{metrics_html}</div>
      {penalties_html}
    </article>"""


def _render_hotspots_rows(report: AuditReport) -> str:
    """Формирует строки таблицы проблемных файлов (hotspots)."""
    if not report.hotspots:
        return '<tr><td colspan="5" class="muted">Продуктовые файлы не найдены</td></tr>'
    rows: list[str] = []
    for item in report.hotspots:
        issues = int(item.get("issues", 0))
        badge_cls = "badge-ok" if issues == 0 else "badge-warn"
        rows.append(
            "<tr>"
            f'<td class="mono">{html.escape(str(item.get("path", "")))}</td>'
            f'<td>{item.get("sloc", 0)}</td>'
            f'<td>{item.get("max_cc", 0)}</td>'
            f'<td>{item.get("max_nesting", 0)}</td>'
            f'<td><span class="badge {badge_cls}">{issues}</span></td>'
            "</tr>"
        )
    return "\n".join(rows)


def render_html_report(report: AuditReport) -> str:
    """Рендерит автономный HTML-отчет CQI в стиле Google Lighthouse."""
    gate_fg, gate_bg = _gate_colors(report.quality_gate)
    hero_svg = (
        '<svg viewBox="0 0 140 140" width="132" height="132" aria-label="Final CQI">'
        + _svg_gauge(70, 70, 56, report.final_cqi, stroke_width=10.0, font_size=30)
        + "</svg>"
    )

    top_gauges: list[str] = []
    for key, dim in report.dimensions.items():
        short_name = _SHORT_DIM_LABELS.get(key, key.title())
        top_gauges.append(
            f'<a class="top-gauge" href="#dim-{html.escape(key)}">'
            '<svg viewBox="0 0 100 100" width="76" height="76">'
            + _svg_gauge(50, 50, 40, dim.score, stroke_width=7.5, font_size=22)
            + "</svg>"
            f"<span>{html.escape(short_name)}</span>"
            "</a>"
        )

    cards_html = "\n".join(_render_dimension_card(k, d) for k, d in report.dimensions.items())
    hotspots_html = _render_hotspots_rows(report)

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>CQI Lighthouse Report — {html.escape(report.profile.upper())}</title>
  <style>
    :root {{
      --bg: #f8fafc; --surface: #ffffff; --border: #e2e8f0;
      --text: #0f172a; --muted: #64748b; --pill-bg: #f1f5f9;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: #0b1120; --surface: #111827; --border: #1f2937;
        --text: #f8fafc; --muted: #94a3b8; --pill-bg: #1e293b;
      }}
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; padding: 32px 20px; background: var(--bg); color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      line-height: 1.5;
    }}
    .wrap {{ max-width: 1040px; margin: 0 auto; }}
    .header {{
      background: var(--surface); border: 1px solid var(--border); border-radius: 16px;
      padding: 24px 28px; display: flex; flex-wrap: wrap; gap: 24px;
      align-items: center; justify-content: space-between;
    }}
    .hero {{ display: flex; align-items: center; gap: 20px; }}
    .title h1 {{ margin: 0 0 4px; font-size: 22px; }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; color: var(--muted); word-break: break-all; }}
    .badges {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }}
    .badge {{ display: inline-block; padding: 4px 12px; border-radius: 999px; font-size: 12px; font-weight: 700; }}
    .badge-neutral {{ background: var(--pill-bg); color: var(--text); }}
    .badge-ok {{ background: #d1fae5; color: #065f46; }}
    .badge-warn {{ background: #fee2e2; color: #991b1b; }}
    .top-gauges {{
      display: grid; grid-template-columns: repeat(5, minmax(96px, 1fr)); gap: 12px;
      background: var(--surface); border: 1px solid var(--border); border-radius: 16px;
      padding: 20px; margin-top: 18px;
    }}
    .top-gauge {{
      display: flex; flex-direction: column; align-items: center; gap: 8px;
      text-decoration: none; color: var(--text); font-size: 13px; font-weight: 600;
    }}
    .top-gauge:hover {{ opacity: 0.85; }}
    .legend {{
      display: flex; justify-content: center; gap: 24px; margin: 14px 0 24px;
      font-size: 12px; color: var(--muted); flex-wrap: wrap;
    }}
    .dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }}
    .card {{
      background: var(--surface); border: 1px solid var(--border); border-radius: 14px;
      padding: 18px 20px;
    }}
    .card-head {{ display: flex; align-items: center; gap: 14px; margin-bottom: 12px; }}
    .card-head h3 {{ margin: 0 0 4px; font-size: 16px; }}
    .sub {{ font-size: 12px; color: var(--muted); }}
    .pills {{ display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }}
    .pill {{ background: var(--pill-bg); padding: 3px 10px; border-radius: 8px; font-size: 12px; }}
    .penalties {{ margin: 0; padding-left: 18px; color: #ef4444; font-size: 13px; }}
    .ok-note {{ font-size: 13px; color: #10b981; font-weight: 600; }}
    .panel {{
      margin-top: 20px; background: var(--surface); border: 1px solid var(--border);
      border-radius: 14px; padding: 20px; overflow-x: auto;
    }}
    .panel h2 {{ margin: 0 0 12px; font-size: 17px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border); }}
    th {{ color: var(--muted); font-weight: 600; }}
    @media (max-width: 680px) {{ .top-gauges {{ grid-template-columns: repeat(2, 1fr); }} }}
  </style>
</head>
<body>
  <main class="wrap">
    <section class="header">
      <div class="hero">
        {hero_svg}
        <div class="title">
          <h1>Code Quality Index (CQI)</h1>
          <div class="mono">{html.escape(report.project_path)}</div>
          <div class="badges">
            <span class="badge badge-neutral">Профиль: {html.escape(report.profile.upper())}</span>
            <span class="badge badge-neutral">{html.escape(report.grade)}</span>
            <span class="badge" style="background:{gate_bg};color:{gate_fg};">Quality Gate: {html.escape(report.quality_gate)}</span>
          </div>
        </div>
      </div>
      <div class="badges">
        <span class="badge badge-neutral">Файлов: {report.files_scanned}</span>
        <span class="badge badge-neutral">Prod SLOC: {report.total_sloc}</span>
        <span class="badge badge-neutral">Test SLOC: {report.test_sloc}</span>
        <span class="badge badge-neutral">Raw: {report.raw_cqi:.1f} | Veto: x{report.penalty_multiplier:.2f}</span>
      </div>
    </section>

    <section class="top-gauges" aria-label="Оценки по направлениям">
      {"".join(top_gauges)}
    </section>

    <div class="legend">
      <span><i class="dot" style="background:#0cce6b;"></i>90–100 (Good)</span>
      <span><i class="dot" style="background:#ffa400;"></i>50–89 (Needs Improvement)</span>
      <span><i class="dot" style="background:#ff4e42;"></i>0–49 (Critical)</span>
    </div>

    <section class="grid">
      {cards_html}
    </section>

    <section class="panel">
      <h2>Top-5 Hotspots</h2>
      <table>
        <thead>
          <tr><th>Файл</th><th>SLOC</th><th>Max CC</th><th>Max Nesting</th><th>Issues</th></tr>
        </thead>
        <tbody>
          {hotspots_html}
        </tbody>
      </table>
    </section>
  </main>
</body>
</html>
"""


def write_svg_report(report: AuditReport, output_path: object) -> None:
    """Сохраняет SVG-отчет CQI в указанный файл."""
    from pathlib import Path

    Path(str(output_path)).write_text(render_svg_report(report), encoding="utf-8")


def write_html_report(report: AuditReport, output_path: object) -> None:
    """Сохраняет HTML-отчет CQI в указанный файл."""
    from pathlib import Path

    Path(str(output_path)).write_text(render_html_report(report), encoding="utf-8")
