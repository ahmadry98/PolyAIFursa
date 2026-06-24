import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("CONFIDENCE_THRESHOLD", "0.5")

from app import app
import database
from database import Base, get_db


@pytest.fixture
def db_session(monkeypatch):
    test_database_url = os.environ.get("TEST_DATABASE_URL", "sqlite://")
    engine_options = {}
    if test_database_url.startswith("sqlite"):
        engine_options["connect_args"] = {"check_same_thread": False}
    if test_database_url == "sqlite://":
        engine_options["poolclass"] = StaticPool

    test_engine = create_engine(test_database_url, **engine_options)
    TestSession = sessionmaker(
        bind=test_engine,
        autoflush=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(bind=test_engine)

    def override_get_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(database, "engine", test_engine)

    session = TestSession()

    yield session

    app.dependency_overrides.clear()
    session.close()
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


@pytest.fixture
def client(db_session):
    with TestClient(app) as test_client:
        yield test_client
