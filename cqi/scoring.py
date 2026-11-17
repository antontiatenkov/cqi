"""Расчет оценок по 5 направлениям CQI, Veto-штрафов, грейда и Quality Gate."""

from pathlib import Path
from typing import Dict, List, Tuple

from cqi.models import (
    INFRA_FILES,
    LOCKFILES,
    WEIGHTS_MAP,
    AuditReport,
    DimensionScore,
    FileMetrics,
    clamp,
)


def _score_maintainability(
    prod_files: List[FileMetrics], total_sloc: int, weight: float
) -> DimensionScore:
    """Рассчитывает оценку направления Поддерживаемость (Maintainability)."""
    weighted_cc = sum(f.avg_cc * f.sloc for f in prod_files) / max(1, total_sloc)
    max_cc_global = max((f.max_cc for f in prod_files), default=1)
    oversized_files = sum(1 for f in prod_files if f.sloc > 400)
    oversized_funcs = sum(1 for f in prod_files if f.max_func_length > 60)
    avg_imports = sum(f.imports_count for f in prod_files) / max(1, len(prod_files))

    cc_score = clamp(100.0 - max(0.0, (weighted_cc - 4.0) * 7.5))
    file_size_score = clamp(100.0 - (oversized_files / max(1, len(prod_files))) * 150.0)
    func_size_score = clamp(100.0 - (oversized_funcs / max(1, len(prod_files))) * 120.0)
    coupling_score = clamp(100.0 - max(0.0, (avg_imports - 12.0) * 4.0))

    score = clamp(0.40 * cc_score + 0.25 * file_size_score + 0.20 * func_size_score + 0.15 * coupling_score)
    penalties: List[str] = []
    if max_cc_global > 15:
        penalties.append(f"Высокая пиковая цикломатическая сложность (max CC = {max_cc_global})")
    if oversized_files > 0:
        penalties.append(f"Обнаружено {oversized_files} файлов размером более 400 SLOC")

    return DimensionScore(
        name="Поддерживаемость (Maintainability)",
        weight=weight,
        score=round(score, 1),
        weighted_score=round(score * weight, 2),
        penalties=penalties,
        metrics_summary={
            "avg_cc": round(weighted_cc, 2),
            "max_cc": max_cc_global,
            "oversized_files": oversized_files,
        },
    )


def _score_readability(
    prod_files: List[FileMetrics], total_sloc: int, weight: float
) -> DimensionScore:
    """Рассчитывает оценку направления Читаемость (Readability)."""
    max_nesting_global = max((f.max_nesting for f in prod_files), default=0)
    avg_doc = sum(f.docstring_coverage * f.sloc for f in prod_files) / max(1, total_sloc)
    long_line_ratio = sum(f.long_lines for f in prod_files) / max(1, sum(f.loc for f in prod_files))
    todo_density = (sum(f.todo_count for f in prod_files) / max(1, total_sloc)) * 1000.0

    nesting_score = clamp(100.0 - max(0, max_nesting_global - 3) * 15.0)
    doc_score = clamp(min(100.0, (avg_doc / 0.60) * 100.0))
    line_score = clamp(100.0 - long_line_ratio * 300.0)
    todo_score = clamp(100.0 - todo_density * 3.5)

    score = clamp(0.35 * nesting_score + 0.30 * doc_score + 0.20 * line_score + 0.15 * todo_score)
    penalties: List[str] = []
    if max_nesting_global > 4:
        penalties.append(f"Глубокая вложенность управляющих конструкций ({max_nesting_global} уровней)")
    if avg_doc < 0.35:
        penalties.append(f"Низкое покрытие docstring/комментариями ({avg_doc * 100:.1f}%)")

    return DimensionScore(
        name="Читаемость (Readability)",
        weight=weight,
        score=round(score, 1),
        weighted_score=round(score * weight, 2),
        penalties=penalties,
        metrics_summary={
            "max_nesting": max_nesting_global,
            "docstring_cov": round(avg_doc, 2),
            "todo_per_kloc": round(todo_density, 2),
        },
    )


