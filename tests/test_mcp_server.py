"""Unit-тесты для stdio MCP-сервера CQI."""

import io
import json
import tempfile
import unittest
from pathlib import Path

from cqi.mcp_server import handle_request, serve_stdio


class TestMCPServer(unittest.TestCase):
    """Тесты JSON-RPC 2.0 обработчиков MCP-сервера."""

    def test_initialize_and_tools_list(self) -> None:
        """Проверяет handshake initialize и список инструментов tools/list."""
        init_resp = handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert init_resp is not None
        assert init_resp["result"]["serverInfo"]["name"] == "cqi-mcp"
        assert "tools" in init_resp["result"]["capabilities"]

        list_resp = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert list_resp is not None
        tool_names = {t["name"] for t in list_resp["result"]["tools"]}
        assert tool_names == {"audit_project", "audit_file", "render_lighthouse_report"}

    def test_notifications_return_none(self) -> None:
        """Уведомления без id не должны порождать ответ."""
        resp = handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert resp is None

    def test_tools_call_audit_project_and_lighthouse(self) -> None:
        """Вызов audit_project и render_lighthouse_report возвращает валидные результаты."""
        project_root = str(Path(__file__).resolve().parent.parent)
        with tempfile.TemporaryDirectory() as tmp:
            svg_path = Path(tmp) / "out.svg"
            resp = handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "audit_project",
                        "arguments": {"path": project_root, "profile": "saas", "svg_out": str(svg_path)},
                    },
                }
            )
            assert resp is not None
            assert resp["result"]["isError"] is False
            data = json.loads(resp["result"]["content"][0]["text"])
            assert data["quality_gate"] == "PASSED"
            assert svg_path.exists()

        html_resp = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "render_lighthouse_report",
                    "arguments": {"path": project_root, "format": "html"},
                },
            }
        )
        assert html_resp is not None
        assert "<!DOCTYPE html>" in html_resp["result"]["content"][0]["text"]

    def test_tools_call_audit_file_and_error_handling(self) -> None:
        """Проверяет audit_file и обработку ошибок несуществующего пути."""
        target_file = str(Path(__file__).resolve().parent.parent / "cqi" / "models.py")
        resp = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "audit_file", "arguments": {"file_path": target_file}},
            }
        )
        assert resp is not None
        assert resp["result"]["isError"] is False
        metrics = json.loads(resp["result"]["content"][0]["text"])
        assert metrics["sloc"] > 0

        err_resp = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {"name": "audit_project", "arguments": {"path": "/nonexistent/cqi/path"}},
            }
        )
        assert err_resp is not None
        assert err_resp["result"]["isError"] is True

    def test_serve_stdio_roundtrip(self) -> None:
        """Проверяет потоковый цикл serve_stdio на нескольких строках."""
        inp = io.StringIO(
            '{"jsonrpc":"2.0","id":1,"method":"ping"}\n'
            '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
            "{invalid json\n"
        )
        out = io.StringIO()
        serve_stdio(inp, out)
        lines = out.getvalue().strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["result"] == {}
        assert json.loads(lines[1])["error"]["code"] == -32700


if __name__ == "__main__":
    unittest.main()
