#!/usr/bin/env python3
"""Schema audit consistency check — all business-table Response schemas
MUST inherit ``AuditFields`` from ``src.schemas.common``.

Rationale: Pydantic ``from_attributes=True`` silently omits fields not
defined in the schema.  If a Response schema forgets to inherit
``AuditFields``, the API will drop audit columns (create_user_id,
version_no, etc.) from the response — without any error.

This script closes the gap by statically verifying inheritance.

Exemptions (non-business-table responses):
  - ErrorResponse / ErrorDetail       (not persisted)
  - TokenResponse / AuthStatusResponse (auth plumbing)
  - WorkerCreateResponse               (wrapper around WorkerResponse)
  - ScanListResponse                  (wrapper around list of ScanResponse)
  - CursorPage                        (generic pagination)
  - EventResponse                     (immutable ledger, exempt by design)
"""

from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────

EXEMPT_CLASSES = frozenset({
    "ErrorResponse",
    "ErrorDetail",
    "TokenResponse",
    "AuthStatusResponse",
    "WorkerCreateResponse",
    "BatchClaimResponse",  # operational result (claimed_count + task_ids), not an entity
    "BatchOperationResponse",  # P9-B72: batch operation result (updated_count + errors), not a persisted entity
    "VerificationBatchResponse",  # P8-B6: batch operation result, not a persisted entity
    "CursorPage",
    "EventResponse",
    "ProtocolResponse",  # P9-B21: rendered template content, not a persisted entity
    "CapabilityAuditResponse",  # P11-B57: immutable audit record (append-only, no updated_at/is_disabled)
    "DecisionAuditResponse",  # P10-B35: immutable audit record (append-only, no updated_at/is_disabled)
    "WorkerProjectResponse",  # P11-B9: lightweight project summary projection, not a persisted entity
    "CapabilityResponse",  # P11-B46: read from YAML config file, not a DB entity
    "OrchestratorStatusResponse",  # P11-B87: lightweight heartbeat status projection, not a persisted entity
    "WorkerHeartbeatResponse",  # P11-B94: transient heartbeat response (not persisted, no audit fields)
})

AUDIT_FIELDS_CLASS = "AuditFields"
COMMON_MODULE = "src.schemas.common"
SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "src" / "schemas"


def find_response_classes() -> list[tuple[str, str, type]]:
    """Discover all ``*Response`` classes in src/schemas/*.py.

    Returns list of (module_path, class_name, class_obj).
    """
    results: list[tuple[str, str, type]] = []

    for py_file in sorted(SCHEMAS_DIR.glob("*.py")):
        if py_file.name.startswith("_"):
            continue

        # Build import path: src.schemas.foo
        module_name = py_file.stem
        full_name = f"src.schemas.{module_name}"

        try:
            mod = importlib.import_module(full_name)
        except Exception as exc:
            print(f"  ⚠️  Cannot import {full_name}: {exc}")
            continue

        for name, obj in inspect.getmembers(mod, inspect.isclass):
            if name.endswith("Response") and obj.__module__ == full_name:
                results.append((full_name, name, obj))

    return results


def check_audit_inheritance(
    classes: list[tuple[str, str, type]],
) -> tuple[list[str], list[str]]:
    """Check each Response class inherits AuditFields (or is exempt).

    Returns (violations, warnings).
    """
    violations: list[str] = []
    warnings: list[str] = []

    for module_path, class_name, cls in classes:
        if class_name in EXEMPT_CLASSES:
            continue

        # Check AuditFields in MRO
        mro_names = {c.__name__ for c in cls.__mro__}
        inherits_audit = AUDIT_FIELDS_CLASS in mro_names

        has_from_attributes = False
        if hasattr(cls, "model_config") and isinstance(cls.model_config, dict):
            has_from_attributes = cls.model_config.get("from_attributes", False)

        if not inherits_audit:
            # Check if fields are manually defined (warning vs violation)
            audit_field_names = {
                "is_disabled", "create_user_id", "last_update_user_id",
                "remark", "version_no", "created_at", "updated_at",
            }
            manual_fields = audit_field_names & set(cls.model_fields.keys())
            missing = audit_field_names - set(cls.model_fields.keys())

            if missing:
                violations.append(
                    f"{class_name} ({module_path}): "
                    f"missing {len(missing)} audit field(s): {', '.join(sorted(missing))}"
                )
            else:
                warnings.append(
                    f"{class_name} ({module_path}): "
                    f"has all audit fields but doesn't inherit AuditFields — "
                    f"use `class {class_name}(AuditFields):`"
                )

        if inherits_audit and not has_from_attributes:
            warnings.append(
                f"{class_name} ({module_path}): "
                f"inherits AuditFields but model_config missing from_attributes=True"
            )

        # Check for redundant version_no redeclaration
        if inherits_audit and "version_no" in cls.model_fields:
            # If the class itself (not a parent) defines version_no, it's redundant
            if "version_no" in cls.__dict__:
                warnings.append(
                    f"{class_name} ({module_path}): "
                    f"redundantly redeclares 'version_no' — already inherited from AuditFields"
                )

    return violations, warnings


def main() -> int:
    print("=== Schema Audit 继承检查 ===")
    print()

    classes = find_response_classes()
    print(f"  发现 {len(classes)} 个 Response 类")
    print(f"  豁免: {len(EXEMPT_CLASSES)} 个 ({', '.join(sorted(EXEMPT_CLASSES))})")
    print()

    violations, warnings = check_audit_inheritance(classes)

    if warnings:
        print("--- 建议 ---")
        for w in warnings:
            print(f"  \033[33m💡 {w}\033[0m")
        print()

    if violations:
        print(f"--- \033[31m违规 ({len(violations)}) — 必须修复\033[0m ---")
        for v in violations:
            print(f"  \033[31m🚫 {v}\033[0m")
        print()
        print("=========================================")
        print("\033[31m❌ Schema Audit 检查失败 — 以上 Response 类缺少 AuditFields\033[0m")
        return 1

    print("=========================================")
    print("\033[32m✅ Schema Audit 检查通过 — 所有 Response 类继承 AuditFields\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
