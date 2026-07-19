"""V-020 Scope-shift gate test.

Verifies check-plan-mode.sh detects scope expansion:
- ≥5 staged files + no plan → V-020 warning
- ≤2 code files → micro pass (no warning)
"""

from . import (
    run_gate,
    make_temp_git_repo,
    make_track_file,
    make_empty_plans_dir,
    stage_files,
)


def test_v020_scope_shift_warns_on_5_staged(tmp_path):
    """5 staged files + no plan → V-020 scope-shift warning fires."""
    repo = make_temp_git_repo(tmp_path)
    make_track_file(repo, next_batch="T-B2")
    make_empty_plans_dir(repo)

    # Create 5 .py files and stage them
    src = repo / "src"
    src.mkdir()
    for i in range(5):
        f = src / f"module_{i}.py"
        f.write_text(f"# module {i}\nx = {i}\n")
    stage_files(repo, "src/module_0.py", "src/module_1.py",
                "src/module_2.py", "src/module_3.py", "src/module_4.py")

    result = run_gate("check-plan-mode.sh", cwd=repo)

    assert result.returncode == 0  # warning only
    assert "V-020" in result.stdout
    assert "scope 跃迁" in result.stdout


def test_v020_scope_shift_warns_on_new_entries(tmp_path):
    """≥3 new P-XXX/LL/S-XXX entries + no plan → V-020 fires regardless of file count."""
    repo = make_temp_git_repo(tmp_path)
    make_track_file(repo, next_batch="T-B2")
    make_empty_plans_dir(repo)

    # Create and stage pitfalls.md with 3 new P-XXX entries
    docs = repo / "synapse" / "docs"
    docs.mkdir(parents=True)
    pitfalls = docs / "pitfalls.md"
    pitfalls.write_text("""## New Pitfalls

### P-999: test pitfall 1
### P-998: test pitfall 2
### P-997: test pitfall 3
""")
    stage_files(repo, "synapse/docs/pitfalls.md")

    result = run_gate("check-plan-mode.sh", cwd=repo)

    assert result.returncode == 0
    # V-020 should fire because new_entries ≥ 3
    assert "V-020" in result.stdout


def test_v020_micro_change_passes(tmp_path):
    """≤2 code files + no interface changes → micro pass, no V-020."""
    repo = make_temp_git_repo(tmp_path)
    make_track_file(repo, next_batch="T-B2")
    make_empty_plans_dir(repo)

    # Stage just 1 .py file
    src = repo / "src"
    src.mkdir()
    (src / "single.py").write_text("x = 1\n")
    stage_files(repo, "src/single.py")

    result = run_gate("check-plan-mode.sh", cwd=repo)

    assert result.returncode == 0
    assert "微型变更" in result.stdout
    assert "V-020" not in result.stdout  # no scope-shift on micro change
