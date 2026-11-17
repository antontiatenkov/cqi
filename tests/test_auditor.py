"""Unit-тесты для аудитора качества кода CQI."""

import ast
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cqi.ast_analyzer import PythonASTAnalyzer
from cqi.models import FileMetrics, clamp
from cqi.scanner import analyze_file, is_test_file, scan_directory
from cqi.scoring import compute_scores


class TestPythonASTAnalyzer(unittest.TestCase):
    """Тесты AST-анализатора Python-кода."""

    def _parse(self, source: str) -> PythonASTAnalyzer:
        """Разбирает исходный код и возвращает заполненный PythonASTAnalyzer."""
        tree = ast.parse(source)
        analyzer = PythonASTAnalyzer()
        analyzer.visit(tree)
        return analyzer

    def test_re_compile_is_not_flagged_as_dangerous(self) -> None:
        """Вызов re.compile не должен считаться опасным вызовом встроенного compile."""
        code = (
            '"""Модуль."""\n'
            "import re\n"
            'PAT = re.compile(r"abc")\n'
        )
        analyzer = self._parse(code)
        assert analyzer.dangerous_calls == 0

    def test_builtin_eval_exec_and_shell_true_are_flagged(self) -> None:
        """Встроенные eval/exec/compile и subprocess(..., shell=True) должны фиксироваться."""
        code = (
            "import subprocess\n"
            "eval('1+1')\n"
            "exec('x=1')\n"
            "compile('1', '<x>', 'eval')\n"
            "subprocess.run('ls', shell=True)\n"
        )
        analyzer = self._parse(code)
        assert analyzer.dangerous_calls == 4

    def test_dict_get_is_not_flagged_as_network_call(self) -> None:
        """Метод словаря .get() не должен считаться сетевым вызовом без timeout."""
        code = (
            "weights = {'saas': 1}\n"
            "val = weights.get('saas', 1)\n"
        )
        analyzer = self._parse(code)
        assert analyzer.network_calls_without_timeout == 0

    def test_requests_without_and_with_timeout(self) -> None:
        """Сетевой вызов requests.get фиксируется только при отсутствии timeout."""
        code = (
            "import requests\n"
            "requests.get('https://example.com')\n"
            "requests.post('https://example.com', timeout=5)\n"
        )
        analyzer = self._parse(code)
        assert analyzer.network_calls_without_timeout == 1

    def test_silent_except_not_double_counted(self) -> None:
        """Перехват except Exception: pass должен учитываться ровно один раз."""
        code = (
            "try:\n"
            "    x = 1\n"
            "except Exception:\n"
            "    pass\n"
        )
        analyzer = self._parse(code)
        assert analyzer.bare_excepts == 0
        assert analyzer.silent_excepts == 1

    def test_bare_except_and_complexity_and_typing(self) -> None:
        """Проверяет подсчет bare_excepts, CC, вложенности, docstring и type hints."""
        code = (
            '"""Doc."""\n'
            "def f(a: int, b: str) -> bool:\n"
            '    """Fn doc."""\n'
            "    if a > 0 and b:\n"
            "        for ch in b:\n"
            "            if ch == 'x':\n"
            "                return True\n"
            "    try:\n"
            "        pass\n"
            "    except:\n"
            "        return False\n"
            "    return False\n"
        )
        analyzer = self._parse(code)
        assert analyzer.functions_count == 1
        assert analyzer.bare_excepts == 1
        assert analyzer.complexities[0] >= 5
        assert analyzer.max_nesting == 3
        assert analyzer.documented_items == 2
        assert analyzer.documentable_items == 2
        assert analyzer.typed_args == 3
        assert analyzer.total_args == 3


