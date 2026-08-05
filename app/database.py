import time

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    connect_args={"connect_timeout": 30},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

Base = declarative_base()

# Absorbs a serverless Postgres waking up from auto-suspend (a few seconds of
# cold start) without surfacing it to the client as a failed request.
RETRY_DELAYS = (0, 1, 2, 4)


def get_db():
    session = SessionLocal()
    last_error: Exception | None = None
    for delay in RETRY_DELAYS:
        if delay:
            time.sleep(delay)
            session = SessionLocal()
        try:
            session.execute(text("SELECT 1"))
            last_error = None
            break
        except OperationalError as exc:
            last_error = exc
            session.close()
    if last_error is not None:
        raise last_error
    try:
        yield session
    finally:
        session.close()
