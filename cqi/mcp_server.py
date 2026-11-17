"""Stdio MCP-сервер (JSON-RPC 2.0) для аудитора качества кода CQI."""

import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TextIO

from cqi.lighthouse_reporter import (
    render_html_report,
    render_svg_report,
    write_html_report,
    write_svg_report,
)
from cqi.reporter import write_json_report
from cqi.scanner import analyze_file, scan_directory
from cqi.scoring import compute_scores

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "cqi-mcp", "version": "0.1.0"}
VALID_PROFILES = ("saas", "erp", "mvp")

TOOLS_SCHEMA: List[Dict[str, Any]] = [
    {
        "name": "audit_project",
        "description": (
            "Запускает аудит качества кода директории проекта по 5 направлениям CQI "
            "и опционально сохраняет JSON/HTML/SVG отчеты в стиле Google Lighthouse."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Путь к директории проекта"},
                "profile": {
                    "type": "string",
                    "enum": list(VALID_PROFILES),
                    "default": "saas",
                    "description": "Профиль весов (saas, erp, mvp)",
                },
                "json_out": {"type": "string", "description": "Опциональный путь для JSON-отчета"},
                "html_out": {"type": "string", "description": "Опциональный путь для HTML-отчета"},
                "svg_out": {"type": "string", "description": "Опциональный путь для SVG-отчета"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "audit_file",
        "description": "Собирает статические AST- и структурные метрики (FileMetrics) для одного файла.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Путь к файлу исходного кода"},
                "root_path": {"type": "string", "description": "Корневая директория проекта (опционально)"},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "render_lighthouse_report",
        "description": "Генерирует отчет CQI в стиле Google Lighthouse в формате SVG или HTML.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Путь к директории проекта"},
                "format": {
                    "type": "string",
                    "enum": ["svg", "html"],
                    "default": "svg",
                    "description": "Формат отчета (svg или html)",
                },
                "profile": {
                    "type": "string",
                    "enum": list(VALID_PROFILES),
                    "default": "saas",
                    "description": "Профиль весов (saas, erp, mvp)",
                },
            },
            "required": ["path"],
        },
    },
]


def _validate_profile(profile: str) -> str:
    """Проверяет корректность профиля весов CQI."""
    if profile not in VALID_PROFILES:
        raise ValueError(f"Неизвестный профиль '{profile}'. Допустимые: {', '.join(VALID_PROFILES)}")
    return profile


def _tool_audit_project(args: Dict[str, Any]) -> str:
    """Выполняет аудит директории и возвращает JSON с отчетом."""
    target = Path(str(args["path"])).resolve()
    if not target.exists() or not target.is_dir():
        raise FileNotFoundError(f"Директория не найдена: {target}")

    profile = _validate_profile(str(args.get("profile", "saas")))
    files = scan_directory(target)
    report = compute_scores(files, target, profile)

    if args.get("json_out"):
        write_json_report(report, Path(str(args["json_out"])))
    if args.get("html_out"):
        write_html_report(report, Path(str(args["html_out"])))
    if args.get("svg_out"):
        write_svg_report(report, Path(str(args["svg_out"])))

    return json.dumps(asdict(report), ensure_ascii=False, indent=2)


def _tool_audit_file(args: Dict[str, Any]) -> str:
    """Анализирует один файл и возвращает FileMetrics в JSON."""
    file_path = Path(str(args["file_path"])).resolve()
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"Файл не найден: {file_path}")

    root_arg = args.get("root_path")
    root_path = Path(str(root_arg)).resolve() if root_arg else file_path.parent
    metrics = analyze_file(file_path, root_path)
    if metrics is None:
        raise RuntimeError(f"Не удалось прочитать файл: {file_path}")

    return json.dumps(asdict(metrics), ensure_ascii=False, indent=2)


def _tool_render_lighthouse(args: Dict[str, Any]) -> str:
    """Генерирует и возвращает SVG или HTML отчет в стиле Lighthouse."""
    target = Path(str(args["path"])).resolve()
    if not target.exists() or not target.is_dir():
        raise FileNotFoundError(f"Директория не найдена: {target}")

    profile = _validate_profile(str(args.get("profile", "saas")))
    fmt = str(args.get("format", "svg")).lower()
    if fmt not in ("svg", "html"):
        raise ValueError(f"Неподдерживаемый формат '{fmt}'. Используйте 'svg' или 'html'.")

    report = compute_scores(scan_directory(target), target, profile)
    return render_html_report(report) if fmt == "html" else render_svg_report(report)


_TOOL_HANDLERS: Dict[str, Callable[[Dict[str, Any]], str]] = {
    "audit_project": _tool_audit_project,
    "audit_file": _tool_audit_file,
    "render_lighthouse_report": _tool_render_lighthouse,
}


def _jsonrpc_result(req_id: Any, result: Any) -> Dict[str, Any]:
    """Формирует успешный JSON-RPC 2.0 ответ."""
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _jsonrpc_error(req_id: Any, code: int, message: str) -> Dict[str, Any]:
    """Формирует JSON-RPC 2.0 ответ с ошибкой."""
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _handle_tools_call(req_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Обрабатывает вызов инструмента tools/call."""
    name = params.get("name", "")
    args = params.get("arguments") or {}
    handler = _TOOL_HANDLERS.get(name)
    if handler is None:
        return _jsonrpc_error(req_id, -32601, f"Неизвестный инструмент: {name}")

    try:
        text = handler(args)
        return _jsonrpc_result(req_id, {"content": [{"type": "text", "text": text}], "isError": False})
    except (ValueError, FileNotFoundError, KeyError, RuntimeError) as exc:
        return _jsonrpc_result(req_id, {"content": [{"type": "text", "text": str(exc)}], "isError": True})


def handle_request(request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Маршрутизирует входящее JSON-RPC 2.0 сообщение и возвращает ответ или None для уведомлений."""
    method = request.get("method")
    req_id = request.get("id")
    params = request.get("params") or {}

    if req_id is None:
        return None

    if method == "initialize":
        return _jsonrpc_result(
            req_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        )
    if method == "ping":
        return _jsonrpc_result(req_id, {})
    if method == "tools/list":
        return _jsonrpc_result(req_id, {"tools": TOOLS_SCHEMA})
    if method == "tools/call":
        return _handle_tools_call(req_id, params)

    return _jsonrpc_error(req_id, -32601, f"Метод не поддерживается: {method}")


def serve_stdio(stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
    """Читает JSON-RPC запросы построчно из stdin и пишет ответы в stdout."""
    for raw_line in stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            resp: Optional[Dict[str, Any]] = _jsonrpc_error(None, -32700, f"Ошибка парсинга JSON: {exc}")
        else:
            resp = handle_request(payload)

        if resp is not None:
            stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            stdout.flush()


def main() -> None:
    """Точка входа stdio MCP-сервера CQI."""
    serve_stdio()


if __name__ == "__main__":
    main()
