import os
import sys
import tempfile
from pathlib import Path

import pytest

_tmp = tempfile.mkdtemp(prefix="zkpro_test_")
os.environ["ZK_DATA_DIR"] = _tmp
os.environ["ZK_CONFIG"] = str(Path(_tmp) / "none.ini")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from fastapi.testclient import TestClient  # noqa: E402

from zkpro.app import app  # noqa: E402
from zkpro.bootstrap import init_db  # noqa: E402
from zkpro.db import Base, engine  # noqa: E402
from zkpro.adms.server import TRAFFIC  # noqa: E402


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    TRAFFIC.clear()
    init_db()
    with TestClient(app) as c:
        r = c.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        assert r.status_code == 200
        yield c


@pytest.fixture()
def device_factory(client):
    from device_simulator import SimDevice

    def transport(method, path, params, body=b""):
        r = client.request(method, path, params=params, content=body)
        assert r.status_code == 200, r.text
        return r.text

    def make(sn="SIM0001", **kw):
        return SimDevice(transport, sn=sn, **kw)
    return make
