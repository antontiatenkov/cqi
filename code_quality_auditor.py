#!/usr/bin/env python3
"""
Автоматизированный аудитор качества кодовой базы (Code Quality Index - CQI).
Точка входа CLI, делегирующая анализ, расчет метрик и вывод отчета пакету cqi.
"""

import argparse
import sys
from pathlib import Path

from cqi import (
    AuditReport,
    DimensionScore,
    FileMetrics,
    PythonASTAnalyzer,
    analyze_file,
    clamp,
    compute_scores,
    is_test_file,
    print_cli_report,
    scan_directory,
    write_html_report,
    write_json_report,
    write_svg_report,
)

__all__ = [
    "AuditReport",
    "DimensionScore",
    "FileMetrics",
    "PythonASTAnalyzer",
    "analyze_file",
    "clamp",
    "compute_scores",
    "is_test_file",
    "main",
    "print_cli_report",
    "scan_directory",
]


def main() -> None:
    """Разбирает аргументы CLI, запускает аудит и выводит отчет."""
    parser = argparse.ArgumentParser(
        description="Аудитор качества кода проекта по 5 направлениям (CQI)."
    )
    parser.add_argument("path", nargs="?", default=".", help="Путь к папке с файлами проекта")
    parser.add_argument(
        "--profile",
        choices=["saas", "erp", "mvp"],
        default="saas",
        help="Профиль весов (saas, erp, mvp)",
    )
    parser.add_argument("--json-out", type=str, default="", help="Путь для сохранения JSON-отчета")
    parser.add_argument("--html-out", type=str, default="", help="Путь для сохранения HTML-отчета (Lighthouse)")
    parser.add_argument("--svg-out", type=str, default="", help="Путь для сохранения SVG-отчета (Lighthouse)")
    args = parser.parse_args()

    target = Path(args.path).resolve()
    if not target.exists():
        print(f"Ошибка: путь {target} не существует.", file=sys.stderr)
        sys.exit(1)

    files = scan_directory(target)
    report = compute_scores(files, target, args.profile)
    print_cli_report(report)

    if args.json_out:
        write_json_report(report, Path(args.json_out))
    if args.html_out:
        write_html_report(report, Path(args.html_out))
    if args.svg_out:
        write_svg_report(report, Path(args.svg_out))


if __name__ == "__main__":
    main()
