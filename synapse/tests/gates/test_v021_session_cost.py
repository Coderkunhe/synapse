"""V-021 Session cost gate test.

Verifies session-checkpoint.sh detects session overrun:
- ≥6 commits today → V-021 critical warning fires
- <4 commits today → normal pass

Uses SYNAPSE_MEM_DIR env var to point to a temp checkpoint dir,
avoiding dependency on the user's actual memory directory.
"""

import subprocess
from datetime import date

from . import (
    run_gate,
    make_temp_git_repo,
    make_checkpoint_file,
    make_commit,
)


def _stage_and_commit(repo, filename: str, msg: str, commit_date: str):
    """Helper: write file, stage, commit with given date."""
    f = repo / filename
    f.write_text(f"content: {msg}\n")
    subprocess.run(["git", "add", filename], cwd=repo, capture_output=True, check=True)
    make_commit(repo, msg, date=commit_date)


def test_v021_session_cost_normal(tmp_path):
    """Few commits today → normal density, no V-021 warning."""
    repo = make_temp_git_repo(tmp_path)
    cp = make_checkpoint_file(repo)

    today_str = date.today().isoformat()
    _stage_and_commit(repo, "f1.txt", "test: single commit", f"{today_str}T10:00:00")

    result = run_gate("session-checkpoint.sh", cwd=repo, env={
        "SYNAPSE_MEM_DIR": str(cp.parent),
    })

    assert "会话执行密度正常" in result.stdout
    assert "V-021 违纪风险" not in result.stdout


def test_v021_session_cost_warns(tmp_path):
    """≥6 commits today → V-021 critical warning fires."""
    repo = make_temp_git_repo(tmp_path)
    cp = make_checkpoint_file(repo)

    today_str = date.today().isoformat()
    for i in range(6):
        ts = f"{today_str}T{10 + i:02d}:00:00"
        _stage_and_commit(repo, f"f{i}.txt", f"test: commit {i}", ts)

    result = run_gate("session-checkpoint.sh", cwd=repo, env={
        "SYNAPSE_MEM_DIR": str(cp.parent),
    })

    assert "V-021 违纪风险" in result.stdout


def test_v021_detects_high_line_count(tmp_path):
    """≥1000 lines changed today → V-021 warning on line count signal."""
    repo = make_temp_git_repo(tmp_path)
    cp = make_checkpoint_file(repo)

    today_str = date.today().isoformat()
    big_file = repo / "big.py"
    big_file.write_text("".join(["# big file\n"] * 1200))
    subprocess.run(["git", "add", "big.py"], cwd=repo, capture_output=True, check=True)
    make_commit(repo, "test: massive file", date=f"{today_str}T10:00:00")

    result = run_gate("session-checkpoint.sh", cwd=repo, env={
        "SYNAPSE_MEM_DIR": str(cp.parent),
    })

    assert "V-021 违纪风险" in result.stdout
