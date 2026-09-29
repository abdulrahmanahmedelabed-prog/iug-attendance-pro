"""Importing from a running ZKBioTime through its REST API (terminals stay on BioTime)."""
import json
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest


class FakeBioTimeAPI:
    def __init__(self):
        now = datetime.now().replace(microsecond=0)
        self.token = "tok123"
        self.areas = [{"id": 1, "area_code": "2", "area_name": "غزة"}]
        self.depts = [{"id": 5, "dept_code": "10", "dept_name": "الموارد البشرية"}]
        self.positions = [{"id": 3, "position_code": "P1", "position_name": "محاسب"}]
        self.employees = [
            {"id": 1, "emp_code": "101", "first_name": "أحمد", "last_name": "سالم", "card_no": "5566",
             "department": {"id": 5, "dept_code": "10", "dept_name": "الموارد البشرية"},
             "position": {"id": 3, "position_code": "P1"}, "area": [{"id": 1, "area_code": "2"}],
             "hire_date": "2020-01-01", "gender": "M"},
            {"id": 2, "emp_code": "102", "first_name": "منى", "last_name": "", "department": 5, "area": [1]},
        ]
        self.terminals = [
            {"id": 1, "sn": "7691222360357", "alias": "غزة", "ip_address": "10.28.65.253",
             "area": {"id": 1, "area_code": "2", "area_name": "غزة"}, "last_activity": (now - timedelta(seconds=30)).strftime("%Y-%m-%d %H:%M:%S"),
             "user_count": 420, "fp_count": 246, "face_count": 399, "palm_count": 80, "transaction_count": 20941,
             "fw_ver": "ZAM180-NF50VA-Ver3.0.36", "terminal_name": "SpeedFace-V5L"},
            {"id": 2, "sn": "7691222360009", "alias": "الوسطى", "ip_address": "10.130.0.28", "area": 1,
             "last_activity": (now - timedelta(days=9)).strftime("%Y-%m-%d %H:%M:%S"), "user_count": 420},
        ]
        base = now.replace(hour=0, minute=0, second=0) - timedelta(days=7)
        self.punches = [{"id": i, "emp_code": "101" if i % 2 else "102",
                         "punch_time": (base + timedelta(minutes=7 * i)).strftime("%Y-%m-%d %H:%M:%S"),
                         "punch_state": "0", "verify_type": 15, "terminal_sn": "7691222360357"} for i in range(1200)]
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, obj, status=200):
                data = json.dumps(obj, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                if self.path == "/jwt-api-token-auth/" and body.get("password") == "pw":
                    return self._json({"token": fake.token})
                return self._json({"non_field_errors": ["Unable to log in"]}, 400)

            def do_GET(self):
                if self.headers.get("Authorization") != f"JWT {fake.token}":
                    return self._json({"detail": "auth"}, 401)
                u = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                rows = {"/personnel/api/areas/": fake.areas, "/personnel/api/departments/": fake.depts,
                        "/personnel/api/positions/": fake.positions, "/personnel/api/employees/": fake.employees,
                        "/iclock/api/terminals/": fake.terminals, "/iclock/api/transactions/": fake.punches}.get(u.path)
                if rows is None:
                    return self._json({"detail": "not found"}, 404)
                if u.path == "/iclock/api/transactions/" and q.get("start_time"):
                    rows = [r for r in rows if q["start_time"] <= r["punch_time"] <= q.get("end_time", "9")]
                page, size = int(q.get("page", 1)), min(int(q.get("page_size", 10)), 300)  # BioTime caps page size
                chunk = rows[(page - 1) * size: page * size]
                nxt = f"{u.path}?page={page + 1}" if page * size < len(rows) else None
                return self._json({"count": len(rows), "next": nxt, "previous": None, "msg": "", "code": 0,
                                   "data": chunk})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


@pytest.fixture()
def api(client):
    fake = FakeBioTimeAPI()
    client.put("/api/settings", json={"biotime.url": fake.url, "biotime.username": "admin",
                                      "biotime.password": "pw", "biotime.enabled": True})
    yield fake
    fake.close()


def _devices(client):
    return {d["sn"]: d for d in client.get("/api/devices").json()["rows"]}


def test_test_endpoint_lists_terminals(client, api):
    r = client.post("/api/biotime/test", json={"url": api.url, "username": "admin", "password": "********"}).json()
    assert r["ok"] and {t["sn"] for t in r["terminals"]} == {"7691222360357", "7691222360009"}
    assert r["employees"] == 2
    bad = client.post("/api/biotime/test", json={"url": api.url, "username": "admin", "password": "x"}).json()
    assert bad["ok"] is False and "login failed" in bad["error"]
    assert client.get("/api/settings").json()["biotime.password"] == "********"


def test_full_import(client, api):
    r = client.post("/api/biotime/sync").json()
    assert r["terminals"] == 2 and r["employees"] == 2 and r["punches"] == 1200
    devs = _devices(client)
    gaza = devs["7691222360357"]
    assert gaza["alias"] == "غزة" and gaza["area"] == "غزة" and gaza["ip"] == "10.28.65.253"
    assert (gaza["user_count"], gaza["fp_count"], gaza["face_count"], gaza["palm_count"], gaza["att_count"]) == (420, 246, 399, 80, 20941)
    assert gaza["state"] == "online" and devs["7691222360009"]["state"] == "offline"
    assert gaza["managed_by"] == "biotime"
    emp = client.get("/api/employees", params={"q": "101"}).json()["rows"][0]
    assert emp["name"] == "أحمد سالم" and emp["department"] == "الموارد البشرية" and emp["position"] == "محاسب"
    assert emp["areas"] == "غزة" and emp["card_no"] == "5566"
    assert client.get("/api/employees", params={"q": "102"}).json()["rows"][0]["department"] == "الموارد البشرية"
    assert client.get("/api/transactions", params={"sn": "7691222360357", "limit": 1}).json()["total"] == 1200


def test_incremental_sync_has_no_duplicates(client, api):
    client.post("/api/biotime/sync")
    api.punches.append({"emp_code": "101", "punch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "punch_state": "Check Out", "verify_type": 1, "terminal_sn": "7691222360357"})
    r = client.post("/api/biotime/sync").json()
    assert r["punches"] == 1
    assert client.get("/api/transactions", params={"sn": "7691222360357", "limit": 1}).json()["total"] == 1201


def test_biotime_terminals_get_no_commands_until_they_connect(client, api, device_factory):
    client.post("/api/biotime/sync")
    client.post("/api/employees", json={"emp_code": "200", "first_name": "New", "area_ids": [
        next(a["id"] for a in client.get("/api/areas").json()["rows"] if a["name"] == "غزة")]})
    assert client.get("/api/device-commands").json()["total"] == 0
    gaza = _devices(client)["7691222360357"]
    assert client.post(f"/api/devices/{gaza['id']}/action", json={"action": "reboot"}).status_code == 409
    # the terminal is pointed at this server (or the relay): it becomes fully managed
    dev = device_factory("7691222360357")
    dev.handshake()
    assert _devices(client)["7691222360357"]["managed_by"] is None
    assert client.post(f"/api/devices/{gaza['id']}/action", json={"action": "reboot"}).status_code == 200


def test_sync_error_is_reported(client, api):
    client.put("/api/settings", json={"biotime.password": "wrong"})
    r = client.post("/api/biotime/sync")
    assert r.status_code == 502
    assert "error" in json.loads(client.get("/api/settings").json()["biotime.last_result"])
