from sqlalchemy import String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})


class Base(DeclarativeBase):
    pass


class SessionRow(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    resource_type: Mapped[str] = mapped_column(String(128), default="")
    source: Mapped[str] = mapped_column(String(128), default="")
    scope_json: Mapped[str] = mapped_column(Text, default="{}")
    scope_hash: Mapped[str] = mapped_column(String(64), default="")
    pagination_type: Mapped[str] = mapped_column(String(32), default="cursor")
    snapshot_strategy: Mapped[str] = mapped_column(String(32), default="STRICT")
    status: Mapped[str] = mapped_column(String(32), default="collecting")
    observations_json: Mapped[str] = mapped_column(Text, default="[]")
    failures_json: Mapped[str] = mapped_column(Text, default="[]")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    certificate_json: Mapped[str] = mapped_column(Text, default="{}")


def init_db() -> None:
    Base.metadata.create_all(engine)
