import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TEST_DATABASE_URL = "postgresql+psycopg://attendance:attendance@localhost:5433/attendance_test"

from app.database import Base  # noqa: E402
import app.models  # noqa: E402,F401

engine = create_engine(TEST_DATABASE_URL)
TestSessionLocal = sessionmaker(bind=engine)


@pytest.fixture(scope="session", autouse=True)
def _create_schema():
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture
def db():
    session = TestSessionLocal()
    yield session
    session.close()