def _score_resilience(
    prod_files: List[FileMetrics], total_sloc: int, weight: float
) -> DimensionScore:
    """Рассчитывает оценку направления Отказоустойчивость (Resilience)."""
    bare_excepts = sum(f.bare_excepts for f in prod_files)
    silent_excepts = sum(f.silent_excepts for f in prod_files)
    unbounded_net = sum(f.network_calls_without_timeout for f in prod_files)
    avg_typing = sum(f.type_hint_coverage * f.sloc for f in prod_files) / max(1, total_sloc)

    exc_score = clamp(100.0 - (bare_excepts * 18.0 + silent_excepts * 12.0))
    net_score = clamp(100.0 - unbounded_net * 15.0)
    typing_score = clamp(avg_typing * 100.0)

    score = clamp(0.45 * exc_score + 0.30 * net_score + 0.25 * typing_score)
    penalties: List[str] = []
    if bare_excepts > 0 or silent_excepts > 0:
        penalties.append(
            f"Подавление или перехват неспецифичных исключений (bare: {bare_excepts}, silent: {silent_excepts})"
        )
    if unbounded_net > 0:
        penalties.append(f"Сетевые вызовы без явного timeout ({unbounded_net} шт.)")

    return DimensionScore(
        name="Отказоустойчивость (Resilience)",
        weight=weight,
        score=round(score, 1),
        weighted_score=round(score * weight, 2),
        penalties=penalties,
        metrics_summary={
            "bare_excepts": bare_excepts,
            "silent_excepts": silent_excepts,
            "type_hint_cov": round(avg_typing, 2),
        },
    )


def _score_security(
    all_files: List[FileMetrics], prod_files: List[FileMetrics], root_path: Path, weight: float
) -> Tuple[DimensionScore, int]:
    """Рассчитывает оценку направления Безопасность (Security) и возвращает число секретов."""
    secrets_total = sum(f.hardcoded_secrets for f in all_files)
    dangerous_total = sum(f.dangerous_calls for f in prod_files)
    has_lockfile = any((root_path / name).exists() for name in LOCKFILES)

    score = clamp(100.0 - secrets_total * 45.0 - dangerous_total * 20.0 - (0.0 if has_lockfile else 10.0))
    penalties: List[str] = []
    if secrets_total > 0:
        penalties.append(f"КРИТИЧНО: Обнаружены потенциальные захардкоженные секреты ({secrets_total} шт.)")
    if dangerous_total > 0:
        penalties.append(f"Использование небезопасных вызовов eval/exec/shell=True ({dangerous_total} шт.)")
    if not has_lockfile:
        penalties.append("Отсутствует манифест или lock-файл зависимостей в корне проекта")

    dim = DimensionScore(
        name="Безопасность (Security)",
        weight=weight,
        score=round(score, 1),
        weighted_score=round(score * weight, 2),
        penalties=penalties,
        metrics_summary={"secrets_found": secrets_total, "dangerous_calls": dangerous_total},
    )
    return dim, secrets_total


def _score_testability(
    prod_files: List[FileMetrics],
    test_files: List[FileMetrics],
    total_sloc: int,
    test_sloc: int,
    root_path: Path,
    weight: float,
) -> DimensionScore:
    """Рассчитывает оценку направления Тестируемость (Testability)."""
    test_ratio = test_sloc / max(1, total_sloc)
    total_asserts = sum(f.asserts_count for f in test_files)
    has_ci_or_docker = any((root_path / name).exists() for name in INFRA_FILES)

    ratio_score = clamp(min(100.0, (test_ratio / 0.50) * 100.0))
    assert_score = clamp(min(100.0, (total_asserts / max(1, len(prod_files) * 3)) * 100.0))
    infra_score = 100.0 if has_ci_or_docker else 50.0

    score = clamp(0.55 * ratio_score + 0.30 * assert_score + 0.15 * infra_score)
    penalties: List[str] = []
    if test_ratio < 0.15:
        penalties.append(f"Низкое соотношение объема тестов к коду (Test-to-Code Ratio = {test_ratio:.2f})")

    return DimensionScore(
        name="Тестируемость (Testability)",
        weight=weight,
        score=round(score, 1),
        weighted_score=round(score * weight, 2),
        penalties=penalties,
        metrics_summary={"test_to_code_ratio": round(test_ratio, 2), "total_asserts": total_asserts},
    )


