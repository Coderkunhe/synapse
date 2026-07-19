"""G-007 Fresh-eyes gate test.

Verifies check-fresh-eyes.sh correctly reads/deletes the
.git/synapse-pending-fresh-eyes marker and outputs the
appropriate warning or green pass.
"""

from . import run_gate, make_temp_git_repo


def test_g007_no_marker_passes(tmp_path):
    """Without a marker file, the gate should pass silently."""
    repo = make_temp_git_repo(tmp_path)

    result = run_gate("check-fresh-eyes.sh", cwd=repo)

    assert result.returncode == 0
    assert "Fresh-eyes 复审待做" not in result.stdout  # no warning text
    assert "✅ 无 pending fresh-eyes marker" in result.stdout


def test_g007_marker_warns(tmp_path):
    """With a marker file, the gate should warn about pending fresh-eyes."""
    repo = make_temp_git_repo(tmp_path)

    # Write marker
    marker = repo / ".git" / "synapse-pending-fresh-eyes"
    marker.write_text("abc123def456 2026-07-13T20:00:00\n")

    result = run_gate("check-fresh-eyes.sh", cwd=repo)

    assert result.returncode == 0  # warning only, not blocking
    assert "Fresh-eyes 复审待做" in result.stdout


def test_g007_marker_cleared_passes(tmp_path):
    """After deleting the marker, the gate should pass again."""
    repo = make_temp_git_repo(tmp_path)

    # Write marker, run (should warn), delete, run again (should pass)
    marker = repo / ".git" / "synapse-pending-fresh-eyes"
    marker.write_text("abc123 2026-07-13T20:00:00\n")

    result1 = run_gate("check-fresh-eyes.sh", cwd=repo)
    assert "Fresh-eyes 复审待做" in result1.stdout  # warned

    marker.unlink()

    result2 = run_gate("check-fresh-eyes.sh", cwd=repo)
    assert result2.returncode == 0
    assert "Fresh-eyes 复审待做" not in result2.stdout  # clean pass
