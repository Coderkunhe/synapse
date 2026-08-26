"""P16-B6 任务 C — worker-health-report.sh CLI 测试。

覆盖契约要求的三条路径：
  1. 成功 — 端点 200 返回六字段 JSON → stdout 表格输出 + exit 0
  2. 缺参数 — 无 <worker_id> → usage 打到 stderr + exit 2
  3. 未知 worker — 端点 404 → 错误信息含 HTTP 状态码打到 stderr + 非零退出

三条路径用本地 mock HTTP server 提供确定性端点响应，不依赖运行中的
Synapse 服务（该服务可能未部署任务 B 的 health-summary 端点）。
"""

from __future__ import annotations

import http.server
import json
import os
import subprocess
import threading
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
SCRIPT = TOOLS_DIR / "worker-health-report.sh"

# 成功路径的六字段响应（字段名为任务 B 定义的响应契约，不得擅改）
OK_BODY = {
    "worker_id": "ag_ok",
    "last_heartbeat_at": "2026-08-26T12:00:00Z",
    "heartbeat_count": 42,
    "avg_interval_seconds": 60.5,
    "is_online": True,
    "window_hours": 24,
}


class _Handler(http.server.BaseHTTPRequestHandler):
    """确定性 mock：/workers/ag_ok/health-summary → 200，其余 → 404。"""

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/v1/workers/ag_ok/health-summary"):
            self._respond(200, OK_BODY)
        else:
            self._respond(404, {"detail": "worker not found"})

    def _respond(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:  # noqa: D102
        pass


@pytest.fixture(scope="module")
def mock_api() -> str:
    """启动一次性 mock HTTP server，返回其 base URL。"""
    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()


def _run_cli(api_url: str, *args: str) -> subprocess.CompletedProcess:
    """以显式连接信息运行 CLI（覆盖 .claude/.env 回退）。"""
    env = os.environ.copy()
    env["SYNAPSE_API_URL"] = api_url
    env["SYNAPSE_API_KEY"] = "sk-syn-test"
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


class TestSuccess:
    def test_six_fields_tabulated_to_stdout(self, mock_api: str):
        result = _run_cli(mock_api, "ag_ok")

        assert result.returncode == 0, (
            f"expected exit 0, got {result.returncode}\n"
            f"stderr:\n{result.stderr}"
        )
        # 六个字段名 + 值均须出现在 stdout
        assert "worker_id" in result.stdout
        assert "ag_ok" in result.stdout
        assert "last_heartbeat_at" in result.stdout
        assert "2026-08-26T12:00:00Z" in result.stdout
        assert "heartbeat_count" in result.stdout
        assert "42" in result.stdout
        assert "avg_interval_seconds" in result.stdout
        assert "60.5" in result.stdout
        assert "is_online" in result.stdout
        assert "true" in result.stdout
        assert "window_hours" in result.stdout
        assert "24" in result.stdout


class TestMissingArg:
    def test_usage_to_stderr_exit_2(self, mock_api: str):
        result = _run_cli(mock_api)

        assert result.returncode == 2, (
            f"expected exit 2, got {result.returncode}\n"
            f"stderr:\n{result.stderr}"
        )
        assert "usage" in result.stderr.lower()
        assert result.stdout == ""


class TestUnknownWorker:
    def test_404_error_to_stderr_nonzero(self, mock_api: str):
        result = _run_cli(mock_api, "ag_unknown")

        assert result.returncode != 0, (
            f"expected non-zero exit, got {result.returncode}\n"
            f"stdout:\n{result.stdout}"
        )
        # 契约：错误信息含 HTTP 状态码，打到 stderr
        assert "404" in result.stderr
        assert "error" in result.stderr.lower()
        assert result.stdout == ""
