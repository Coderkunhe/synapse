"""Gate tests for P100-B25 mechanical defenses (P100-B27 validation).

Each test verifies that a gate script actually triggers under its
defined violation conditions — asserting the mechanism works, not
just that the script exists.
"""

import os
import subprocess
import sys
from pathlib import Path

# Path to the synapse/ project root (2 levels up from tests/gates/)
PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
TOOLS_DIR = PROJECT_DIR / "tools"


def run_gate(script_name: str, cwd: Path | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run a gate script and return the CompletedProcess.

    Args:
        script_name: e.g. "check-fresh-eyes.sh"
        cwd: working directory for the subprocess
        env: extra environment variables (merged with os.environ)
    """
    script_path = TOOLS_DIR / script_name
    if not script_path.exists():
        raise FileNotFoundError(f"Gate script not found: {script_path}")

    run_env = os.environ.copy()
    if env:
        run_env.update(env)

    return subprocess.run(
        ["bash", str(script_path)],
        cwd=cwd or PROJECT_DIR,
        capture_output=True,
        text=True,
        env=run_env,
        timeout=30,
    )


def make_temp_git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo in tmp_path and return it."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@synapse.local"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Gate Test"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    return tmp_path


def make_track_file(repo: Path, next_batch: str = "T-B2") -> Path:
    """Create tracks/synapse.md with frontmatter in the repo."""
    track_dir = repo / "tracks"
    track_dir.mkdir(parents=True, exist_ok=True)
    track_file = track_dir / "synapse.md"
    track_file.write_text(f"""---
project: test
phase: test
last_batch: T-B1
next_batch: {next_batch}
description: Test track for gate validation
---

# Test Track
""")
    return track_file


def make_empty_plans_dir(repo: Path) -> Path:
    """Create docs/plans/ (empty — simulates no plan written)."""
    plans_dir = repo / "docs" / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    return plans_dir


def make_checkpoint_file(repo: Path) -> Path:
    """Create a minimal checkpoint file so session-checkpoint.sh can find one."""
    mem_dir = repo / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    cp = mem_dir / "synapse-session-2026-07-13-test.md"
    cp.write_text("""---
name: test-checkpoint
description: test
metadata:
  type: session
---

## 快速状态
- 接头暗号: test
- 下一站: test
""")
    return cp


def stage_files(repo: Path, *paths: str) -> None:
    """Stage files in the repo."""
    for p in paths:
        subprocess.run(["git", "add", p], cwd=repo, check=True, capture_output=True)


def make_commit(repo: Path, msg: str, date: str | None = None) -> None:
    """Make a commit in the repo, optionally with a specific date."""
    env = None
    if date:
        env = os.environ.copy()
        env["GIT_AUTHOR_DATE"] = date
        env["GIT_COMMITTER_DATE"] = date
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", msg],
        cwd=repo, check=True, capture_output=True, env=env,
    )
