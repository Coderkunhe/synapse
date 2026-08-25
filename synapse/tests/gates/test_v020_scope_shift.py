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


def test_v020_reads_temp_repo_track_not_real_one(tmp_path):
    """P100-B152 回归：门禁必须读 temp repo 的 track/plans，不得泄漏到真实仓库。

    此前 check-plan-mode.sh 用 $0 硬推导 PROJECT_DIR，导致上面三条测试的绿是
    **偶然**的 —— 真实仓库当前批次一旦有了对应 plan 文件，门禁就短路放行，
    上面的 V-020 断言随即变红。等于「按规矩写 plan」反而踩红门禁。

    本测试直接钉住隔离本身：temp repo 的 next_batch 是 T-B2，真实仓库不是。
    只要输出里出现的是 T-B2，就证明 PROJECT_DIR 确实指向了 temp repo。
    """
    repo = make_temp_git_repo(tmp_path)
    make_track_file(repo, next_batch="T-B2")
    plans = make_empty_plans_dir(repo)
    # temp repo 里放一个与 T-B2 匹配的 plan —— 真实仓库不可能有 t-b2 开头的计划
    (plans / "t-b2-plan.md").write_text("# T-B2 plan\n")

    src = repo / "src"
    src.mkdir()
    for i in range(5):
        (src / f"module_{i}.py").write_text(f"x = {i}\n")
    stage_files(repo, *[f"src/module_{i}.py" for i in range(5)])

    result = run_gate("check-plan-mode.sh", cwd=repo)

    assert result.returncode == 0
    assert "T-B2" in result.stdout, (
        f"门禁没读 temp repo 的 track 文件 —— 隔离泄漏到真实仓库了。stdout={result.stdout!r}"
    )
    assert "t-b2-plan.md" in result.stdout, "门禁没读 temp repo 的 docs/plans/"
