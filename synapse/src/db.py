"""SQLAlchemy async engine and session factory."""

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    future=True,
)


# ── SQLite FK 强制（P100-B106 · ⑪）─────────────────────────────
# SQLite 默认不强制外键约束。通过 event listener 为每个新连接
# 启用 PRAGMA foreign_keys = ON，确保参照完整性在开发和生产环境一致。
@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record):  # pragma: no cover — event listener
    if settings.database_url.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    """FastAPI dependency: yield an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
