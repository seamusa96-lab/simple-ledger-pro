import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="slp-test-")
os.environ["SLP_DATA_DIR"] = _tmp

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client():
    with TestClient(app, headers={"X-User": "pytest"}) as c:
        yield c


@pytest.fixture(scope="session")
def seeded(client):
    r = client.post("/api/demo/seed")
    assert r.status_code in (200, 201), r.text
    return client
