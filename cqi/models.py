"""Модели данных, константы и базовые утилиты для аудитора качества кода CQI."""

import re
from dataclasses import dataclass, field
from typing import Dict, List

IGNORED_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv",
    "env", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist",
    "build", "target", "vendor", ".idea", ".vscode", "coverage", "htmlcov",
}

CODE_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java"}

SECRET_PATTERNS = [
    re.compile(
        r"(?i)(api[_-]?key|secret[_-]?key|access[_-]?token|password|passwd|private[_-]?key)"
        r"\s*[:=]\s*['\"][A-Za-z0-9_\-]{12,}['\"]"
    ),
    re.compile(r"-----BEGIN (RSA|OPENSSH|EC|PGP) PRIVATE KEY-----"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    re.compile(r"sk-[A-Za-z0-9]{32,}"),
]

DANGEROUS_CALLS_PY = {"eval", "exec", "compile", "__import__"}
SUBPROCESS_CALLS_PY = {"Popen", "run", "call"}
NETWORK_CALLS_PY = {"get", "post", "put", "delete", "patch", "request", "urlopen"}
NETWORK_RECEIVERS_PY = {
    "requests", "httpx", "urllib", "session", "client", "http", "aiohttp",
}

LOCKFILES = (
    "poetry.lock", "uv.lock", "Pipfile.lock", "requirements.txt",
    "package-lock.json", "pnpm-lock.yaml", "go.sum", "Cargo.lock",
)

INFRA_FILES = (
    "Dockerfile", "docker-compose.yml", "compose.yaml",
    ".github", ".gitlab-ci.yml", "Makefile", "pyproject.toml",
)

WEIGHTS_MAP: Dict[str, Dict[str, float]] = {
    "saas": {
        "maintainability": 0.25,
        "readability": 0.20,
        "resilience": 0.20,
        "security": 0.20,
        "testability": 0.15,
    },
    "erp": {
        "maintainability": 0.20,
        "readability": 0.10,
        "resilience": 0.25,
        "security": 0.30,
        "testability": 0.15,
    },
    "mvp": {
        "maintainability": 0.30,
        "readability": 0.30,
        "resilience": 0.15,
        "security": 0.15,
        "testability": 0.10,
    },
}


@dataclass
class FileMetrics:
    """Собранные статические метрики для одного файла исходного кода."""

    path: str
    loc: int = 0
    sloc: int = 0
    comment_lines: int = 0
    long_lines: int = 0
    todo_count: int = 0
    is_test: bool = False
    functions_count: int = 0
    classes_count: int = 0
    avg_cc: float = 1.0
    max_cc: int = 1
    max_func_length: int = 0
    max_nesting: int = 0
    docstring_coverage: float = 1.0
    type_hint_coverage: float = 1.0
    bare_excepts: int = 0
    silent_excepts: int = 0
    network_calls_without_timeout: int = 0
    dangerous_calls: int = 0
    hardcoded_secrets: int = 0
    imports_count: int = 0
    asserts_count: int = 0


@dataclass
class DimensionScore:
    """Итоговая оценка и штрафы по одному из 5 направлений CQI."""

    name: str
    weight: float
    score: float
    weighted_score: float
    penalties: List[str] = field(default_factory=list)
    metrics_summary: Dict[str, float] = field(default_factory=dict)


@dataclass
class AuditReport:
    """Полный отчет аудита качества кодовой базы (CQI)."""

    project_path: str
    profile: str
    files_scanned: int
    total_sloc: int
    test_sloc: int
    raw_cqi: float
    penalty_multiplier: float
    final_cqi: float
    grade: str
    quality_gate: str
    dimensions: Dict[str, DimensionScore]
    hotspots: List[Dict[str, object]]


def clamp(val: float, low: float = 0.0, high: float = 100.0) -> float:
    """Ограничивает числовое значение заданным диапазоном [low, high]."""
    return max(low, min(high, val))
