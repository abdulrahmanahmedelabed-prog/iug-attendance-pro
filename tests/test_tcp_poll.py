"""Reading terminals directly over TCP 4370 while they keep pushing to ZKBioTime."""
from datetime import datetime, timedelta

from zkpro import tcp_pull
from zkpro.adms.protocol import AttRecord


def _fake_reader(records, users, calls):
    def read_device(ip, port=4370, comm_key="0", timeout=15, with_users=True):
        calls.append((ip, port, comm_key))
        return records, users, {"DeviceName": "SpeedFace-V5L", "UserCount": str(len(users))}
    return read_device


def test_pull_button_reads_punches_and_users(client, monkeypatch):
    dev = client.post("/api/devices", json={"sn": "7691222360357", "alias": "غزة", "area_id": 1,
                                            "ip": "10.28.65.253", "comm_key": "123"}).json()
    t0 = datetime(2026, 9, 29, 8, 0)
    recs = [AttRecord(pin="5", time=t0), AttRecord(pin="5", time=t0 + timedelta(hours=8), state=1)]
    users = [{"pin": "5", "name": "Salem", "card": "777", "passwd": "", "pri": "0"}]
    calls = []
    monkeypatch.setattr(tcp_pull, "read_device", _fake_reader(recs, users, calls))
    r = client.post(f"/api/devices/{dev['id']}/pull").json()
    assert r == {"read": 2, "new": 2, "users": 1}
    assert calls == [("10.28.65.253", 4370, "123")]
    emp = client.get("/api/employees", params={"q": "5"}).json()["rows"][0]
    assert emp["name"] == "Salem" and emp["card_no"] == "777"
    # reading again adds nothing and sends no commands to the terminal
    assert client.post(f"/api/devices/{dev['id']}/pull").json()["new"] == 0
    assert client.get("/api/tcp-status").json()["7691222360357"]["ok"] is True


def test_scheduled_poll_only_for_ticked_devices(client, monkeypatch):
    a = client.post("/api/devices", json={"sn": "A", "alias": "A", "area_id": 1, "ip": "10.0.0.1"}).json()
    client.post("/api/devices", json={"sn": "B", "alias": "B", "area_id": 1, "ip": "10.0.0.2"})
    client.put(f"/api/devices/{a['id']}", json={"tcp_poll": True})
    calls = []
    monkeypatch.setattr(tcp_pull, "read_device",
                        _fake_reader([AttRecord(pin="9", time=datetime(2026, 9, 29, 8, 0))], [], calls))
    state = {}
    tcp_pull.poll_due(state)
    tcp_pull.poll_due(state)  # not due again within the interval
    assert calls == [("10.0.0.1", 4370, "0")]
    assert client.get("/api/transactions", params={"sn": "A"}).json()["total"] == 1


def test_unreachable_device_is_reported(client, monkeypatch):
    d = client.post("/api/devices", json={"sn": "X", "alias": "X", "area_id": 1, "ip": "10.9.9.9"}).json()

    def boom(*a, **k):
        raise tcp_pull.TcpPullError("timed out")
    monkeypatch.setattr(tcp_pull, "read_device", boom)
    r = client.post(f"/api/devices/{d['id']}/pull")
    assert r.status_code == 502 and "timed out" in r.text
    assert client.get("/api/tcp-status").json()["X"]["ok"] is False


def test_biotime_managed_device_can_still_be_read(client, monkeypatch):
    from zkpro.db import session_scope
    from zkpro import models as m
    with session_scope() as db:
        db.add(m.Device(sn="BT1", alias="BT1", ip="10.28.65.253", managed_by="biotime", area_id=1))
    dev = next(x for x in client.get("/api/devices").json()["rows"] if x["sn"] == "BT1")
    monkeypatch.setattr(tcp_pull, "read_device", _fake_reader([AttRecord(pin="3", time=datetime(2026, 9, 29, 9))], [], []))
    assert client.post(f"/api/devices/{dev['id']}/pull").json()["new"] == 1
    assert next(x for x in client.get("/api/devices").json()["rows"] if x["sn"] == "BT1")["managed_by"] == "biotime"
