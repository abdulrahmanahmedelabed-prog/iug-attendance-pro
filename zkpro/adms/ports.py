"""How each terminal port is being served — kept up to date by run.py.

mode:
  own      this program listens on the port
  waiting  another program (e.g. ZKBioTime) holds it; run.py retries every few seconds
           and takes the port as soon as it is released — no restart needed
"""
from __future__ import annotations

PORTS: dict[int, dict] = {}


def set_mode(port: int, mode: str, detail: str = "") -> None:
    PORTS[port] = {"port": port, "mode": mode, "detail": detail}


def snapshot() -> list[dict]:
    return [PORTS[p] for p in sorted(PORTS)]
