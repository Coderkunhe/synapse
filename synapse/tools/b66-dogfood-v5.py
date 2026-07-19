#!/usr/bin/env python3
"""Dogfooding v5 — B61 7 friction 修复验证 + 新 friction 发现.

Schema corrections from live testing:
  - Handshake: agent_version (default "0.0.0"), capabilities (default []),
    CapabilityDeclaration.name (required, NOT "type")
  - Claim: TaskClaimRequest {expected_version: int}
  - Submit: TaskSubmitRequest {summary: str, expected_version: int, evidence?: dict}
  - Verify: VerificationVerifyRequest {status: passed|failed|approved|rejected,
    expected_version: int, comment?: str}
  - Task ready: TaskReadyRequest {expected_version: int}
  - Task cancel: TaskCancelRequest {expected_version: int}
  - Provider enum: claude | codex | custom
"""

import sys
import sqlite3
import json
import urllib.request
import urllib.error
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from src.auth import create_access_token

BASE = "http://localhost:8000"
RESULTS = []
NEW_FRICTION = []


def log(icon, label, detail="", passed=None):
    status = "PASS" if passed is True else ("FAIL" if passed is False else "----")
    line = f"[{status}] {icon} {label}"
    if detail:
        line += f" — {detail}"
    print(line)
    RESULTS.append({"status": status, "icon": icon, "label": label, "detail": detail})


def friction(fid, desc, severity="🟡"):
    NEW_FRICTION.append({"id": fid, "desc": desc, "severity": severity})
    print(f"  🔴 NEW FRICTION: {fid} [{severity}] {desc}")


def api(method, path, token=None, body=None):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_bytes = e.read()
        try:
            return e.code, json.loads(body_bytes)
        except json.JSONDecodeError:
            return e.code, {"detail": body_bytes.decode()}
    except Exception as e:
        return 0, {"detail": str(e)}


def get_context():
    conn = sqlite3.connect(str(PROJECT_DIR / "data" / "synapse.db"))
    conn.row_factory = sqlite3.Row
    member = dict(conn.execute(
        "SELECT m.id, m.user_id, m.display_name, m.role, m.team_id "
        "FROM member m WHERE m.role = 'admin' ORDER BY m.created_at ASC LIMIT 1"
    ).fetchone())
    proj = dict(conn.execute("SELECT p.id, p.name FROM project p ORDER BY p.created_at ASC LIMIT 1").fetchone())
    conn.close()
    token = create_access_token(
        user_id=member["user_id"], member_id=member["id"],
        team_id=member["team_id"], role=member["role"],
    )
    return token, member, proj


def ensure_ready_tasks(token, project_id):
    """Ensure we have ready tasks, promoting from backlog if needed."""
    s, d = api("GET", f"/v1/projects/{project_id}/tasks?status=ready&limit=3", token=token)
    if s == 200:
        tasks = d if isinstance(d, list) else d.get("items", d.get("tasks", []))
        if tasks:
            return tasks

    # Promote backlog tasks
    s, d = api("GET", f"/v1/projects/{project_id}/tasks?status=backlog&limit=3", token=token)
    if s != 200:
        return []
    tasks = d if isinstance(d, list) else d.get("items", d.get("tasks", []))
    ready = []
    for t in tasks[:2]:
        tid = t["id"]
        s2, d2 = api("POST", f"/v1/tasks/{tid}/ready", token=token,
                     body={"expected_version": t.get("version_no", 1)})
        if s2 == 200:
            ready.append(d2)
    return ready


