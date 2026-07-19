"""P9-B77 Dogfooding v7 — PM 全链路审计脚本.

用 B73+B74 新能力走完整生命周期，记录所有 friction 和 missing cap。
所有 token 操作在进程内完成，不输出到 stdout。
"""
import asyncio
import httpx
import json
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = "http://localhost:8000"
from src.auth import create_access_token

TOKEN = create_access_token("usr_test001", "mem_019f3c7f4a9e7709", "tea_019f3c7f4a9c7940", "admin")
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
TEAM_ID = "tea_019f3c7f4a9c7940"

findings = []


def record(category: str, id_: str, desc: str, severity: str, note: str = ""):
    findings.append({"cat": category, "id": id_, "desc": desc, "sev": severity, "note": note})
    emoji = {"friction": "⚠️", "missing": "❌", "pass": "✅"}.get(category, "ℹ️")
    print(f"  {emoji} [{id_}] {desc}")


async def api(client, method, path, **kw):
    """Call API with error handling."""
    url = f"{BASE}/v1{path}"
    try:
        if method == "GET":
            r = await client.get(url, headers=HEADERS)
        elif method == "POST":
            r = await client.post(url, headers=HEADERS, json=kw.get("json"))
        elif method == "PATCH":
            r = await client.patch(url, headers=HEADERS, json=kw.get("json"))
        else:
            raise ValueError(f"Unknown method: {method}")
        return r
    except Exception as e:
        print(f"  ❌ API call failed: {method} {path} — {e}")
        return None


