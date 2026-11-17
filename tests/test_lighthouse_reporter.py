"""Unit-тесты для генератора отчетов в стиле Google Lighthouse (HTML и SVG)."""

import tempfile
import unittest
from pathlib import Path

from cqi.lighthouse_reporter import (
    _gate_colors,
    _score_color,
    render_html_report,
    render_svg_report,
    write_html_report,
    write_svg_report,
)
from cqi.models import AuditReport, DimensionScore


def _make_sample_report(
    project_path: str = "/tmp/sample-project",
    profile: str = "saas",
    final_cqi: float = 92.5,
    quality_gate: str = "PASSED",
    hotspots: list | None = None,
    with_penalties: bool = False,
) -> AuditReport:
    """Создает тестовый экземпляр AuditReport с настраиваемыми параметрами."""
    penalties = ["Высокая сложность (max CC = 25)"] if with_penalties else []
    dims = {
        "maintainability": DimensionScore(
            name="Поддерживаемость (Maintainability)",
            weight=0.25,
            score=95.0 if not with_penalties else 45.0,
            weighted_score=23.75,
            penalties=penalties,
            metrics_summary={"avg_cc": 3.2, "max_cc": 8, "oversized_files": 0},
        ),
        "readability": DimensionScore(
            name="Читаемость (Readability)",
            weight=0.20,
            score=90.0,
            weighted_score=18.0,
            penalties=[],
            metrics_summary={"max_nesting": 3, "docstring_cov": 0.85, "todo_per_kloc": 0.0},
        ),
        "resilience": DimensionScore(
            name="Отказоустойчивость (Resilience)",
            weight=0.20,
            score=85.0,
            weighted_score=17.0,
            penalties=[],
            metrics_summary={"bare_excepts": 0, "silent_excepts": 0, "type_hint_cov": 0.95},
        ),
        "security": DimensionScore(
            name="Безопасность (Security)",
            weight=0.20,
            score=100.0 if quality_gate != "BLOCKED" else 30.0,
            weighted_score=20.0,
            penalties=["<script>alert(1)</script>"] if with_penalties else [],
            metrics_summary={"secrets_found": 0, "dangerous_calls": 0},
        ),
        "testability": DimensionScore(
            name="Тестируемость (Testability)",
            weight=0.15,
            score=88.0,
            weighted_score=13.2,
            penalties=[],
            metrics_summary={"test_to_code_ratio": 0.45, "total_asserts": 24},
        ),
    }
    return AuditReport(
        project_path=project_path,
        profile=profile,
        files_scanned=10,
        total_sloc=500,
        test_sloc=225,
        raw_cqi=92.5,
        penalty_multiplier=1.0 if quality_gate != "BLOCKED" else 0.5,
        final_cqi=final_cqi,
        grade="A (Exemplary)" if final_cqi >= 90 else "F (Critical)",
        quality_gate=quality_gate,
        dimensions=dims,
        hotspots=hotspots if hotspots is not None else [],
    )


class TestLighthouseHelpers(unittest.TestCase):
    """Тесты цветовых порогов и вспомогательных функций Lighthouse."""

    def test_score_color_tiers(self) -> None:
        """Проверяет выбор цветов для диапазонов 90-100, 50-89 и 0-49."""
        fg_good, _ = _score_color(95.0)
        fg_boundary, _ = _score_color(90.0)
        fg_warn, _ = _score_color(72.0)
        fg_warn_low, _ = _score_color(50.0)
        fg_crit, _ = _score_color(49.9)
        assert fg_good == "#0cce6b"
        assert fg_boundary == "#0cce6b"
        assert fg_warn == "#ffa400"
        assert fg_warn_low == "#ffa400"
        assert fg_crit == "#ff4e42"

    def test_gate_colors_all_statuses(self) -> None:
        """Проверяет цвета бейджа для PASSED, WARN, BLOCKED и неизвестного статуса."""
        assert _gate_colors("PASSED") == ("#065f46", "#d1fae5")
        assert _gate_colors("WARN") == ("#92400e", "#fef3c7")
        assert _gate_colors("BLOCKED") == ("#991b1b", "#fee2e2")
        assert _gate_colors("UNKNOWN") == ("#1e293b", "#e2e8f0")


class TestSvgAndHtmlRendering(unittest.TestCase):
    """Тесты генерации и сохранения SVG и HTML отчетов."""

    def test_render_svg_truncates_long_path_and_renders_dimensions(self) -> None:
        """Длинный путь усекается, а все 5 измерений присутствуют в SVG."""
        long_path = "/very/long/nested/directory/structure/for/testing/my_awesome_project"
        report = _make_sample_report(project_path=long_path, profile="erp")
        svg = render_svg_report(report)
        assert svg.startswith("<svg ")
        assert "..." in svg
        assert "ERP" in svg
        assert "GATE: PASSED" in svg
        for label in ("Maintainability", "Readability", "Resilience", "Security", "Testability"):
            assert label in svg

    def test_render_html_escapes_xss_and_renders_hotspots(self) -> None:
        """HTML-отчет экранирует спецсимволы и отображает таблицу hotspots."""
        hotspots = [
            {"path": "core/<bad>.py", "sloc": 320, "max_cc": 18, "max_nesting": 4, "issues": 2},
            {"path": "clean.py", "sloc": 40, "max_cc": 2, "max_nesting": 1, "issues": 0},
        ]
        report = _make_sample_report(
            project_path="/tmp/<script>xss</script>",
            final_cqi=40.0,
            quality_gate="BLOCKED",
            hotspots=hotspots,
            with_penalties=True,
        )
        html_doc = render_html_report(report)
        assert "<script>xss</script>" not in html_doc
        assert "&lt;script&gt;xss&lt;/script&gt;" in html_doc
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_doc
        assert "core/&lt;bad&gt;.py" in html_doc
        assert "badge-warn" in html_doc
        assert "badge-ok" in html_doc
        assert "Quality Gate: BLOCKED" in html_doc

    def test_render_html_empty_hotspots_and_no_penalties(self) -> None:
        """При отсутствии hotspots и штрафов выводятся соответствующие заглушки."""
        report = _make_sample_report(hotspots=[], with_penalties=False)
        html_doc = render_html_report(report)
        assert "Продуктовые файлы не найдены" in html_doc
        assert "Нарушений по порогам не обнаружено" in html_doc

    def test_write_svg_and_html_files(self) -> None:
        """write_svg_report и write_html_report записывают файлы на диск."""
        report = _make_sample_report()
        with tempfile.TemporaryDirectory() as tmp:
            svg_file = Path(tmp) / "cqi.svg"
            html_file = Path(tmp) / "cqi.html"
            write_svg_report(report, svg_file)
            write_html_report(report, html_file)
            assert svg_file.exists()
            assert html_file.exists()
            assert "<svg " in svg_file.read_text(encoding="utf-8")
            assert "<!DOCTYPE html>" in html_file.read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
