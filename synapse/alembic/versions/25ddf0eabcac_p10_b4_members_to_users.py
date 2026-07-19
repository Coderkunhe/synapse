"""p10_b4_members_to_users

Revision ID: 25ddf0eabcac
Revises: 0fb3b370971c
Create Date: 2026-07-17 12:13:57.675878

P10-B4: members → users + human workers 数据迁移

从存量 Member 记录创建对应的 User + human Worker 记录。
幂等设计：基于确定性 derived ID，所有 INSERT 均包裹 WHERE NOT EXISTS。

数据流向：
  member ──→ user (derive_id: member.id → usr_xxx)
          ──→ user_auth_method (仅 OAuth 成员)
          ──→ worker (actor_type='human', user_id=derived_user_id)

Bonus: 存量 agent worker 的 registered_by=NULL → 指向对应 team 的 human worker。

API Key 使用 member_id 确定性派生（非 secrets.token_hex），确保迁移幂等。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '25ddf0eabcac'
down_revision: Union[str, None] = '0fb3b370971c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _derive_id(source: str, entity_type: str) -> str:
    """确定性 ID 派生 — 与 src/utils/id_gen.py:derive_id 同逻辑。

    迁移文件内联此函数以避免跨文件 import 依赖（migration 需自包含）。
    """
    import hashlib

    PREFIXES = {
        "user": "usr",
        "worker": "ag",
        "user_auth_method": "uam",
    }
    prefix = PREFIXES[entity_type]
    h = hashlib.sha256(source.encode()).hexdigest()[:16]
    return f"{prefix}_{h}"


def _derive_api_key(member_id: str, worker_id: str) -> dict:
    """确定性派生 API Key（非 secrets.token_hex，保证幂等）。

    Returns:
        dict with keys: plaintext, hash, prefix
    """
    import hashlib

    deterministic_random = hashlib.sha256(
        ("api_key:" + member_id).encode()
    ).hexdigest()
    worker_prefix = worker_id.replace("ag_", "")[:8]
    plaintext = f"sk-syn-{deterministic_random}.{worker_prefix}"
    hashed = hashlib.sha256(plaintext.encode()).hexdigest()
    return {
        "plaintext": plaintext,
        "hash": hashed,
        "prefix": plaintext[:12],
    }


def _member_source(m: sa.engine.Row) -> str:
    """返回 member 的稳定 source string（用于 derive_id）。

    使用 member.id 作为 source — 与 Router 中 _resolve_human_worker_id
    的逻辑一致（actor.actor_id = member_id from JWT）。
    """
    return m.id


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. 读取所有 Member ──────────────────────────────────────────
    members = conn.execute(
        sa.text(
            "SELECT id, team_id, user_id, display_name, role, email, "
            "avatar_url, oauth_provider, oauth_subject "
            "FROM member"
        )
    ).fetchall()

    for m in members:
        member_id = m.id
        source = _member_source(m)
        user_id = _derive_id(source, "user")
        worker_id = _derive_id(source, "worker")
        api_key = _derive_api_key(member_id, worker_id)

        # ── 2. INSERT INTO user (幂等) ──────────────────────────────
        conn.execute(
            sa.text(
                "INSERT INTO \"user\" (id, email, password_hash, display_name, "
                "avatar_url, is_active, is_disabled, create_user_id, "
                "last_update_user_id, remark, version_no, created_at, updated_at) "
                "SELECT :id, :email, NULL, :display_name, "
                ":avatar_url, 1, 0, 'system', "
                "NULL, :remark, 1, datetime('now'), datetime('now') "
                "WHERE NOT EXISTS (SELECT 1 FROM \"user\" WHERE id = :id)"
            ),
            {
                "id": user_id,
                "email": m.email,
                "display_name": m.display_name,
                "avatar_url": m.avatar_url,
                "remark": f"migrated from member {member_id}",
            },
        )

        # ── 3. INSERT INTO user_auth_method (仅 OAuth，幂等) ─────────
        if m.oauth_provider and m.oauth_subject:
            uam_source = f"{m.oauth_provider}:{m.oauth_subject}"
            uam_id = _derive_id(uam_source, "user_auth_method")
            conn.execute(
                sa.text(
                    "INSERT INTO user_auth_method (id, user_id, provider, subject, "
                    "created_at, is_disabled, create_user_id, "
                    "last_update_user_id, remark, version_no, updated_at) "
                    "SELECT :id, :user_id, :provider, :subject, "
                    "datetime('now'), 0, 'system', "
                    "NULL, :remark, 1, datetime('now') "
                    "WHERE NOT EXISTS (SELECT 1 FROM user_auth_method WHERE id = :id)"
                ),
                {
                    "id": uam_id,
                    "user_id": user_id,
                    "provider": m.oauth_provider,
                    "subject": m.oauth_subject,
                    "remark": f"migrated from member {member_id}",
                },
            )

        # ── 4. INSERT INTO worker (human，幂等) ──────────────────────
        conn.execute(
            sa.text(
                "INSERT INTO worker (id, actor_type, user_id, team_id, name, "
                "provider, provider_model, registered_by, "
                "api_key_hash, api_key_prefix, status, "
                "system_prompt, metadata, runtime_status, "
                "batch_size, capability_tags, "
                "active_task_id, last_heartbeat_at, last_progress_at, "
                "is_disabled, create_user_id, last_update_user_id, "
                "remark, version_no, created_at, updated_at) "
                "SELECT :id, 'human', :user_id, :team_id, :name, "
                "'', NULL, NULL, "
                ":api_key_hash, :api_key_prefix, 'active', "
                "NULL, NULL, 'idle', "
                "3, NULL, "
                "NULL, NULL, NULL, "
                "0, 'system', NULL, "
                ":remark, 1, datetime('now'), datetime('now') "
                "WHERE NOT EXISTS (SELECT 1 FROM worker WHERE id = :id)"
            ),
            {
                "id": worker_id,
                "user_id": user_id,
                "team_id": m.team_id,
                "name": m.display_name,
                "api_key_hash": api_key["hash"],
                "api_key_prefix": api_key["prefix"],
                "remark": f"migrated from member {member_id}",
            },
        )

    # ── 5. UPDATE: wire existing agent workers' registered_by ────────
    # 存量 agent worker (registered_by=NULL) → 指向同 team 的 human worker
    conn.execute(
        sa.text(
            "UPDATE worker SET registered_by = ("
            "  SELECT hw.id FROM worker AS hw "
            "  WHERE hw.team_id = worker.team_id "
            "    AND hw.actor_type = 'human' "
            "    AND hw.id != worker.id "
            "  LIMIT 1"
            ") "
            "WHERE worker.actor_type = 'agent' "
            "  AND worker.registered_by IS NULL"
        )
    )


def downgrade() -> None:
    """移除迁移创建的数据。

    先解除 agent worker 的 registered_by 引用 → 删 human worker →
    删 user_auth_method → 删 user。通过 remark 字段定位迁移创建的记录。
    """
    conn = op.get_bind()

    # 1. 重置 agent worker registered_by (指向 human worker 的)
    conn.execute(
        sa.text(
            "UPDATE worker SET registered_by = NULL "
            "WHERE registered_by IN ("
            "  SELECT id FROM worker WHERE remark LIKE 'migrated from member %'"
            ")"
        )
    )

    # 2. 删 human worker
    conn.execute(
        sa.text(
            "DELETE FROM worker WHERE remark LIKE 'migrated from member %'"
        )
    )

    # 3. 删 user_auth_method
    conn.execute(
        sa.text(
            "DELETE FROM user_auth_method WHERE remark LIKE 'migrated from member %'"
        )
    )

    # 4. 删 user
    conn.execute(
        sa.text(
            "DELETE FROM \"user\" WHERE remark LIKE 'migrated from member %'"
        )
    )
