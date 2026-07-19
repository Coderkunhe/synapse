"""S-024(b) doc-curl gate test.

Verifies check-doc-curl.sh correctly detects structural issues
in curl commands within onboarding.md bash blocks:
- Broken URL patterns (wrong /v1/ path)
- Missing Authorization header
- Invalid JSON body syntax
- Clean pass on well-formed doc
"""

import os
import subprocess
from pathlib import Path


def run_doc_curl_check(repo: Path, onboarding_content: str) -> subprocess.CompletedProcess:
    """Create a mock onboarding.md and run check-doc-curl.sh against it.

    Args:
        repo: temp directory to create the mock file in
        onboarding_content: content of the mock onboarding.md

    Returns:
        CompletedProcess with stdout, stderr, returncode
    """
    docs_dir = repo / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "onboarding.md").write_text(onboarding_content)

    script_path = Path(__file__).resolve().parent.parent.parent / "tools" / "check-doc-curl.sh"
    env = os.environ.copy()
    env["CHECK_ONBOARDING"] = str(docs_dir / "onboarding.md")

    return subprocess.run(
        ["bash", str(script_path)],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


# ── Valid doc fixtures ──────────────────────────────────────────

VALID_ONBOARDING = """# Test Onboarding

## Quick Start

```bash
curl -X POST http://localhost:8000/v1/teams/tea_019f45fe0000/agents \\
  -H "Authorization: Bearer eyJ...admin..." \\
  -H "Content-Type: application/json" \\
  -d '{"name": "Test Worker", "provider": "claude"}'
```

## Worker API

```bash
curl -X POST http://localhost:8000/v1/agents/ag_019f45fe0001/handshake \\
  -H "Authorization: Bearer sk-syn-1234...5678" \\
  -H "Content-Type: application/json" \\
  -d '{"worker_version": "1.0.0", "capabilities": []}'

curl -X POST http://localhost:8000/v1/agents/ag_019f45fe0001/heartbeat \\
  -H "Authorization: Bearer sk-syn-1234...5678" \\
  -H "Content-Type: application/json" \\
  -d '{"current_load": 0}'
```

## Task API

```bash
curl -X POST 'http://localhost:8000/v1/tasks/tsk_019f45fe0002/claim?expected_version=2' \\
  -H "Authorization: Bearer sk-syn-1234...5678"
```

```bash
curl "http://localhost:8000/v1/projects/prj_019f45fe0003/tasks?owner_id=ag_019f45fe0001" \\
  -H "Authorization: Bearer sk-syn-1234...5678"
```
"""


def test_all_valid_passes(tmp_path):
    """Well-formed curl commands → all pass, exit 0."""
    result = run_doc_curl_check(tmp_path, VALID_ONBOARDING)

    assert result.returncode == 0, f"Expected exit 0, got {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "全部" in result.stdout
    assert "通过" in result.stdout


# ── Error detection tests ──────────────────────────────────────

def test_catches_missing_auth(tmp_path):
    """Curl without Authorization header → error detected."""
    doc = """# Missing Auth

```bash
curl -X POST http://localhost:8000/v1/agents/ag_019f45fe0001/heartbeat \\
  -H "Content-Type: application/json" \\
  -d '{"current_load": 0}'
```
"""
    result = run_doc_curl_check(tmp_path, doc)

    assert result.returncode == 1, f"Expected exit 1 for missing auth\nstdout:\n{result.stdout}"
    assert "Authorization" in result.stdout


def test_catches_invalid_json_body(tmp_path):
    """Curl with malformed JSON body → error detected."""
    doc = """# Invalid JSON

```bash
curl -X POST http://localhost:8000/v1/agents/ag_019f45fe0001/handshake \\
  -H "Authorization: Bearer sk-syn-1234...5678" \\
  -H "Content-Type: application/json" \\
  -d '{worker_version: "1.0.0", capabilities: [}'
```
"""
    result = run_doc_curl_check(tmp_path, doc)

    assert result.returncode == 1, f"Expected exit 1 for invalid JSON\nstdout:\n{result.stdout}"
    assert "JSON" in result.stdout


def test_catches_broken_url_pattern(tmp_path):
    """Curl with non-/v1/ URL → error detected."""
    doc = """# Wrong URL

```bash
curl -X POST http://localhost:8000/api/v2/agents/ag_019f45fe0001/heartbeat \\
  -H "Authorization: Bearer sk-syn-1234...5678" \\
  -H "Content-Type: application/json" \\
  -d '{"current_load": 0}'
```
"""
    result = run_doc_curl_check(tmp_path, doc)

    assert result.returncode == 1, f"Expected exit 1 for wrong URL\nstdout:\n{result.stdout}"
    assert "v1/" in result.stdout


def test_catches_missing_url(tmp_path):
    """Curl without http:// URL → error detected."""
    doc = """# Missing URL

```bash
curl -X POST \\
  -H "Authorization: Bearer sk-syn-1234...5678" \\
  -d '{"current_load": 0}'
```
"""
    result = run_doc_curl_check(tmp_path, doc)

    assert result.returncode == 1, f"Expected exit 1 for missing URL\nstdout:\n{result.stdout}"
    assert "URL" in result.stdout


def test_skips_non_curl_blocks(tmp_path):
    """Bash blocks without curl (env exports, script invocations) should be skipped."""
    doc = """# Non-curl blocks

```bash
export SYNAPSE_API_URL="http://localhost:8000"
export SYNAPSE_API_KEY="sk-syn-..."
```

```bash
bash tools/generate-skill.sh --client --output .
```

```bash
curl -X POST http://localhost:8000/v1/agents/ag_019f45fe0001/heartbeat \\
  -H "Authorization: Bearer sk-syn-1234...5678" \\
  -H "Content-Type: application/json" \\
  -d '{"current_load": 0}'
```
"""
    result = run_doc_curl_check(tmp_path, doc)

    assert result.returncode == 0, f"Expected exit 0 (non-curl blocks skipped)\nstdout:\n{result.stdout}"
    assert "全部 1 条" in result.stdout or "1 条 curl" in result.stdout


def test_multiple_errors_reported(tmp_path):
    """When multiple curls have issues, all are reported."""
    doc = """# Multiple Errors

```bash
curl -X POST http://localhost:8000/v1/agents/ag_019f45fe0001/handshake \\
  -H "Content-Type: application/json" \\
  -d '{"worker_version": "1.0.0"}'
```

```bash
curl -X GET http://localhost:8000/v1/agents/ag_019f45fe0002/heartbeat \\
  -H "Content-Type: application/json" \\
  -d 'bad json here'
```
"""
    result = run_doc_curl_check(tmp_path, doc)

    assert result.returncode == 1, f"Expected exit 1 for multiple errors\nstdout:\n{result.stdout}"
    assert "Authorization" in result.stdout  # First curl: missing auth
    assert "JSON" in result.stdout  # Second curl: invalid JSON