def main():
    print("=" * 60)
    print("Dogfooding v5 — B61 Friction Fix Verification")
    print("=" * 60)

    token, member, project = get_context()
    member_id = member["id"]
    team_id = member["team_id"]
    project_id = project["id"]

    print(f"\n👤 {member['display_name']} ({member['role']})")
    print(f"   project={project['name']} ({project_id})")

    # Ensure ready tasks exist
    ready_tasks = ensure_ready_tasks(token, project_id)
    log("ℹ️", f"Ready tasks: {len(ready_tasks)}")

    # ==================================================================
    # F-B61-4: Handshake 简化 (B65)
    # ==================================================================
    print("\n--- F-B61-4: Handshake 简化 ---")

    s, d = api("POST", f"/v1/teams/{team_id}/agents", token=token, body={
        "name": "dogfood-v5-fb61-4",
        "type": "ai", "role": "builder", "provider": "claude",
    })
    agent = d.get("agent", {}) if s in (200, 201) else {}
    agent_id = agent.get("id", "")
    agent_api_key = d.get("api_key", "")

    if not agent_id:
        log("❌", "Cannot create test agent", f"status={s}", passed=False)
    else:
        log("ℹ️", f"Agent: {agent_id}")

        # F-B61-4a: Empty body → defaults should work
        s, d = api("POST", f"/v1/agents/{agent_id}/handshake", token=agent_api_key, body={})
        passed = s == 200
        log("✅" if passed else "❌", "F-B61-4a 空 body {} handshake",
            f"status={s}", passed=passed)
        if s == 200:
            log("   ", f"version={d.get('agent_version')}, caps_count={len(d.get('capabilities',[]))}")
        else:
            log("   ", f"err: {json.dumps(d.get('detail', d), ensure_ascii=False)[:200]}")

        # F-B61-4b: String shorthand for capabilities
        s, d = api("POST", f"/v1/agents/{agent_id}/handshake", token=agent_api_key, body={
            "capabilities": ["code_gen", "code_review"]
        })
        passed = s == 200
        log("✅" if passed else "❌", "F-B61-4b capabilities str 简写",
            f"status={s}", passed=passed)
        if s != 200:
            log("   ", f"err: {json.dumps(d.get('detail', d), ensure_ascii=False)[:200]}")

        # F-B61-4c: Full handshake with all fields
        s, d = api("POST", f"/v1/agents/{agent_id}/handshake", token=agent_api_key, body={
            "agent_version": "1.0.0",
            "capabilities": [{"name": "code_gen", "description": "Code generation"}],
            "supported_events": ["task.assigned"],
            "preferred_channel": "websocket",
        })
        passed = s == 200
        log("✅" if passed else "❌", "F-B61-4c 完整 handshake",
            f"status={s}", passed=passed)
        if s != 200:
            log("   ", f"err: {json.dumps(d.get('detail', d), ensure_ascii=False)[:200]}")

    # ==================================================================
    # F-B61-5: Agent 清理 (B64)
    # ==================================================================
    print("\n--- F-B61-5: Agent 清理 ---")
    s, d = api("GET", f"/v1/teams/{team_id}/agents?limit=200", token=token)
    if s == 200:
        agents = d if isinstance(d, list) else d.get("items", d.get("agents", []))
        count = len(agents)
        disabled = len([a for a in agents if a.get("is_disabled")])
        active = count - disabled
        ok = count <= 30
        log("✅" if ok else "⚠️", f"F-B61-5 Agent: {count} total ({active} active, {disabled} disabled)",
            f"threshold=30", passed=ok)
        if not ok:
            friction("F-B66-N1", f"Agent count {count} > 30 after B64 cleanup", "🟠")

    # ==================================================================
    # F-B61-7: API Key 警告增强 (B64)
    # ==================================================================
    print("\n--- F-B61-7: API Key 警告 ---")
    s, d = api("POST", f"/v1/teams/{team_id}/agents", token=token, body={
        "name": "dogfood-v5-apikey-check",
        "type": "ai", "role": "builder", "provider": "codex",
    })
    if s in (200, 201):
        has_key = len(d.get("api_key", "")) > 10
        log("✅" if has_key else "❌", "F-B61-7 api_key returned",
            f"key_len={len(d.get('api_key',''))}", passed=has_key)

        # Check response for warning language
        resp_str = json.dumps(d, ensure_ascii=False)
        warnings = ["warning", "save", "store", "copy", "shown only once",
                    "只显示一次", "重要", "保存", "请妥善"]
        found = [w for w in warnings if w.lower() in resp_str.lower()]
        if found:
            log("   ", f"Warning keywords found: {found}", passed=True)
        else:
            log("   ", "No warning keywords in response body", passed=None)
            # Check if the warning might be in a header or separate field
            friction("F-B66-N2", "Agent 创建响应中未检测到 API key 保存警告文案", "🟡")

    # ==================================================================
    # F-B61-1: Human claim 权限修复 (B62)
    # ==================================================================
    print("\n--- F-B61-1: Human claim 权限 ---")
    tasks = ensure_ready_tasks(token, project_id)
    if tasks:
        task = tasks[0]
        task_id = task["id"]
        vno = task.get("version_no", 1)

        # Claim requires expected_version in body (B63)
        s, d = api("POST", f"/v1/tasks/{task_id}/claim", token=token,
                   body={"expected_version": vno})
        passed = s == 200
        log("✅" if passed else "❌", f"F-B61-1 Human claim (member role)",
            f"status={s}", passed=passed)

        if not passed:
            err = str(d.get("detail", d))
            log("   ", f"error: {err[:200]}")
            if "ONLY_AGENTS" in err.upper():
                friction("F-B66-N3", "F-B61-1 修复未生效: claim 仍拒绝 member", "🔴")

        # Cancel to unclaim (also needs expected_version)
        if s == 200:
            new_vno = d.get("version_no", vno + 1)
            api("POST", f"/v1/tasks/{task_id}/cancel", token=token,
                body={"expected_version": new_vno})
    else:
        log("⚠️", "F-B61-1 无 ready task", "SKIP")

    # ==================================================================
    # F-B61-2: expected_version body 统一 (B63)
    # ==================================================================
    print("\n--- F-B61-2: expected_version body 统一 ---")
    tasks2 = ensure_ready_tasks(token, project_id)
    if tasks2:
        tid = tasks2[0]["id"]
        vno = tasks2[0].get("version_no", 1)

        # Claim
        s, d = api("POST", f"/v1/tasks/{tid}/claim", token=token,
                   body={"expected_version": vno})
        if s != 200:
            log("⚠️", "F-B61-2 claim failed, cannot test submit", "SKIP")
        else:
            new_vno = d.get("version_no", vno + 1)

            # Submit: needs summary + expected_version in body
            s, d = api("POST", f"/v1/tasks/{tid}/submit", token=token, body={
                "summary": "Dogfood v5 test submission",
                "evidence": {"result": "all good"},
                "expected_version": new_vno,
            })
            passed = s in (200, 201)
            log("✅" if passed else "❌", "F-B61-2 submit (expected_version in body)",
                f"status={s}", passed=passed)
            if not passed:
                err = str(d.get("detail", d))[:200]
                log("   ", f"error: {err}")
    else:
        log("⚠️", "F-B61-2 无 ready task", "SKIP")

    # ==================================================================
    # F-B61-3: Verify status 字段对齐 (B63)
    # ==================================================================
    print("\n--- F-B61-3: Verify status 字段对齐 ---")
    s, d = api("GET", f"/v1/projects/{project_id}/tasks?status=in_verification&limit=3", token=token)
    vtasks = d if isinstance(d, list) else d.get("items", d.get("tasks", [])) if s == 200 else []

    if not vtasks:
        # F-B61-2 submit might have created one — re-check
        s, d = api("GET", f"/v1/projects/{project_id}/tasks?status=in_verification&limit=3", token=token)
        vtasks = d if isinstance(d, list) else d.get("items", d.get("tasks", [])) if s == 200 else []

    if vtasks:
        vtask_id = vtasks[0]["id"]
        log("ℹ️", f"in_verification: {vtask_id}")

        s, d = api("GET", f"/v1/tasks/{vtask_id}/verifications", token=token)
        if s == 200:
            verifs = d if isinstance(d, list) else d.get("items", d.get("verifications", []))
            pending = [v for v in verifs if v.get("status") == "pending"]
            if pending:
                vid = pending[0]["id"]
                ver_vno = pending[0].get("version_no", 1)

                # Verify with status+expected_version in body
                s2, d2 = api("POST", f"/v1/verifications/{vid}/verify", token=token, body={
                    "status": "approved",
                    "comment": "dogfood v5 verification",
                    "expected_version": ver_vno,
                })
                passed = s2 in (200, 201)
                log("✅" if passed else "❌", "F-B61-3 verify (status=approved in body)",
                    f"status={s2}", passed=passed)
                if not passed:
                    log("   ", f"error: {str(d2.get('detail', d2))[:200]}")
            else:
                log("⚠️", "F-B61-3 no pending verification", "SKIP")
                if verifs:
                    log("   ", f"First verif status: {verifs[0].get('status')}")
    else:
        log("⚠️", "F-B61-3 无 in_verification task", "SKIP")

    # ==================================================================
    # F-B61-6: Bearer 前缀说明 (B64)
    # ==================================================================
    print("\n--- F-B61-6: Bearer 前缀说明 (文档检查) ---")
    onboarding = PROJECT_DIR / "docs" / "onboarding.md"
    if onboarding.exists():
        content = onboarding.read_text()
        count = content.count("Bearer")
        log("✅" if count > 0 else "❌", f"F-B61-6 Bearer: {count} occurrences",
            "", passed=(count > 0))
        # Check protocol.md too for API key auth docs
        protocol = PROJECT_DIR / "docs" / "protocol.md"
        if protocol.exists():
            pcount = protocol.read_text().count("Bearer")
            log("   ", f"protocol.md Bearer: {pcount} occurrences", passed=True)
    else:
        log("❌", "F-B61-6 onboarding.md missing", passed=False)

    # ==================================================================
    # E2E: Full claim → submit → verify
    # ==================================================================
    print("\n--- E2E: claim → submit → verify ---")
    tasks3 = ensure_ready_tasks(token, project_id)
    if tasks3:
        tid = tasks3[0]["id"]
        vno = tasks3[0].get("version_no", 1)
        log("ℹ️", f"E2E: {tid}")

        # Claim
        s, d = api("POST", f"/v1/tasks/{tid}/claim", token=token,
                   body={"expected_version": vno})
        claim_ok = s == 200
        log("✅" if claim_ok else "❌", "E2E-1 claim", f"status={s}", passed=claim_ok)

        if claim_ok:
            v2 = d.get("version_no", vno + 1)

            # Submit
            s, d = api("POST", f"/v1/tasks/{tid}/submit", token=token, body={
                "summary": "Dogfood v5 E2E test",
                "evidence": {"completed": True},
                "expected_version": v2,
            })
            submit_ok = s in (200, 201)
            log("✅" if submit_ok else "❌", "E2E-2 submit", f"status={s}", passed=submit_ok)

            if submit_ok:
                # Verify
                s, d = api("GET", f"/v1/tasks/{tid}/verifications", token=token)
                if s == 200:
                    verifs = d if isinstance(d, list) else d.get("items", d.get("verifications", []))
                    if verifs:
                        vid = verifs[0]["id"]
                        ver_vno = verifs[0].get("version_no", 1)
                        s2, d2 = api("POST", f"/v1/verifications/{vid}/verify", token=token, body={
                            "status": "approved",
                            "comment": "dogfood v5 e2e final",
                            "expected_version": ver_vno,
                        })
                        verify_ok = s2 in (200, 201)
                        log("✅" if verify_ok else "❌", "E2E-3 verify", f"status={s2}", passed=verify_ok)
                    else:
                        log("⚠️", "E2E-3 no verification after submit")
                        friction("F-B66-N6", "Submit 后未创建 verification", "🟠")
                else:
                    log("❌", "E2E-3 get verifications failed", f"status={s}")

            # Final state
            s, d = api("GET", f"/v1/tasks/{tid}", token=token)
            if s == 200:
                log("ℹ️", f"E2E-4 final: {d.get('status')}")
        else:
            log("⚠️", "E2E blocked at claim", "SKIP")
    else:
        log("⚠️", "E2E 无 ready task", "SKIP")

    # ==================================================================
    # Additional: Response format check
    # ==================================================================
    print("\n--- API Response Format ---")
    s, d = api("GET", f"/v1/projects/{project_id}/tasks?limit=2", token=token)
    if s == 200:
        tasks = d if isinstance(d, list) else d.get("items", d.get("tasks", []))
        log("ℹ️", f"Tasks: type={type(d).__name__}, items={len(tasks)}")

    s, d = api("GET", f"/v1/teams/{team_id}/agents?limit=2", token=token)
    if s == 200:
        agents = d if isinstance(d, list) else d.get("items", d.get("agents", []))
        log("ℹ️", f"Agents: type={type(d).__name__}, items={len(agents)}")

    # ==================================================================
    # SUMMARY
    # ==================================================================
    print("\n" + "=" * 60)
    print("Dogfooding v5 — FINAL SUMMARY")
    print("=" * 60)
    passed = sum(1 for r in RESULTS if r["status"] == "PASS")
    failed = sum(1 for r in RESULTS if r["status"] == "FAIL")
    skipped = sum(1 for r in RESULTS if r["status"] == "----")
    print(f"Checks: {len(RESULTS)} | PASS: {passed} | FAIL: {failed} | SKIP: {skipped}")

    print(f"\n🔍 New Friction ({len(NEW_FRICTION)}):")
    for f in NEW_FRICTION:
        print(f"  {f['id']} [{f['severity']}] {f['desc']}")
    if not NEW_FRICTION:
        print("  (none)")

    print(f"\nB61 Fix Verification:")
    b61_status = {}
    for fix_id in ["F-B61-1", "F-B61-2", "F-B61-3", "F-B61-4", "F-B61-5", "F-B61-6", "F-B61-7"]:
        ok = any(fix_id in r["label"] and r["status"] == "PASS" for r in RESULTS)
        skipped_flag = any(fix_id in r["label"] and r["status"] == "----" for r in RESULTS)
        if ok:
            icon = "✅"
        elif skipped_flag:
            icon = "⚠️"
        else:
            icon = "❌"
        print(f"  {icon} {fix_id}")
        b61_status[fix_id] = ok

    return 0 if (failed == 0 and len(NEW_FRICTION) == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
