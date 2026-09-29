import asyncio
from concurrent.futures import Future
from threading import Lock, Thread

from sqlalchemy import String, Text, create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import StaticPool

from app.core.config import DATABASE_URL

_engine_options = {"connect_args": {"check_same_thread": False, "timeout": 2}} if DATABASE_URL.startswith("sqlite") else {}
if DATABASE_URL.startswith(("postgresql", "postgres")):
    _engine_options.update(connect_args={"connect_timeout": 2, "options": "-c statement_timeout=2000"}, pool_timeout=2)
if DATABASE_URL in {"sqlite://", "sqlite:///:memory:"}:
    _engine_options["poolclass"] = StaticPool
engine = create_engine(DATABASE_URL, **_engine_options)

READINESS_TIMEOUT = 2.0
_probe_lock = Lock()
_probe = None


async def database_ready() -> bool:
    global _probe

    def check(future):
        try:
            with engine.connect() as connection:
                available = connection.execute(text("SELECT 1")).scalar() == 1
        except (SQLAlchemyError, OSError, RuntimeError):
            available = False
        future.set_result(available)

    # A stalled driver occupies at most one daemon worker, not one per request.
    with _probe_lock:
        if _probe is None or _probe.done():
            _probe = Future()
            Thread(target=check, args=(_probe,), daemon=True).start()
        probe = _probe
    try:
        async with asyncio.timeout(READINESS_TIMEOUT):
            # Poll without retaining one future callback per timed-out request.
            while not probe.done():
                await asyncio.sleep(0.02)
            return probe.result()
    except TimeoutError:
        return False


class Base(DeclarativeBase):
    pass


class ProjectRow(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    openapi_url: Mapped[str] = mapped_column(Text, default="")
    spec_json: Mapped[str] = mapped_column(Text, default="{}")
    analysis_json: Mapped[str] = mapped_column(Text, default="{}")
    tests_json: Mapped[str] = mapped_column(Text, default="[]")
    issues_json: Mapped[str] = mapped_column(Text, default="[]")
    score_json: Mapped[str] = mapped_column(Text, default="{}")
    repairs_json: Mapped[str] = mapped_column(Text, default="[]")
    tools_json: Mapped[str] = mapped_column(Text, default="[]")
    retest_json: Mapped[str] = mapped_column(Text, default="{}")
    proof_json: Mapped[str] = mapped_column(Text, default="{}")


class OutcomeReceiptRow(Base):
    __tablename__ = "outcome_receipts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_at: Mapped[str] = mapped_column(String(40))
    receipt_json: Mapped[str] = mapped_column(Text)


class OutcomeLabReceiptRow(Base):
    """Separate persistence boundary for Chaos Lab fixture receipts.

    Lab traffic must never count against, retain, or evict production
    evidence in ``outcome_receipts``. ``Base.metadata.create_all`` creates
    this table on existing deployments without touching production rows.
    """

    __tablename__ = "outcome_lab_receipts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_at: Mapped[str] = mapped_column(String(40))
    receipt_json: Mapped[str] = mapped_column(Text)


def init_db() -> None:
    Base.metadata.create_all(engine)
    columns = {column["name"] for column in inspect(engine).get_columns("projects")}
    if "proof_json" not in columns:
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE projects ADD COLUMN proof_json TEXT DEFAULT '{}'")
