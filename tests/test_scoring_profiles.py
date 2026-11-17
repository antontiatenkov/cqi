"""Unit-тесты для профилей скоринга, Veto-правил, штрафов, hotspots и CLI-вывода."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from cqi.models import FileMetrics
from cqi.reporter import print_cli_report, write_json_report
from cqi.scoring import compute_scores


class TestScoringProfilesAndGates(unittest.TestCase):
    """Тесты профилей весов, Veto-штрафов, грейдов и Quality Gate."""

    def test_profiles_weights_and_unknown_fallback(self) -> None:
        """Профили saas, erp, mvp используют свои веса; неизвестный откатывается к saas."""
        files = [FileMetrics(path="app.py", loc=50, sloc=40)]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            erp = compute_scores(files, root, "erp")
            mvp = compute_scores(files, root, "mvp")
            unknown = compute_scores(files, root, "custom")
            assert erp.dimensions["security"].weight == 0.30
            assert mvp.dimensions["maintainability"].weight == 0.30
            assert unknown.dimensions["maintainability"].weight == 0.25

    def test_empty_files_list_uses_synthetic_fallback(self) -> None:
        """Пустой список файлов не вызывает деление на ноль и возвращает корректный отчет."""
        with tempfile.TemporaryDirectory() as tmp:
            report = compute_scores([], Path(tmp), "saas")
            assert report.files_scanned == 0
            assert report.total_sloc == 1
            assert report.test_sloc == 0

    def test_veto_080_when_non_security_dimension_below_50(self) -> None:
        """Если минимальное измерение < 50, а security >= 40 и секретов нет, Veto = 0.8."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "requirements.txt").write_text("", encoding="utf-8")
            (root / "Dockerfile").write_text("FROM python:3.12\n", encoding="utf-8")
            files = [
                FileMetrics(
                    path="complex.py",
                    loc=500,
                    sloc=450,
                    avg_cc=18.0,
                    max_cc=30,
                    max_func_length=90,
                    imports_count=25,
                    docstring_coverage=0.8,
                    type_hint_coverage=0.9,
                ),
                FileMetrics(
                    path="tests/test_complex.py",
                    loc=250,
                    sloc=230,
                    is_test=True,
                    asserts_count=10,
                ),
            ]
            report = compute_scores(files, root, "saas")
            assert report.dimensions["maintainability"].score < 50.0
            assert report.dimensions["security"].score >= 40.0
            assert report.penalty_multiplier == 0.8

    def test_all_penalties_are_reported(self) -> None:
        """Проверяет формирование текстовых штрафов по всем 5 направлениям."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = [
                FileMetrics(
                    path="bad.py",
                    loc=500,
                    sloc=450,
                    max_cc=22,
                    max_nesting=6,
                    docstring_coverage=0.1,
                    bare_excepts=2,
                    silent_excepts=1,
                    network_calls_without_timeout=2,
                    dangerous_calls=1,
                    hardcoded_secrets=1,
                )
            ]
            report = compute_scores(files, root, "saas")
            assert any("max CC = 22" in p for p in report.dimensions["maintainability"].penalties)
            assert any("более 400 SLOC" in p for p in report.dimensions["maintainability"].penalties)
            assert any("Глубокая вложенность" in p for p in report.dimensions["readability"].penalties)
            assert any("Низкое покрытие docstring" in p for p in report.dimensions["readability"].penalties)
            assert any("перехват неспецифичных исключений" in p for p in report.dimensions["resilience"].penalties)
            assert any("без явного timeout" in p for p in report.dimensions["resilience"].penalties)
            assert any("захардкоженные секреты" in p for p in report.dimensions["security"].penalties)
            assert any("eval/exec/shell=True" in p for p in report.dimensions["security"].penalties)
            assert any("Отсутствует манифест" in p for p in report.dimensions["security"].penalties)
            assert any("Test-to-Code Ratio" in p for p in report.dimensions["testability"].penalties)

    def test_hotspots_sorted_and_capped_at_five(self) -> None:
        """Список hotspots содержит не более 5 файлов, отсортированных по риску."""
        files = [
            FileMetrics(path=f"f{i}.py", loc=100, sloc=80 + i * 20, max_cc=5 + i, bare_excepts=i % 2)
            for i in range(8)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            report = compute_scores(files, Path(tmp), "saas")
            assert len(report.hotspots) == 5
            assert report.hotspots[0]["path"] == "f7.py"

    def test_warn_quality_gate_and_grades(self) -> None:
        """Проверяет срабатывание статуса WARN при среднем качестве без критических блокеров."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "requirements.txt").write_text("", encoding="utf-8")
            files = [
                FileMetrics(
                    path="mid.py",
                    loc=120,
                    sloc=100,
                    avg_cc=13.0,
                    max_cc=14,
                    max_nesting=5,
                    docstring_coverage=0.3,
                    type_hint_coverage=0.5,
                    bare_excepts=2,
                ),
                FileMetrics(
                    path="tests/test_mid.py",
                    loc=20,
                    sloc=15,
                    is_test=True,
                    asserts_count=1,
                ),
            ]
            report = compute_scores(files, root, "saas")
            assert report.penalty_multiplier == 0.8
            assert 55.0 <= report.final_cqi < 70.0
            assert report.quality_gate == "WARN"
            assert report.grade in ("C (Acceptable)", "B (Good)", "D (High Debt)")


class TestReporterOutputs(unittest.TestCase):
    """Тесты CLI-печати и сохранения JSON-отчета."""

    def test_print_cli_report_and_write_json(self) -> None:
        """print_cli_report печатает сводку, а write_json_report сохраняет валидный JSON."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "requirements.txt").write_text("", encoding="utf-8")
            files = [FileMetrics(path="app.py", loc=20, sloc=15)]
            report = compute_scores(files, root, "mvp")

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                print_cli_report(report)
            output = buf.getvalue()
            assert "ОТЧЕТ О КАЧЕСТВЕ КОДА (CQI) | Профиль: MVP" in output
            assert "ИТОГОВАЯ ОЦЕНКА (CQI)" in output
            assert "Статус Quality Gate" in output

            json_path = root / "out.json"
            write_json_report(report, json_path)
            parsed = json.loads(json_path.read_text(encoding="utf-8"))
            assert parsed["profile"] == "mvp"
            assert "dimensions" in parsed


if __name__ == "__main__":
    unittest.main()
