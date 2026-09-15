import os

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

db_path = settings.database_url.replace("sqlite:///", "")
if db_path.startswith("./"):
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

# The deployed service runs two uvicorn workers against one SQLite file,
# and a league sync is a single long write transaction (hundreds of
# players, thousands of stat rows). The default rollback journal blocks
# readers for that whole window and gives up after 5s, which surfaces as
# "database is locked" on whatever request happens to land mid-sync — so
# wait considerably longer before giving up.
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    # WAL lets reads run concurrently with the sync's write transaction
    # instead of queueing behind it. synchronous=NORMAL is the usual
    # companion: still crash-safe against process death, and only risks
    # the last commits if the whole machine loses power.
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ensure_column(conn, table: str, column: str, ddl: str) -> None:
    """Adds `column` to `table` if it isn't there yet. Base.metadata.create_all()
    below only creates whole new tables — it never alters one that already
    exists — so a column added to a model after real installs already have
    that table on disk needs to be backfilled here, or every request
    touching it 500s with "no such column"."""
    existing = {row[1] for row in conn.execute(text(f'PRAGMA table_info("{table}")'))}
    if column not in existing:
        conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {column} {ddl}'))


def init_db():
    from app import models  # noqa: F401  (ensure models are registered)

    Base.metadata.create_all(bind=engine)

    with engine.connect() as conn:
        _ensure_column(conn, "users", "admin_granted", "BOOLEAN NOT NULL DEFAULT 0")
        _ensure_column(conn, "leagues", "fantasycalc_values", "JSON DEFAULT '{}'")
        conn.commit()
