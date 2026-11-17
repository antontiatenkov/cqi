"""Сканер директорий и сборщик файловых метрик."""

import ast
import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from cqi.ast_analyzer import PythonASTAnalyzer
from cqi.models import CODE_EXTENSIONS, IGNORED_DIRS, SECRET_PATTERNS, FileMetrics


def is_test_file(path: Path) -> bool:
    """Определяет, является ли файл тестовым по имени или расположению в каталоге тестов."""
    name = path.name.lower()
    parts = [p.lower() for p in path.parts]
    return (
        name.startswith("test_")
        or name.endswith(("_test.py", ".test.ts", ".test.js", ".spec.ts", ".spec.js", "_test.go"))
        or any(folder in parts for folder in ("tests", "test", "__tests__"))
    )


def _count_line_stats(lines: List[str]) -> Tuple[int, int, int, int]:
    """Подсчитывает SLOC, строки комментариев, длинные строки и маркеры техдолга."""
    sloc = 0
    comment_lines = 0
    long_lines = 0
    todo_count = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if len(line) > 100:
            long_lines += 1
        if stripped.startswith(("#", "//", "/*", "*", "--")):
            comment_lines += 1
        else:
            sloc += 1
        if re.search(r"\b(TODO|FIXME|HACK|XXX)\b", stripped):
            todo_count += 1

    return sloc, comment_lines, long_lines, todo_count


def _apply_python_ast(metrics: FileMetrics, content: str, rel_path: str) -> None:
    """Заполняет AST-метрики для Python-файла."""
    try:
        tree = ast.parse(content, filename=rel_path)
    except SyntaxError:
        metrics.bare_excepts += 1
        return

    visitor = PythonASTAnalyzer()
    visitor.visit(tree)

    metrics.functions_count = visitor.functions_count
    metrics.classes_count = visitor.classes_count
    metrics.avg_cc = (
        sum(visitor.complexities) / len(visitor.complexities)
        if visitor.complexities else 1.0
    )
    metrics.max_cc = max(visitor.complexities) if visitor.complexities else 1
    metrics.max_func_length = max(visitor.func_lengths) if visitor.func_lengths else 0
    metrics.max_nesting = visitor.max_nesting
    metrics.docstring_coverage = (
        visitor.documented_items / visitor.documentable_items
        if visitor.documentable_items > 0 else 1.0
    )
    metrics.type_hint_coverage = (
        visitor.typed_args / visitor.total_args
        if visitor.total_args > 0 else 1.0
    )
    metrics.bare_excepts = visitor.bare_excepts
    metrics.silent_excepts = visitor.silent_excepts
    metrics.network_calls_without_timeout = visitor.network_calls_without_timeout
    metrics.dangerous_calls = visitor.dangerous_calls
    metrics.imports_count = visitor.imports_count
    metrics.asserts_count = visitor.asserts_count


def _apply_generic_heuristics(metrics: FileMetrics, content: str) -> None:
    """Применяет регулярные эвристики для JS/TS/Go/Rust/Java файлов."""
    branch_matches = re.findall(
        r"\b(if|else\s+if|for|while|case|catch|\?\s*[^:]+:)\b|(\&\&|\|\|)", content
    )
    func_matches = re.findall(r"\b(function|func|def)\b|=>", content)
    funcs = max(1, len(func_matches))
    metrics.functions_count = funcs
    metrics.avg_cc = 1.0 + (len(branch_matches) / funcs)
    metrics.max_cc = int(metrics.avg_cc * 1.8)
    metrics.dangerous_calls = len(re.findall(r"\b(eval|exec|dangerouslySetInnerHTML)\b", content))
    metrics.asserts_count = len(re.findall(r"\b(assert|expect|should|require\.)\b", content))


def analyze_file(file_path: Path, root_path: Path) -> Optional[FileMetrics]:
    """Анализирует один файл исходного кода и возвращает FileMetrics или None при ошибке чтения."""
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None

    rel_path = str(file_path.relative_to(root_path))
    lines = content.splitlines()
    sloc, comment_lines, long_lines, todo_count = _count_line_stats(lines)
    secrets_found = sum(len(pattern.findall(content)) for pattern in SECRET_PATTERNS)

    metrics = FileMetrics(
        path=rel_path,
        loc=len(lines),
        sloc=sloc,
        comment_lines=comment_lines,
        long_lines=long_lines,
        todo_count=todo_count,
        is_test=is_test_file(file_path),
        hardcoded_secrets=secrets_found,
    )

    if file_path.suffix == ".py" and sloc > 0:
        _apply_python_ast(metrics, content, rel_path)
    elif file_path.suffix != ".py":
        _apply_generic_heuristics(metrics, content)

    return metrics


def scan_directory(root_path: Path) -> List[FileMetrics]:
    """Рекурсивно обходит директорию проекта, пропуская служебные каталоги."""
    results: List[FileMetrics] = []
    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS and not d.startswith(".")]
        for fname in filenames:
            fpath = Path(dirpath) / fname
            if fpath.suffix.lower() in CODE_EXTENSIONS:
                metrics = analyze_file(fpath, root_path)
                if metrics is not None:
                    results.append(metrics)
    return results
