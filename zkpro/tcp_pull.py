"""TCP/4370 access to terminals (the classic ZK SDK protocol) via ``pyzk``.

Used to read punches and users straight from a terminal while it keeps
pushing to another server (e.g. ZKBioTime on port 90): the terminal answers
on its own port 4370 independently of its ADMS/Cloud Server setting, so
nothing on the terminal or in BioTime has to change. The terminal is not
disabled during the read, so employees can keep punching.
Installed automatically by start.bat.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import func, select

from .adms.protocol import AttRecord
from .db import now, session_scope
from . import models as m
from . import store

log = logging.getLogger("zkpro.tcp")

# sn -> {"time", "ok", "read", "new", "users", "error"} for the UI
STATUS: dict[str, dict] = {}


class TcpPullError(Exception):
    pass


def _connect(ip: str, port: int, comm_key: str, timeout: int):
    try:
        from zk import ZK  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on the package
        raise TcpPullError("pyzk is missing: close the program and run start.bat again") from exc
    try:
        password = int(comm_key or 0)
    except ValueError:
        raise TcpPullError("communication key must be a number")
    try:  # pragma: no cover - needs a real terminal
        return ZK(ip, port=int(port), timeout=timeout, password=password, force_udp=False,
                  ommit_ping=True).connect()
    except Exception as exc:  # pragma: no cover
        raise TcpPullError(f"{type(exc).__name__}: {exc}") from exc


def read_device(ip: str, port: int = 4370, comm_key: str = "0", timeout: int = 15,
                with_users: bool = True):  # pragma: no cover - needs a real terminal
    """-> (punches, users, info). users: dicts shaped like an ADMS USER line."""
    conn = _connect(ip, port, comm_key, timeout)
    try:
        atts = conn.get_attendance()
        users = conn.get_users() if with_users else []
        conn.read_sizes()
        info = {"FWVersion": conn.get_firmware_version(), "DeviceName": conn.get_device_name(),
                "UserCount": str(conn.users), "FPCount": str(conn.fingers),
                "TransactionCount": str(conn.records)}
        try:
            info["SerialNumber"] = conn.get_serialnumber()
        except Exception:
            pass
    except TcpPullError:
        raise
    except Exception as exc:
        raise TcpPullError(f"{type(exc).__name__}: {exc}") from exc
    finally:
        try:
            conn.disconnect()
        except Exception:
            pass
    records = [AttRecord(pin=str(a.user_id), time=a.timestamp, state=int(a.punch or 0),
                         verify=int(a.status or 0)) for a in atts]
    user_rows = [{"pin": str(u.user_id), "name": u.name or "", "card": str(u.card or ""),
                  "passwd": u.password or "", "pri": str(u.privilege or 0)} for u in users]
    return records, user_rows, info


def pull_attendance(ip: str, port: int = 4370, comm_key: str = "0", timeout: int = 15):
    records, _users, info = read_device(ip, port, comm_key, timeout, with_users=False)
    return records, info


def store_read(sn: str, records: list[AttRecord], users: list[dict], info: dict) -> dict:
    """Save what was read from a terminal. Only punches newer than what we already
    hold for it (minus a day) are compared, so a 20,000-record log stays cheap."""
    from .adms import sync
    with session_scope() as db:
        dev = db.scalar(select(m.Device).where(m.Device.sn == sn))
        if dev is None:
            raise TcpPullError(f"device {sn} not found")
        last = db.scalar(select(func.max(m.Transaction.punch_time)).where(m.Transaction.device_sn == sn))
        if last:
            records = [r for r in records if r.time >= last - timedelta(days=1)]
        new = sync.save_punches(db, dev, records, source="tcp")
        for u in users:  # names/cards into personnel; never pushed back to terminals from here
            sync._apply_user(db, dev, u)
        if info:
            sync.apply_device_info(dev, info)
        dev.last_sync = now()
    return {"read": len(records), "new": len(new), "users": len(users)}


def poll_due(state: dict) -> None:
    """Called every minute by the maintenance loop."""
    with session_scope() as db:
        every = max(1, int(store.get(db, "tcp.poll_minutes") or 5))
        devices = [(d.sn, d.ip, d.tcp_port or 4370, d.comm_key or "0") for d in
                   db.scalars(select(m.Device).where(m.Device.tcp_poll.is_(True), m.Device.enabled.is_(True))).all()
                   if d.ip]
    stamp = now().timestamp()
    for sn, ip, port, key in devices:
        if stamp - state.get(("tcp", sn), 0) < every * 60:
            continue
        state[("tcp", sn)] = stamp
        try:
            records, users, info = read_device(ip, port, key)
            result = store_read(sn, records, users, info)
            STATUS[sn] = {"time": now().isoformat(sep=" "), "ok": True, **result}
        except TcpPullError as exc:
            STATUS[sn] = {"time": now().isoformat(sep=" "), "ok": False, "error": str(exc)}
            log.warning("TCP read of %s (%s:%s) failed: %s", sn, ip, port, exc)