def _determine_verdict(
    raw_cqi: float, dimensions: Dict[str, DimensionScore], secrets_total: int
) -> Tuple[float, float, str, str]:
    """Определяет Veto-мультипликатор, итоговый CQI, грейд и статус Quality Gate."""
    min_dim_score = min(d.score for d in dimensions.values())
    penalty_multiplier = 1.0
    if secrets_total > 0 or dimensions["security"].score < 40.0:
        penalty_multiplier = 0.5
    elif min_dim_score < 50.0:
        penalty_multiplier = 0.8

    final_cqi = round(raw_cqi * penalty_multiplier, 1)

    grade_thresholds = (
        (90.0, "A (Exemplary)"),
        (75.0, "B (Good)"),
        (60.0, "C (Acceptable)"),
        (45.0, "D (High Debt)"),
    )
    grade = next((label for thr, label in grade_thresholds if final_cqi >= thr), "F (Critical)")

    if final_cqi >= 70.0 and penalty_multiplier == 1.0:
        quality_gate = "PASSED"
    elif final_cqi >= 55.0 and penalty_multiplier >= 0.8:
        quality_gate = "WARN"
    else:
        quality_gate = "BLOCKED"

    return penalty_multiplier, final_cqi, grade, quality_gate


def _build_hotspots(prod_files: List[FileMetrics]) -> List[Dict[str, object]]:
    """Формирует топ-5 проблемных файлов (hotspots)."""
    items = [
        {
            "path": f.path,
            "sloc": f.sloc,
            "max_cc": f.max_cc,
            "max_nesting": f.max_nesting,
            "issues": f.bare_excepts + f.silent_excepts + f.dangerous_calls + f.hardcoded_secrets,
        }
        for f in prod_files
    ]
    return sorted(
        items,
        key=lambda x: (int(x["issues"]) * 10 + int(x["max_cc"]) + int(x["sloc"]) // 100),
        reverse=True,
    )[:5]


def compute_scores(files: List[FileMetrics], root_path: Path, profile: str) -> AuditReport:
    """Агрегирует файловые метрики и формирует итоговый AuditReport."""
    weights = WEIGHTS_MAP.get(profile, WEIGHTS_MAP["saas"])

    prod_files = [f for f in files if not f.is_test and f.sloc > 0]
    test_files = [f for f in files if f.is_test and f.sloc > 0]

    total_sloc = sum(f.sloc for f in prod_files)
    test_sloc = sum(f.sloc for f in test_files)

    if not prod_files:
        prod_files = files if files else [FileMetrics(path="empty", sloc=1)]
        total_sloc = max(1, sum(f.sloc for f in prod_files))

    sec_dim, secrets_total = _score_security(files, prod_files, root_path, weights["security"])
    dimensions = {
        "maintainability": _score_maintainability(prod_files, total_sloc, weights["maintainability"]),
        "readability": _score_readability(prod_files, total_sloc, weights["readability"]),
        "resilience": _score_resilience(prod_files, total_sloc, weights["resilience"]),
        "security": sec_dim,
        "testability": _score_testability(
            prod_files, test_files, total_sloc, test_sloc, root_path, weights["testability"]
        ),
    }

    raw_cqi = sum(d.weighted_score for d in dimensions.values())
    penalty_multiplier, final_cqi, grade, quality_gate = _determine_verdict(
        raw_cqi, dimensions, secrets_total
    )

    return AuditReport(
        project_path=str(root_path),
        profile=profile,
        files_scanned=len(files),
        total_sloc=total_sloc,
        test_sloc=test_sloc,
        raw_cqi=round(raw_cqi, 1),
        penalty_multiplier=penalty_multiplier,
        final_cqi=final_cqi,
        grade=grade,
        quality_gate=quality_gate,
        dimensions=dimensions,
        hotspots=_build_hotspots(prod_files),
    )
