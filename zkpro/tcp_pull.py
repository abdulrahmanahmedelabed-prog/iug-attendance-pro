"""Optional TCP/4370 pull (the classic ZK SDK protocol) via the ``pyzk`` package.

BioTime itself only uses ADMS push. This is a fallback for older terminals
without ADMS, or to recover records while ADMS is being configured.
Installed automatically by start.bat.
"""
from __future__ import annotations

from .adms.protocol import AttRecord


class TcpPullError(Exception):
    pass


def pull_attendance(ip: str, port: int = 4370, comm_key: str = "0", timeout: int = 15):
    try:
        from zk import ZK  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on optional package
        raise TcpPullError("pyzk is missing: close the program and run start.bat again") from exc
    try:
        password = int(comm_key or 0)
    except ValueError:
        raise TcpPullError("communication key must be a number")
    conn = None
    try:  # pragma: no cover - needs a real terminal
        conn = ZK(ip, port=int(port), timeout=timeout, password=password, force_udp=False,
                  ommit_ping=True).connect()
        conn.disable_device()
        try:
            atts = conn.get_attendance()
            conn.read_sizes()
            info = {"FWVersion": conn.get_firmware_version(), "DeviceName": conn.get_device_name(),
                    "UserCount": str(conn.users), "FPCount": str(conn.fingers),
                    "TransactionCount": str(conn.records)}
        finally:
            conn.enable_device()
        records = [AttRecord(pin=str(a.user_id), time=a.timestamp, state=int(a.punch or 0),
                             verify=int(a.status or 0)) for a in atts]
        return records, info
    except TcpPullError:
        raise
    except Exception as exc:  # pragma: no cover
        raise TcpPullError(f"{type(exc).__name__}: {exc}") from exc
    finally:
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:
                pass
