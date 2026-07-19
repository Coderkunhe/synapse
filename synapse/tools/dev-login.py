#!/usr/bin/env python3
"""Dev helper: generate a JWT for local dev and open the browser with it.

Usage:
    python3 tools/dev-login.py

Only works when the Synapse backend is running on localhost:8000.
The token is injected via the OAuth callback page.

IDs are resolved dynamically from the local SQLite DB — no hardcoded IDs
that drift across DB rebuilds.
"""

import sys
import os
import sqlite3
import webbrowser
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "data" / "synapse.db"

sys.path.insert(0, str(PROJECT_DIR))

from src.auth import create_access_token
from src.config import settings


def find_admin_member(db_path: str) -> dict:
    """Find an admin member in the local dev DB. Returns {user_id, member_id, team_id, role, display_name}."""
    if not os.path.exists(db_path):
        print(f"❌ Database not found: {db_path}")
        print("   Run: make db-reset  or  start the dev server once to create it")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Prefer: find any admin member
    row = conn.execute(
        "SELECT m.id, m.user_id, m.display_name, m.role, m.team_id "
        "FROM member m "
        "WHERE m.role = 'admin' "
        "ORDER BY m.created_at ASC "
        "LIMIT 1"
    ).fetchone()

    if row is None:
        # Fallback: any member at all
        row = conn.execute(
            "SELECT m.id, m.user_id, m.display_name, m.role, m.team_id "
            "FROM member m "
            "ORDER BY m.created_at ASC "
            "LIMIT 1"
        ).fetchone()

    conn.close()

    if row is None:
        print("❌ No member found in database.")
        print("   Run: python3 tools/seed-synapse-project.py")
        sys.exit(1)

    return dict(row)


def main():
    member = find_admin_member(str(DB_PATH))

    print(f"✅ Found member: {member['display_name']} ({member['role']})")
    print(f"   member_id: {member['id']}")
    print(f"   team_id:   {member['team_id']}")

    TOKEN = create_access_token(
        user_id=member["user_id"],
        member_id=member["id"],
        team_id=member["team_id"],
        role=member["role"],
    )

    url = (
        f"{settings.frontend_url}/oauth/callback"
        f"?access_token={TOKEN}"
        f"&member_id={member['id']}"
        f"&team_id={member['team_id']}"
        f"&role={member['role']}"
        f"&display_name={member['display_name']}"
        f"&expires_in={settings.jwt_expire_minutes * 60}"
    )

    print(f"Opening: {settings.frontend_url}/oauth/callback?access_token=...")
    webbrowser.open(url)


if __name__ == "__main__":
    main()
