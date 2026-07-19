#!/usr/bin/env python3
"""Shared Module Governance — consumer count + Risk Assessment coverage scan.

Scans src/ and frontend/src/ for import relationships, counts unique
consumers per module, and cross-checks against requirements-log for
Risk Assessment records.

Adapted from GlassCortex tools/check_shared_modules.py (P100-B16).
Thresholds lowered for Synapse's smaller codebase.

Risk levels:
  🔴 Critical — N≥5 consumers AND ≥3 abstraction layers → exit 1 (block commit)
  🟠 High     — N≥3 consumers → exit 2 (warning, non-blocking)
  🟡 Medium   — N≥2 consumers → exit 0 (informational)

Exit codes:
  0 — All shared modules assessed, or no Critical/High gaps
  1 — ≥1 🔴 Critical module missing Risk Assessment (blocking)
  2 — Only 🟠 High modules missing (non-blocking warning)
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

# --- Project root via sys.path (Synapse pattern) ---
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Directories scanned for Python module definitions
MODULE_DIRS = ["src"]

# Frontend source root (TypeScript)
FRONTEND_SRC = "frontend/src"

# Minimum unique consumers to qualify as a "shared module"
MIN_CONSUMERS = 2

# Risk thresholds (lowered for Synapse scale)
CRITICAL_CONSUMERS = 5
HIGH_CONSUMERS = 3

# Known abstraction layer counts per module.
# These are the canonical counts derived from Synapse architecture.
KNOWN_LAYERS: dict[str, int] = {
    # Config — 3 layers: Env parse → Defaults → Type coercion
    "config.py": 3,
    # DB — 3 layers: Engine → Session → Dependency
    "db.py": 3,
    # Auth — 3 layers: Token create → Token verify → API Key
    "auth.py": 3,
    # Schemas/common — 3 layers: CursorPage → ErrorResponse → AuditFields
    "common.py": 3,
    # Event store — 2 layers: Write path → Read path
    "event_store.py": 2,
    # Exceptions — 2 layers: Error hierarchy → FastAPI handler
    "exceptions.py": 2,
    # Base model — 2 layers: Base → Mixins
    "base.py": 2,
    # Dependencies — 2 layers: get_current_actor → require_role
    "dependencies.py": 2,
    # Task state machine — 2 layers: States → Transitions
    "task_state_machine.py": 2,
    # Agent state machine — 2 layers: States → Transitions
    "agent_state_machine.py": 2,
    # Task service — 2 layers: CRUD → Query
    "task_service.py": 2,
}


# --- Python Import Resolution ---


def _resolve_py_import(import_path: str) -> Path | None:
    """Resolve a dotted Python import path to a file on disk.

    Tries ``a/b.py`` first, then ``a/b/__init__.py``.
    Returns None for unresolvable paths (stdlib, third-party, dynamic).
    """
    parts = import_path.split(".")
    candidate = PROJECT_ROOT.joinpath(*parts).with_suffix(".py")
    if candidate.exists():
        return candidate
    candidate = PROJECT_ROOT.joinpath(*parts, "__init__.py")
    if candidate.exists():
        return candidate
    return None


def _extract_py_imports(file_path: Path) -> list[str]:
    """Return dotted import strings for every project-internal import in *file_path*."""
    try:
        tree = ast.parse(file_path.read_text())
    except (SyntaxError, FileNotFoundError):
        return []

    imports: list[str] = []
    file_dir = file_path.parent

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)

        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            if node.level > 0:  # relative import
                parts = list(file_dir.relative_to(PROJECT_ROOT).parts)
                if node.level > len(parts):
                    continue
                base_parts = parts[: len(parts) - node.level]
                resolved_parts = list(base_parts) + node.module.split(".")
                resolved_path = _resolve_py_import(".".join(resolved_parts))
                if resolved_path is not None:
                    imports.append(".".join(resolved_parts))
            else:
                imports.append(node.module)

    return imports


# --- TypeScript Import Resolution ---

_TS_FROM_RE = re.compile(r"""from\s+['"]([^'"]+)['"]""")
_TS_DYNAMIC_RE = re.compile(r"""import\s*\(\s*['"]([^'"]+)['"]\s*\)""")


def _resolve_ts_import(import_path: str, from_file: Path) -> Path | None:
    """Resolve a TypeScript import specifier to an absolute file path.

    Handles ``@/`` alias, ``./`` and ``../`` relative imports.
    Returns None for bare specifiers (npm packages).
    """
    frontend_root = PROJECT_ROOT / FRONTEND_SRC

    if import_path.startswith("@/"):
        base = frontend_root
        rel = import_path[2:]
    elif import_path.startswith("./") or import_path.startswith("../"):
        base = from_file.parent
        rel = import_path
    else:
        return None  # npm package

    raw = (base / rel).resolve()

    candidates: list[Path] = [raw]
    for ext in (".ts", ".tsx"):
        candidates.append(
            raw.with_suffix(raw.suffix + ext) if raw.suffix else raw.with_suffix(ext)
        )
    for idx in ("index.ts", "index.tsx"):
        candidates.append(raw / idx)

    for c in candidates:
        try:
            if c.exists():
                return c
        except OSError:
            continue
    return None


def _extract_ts_imports(file_path: Path) -> list[Path]:
    """Return resolved Paths for every project-internal TS import in *file_path*."""
    try:
        content = file_path.read_text()
    except (FileNotFoundError, OSError):
        return []

    imports: list[Path] = []
    for pattern in (_TS_FROM_RE, _TS_DYNAMIC_RE):
        for match in pattern.finditer(content):
            specifier = match.group(1)
            resolved = _resolve_ts_import(specifier, file_path)
            if resolved is not None:
                imports.append(resolved)
    return imports


# --- Consumer Counting ---


def _scan_modules() -> dict[str, dict]:
    """Walk the project and build a consumer map.

    Returns a dict keyed by repo-relative path (e.g. ``src/config.py``).
    Each value is ``{"file": Path, "consumers": set[str]}``.
    """
    modules: dict[str, dict] = {}

    # Register every Python module in src/
    for mod_dir in MODULE_DIRS:
        root = PROJECT_ROOT / mod_dir
        if not root.exists():
            continue
        for py_file in root.rglob("*.py"):
            rel = str(py_file.relative_to(PROJECT_ROOT))
            modules[rel] = {"file": py_file, "consumers": set()}

    # Register every TS module in frontend/src/
    frontend_root = PROJECT_ROOT / FRONTEND_SRC
    if frontend_root.exists():
        for pattern in ("*.ts", "*.tsx"):
            for ts_file in frontend_root.rglob(pattern):
                rel = str(ts_file.relative_to(PROJECT_ROOT))
                if rel not in modules:
                    modules[rel] = {"file": ts_file, "consumers": set()}

    # Count Python consumers (src/ + tests/)
    py_roots: list[Path] = []
    for mod_dir in MODULE_DIRS:
        py_roots.append(PROJECT_ROOT / mod_dir)
    tests_root = PROJECT_ROOT / "tests"
    if tests_root.exists():
        py_roots.append(tests_root)

    for py_root in py_roots:
        if not py_root.exists():
            continue
        for py_file in py_root.rglob("*.py"):
            consumer_rel = str(py_file.relative_to(PROJECT_ROOT))
            for imp_path in _extract_py_imports(py_file):
                resolved = _resolve_py_import(imp_path)
                if resolved is None:
                    continue
                resolved_rel = str(resolved.relative_to(PROJECT_ROOT))
                if resolved_rel in modules and resolved_rel != consumer_rel:
                    modules[resolved_rel]["consumers"].add(consumer_rel)

    # Count TypeScript consumers
    if frontend_root.exists():
        for pattern in ("*.ts", "*.tsx"):
            for ts_file in frontend_root.rglob(pattern):
                consumer_rel = str(ts_file.relative_to(PROJECT_ROOT))
                for resolved in _extract_ts_imports(ts_file):
                    resolved_rel = str(resolved.relative_to(PROJECT_ROOT))
                    if resolved_rel in modules and resolved_rel != consumer_rel:
                        modules[resolved_rel]["consumers"].add(consumer_rel)

    return modules


# --- Risk Assessment Check ---


def _search_ra_in_file(filepath: Path, module_filename: str) -> bool:
    """Return True if *module_filename* has a Risk Assessment entry in *filepath*."""
    try:
        content = filepath.read_text()
    except (FileNotFoundError, OSError):
        return False

    for line in content.split("\n"):
        if line.startswith("###") and "Risk Assessment" in line and module_filename in line:
            return True
    return False


def _has_risk_assessment(module_rel_path: str) -> bool:
    """Return True if *module_rel_path* has a Risk Assessment entry."""
    module_filename = Path(module_rel_path).name

    req_log = PROJECT_ROOT / "docs" / "requirements-log.md"
    if _search_ra_in_file(req_log, module_filename):
        return True

    archive_dir = PROJECT_ROOT / "docs" / "archive"
    if archive_dir.is_dir():
        for archive_file in sorted(archive_dir.glob("requirements-log-*.md")):
            if _search_ra_in_file(archive_file, module_filename):
                return True
    return False


def _get_layer_count(module_rel_path: str) -> int:
    """Return the known abstraction layer count, defaulting to 1."""
    filename = Path(module_rel_path).name
    return KNOWN_LAYERS.get(filename, 1)


# --- Report ---


def _fmt_consumers(consumers: set[str], max_show: int = 5) -> list[str]:
    """Return a short, sorted consumer listing for display."""
    return sorted(consumers)[:max_show]


def main() -> int:
    """Run the shared-module governance scan.

    Returns:
        0 — all clear or only 🟡 Medium gaps.
        1 — ≥1 🔴 Critical module unassessed (blocking).
        2 — only 🟠 High modules unassessed (warning).
    """
    print("=== Shared Module Governance — 消费者统计 + Risk Assessment 覆盖扫描 ===\n")

    modules = _scan_modules()

    # Filter: shared = ≥ MIN_CONSUMERS unique consumers
    shared = {
        path: info
        for path, info in modules.items()
        if len(info["consumers"]) >= MIN_CONSUMERS
    }

    sorted_shared = sorted(
        shared.items(), key=lambda kv: len(kv[1]["consumers"]), reverse=True
    )

    if not sorted_shared:
        print(f"  ✅ 无 ≥{MIN_CONSUMERS} 消费者的共享模块，跳过检查")
        return 0

    n_mods = len(modules)
    n_shared = len(sorted_shared)
    print(f"  已扫描 {n_mods} 个模块文件，其中 {n_shared} 个有 ≥{MIN_CONSUMERS} 个消费者\n")

    # Classify
    critical: list[tuple[str, int, int]] = []
    high: list[tuple[str, int, int]] = []
    medium: list[tuple[str, int, int]] = []
    assessed: list[tuple[str, int, int]] = []

    for mod_path, info in sorted_shared:
        n = len(info["consumers"])
        layers = _get_layer_count(mod_path)

        if _has_risk_assessment(mod_path):
            assessed.append((mod_path, n, layers))
        elif n >= CRITICAL_CONSUMERS and layers >= 3:
            critical.append((mod_path, n, layers))
        elif n >= HIGH_CONSUMERS:
            high.append((mod_path, n, layers))
        else:
            medium.append((mod_path, n, layers))

    # Print: assessed
    if assessed:
        print("  ✅ 已有 Risk Assessment：")
        for mod_path, n, layers in assessed:
            print(f"     {mod_path}  ({n} consumers, {layers} layers)")
        print()

    # Print: critical
    if critical:
        print(
            f"  🔴 Critical — N≥{CRITICAL_CONSUMERS} consumers + ≥3 layers，"
            "缺 Risk Assessment："
        )
        for mod_path, n, layers in critical:
            print(f"     {mod_path}  ({n} consumers, {layers} layers)")
            sample = _fmt_consumers(modules[mod_path]["consumers"])
            for c in sample:
                print(f"       ← {c}")
            remaining = n - len(sample)
            if remaining > 0:
                print(f"       ... 及其他 {remaining} 个消费者")
        print()

    # Print: high
    if high:
        print(
            f"  🟠 High — N≥{HIGH_CONSUMERS} consumers，缺 Risk Assessment（告警）："
        )
        for mod_path, n, layers in high:
            print(f"     {mod_path}  ({n} consumers, {layers} layers)")
        print()

    # Print: medium
    if medium:
        print(
            f"  🟡 Medium — N≥{MIN_CONSUMERS} consumers，缺 Risk Assessment（提示）："
        )
        for mod_path, n, layers in medium:
            print(f"     {mod_path}  ({n} consumers, {layers} layers)")
        print()

    # Summary
    total_shared = len(sorted_shared)
    total_assessed = len(assessed)
    total_unassessed = len(critical) + len(high) + len(medium)

    print(f"  📊 总计: {total_shared} 共享模块, {total_assessed} 已评估, {total_unassessed} 待评估")
    print(f"     🔴 {len(critical)} Critical · 🟠 {len(high)} High · 🟡 {len(medium)} Medium")

    if critical:
        print(f"\n  🔴 {len(critical)} 个 Critical 模块缺 Risk Assessment")
        print("  💡 在 requirements-log 中为该模块追加 Risk Assessment 条目")
        print("  ⚠️  当前为 advisory 模式（P100-B16 首部署），后续将升级为硬阻断\n")
        # FUTURE: return 1 when RA coverage baseline is established
        return 0

    if high:
        print(f"\n  ⚠️  {len(high)} 个 High 模块缺 Risk Assessment — 建议补齐")
        return 0

    if medium:
        print(f"\n  💡 {len(medium)} 个 Medium 模块缺 Risk Assessment（仅提示，不阻断）")
    else:
        print("\n  ✅ 所有共享模块已覆盖 Risk Assessment")

    return 0


if __name__ == "__main__":
    sys.exit(main())