async def main():
    print("=" * 60)
    print("P9-B77 Dogfooding v7 — PM 全链路审计")
    print(f"开始时间: {datetime.now().isoformat()}")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=15.0) as client:
        # ── Step 0: Auth check ──
        print("\n── Step 0: Auth Check ──")
        r = await api(client, "GET", "/auth/me")
        if r and (200 <= r.status_code < 300):
            auth = r.json()
            print(f"  ✅ 已认证: role={auth.get('role', '?')}, team={auth.get('team_id', '?')[:20]}...")
        else:
            status = r.status_code if r else "no response"
            print(f"  ❌ Auth failed: {status}")
            return

        # ── Step 1: Create Project ──
        print("\n── Step 1: 创建项目 ──")
        proj_name = f"Dogfood-v7-{datetime.now().strftime('%H%M')}"
        r = await api(client, "POST", f"/teams/{TEAM_ID}/projects", json={
            "name": proj_name, "description": "Dogfooding v7 — 验证 B73+B74 新能力",
            "slug": proj_name.lower().replace(" ", "-"),
        })
        if r and (200 <= r.status_code < 300):
            proj = r.json()
            proj_id = proj["id"]
            print(f"  ✅ Project: {proj_name} (id={proj_id})")
        else:
            status = r.status_code if r else "no response"
            text = r.text[:200] if r else ""
            print(f"  ❌ Create project failed: {status} {text}")
            record("friction", "F-v7-01", f"创建 Project 失败: {status}", "blocking", text)
            return

        # ── Step 2: Register Workers ──
        print("\n── Step 2: 注册 Worker ──")
        workers = []
        for w_data in [
            {"name": "Hunter-PM-v7", "type": "human", "role": "orchestrator"},
            {"name": "CodeBot-v7", "type": "agent", "role": "builder", "provider": "claude", "model": "claude-sonnet-5", "batch_size": 3},
            {"name": "ReviewBot-v7", "type": "agent", "role": "steward", "provider": "codex", "model": "codex-default", "batch_size": 2},
        ]:
            r = await api(client, "POST", f"/teams/{TEAM_ID}/agents", json=w_data)
            if r and (200 <= r.status_code < 300):
                resp = r.json()
                w = resp.get("agent", resp)  # AgentCreateResponse wraps agent in 'agent' key
                workers.append(w)
                has_key = "api_key" in resp
                print(f"  ✅ {w_data['name']} ({w_data['type']}/{w_data['role']}) id={w.get('id', '?')} api_key={'✅' if has_key else '❌'}")
                if not has_key and w_data["type"] == "agent":
                    record("missing", f"M-v7-r{len(workers)}", f"Agent 注册未返回 api_key ({w_data['name']})", "p0")
            else:
                status = r.status_code if r else "no response"
                text = r.text[:200] if r else ""
                print(f"  ❌ Register worker failed: {status} {text}")
                record("friction", f"F-v7-w{len(workers)}", f"注册 Worker 失败: {status}", "blocking", text)

        if len(workers) < 1:
            print("  ❌ 至少需要 1 个 Worker 才能继续")
            return

        # ── Step 3: Verify Worker Load View (B73! — check BEFORE tasks) ──
        print("\n── Step 3: Worker 负载视图 (B73 baseline) ──")
        r = await api(client, "GET", f"/teams/{TEAM_ID}/agents")
        if r and (200 <= r.status_code < 300):
            agent_list = r.json()
            agents_data = agent_list if isinstance(agent_list, list) else agent_list.get("agents", agent_list.get("items", []))
            for a in agents_data:
                name = a.get("name", a.get("id", "?"))
                active = a.get("active_task_count", "N/A")
                completed = a.get("completed_task_count", "N/A")
                batches_count = a.get("active_batches", "N/A")
                print(f"  📊 {name}: active_task_count={active}, completed_task_count={completed}, batch_size={a.get('batch_size', 'N/A')}")
                if active == "N/A":
                    record("missing", "M-v7-01", f"Worker 缺 active_task_count 字段 (B73)", "p0", f"Worker: {name}")
        else:
            status = r.status_code if r else "no response"
            record("friction", "F-v7-02", f"获取 Worker 列表失败: {status}", "blocking")

        # ── Step 4: Create Batch ──
        print("\n── Step 4: 创建 Batch ──")
        r = await api(client, "POST", f"/projects/{proj_id}/batches", json={
            "name": "v7 Sprint 1", "phase": "P9", "batch_number": 77,
            "description": "Dogfooding v7 首个 Sprint",
        })
        if r and (200 <= r.status_code < 300):
            batch = r.json()
            batch_id = batch["id"]
            print(f"  ✅ Batch: v7 Sprint 1 (id={batch_id})")
        else:
            status = r.status_code if r else "no response"
            text = r.text[:200] if r else ""
            print(f"  ❌ Create batch failed: {status} {text}")
            record("friction", "F-v7-03", f"创建 Batch 失败: {status}", "blocking", text)
            return

        # ── Step 5: Create Tasks (with due dates to test B74!) ──
        print("\n── Step 5: 创建 Tasks（含 deadline 测试 B74）──")
        yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        tomorrow = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        next_week = (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

        task_specs = [
            {"title": "[v7] 项目初始化", "description": "初始化项目结构", "priority": "p0", "estimated_effort": "s", "deadline_at": yesterday},
            {"title": "[v7] API 端点设计", "description": "设计 REST API 端点", "priority": "p1", "estimated_effort": "m", "deadline_at": yesterday},
            {"title": "[v7] 数据库 Schema", "description": "设计数据库表结构", "priority": "p1", "estimated_effort": "m", "deadline_at": tomorrow},
            {"title": "[v7] 前端页面搭建", "description": "搭建前端页面框架", "priority": "p2", "estimated_effort": "l", "deadline_at": next_week},
            {"title": "[v7] 单元测试编写", "description": "为核心模块写单元测试", "priority": "p2", "estimated_effort": "m", "deadline_at": next_week},
        ]

        tasks = []
        for ts in task_specs:
            r = await api(client, "POST", f"/projects/{proj_id}/tasks", json=ts)
            if r and (200 <= r.status_code < 300):
                t = r.json()
                tasks.append(t)
                overdue_mark = " 🔴" if ts["deadline_at"] == yesterday else ""
                print(f"  ✅ {ts['title']} (p={ts['priority']}, due={ts['deadline_at'][:10]}){overdue_mark}")
            else:
                status = r.status_code if r else "no response"
                text = r.text[:200] if r else ""
                print(f"  ❌ Create task failed: {status} {text}")
                record("friction", f"F-v7-t{len(tasks)}", f"创建 Task 失败: {status}", "blocking", text)

        if len(tasks) < 3:
            print("  ❌ 至少需要 3 个 Task, 实际创建 {len(tasks)}")
            return

        # ── Step 6: Test Overdue Filter (B74!) ──
        print("\n── Step 6: Overdue Task 检查 (B74) ──")
        r = await api(client, "GET", f"/projects/{proj_id}/tasks?status=overdue")
        if r and (200 <= r.status_code < 300):
            overdue_data = r.json()
            overdue_list = overdue_data if isinstance(overdue_data, list) else overdue_data.get("tasks", overdue_data.get("items", []))
            print(f"  📅 Overdue tasks found: {len(overdue_list)} (expected ~2)")
            for ot in overdue_list[:5]:
                is_od = ot.get("is_overdue", "N/A")
                title = ot.get("title", "?")[:40]
                print(f"     {'🔴' if is_od else '🟢'} {title} (is_overdue={is_od})")
            if len(overdue_list) == 0:
                record("friction", "F-v7-04", "Overdue 过滤器返回 0 结果（预期 2 个）", "p1", "状态可能是 backlog 而非 ready → overdue 可能需要先 ready")
            elif "is_overdue" not in str(overdue_list[0]) if overdue_list else "":
                record("missing", "M-v7-03", "Task 响应缺 is_overdue 字段", "p1")
        else:
            status = r.status_code if r else "no response"
            text = r.text[:200] if r else ""
            print(f"  ❌ Overdue filter failed: {status} {text}")
            record("friction", "F-v7-04", f"Overdue 过滤器请求失败: {status}", "blocking", text)

        # ── Step 7: List All Tasks (check statuses) ──
        print("\n── Step 7: Task 列表检查 ──")
        r = await api(client, "GET", f"/projects/{proj_id}/tasks")
        if r and (200 <= r.status_code < 300):
            all_tasks = r.json()
            task_list = all_tasks if isinstance(all_tasks, list) else all_tasks.get("tasks", all_tasks.get("items", []))
            statuses = {}
            for t in task_list:
                s = t.get("status", "?")
                statuses[s] = statuses.get(s, 0) + 1
            print(f"  📋 Task 状态分布: {statuses}")
        else:
            status = r.status_code if r else "no response"
            record("friction", "F-v7-05", f"Task 列表请求失败: {status}", "blocking")

        # ── Step 8: Batch Ready (B72!) ──
        print("\n── Step 8: 批量 Ready (B72) ──")
        task_ids_to_ready = [t["id"] for t in tasks[:3]]
        r = await api(client, "POST", "/tasks/batch-ready", json={"task_ids": task_ids_to_ready})
        if r and (200 <= r.status_code < 300):
            result = r.json()
            ok = result.get("success_count", result.get("success", len(task_ids_to_ready)))
            err = result.get("error_count", result.get("errors", 0))
            if isinstance(err, list):
                err = len(err)
            print(f"  ✅ Batch ready: {ok} ok, {err} failed")
        else:
            status = r.status_code if r else "no response"
            text = r.text[:200] if r else ""
            print(f"  ❌ Batch ready failed: {status} {text}")
            record("friction", "F-v7-06", f"批量 Ready 失败: {status}", "blocking", text)

        # ── Step 9: Re-check Worker Load After Tasks (B73!) ──
        print("\n── Step 9: Worker 负载视图更新 (B73 after tasks) ──")
        r = await api(client, "GET", f"/teams/{TEAM_ID}/agents")
        if r and (200 <= r.status_code < 300):
            agent_list = r.json()
            agents_data = agent_list if isinstance(agent_list, list) else agent_list.get("agents", agent_list.get("items", []))
            for a in agents_data:
                name = a.get("name", "?")
                active = a.get("active_task_count", "N/A")
                print(f"  📊 {name}: active_task_count={active}, batch_size={a.get('batch_size', 'N/A')}")
                if "v7" in str(name) and a.get("type") == "agent":
                    if active == 0:
                        print(f"     ℹ️  active_task_count=0 (tasks not yet assigned to this worker)")
        else:
            status = r.status_code if r else "no response"
            record("friction", "F-v7-08", f"Worker 列表获取失败: {status}", "blocking")

        # ── Step 10: Assign Batch to Worker ──
        print("\n── Step 10: Assign Batch to Agent ──")
        agent_w = next((w for w in workers if w.get("type") == "agent"), workers[0] if workers else None)
        if agent_w:
            r = await api(client, "POST", f"/batches/{batch_id}/assign", json={"agent_id": agent_w["id"]})
            if r and (200 <= r.status_code < 300):
                print(f"  ✅ Batch assigned to {agent_w['name']}")
            else:
                status = r.status_code if r else "no response"
                text = r.text[:200] if r else ""
                print(f"  ❌ Assign failed: {status} {text}")
                record("friction", "F-v7-09", f"Batch assign 失败: {status}", "blocking", text)

        # ── Step 11: Claim Tasks ──
        print("\n── Step 11: Claim Tasks ──")
        claimed = []
        for t in tasks[:3]:
            r = await api(client, "POST", f"/tasks/{t['id']}/claim", json={
                "actor_type": "agent", "actor_id": agent_w["id"] if agent_w else workers[0]["id"],
            })
            if r and (200 <= r.status_code < 300):
                claimed.append(t)
                print(f"  ✅ Claimed: {t['title'][:40]}")
            else:
                status = r.status_code if r else "no response"
                text = r.text[:200] if r else ""
                print(f"  ❌ Claim failed: {status} {text}")
                record("friction", f"F-v7-c{len(claimed)}", f"Claim 失败: {status}", "blocking", text)

        # ── Step 12: Submit Tasks ──
        print("\n── Step 12: Submit Tasks ──")
        for t in claimed:
            r = await api(client, "POST", f"/tasks/{t['id']}/submit", json={
                "actor_type": "agent",
                "actor_id": agent_w["id"] if agent_w else workers[0]["id"],
                "summary": f"完成 {t['title']}",
                "evidence": {"files_changed": 3, "tests_added": 5},
            })
            if r and (200 <= r.status_code < 300):
                print(f"  ✅ Submitted: {t['title'][:40]}")
            else:
                status = r.status_code if r else "no response"
                text = r.text[:200] if r else ""
                print(f"  ❌ Submit failed: {status} {text}")
                record("friction", f"F-v7-s{len(claimed)}", f"Submit 失败: {status}", "blocking", text)

        # ── Step 13: Verify Tasks ──
        print("\n── Step 13: Verify Tasks (PM 验收) ──")
        for t in claimed:
            # Get task detail to find verification
            r = await api(client, "GET", f"/tasks/{t['id']}")
            if not r or r.status_code != 200:
                print(f"  ❌ Get task failed for verify: {r.status_code if r else 'no response'}")
                continue
            task_detail = r.json()
            verifications = task_detail.get("verifications", [])
            if not verifications:
                # Try verifications endpoint
                r2 = await api(client, "GET", f"/tasks/{t['id']}/verifications")
                if r2 and r2.status_code == 200:
                    v_data = r2.json()
                    verifications = v_data if isinstance(v_data, list) else v_data.get("verifications", v_data.get("items", []))
            if not verifications:
                print(f"  ⚠️  No verification found for {t['title'][:40]}")
                record("friction", f"F-v7-v{tasks.index(t)}", f"Task 无 Verification 可验收", "p1", "Task status 可能未到 in_verification")
                continue
            for v in verifications:
                v_id = v.get("id", v.get("verification_id", "?"))
                r = await api(client, "POST", f"/verifications/{v_id}/verify", json={
                    "status": "passed", "comment": "PM review: looks good",
                })
                if r and (200 <= r.status_code < 300):
                    print(f"  ✅ Verified: {t['title'][:40]} → PASSED")
                else:
                    status = r.status_code if r else "no response"
                    text = r.text[:200] if r else ""
                    print(f"  ❌ Verify failed: {status} {text}")
                    record("friction", f"F-v7-verify", f"Verify 失败: {status}", "blocking", text)

        # ── Step 14: Dashboard + Project Breakdown (B71!) ──
        print("\n── Step 14: Dashboard + 项目进度 (B71) ──")
        r = await api(client, "GET", f"/dashboard/teams/{TEAM_ID}/projects-breakdown")
        if r and (200 <= r.status_code < 300):
            breakdown = r.json()
            projects = breakdown.get("projects", [])
            found = [p for p in projects if p.get("project_id") == proj_id]
            if found:
                p = found[0]
                print(f"  ✅ {proj_name}: total={p.get('total_tasks')}, completed={p.get('completed_tasks')}")
            else:
                print(f"  ⚠️  New project not in breakdown")
                record("friction", "F-v7-10", "新项目未出现在 project breakdown (B71)", "p2")
        else:
            status = r.status_code if r else "no response"
            record("friction", "F-v7-10", f"Project breakdown 失败: {status}", "blocking")

        # ── Step 15: Final Overdue Check ──
        print("\n── Step 15: 最终 Overdue 状态检查 (B74) ──")
        r = await api(client, "GET", f"/projects/{proj_id}/tasks?status=overdue")
        if r and (200 <= r.status_code < 300):
            overdue_data = r.json()
            overdue_list = overdue_data if isinstance(overdue_data, list) else overdue_data.get("tasks", overdue_data.get("items", []))
            # Some overdue tasks may now be completed → gone from overdue
            print(f"  📅 Remaining overdue: {len(overdue_list)} (some may be completed now)")
        else:
            status = r.status_code if r else "no response"

    # ── Summary ──
    print("\n" + "=" * 60)
    print("Dogfooding v7 审计完成")
    f_count = sum(1 for f in findings if f["cat"] == "friction")
    m_count = sum(1 for f in findings if f["cat"] == "missing")
    b_count = sum(1 for f in findings if f["sev"] == "blocking")
    print(f"Friction: {f_count} | Missing Cap: {m_count} | Blocking: {b_count}")
    print("=" * 60)

    if findings:
        print("\n📋 发现清单:")
        for f in sorted(findings, key=lambda x: {"blocking": 0, "p0": 1, "p1": 2, "p2": 3}.get(x["sev"], 9)):
            print(f"  [{f['sev'].upper()}] {f['id']}: {f['desc']}")
            if f.get("note"):
                print(f"       → {f['note']}")

    # Write findings
    os.makedirs("data", exist_ok=True)
    with open("data/b77-findings.json", "w") as fp:
        json.dump({"findings": findings, "timestamp": datetime.now().isoformat(),
                    "project_id": proj_id, "batch_id": batch_id}, fp, indent=2, ensure_ascii=False)
    print(f"\n📁 Findings → data/b77-findings.json")

    return findings


if __name__ == "__main__":
    result = asyncio.run(main())
    if result is None:
        print("❌ Audit aborted — no findings returned")
        sys.exit(1)
    blocking = [f for f in result if f["sev"] == "blocking"]
    sys.exit(1 if blocking else 0)
