"""Форматирование и вывод CLI-отчета и JSON-артефактов CQI."""

import json
from dataclasses import asdict
from pathlib import Path

from cqi.models import AuditReport


def print_cli_report(report: AuditReport) -> None:
    """Выводит структурированный отчет CQI в стандартный вывод."""
    print("=" * 72)
    print(f" ОТЧЕТ О КАЧЕСТВЕ КОДА (CQI) | Профиль: {report.profile.upper()}")
    print("=" * 72)
    print(f" Директория : {report.project_path}")
    print(f" Файлов     : {report.files_scanned} | Продуктовый SLOC: {report.total_sloc} | Тестовый SLOC: {report.test_sloc}")
    print("-" * 72)
    for dim in report.dimensions.values():
        w_pct = int(dim.weight * 100)
        print(f" [{w_pct:2d}%] {dim.name:<36} : {dim.score:5.1f} / 100 (вклад: {dim.weighted_score:5.2f})")
        for pen in dim.penalties:
            print(f"       ! {pen}")
    print("-" * 72)
    print(f" Базовый индекс (Raw CQI) : {report.raw_cqi:5.1f}")
    print(f" Коэффициент Veto-штрафа  : x{report.penalty_multiplier:.2f}")
    print(f" ИТОГОВАЯ ОЦЕНКА (CQI)    : {report.final_cqi:5.1f} / 100  -->  Грейд: {report.grade}")
    print(f" Статус Quality Gate      : {report.quality_gate}")
    print("=" * 72)


def write_json_report(report: AuditReport, output_path: Path) -> None:
    """Сохраняет отчет CQI в JSON-файл."""
    output_path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")
