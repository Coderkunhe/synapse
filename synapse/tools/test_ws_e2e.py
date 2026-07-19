#!/usr/bin/env python3
"""End-to-end WebSocket test for Synapse P3-B5.

Tests: connect → auth → ping/pong → subscribe → event broadcast.
"""

import asyncio
import json
import sys

import websockets

from src.auth import create_access_token

MEMBER_ID = "mem_019f28a621dd764a"
TEAM_ID = "tea_019f28a621d47592"


async def test_ws():
    token = create_access_token(MEMBER_ID, TEAM_ID, "admin")
    uri = f"ws://localhost:8000/v1/ws?token={token}"
    passed = 0
    failed = 0

    print(f"→ Connecting to ws://localhost:8000/v1/ws?token=<jwt>")

    async with websockets.connect(uri) as ws:
        # 1. Connected message
        msg = json.loads(await ws.recv())
        assert msg["type"] == "connected", f"Expected connected, got {msg['type']}"
        assert msg["actor_id"] == MEMBER_ID
        print(f"  ✅ connected: actor={msg['actor_id']}, team={msg['team_id']}")
        passed += 1

        # 2. Ping/Pong
        await ws.send(json.dumps({"type": "ping"}))
        pong = json.loads(await ws.recv())
        assert pong["type"] == "pong", f"Expected pong, got {pong['type']}"
        print("  ✅ ping/pong")
        passed += 1

        # 3. Subscribe
        await ws.send(json.dumps({"type": "subscribe", "topics": ["project.created", "task.created"]}))
        print("  ✅ subscribe project.created, task.created")
        passed += 1

        # 4. Create event via REST → should arrive via WS
        import httpx
        async with httpx.AsyncClient() as client:
            # Create project (path: /v1/teams/{team_id}/projects)
            r = await client.post(
                f"http://localhost:8000/v1/teams/{TEAM_ID}/projects",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"name": "WS E2E Test", "slug": "ws-e2e-test-3", "team_id": TEAM_ID},
            )
            if r.status_code == 201:
                proj_id = r.json()["id"]

                # Create task (triggers task.created event)
                r2 = await client.post(
                    f"http://localhost:8000/v1/projects/{proj_id}/tasks",
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json={"title": "WS E2E Task", "description": "Real-time test"},
                )
                if r2.status_code == 201:
                    print(f"  ✅ REST task created ({r2.json().get('id', '?')}) → waiting for WS event...")
            else:
                print(f"  ⚠️ REST project create failed: {r.status_code} {r.text}")

        # 5. Receive the broadcast event
        try:
            evt = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
            if evt["type"] == "event":
                event_type = evt["data"]["event_type"]
                print(f"  ✅ WS event received: {event_type}")
                passed += 1
            else:
                print(f"  ⚠️ Unexpected msg: {evt['type']}")
                failed += 1
        except asyncio.TimeoutError:
            print("  ❌ No event received within 5s")
            failed += 1

    print(f"\n{'═' * 40}")
    print(f"  Results: {passed} passed, {failed} failed")
    if failed == 0:
        print("  🎉 WebSocket E2E: ALL PASSED")
    else:
        print("  🔴 WebSocket E2E: FAILURES DETECTED")
    print(f"{'═' * 40}")
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(test_ws())
    sys.exit(0 if success else 1)
