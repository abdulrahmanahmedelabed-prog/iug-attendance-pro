"""Authentication, permissions, personnel import, settings, backup."""
import io

from fastapi.testclient import TestClient

from zkpro.app import app


def test_login_required_and_wrong_password(client):
    anon = TestClient(app)
    assert anon.get("/api/employees").status_code == 401
    assert anon.post("/api/auth/login", json={"username": "admin", "password": "x"}).status_code == 401


def test_role_permissions(client):
    viewer = next(r for r in client.get("/api/roles").json()["rows"] if r["name"] == "Viewer")
    r = client.post("/api/users", json={"username": "hr", "password": "secret1", "role_id": viewer["id"]})
    assert r.status_code == 200 and "password_hash" not in r.json()
    u = TestClient(app)
    assert u.post("/api/auth/login", json={"username": "hr", "password": "secret1"}).status_code == 200
    assert u.get("/api/employees").status_code == 200
    assert u.post("/api/employees", json={"emp_code": "9"}).status_code == 403
    assert u.get("/api/users").status_code == 403
    assert u.post("/api/devices", json={"sn": "X"}).status_code == 403


def test_password_change_invalidates_old_token(client):
    old = client.post("/api/auth/login", json={"username": "admin", "password": "admin"}).json()["token"]
    r = client.post("/api/auth/password", json={"old_password": "admin", "new_password": "n3w-pass"})
    assert r.status_code == 200
    stale = TestClient(app)
    assert stale.get("/api/auth/me", headers={"Authorization": f"Bearer {old}"}).status_code == 401
    assert client.get("/api/auth/me").json()["must_change_password"] is False


def test_password_hash_cannot_be_injected(client):
    u = client.post("/api/users", json={"username": "x1", "password": "secret1"}).json()
    client.put(f"/api/users/{u['id']}", json={"password_hash": "pbkdf2_sha256$1$00$00"})
    assert TestClient(app).post("/api/auth/login", json={"username": "x1", "password": "secret1"}).status_code == 200


def test_import_employees_csv(client):
    csv = "الرقم,الاسم,القسم,البطاقة\n301,Ali Hassan,Sales,555\n302,Mona,Sales,\n,bad,,\n"
    r = client.post("/api/employees/import", files={"file": ("e.csv", io.BytesIO(csv.encode("utf-8-sig")), "text/csv")})
    body = r.json()
    assert body["created"] == 2 and len(body["errors"]) == 1
    rows = client.get("/api/employees", params={"q": "30"}).json()["rows"]
    assert {e["department"] for e in rows} == {"Sales"} and rows[0]["card_no"] == "555"
    x = client.get("/api/employees-export", params={"fmt": "xlsx"})
    assert x.content[:2] == b"PK"


def test_duplicate_employee_code(client):
    assert client.post("/api/employees", json={"emp_code": "77"}).status_code == 200
    assert client.post("/api/employees", json={"emp_code": "77"}).status_code == 409
    assert client.post("/api/employees", json={"emp_code": "bad code!"}).status_code == 422


def test_settings_and_backup(client):
    s = client.put("/api/settings", json={"company.name": "ACME", "not.a.key": 1}).json()
    assert s["company.name"] == "ACME" and "not.a.key" not in s
    name = client.post("/api/backups").json()["name"]
    assert any(b["name"] == name for b in client.get("/api/backups").json()["rows"])
    assert client.get(f"/api/backups/{name}").content[:15] == b"SQLite format 3"
    assert client.get("/api/backups/..%2F..%2Fetc%2Fpasswd").status_code == 404


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "core.js" in r.text
    assert client.get("/static/js/pages.js").status_code == 200


def test_dashboard(client, device_factory):
    dev = device_factory("DASH")
    dev.handshake()
    d = client.get("/api/dashboard").json()
    assert d["devices"] == 1 and d["online"] == 1 and len(d["trend"]) == 7
