import os

from sqlalchemy import create_engine, event
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


def init_db():
    from app import models  # noqa: F401  (ensure models are registered)

    Base.metadata.create_all(bind=engine)
