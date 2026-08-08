"""通过环境变量加载的应用配置。"""

from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ContinuityConfig(BaseModel):
    """TaskContinuityDetector 的配置。

    Attributes:
        enabled: 功能开关 — 为 False 时 detect() 返回 None。
        snapshot_gap_seconds: 快照之间的最小间隔（秒）。
            若最近一次快照比此值更新，detect() 返回 None。
        num_snapshots_for_summary: 生成连续性摘要时比较的历史快照数量。
    """

    enabled: bool = True
    snapshot_gap_seconds: float = 1800.0  # 30 minutes
    num_snapshots_for_summary: int = 3


class FeaturesConfig(BaseModel):
    """Feature flags controlling UI complexity (S-015 极简模式).

    Attributes:
        project_count: Max projects visible in UI. 0 = unlimited.
            1 = single project mode (no project list, no project selector).
        batch_size: Max batch size. 0 = unlimited.
            1 = single task mode (no batch UI, 1 task = 1 batch auto-created).
    """

    project_count: int = 0  # 0 = unlimited
    batch_size: int = 0  # 0 = unlimited
    teams: bool = True  # True = normal, False = teams hidden


class Settings(BaseSettings):
    """从环境变量 / .env 文件加载的 Synapse 配置。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "sqlite+aiosqlite:///data/synapse.db"

    # JWT
    jwt_secret: str = "dev-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 15

    @field_validator("jwt_secret")
    @classmethod
    def _ensure_jwt_secret_is_set(cls, v: str) -> str:
        """P100-B105: 禁止在非开发环境使用 placeholder JWT 密钥。"""
        if v in ("dev-secret-change-in-production", "change-me-to-a-random-string"):
            raise ValueError(
                "JWT_SECRET 不能使用默认 placeholder 值。"
                " 请设置环境变量 JWT_SECRET 为一个随机字符串。"
                " 生成方式: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
            )
        return v

    # API Key
    api_key_prefix: str = "sk-syn-"

    # Project Key (P11-B8: project-level access credential)
    project_key_prefix: str = "spk-"

    # OAuth — GitHub
    github_client_id: str = ""
    github_client_secret: str = ""
    github_redirect_uri: str = "http://localhost:8000/v1/auth/oauth/github/callback"

    # Refresh token
    refresh_token_expire_days: int = 7

    # Password reset token
    reset_token_expire_minutes: int = 60

    # SMTP Email
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = "noreply@synapse.local"
    smtp_from_name: str = "Synapse"
    smtp_use_tls: bool = True

    # Frontend
    frontend_url: str = "http://localhost:5173"

    # Cookie (access token — httpOnly)
    access_token_cookie_name: str = "access_token"
    cookie_secure: bool = True  # True when not in debug mode

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True

    # Continuity detection
    continuity: ContinuityConfig = ContinuityConfig()

    # Feature flags (S-015 极简模式)
    features: FeaturesConfig = FeaturesConfig()

    # Authorization request expiry scheduler (P11-B50)
    auth_expiry_interval_seconds: int = 30

    # Task staleness detection (P11-B76) + auto-cancel gate (P11-B108)
    # + reassign tier (P11-B125): reclaim abandoned in_progress → READY
    task_stale_threshold_minutes: int = 60
    task_stale_reassign_minutes: int = 45  # B22: 15→45 — 狗粮发现 rework 超过 15min 被误回收
    task_stale_scan_interval_seconds: int = 120
    task_stale_max_detections: int = 10  # auto-cancel after N stale detections
    task_ready_unclaimed_timeout_minutes: int = 30  # PFL-128: READY task 无人认领超时 — Server 层安全网

    # Verification timeout auto-reclaim (P11-B88)
    verification_timeout_minutes: int = 120  # B22: 30→120 — 狗粮发现人工审批 30min 不够
    verification_max_auto_reverts: int = 5  # B22: 3→5 — 更多 rework 容错空间

    # Verification escalation to Human (P12-B47 · PFL-151 Option B)
    verification_escalation_minutes: int = 10  # O 沉默 >10min → auto-escalate to Human
    verification_escalation_cooldown_minutes: int = 30  # 同任务不重复升级的最小间隔

    # Worker heartbeat monitor (P11-B128 · PFL-126 direction 4)
    worker_heartbeat_timeout_seconds: int = 300  # 5 min no heartbeat → offline (standard)
    worker_heartbeat_timeout_seconds_codex: int = 1800  # P12-B42: 30 min for Codex (no daemon)
    worker_heartbeat_monitor_interval_seconds: int = 60  # scan every 60s

    # Verify idempotent guard (P11-B76)
    verify_idempotent_window_seconds: int = 60

    # WebSocket (P11-B23: 生产加固)
    ws_max_connections: int = 200
    ws_max_message_size: int = 65536  # 64 KB

    # Rate limiting (P100-B105 · PFL-085)
    rate_limit_enabled: bool = True
    rate_limit_login: str = "5/minute"
    rate_limit_register: str = "3/minute"
    rate_limit_forgot_password: str = "3/minute"
    rate_limit_reset_password: str = "3/minute"
    rate_limit_notify: str = "5/minute"  # P12-B50: notify 端点频率限制

    # WebPush (P10-B44 · S-066)
    vapid_private_key: str = ""
    vapid_public_key: str = ""
    vapid_claims_email: str = ""  # RFC 8292 contact email


settings = Settings()


# ── Rate limiter (P100-B105 · PFL-085) ──────────────────────────────────

from slowapi import Limiter  # noqa: E402
from slowapi.util import get_remote_address  # noqa: E402

limiter = Limiter(key_func=get_remote_address)
"""共享 Limiter 实例 — main.py 注册中间件，auth.py 用 @limiter.limit 装饰端点。"""
