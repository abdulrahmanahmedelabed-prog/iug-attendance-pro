"""Side-by-side with ZKBioTime: terminals point at us, we relay everything to BioTime."""
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from zkpro.adms.relay import OFFSET


class FakeBioTime:
    """A tiny stand-in for BioTime's /iclock endpoints (a real HTTP server)."""

    def __init__(self):
        self.requests = []          # (method, path, query, body)
        self.pending = {}           # sn -> [command lines]
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self, text, status=200):
                data = text.encode("utf-8") if isinstance(text, str) else text
                self.send_response(status)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _handle(self):
                u = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                fake.requests.append((self.command, u.path, q, body))
                sn = q.get("SN", "")
                if u.path == "/iclock/cdata" and self.command == "GET":
                    return self._reply(f"GET OPTION FROM: {sn}\nATTLOGStamp=500\nOPERLOGStamp=600\nDelay=10\n")
                if u.path == "/iclock/cdata":
                    n = len([ln for ln in body.split(b"\n") if ln.strip()])
                    return self._reply(f"OK: {n}")
                if u.path == "/iclock/getrequest":
                    cmds = fake.pending.pop(sn, [])
                    return self._reply("".join(c + "\n" for c in cmds) if cmds else "OK")
                if u.path == "/iclock/querydata":
                    return self._reply(f"{q.get('tablename')}=1")
                return self._reply("OK")

            do_GET = do_POST = _handle

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def bodies(self, path):
        return [r[3] for r in self.requests if r[1] == path and r[0] == "POST"]

    def close(self):
        self.server.shutdown()


@pytest.fixture()
def biotime(client):
    fake = FakeBioTime()
    client.put("/api/settings", json={"adms.relay_url": fake.url})
    yield fake
    fake.close()


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_handshake_follows_biotime_and_device_is_registered(client, biotime):
    r = client.get("/iclock/cdata", params={"SN": "V5L", "options": "all"})
    assert r.status_code == 200 and "ATTLOGStamp=500" in r.text  # BioTime's stamps drive the terminal
    assert any(d["sn"] == "V5L" for d in client.get("/api/devices").json()["rows"])


def test_upload_reaches_both_byte_for_byte(client, biotime):
    client.get("/iclock/cdata", params={"SN": "V5L", "options": "all"})
    body = "5\t2026-09-29 08:01:00\t0\t15\t0\t0\t0\n".encode()
    r = client.post("/iclock/cdata", params={"SN": "V5L", "table": "ATTLOG", "Stamp": "501"}, content=body)
    assert r.text == "OK: 1"
    assert biotime.bodies("/iclock/cdata")[-1] == body
    assert client.get("/api/transactions", params={"sn": "V5L"}).json()["total"] == 1
    # a legacy-encoded Arabic name is forwarded untouched
    user = "USER PIN=6\tName=".encode() + "علي".encode("cp1256") + b"\tPri=0"
    client.post("/iclock/cdata", params={"SN": "V5L", "table": "OPERLOG"}, content=user)
    assert biotime.bodies("/iclock/cdata")[-1] == user


def test_commands_from_both_servers_and_results_routed_back(client, biotime, device_factory):
    dev = device_factory("V5L")
    dev.handshake()
    dev.drain()
    biotime.pending["V5L"] = ["C:17:DATA UPDATE USERINFO PIN=9999\tName=From BioTime\tPri=0\tPasswd=\tCard="]
    client.post("/api/employees", json={"emp_code": "100", "first_name": "From ZKPro"})
    dev.drain()
    assert dev.users["9999"]["name"] == "From BioTime" and dev.users["100"]["name"] == "From ZKPro"
    results = b"\n".join(biotime.bodies("/iclock/devicecmd"))
    assert b"ID=17&" in results
    assert all(int(line.split(b"&")[0][3:]) < OFFSET for line in results.split(b"\n") if line.startswith(b"ID="))
    ours = client.get("/api/device-commands", params={"sn": "V5L"}).json()["rows"]
    assert ours and all(c["status"] == "done" for c in ours)


def test_biotime_down_makes_terminal_retry(client):
    client.put("/api/settings", json={"adms.relay_url": f"http://127.0.0.1:{_free_port()}"})
    r = client.post("/iclock/cdata", params={"SN": "V5L", "table": "ATTLOG"},
                    content=b"5\t2026-09-29 08:01:00\t0\t15")
    assert r.status_code == 503          # BioTime must not lose the record
    assert client.get("/api/transactions", params={"sn": "V5L"}).json()["total"] == 1  # we kept it
    assert client.get("/api/relay").json()["failed"] >= 1


def test_zkpro_primary_keeps_working_without_biotime(client):
    client.put("/api/settings", json={"adms.relay_url": f"http://127.0.0.1:{_free_port()}",
                                      "adms.relay_primary": "zkpro"})
    r = client.get("/iclock/cdata", params={"SN": "V5L", "options": "all"})
    assert r.status_code == 200 and "ATTLOGStamp=None" in r.text
    r = client.post("/iclock/cdata", params={"SN": "V5L", "table": "ATTLOG"},
                    content=b"5\t2026-09-29 08:01:00\t0\t15")
    assert r.status_code == 200 and r.text == "OK: 1"


def test_querydata_goes_to_the_server_that_asked(client, biotime):
    client.get("/iclock/cdata", params={"SN": "V5L", "options": "all"})
    line = b"user uid=1\tpin=77\tname=Q\tcardno=\tpassword=\tprivilege=0"
    client.post("/iclock/querydata", params={"SN": "V5L", "tablename": "user", "cmdid": str(OFFSET + 5)},
                content=line)
    assert not biotime.bodies("/iclock/querydata")       # our query: not forwarded
    client.post("/iclock/querydata", params={"SN": "V5L", "tablename": "user", "cmdid": "33"}, content=line)
    assert biotime.bodies("/iclock/querydata") == [line]  # BioTime's query: forwarded
    assert client.get("/api/employees", params={"q": "77"}).json()["total"] == 1


def test_relay_test_endpoint(client, biotime):
    assert client.post("/api/relay/test", json={"url": biotime.url}).json()["ok"] is True
    assert client.post("/api/relay/test", json={"url": f"http://127.0.0.1:{_free_port()}"}).json()["ok"] is False
