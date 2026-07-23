#!/usr/bin/env python3
"""一次性：为 github_hunter OAuth 用户添加 email+password 认证方式。

这不是后门 — 是账号 provisioning。github_hunter 通过 GitHub OAuth 创建，
没有 email/password，无法通过网页登录表单登录。本脚本补上 email+password
认证方式，使其可以正经登录网页后台审批授权。

用法：
    python3 tools/setup-hunter-password.py <email> <password>

示例：
    python3 tools/setup-hunter-password.py hunter@synapse.local mypassword123
"""

import sys
import os
import asyncio
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from sqlalchemy import select
from src.db import async_session_factory
from src.models.user import User
from src.models.user_auth_method import UserAuthMethod
from src.models.worker import Worker
from src.models.project_actor_role import ProjectActorRole
from src.utils.security import hash_password
from src.utils.id_gen import derive_id, generate_id


async def main():
    if len(sys.argv) != 3:
        print("用法: python3 tools/setup-hunter-password.py <email> <password>")
        sys.exit(1)

    email = sys.argv[1].strip().lower()
    password = sys.argv[2]

    if len(password) < 6:
        print("❌ 密码至少 6 位")
        sys.exit(1)

    async with async_session_factory() as db:
        # 1. 找到 github_hunter 的 member 记录以获取 user_id
        from src.models.member import Member
        result = await db.execute(
            select(Member).where(Member.user_id == "github_hunter")
        )
        member = result.scalar_one_or_none()
        if not member:
            print("❌ 找不到 github_hunter member 记录")
            sys.exit(1)

        # 2. 找到或创建对应的 User
        # github_hunter 的 user_id 在 member 表中是 "github_hunter"
        # 但 User 表的 PK 是 usr_ 格式
        # 尝试通过 member.user_id 查找
        result = await db.execute(
            select(User).where(User.id == "usr_a85ae684f55132df")
        )
        user = result.scalar_one_or_none()

        if not user:
            # 尝试通过 display_name 查找
            result = await db.execute(
                select(User).where(User.display_name == "Hunter")
            )
            user = result.scalar_one_or_none()

        if not user:
            print("❌ 找不到 github_hunter 对应的 User 记录")
            print("   member.user_id =", member.user_id)
            sys.exit(1)

        print(f"✅ 找到用户: id={user.id}  display_name={user.display_name}")

        # 3. 检查是否已有 email auth method
        result = await db.execute(
            select(UserAuthMethod).where(
                UserAuthMethod.user_id == user.id,
                UserAuthMethod.provider == "email",
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            print(f"⚠️  用户已有 email 认证: {existing.subject}")
            print("   如需重置密码，请使用 forgot-password 流程")
            sys.exit(1)

        # 4. 设置 email + password
        user.email = email
        user.password_hash = hash_password(password)
        print(f"✅ 设置 email={email} + password")

        # 5. 创建 UserAuthMethod
        auth_method = UserAuthMethod(
            id=generate_id("user_auth_method"),
            user_id=user.id,
            provider="email",
            subject=email,
        )
        db.add(auth_method)
        print(f"✅ 创建 UserAuthMethod(provider=email, subject={email})")

        # 6. 确保 derived worker 存在并赋予 admin 角色
        # login_user 会用 derive_id(user.id, "worker") 找 worker
        worker_id = derive_id(user.id, "worker")
        result = await db.execute(select(Worker).where(Worker.id == worker_id))
        worker = result.scalar_one_or_none()

        if not worker:
            worker = Worker(
                id=worker_id,
                name=user.display_name,
                user_id=user.id,
                actor_type="human",
                status="active",
                api_key_hash=None,
            )
            db.add(worker)
            print(f"✅ 创建 Worker: id={worker_id}  name={user.display_name}")
        else:
            print(f"✅ Worker 已存在: id={worker_id}  name={worker.name}")

        # 7. 赋予 Synapse 项目 admin 角色
        SYN = "prj_019f6e082ec572fd"  # Synapse 项目
        result = await db.execute(
            select(ProjectActorRole).where(
                ProjectActorRole.project_id == SYN,
                ProjectActorRole.worker_id == worker_id,
            )
        )
        par = result.scalar_one_or_none()

        if not par:
            # 生成确定性 PAR ID
            par_id = derive_id(f"{SYN}:{worker_id}", "project_actor_role")
            par = ProjectActorRole(
                id=par_id,
                project_id=SYN,
                worker_id=worker_id,
                role="admin",
            )
            db.add(par)
            print(f"✅ 赋予 Synapse 项目 admin 角色: worker={worker_id}")
        else:
            print(f"✅ 项目角色已存在: role={par.role}")
            if par.role != "admin":
                par.role = "admin"
                print(f"   🔄 角色从 {par.role} 升级为 admin")

        await db.commit()

        print()
        print("=" * 60)
        print("🎉 配置完成！")
        print()
        print(f"   登录页面: http://localhost:5173/login")
        print(f"   邮箱:     {email}")
        print(f"   密码:     {password}")
        print()
        print("   登录后访问 /approvals 即可看到待审批的授权请求。")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