class TestScannerAndHelpers(unittest.TestCase):
    """Тесты сканера файлов, эвристик и утилит."""

    def test_clamp_bounds(self) -> None:
        """clamp корректно ограничивает значения снизу и сверху."""
        assert clamp(-10.0) == 0.0
        assert clamp(150.0) == 100.0
        assert clamp(42.5) == 42.5

    def test_is_test_file_variants(self) -> None:
        """is_test_file распознает тестовые файлы по имени и директории."""
        assert is_test_file(Path("tests/foo.py"))
        assert is_test_file(Path("src/test_bar.py"))
        assert is_test_file(Path("src/bar.spec.ts"))
        assert not is_test_file(Path("src/main.py"))

    def test_analyze_file_js_heuristics(self) -> None:
        """Эвристика для JS-файлов корректно считает функции и опасные вызовы."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            js_file = root / "app.js"
            js_file.write_text(
                "// comment\n"
                "function run(x) {\n"
                "  if (x > 0 && x < 10) { return eval('x'); }\n"
                "  return 0;\n"
                "}\n",
                encoding="utf-8",
            )
            metrics = analyze_file(js_file, root)
            assert metrics is not None
            assert metrics.functions_count == 1
            assert metrics.dangerous_calls == 1
            assert metrics.comment_lines == 1
            assert metrics.sloc == 4

    def test_scan_directory_ignores_hidden_and_venv(self) -> None:
        """scan_directory пропускает .venv и скрытые каталоги."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".venv").mkdir()
            (root / ".venv" / "ignored.py").write_text("x = 1\n", encoding="utf-8")
            (root / "app.py").write_text('"""Ok."""\nx = 1\n', encoding="utf-8")
            files = scan_directory(root)
            assert len(files) == 1
            assert files[0].path == "app.py"


class TestScoringAndCLI(unittest.TestCase):
    """Тесты скоринга CQI, Veto-штрафов и CLI-интерфейса."""

    def test_veto_multiplier_and_quality_gate_passed(self) -> None:
        """Качественный проект с lock-файлом и тестами проходит Quality Gate."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "requirements.txt").write_text("", encoding="utf-8")
            (root / "pyproject.toml").write_text("[project]\nname='ok'\n", encoding="utf-8")
            files = [
                FileMetrics(
                    path="app.py",
                    loc=100,
                    sloc=80,
                    docstring_coverage=0.9,
                    type_hint_coverage=1.0,
                    avg_cc=2.0,
                    max_cc=4,
                    max_nesting=2,
                ),
                FileMetrics(
                    path="tests/test_app.py",
                    loc=60,
                    sloc=50,
                    is_test=True,
                    asserts_count=10,
                ),
            ]
            report = compute_scores(files, root, "saas")
            assert report.penalty_multiplier == 1.0
            assert report.quality_gate == "PASSED"
            assert report.final_cqi >= 90.0
            assert report.grade == "A (Exemplary)"

    def test_veto_triggered_by_hardcoded_secret(self) -> None:
        """Наличие секрета активирует Veto x0.50 и блокирует Quality Gate."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = [
                FileMetrics(
                    path="leak.py",
                    loc=20,
                    sloc=15,
                    hardcoded_secrets=1,
                )
            ]
            report = compute_scores(files, root, "erp")
            assert report.penalty_multiplier == 0.5
            assert report.quality_gate == "BLOCKED"

    def test_cli_json_html_svg_outputs(self) -> None:
        """CLI успешно выполняется и записывает валидные JSON, HTML и SVG отчеты."""
        with tempfile.TemporaryDirectory() as tmp:
            out_json = Path(tmp) / "report.json"
            out_html = Path(tmp) / "report.html"
            out_svg = Path(tmp) / "report.svg"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve().parent.parent / "code_quality_auditor.py"),
                    str(Path(__file__).resolve().parent.parent),
                    "--profile",
                    "saas",
                    "--json-out",
                    str(out_json),
                    "--html-out",
                    str(out_html),
                    "--svg-out",
                    str(out_svg),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            assert proc.returncode == 0
            assert out_json.exists()
            assert out_html.exists()
            assert out_svg.exists()
            data = json.loads(out_json.read_text(encoding="utf-8"))
            assert data["quality_gate"] == "PASSED"
            assert data["final_cqi"] >= 75.0
            html_text = out_html.read_text(encoding="utf-8")
            assert "<!DOCTYPE html>" in html_text
            assert "Top-5 Hotspots" in html_text
            svg_text = out_svg.read_text(encoding="utf-8")
            assert "<svg " in svg_text
            assert "GATE: PASSED" in svg_text


if __name__ == "__main__":
    unittest.main()
