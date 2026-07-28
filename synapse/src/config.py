"""通过环境变量加载的应用配置。"""

from pydantic import BaseModel
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

    # Task staleness detection (P11-B76)
    task_stale_threshold_minutes: int = 60
    task_stale_scan_interval_seconds: int = 120

    # Verification timeout auto-reclaim (P11-B88)
    verification_timeout_minutes: int = 30

    # Verify idempotent guard (P11-B76)
    verify_idempotent_window_seconds: int = 60

    # WebSocket (P11-B23: 生产加固)
    ws_max_connections: int = 200
    ws_max_message_size: int = 65536  # 64 KB

    # WebPush (P10-B44 · S-066)
    vapid_private_key: str = ""
    vapid_public_key: str = ""
    vapid_claims_email: str = ""  # RFC 8292 contact email


settings = Settings()
