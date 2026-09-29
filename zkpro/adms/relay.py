"""BioTime relay: run side by side with an existing ZKBioTime server.

Two programs cannot listen on the same port, and a terminal pushes to only
one server. With the relay the terminals are pointed at ZK Attendance Pro,
which handles every request itself **and** forwards it unchanged to BioTime
(e.g. ``http://127.0.0.1:90``), so BioTime keeps working exactly as before:

* uploads (punches, users, templates, photos) are stored here and in BioTime
* heartbeats return BioTime's queued commands *and* ours; our command IDs are
  offset by ``OFFSET`` so each result goes back to the server that sent it
* ``primary = "biotime"`` (default): the terminal follows BioTime's replies
  (option block, upload acknowledgements). If BioTime is down the terminal is
  told to retry, exactly as if it were talking to BioTime directly, so
  BioTime never misses a record.
* ``primary = "zkpro"``: the terminal follows this server; BioTime still gets
  a best-effort copy (for the last days before switching BioTime off).
"""
from __future__ import annotations

import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from .. import store
from ..db import SessionLocal, now

log = logging.getLogger("zkpro.relay")

# Our command ids are sent as id + OFFSET so they never collide with BioTime's.
OFFSET = 1_000_000_000


@dataclass
class RelayConfig:
    url: str
    primary: str = "biotime"  # biotime | zkpro

    @property
    def biotime_primary(self) -> bool:
        return self.primary != "zkpro"


@dataclass
class RelayStatus:
    ok: int = 0
    failed: int = 0
    last_ok: str = ""
    last_error: str = ""
    last_error_at: str = ""


STATUS = RelayStatus()
_cache: tuple[float, RelayConfig | None] = (0.0, None)


def config(ttl: float = 5.0) -> RelayConfig | None:
    global _cache
    if time.monotonic() - _cache[0] < ttl:
        return _cache[1]
    with SessionLocal() as db:
        url = (store.get(db, "adms.relay_url") or "").strip()
        primary = store.get(db, "adms.relay_primary") or "biotime"
    cfg = RelayConfig(url=url.rstrip("/"), primary=primary) if url else None
    _cache = (time.monotonic(), cfg)
    return cfg


def invalidate() -> None:
    global _cache
    _cache = (0.0, None)


def forward(cfg: RelayConfig, method: str, path: str, query: str, body: bytes,
            client_ip: str, timeout: float = 20.0) -> tuple[int, bytes] | None:
    """Send the terminal's request to BioTime unchanged. None = BioTime unreachable."""
    url = cfg.url + path + (("?" + query) if query else "")
    req = urllib.request.Request(url, data=body if method == "POST" else None, method=method, headers={
        "Content-Type": "text/plain", "User-Agent": "iClock Proxy/1.09", "X-Forwarded-For": client_ip})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            STATUS.ok += 1
            STATUS.last_ok = now().isoformat(sep=" ")
            return resp.status, data
    except urllib.error.HTTPError as exc:  # BioTime answered, just not with 200
        STATUS.ok += 1
        STATUS.last_ok = now().isoformat(sep=" ")
        return exc.code, exc.read()
    except (OSError, ValueError) as exc:
        STATUS.failed += 1
        STATUS.last_error = f"{type(exc).__name__}: {exc}"
        STATUS.last_error_at = now().isoformat(sep=" ")
        log.warning("relay to %s failed: %s", url, exc)
        return None


def command_lines(data: bytes) -> list[bytes]:
    """``C:<id>:<cmd>`` lines of a getrequest reply ("OK" = none)."""
    return [ln for ln in data.replace(b"\r\n", b"\n").split(b"\n") if ln.startswith(b"C:")]


def split_results(body: bytes) -> tuple[bytes, bytes]:
    """Split a devicecmd body into (ours, BioTime's) by command id.

    A result starts with ``ID=`` and may be followed by extra ``key=value``
    lines (INFO), which stay with it."""
    ours: list[bytes] = []
    theirs: list[bytes] = []
    target = theirs
    for line in body.replace(b"\r\n", b"\n").split(b"\n"):
        if line.startswith(b"ID="):
            raw_id = line[3:].split(b"&", 1)[0]
            try:
                target = ours if int(raw_id) >= OFFSET else theirs
            except ValueError:
                target = theirs
        if line.strip():
            target.append(line)
    return b"\n".join(ours), b"\n".join(theirs)
