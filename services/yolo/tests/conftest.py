import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("CONFIDENCE_THRESHOLD", "0.5")

import app as app_module
from app import app
from database import Base, get_db


@pytest.fixture
def db_session():
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
    session = TestSession()

    def override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    original_engine = app_module.engine
    app_module.engine = test_engine

    yield session

    app.dependency_overrides.clear()
    app_module.engine = original_engine
    session.close()
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


@pytest.fixture
def client(db_session):
    with TestClient(app) as test_client:
        yield test_client
