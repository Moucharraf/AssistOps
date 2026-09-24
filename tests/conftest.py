import pytest
from fastapi.testclient import TestClient

from assistops.config import Settings
from assistops.main import create_app


@pytest.fixture
def settings():
    return Settings(_env_file=None, environment="test", dependency_timeout_seconds=0.1)


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client
