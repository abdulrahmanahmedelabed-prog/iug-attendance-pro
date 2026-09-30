"""Start ZK Attendance Pro.

    python run.py                   # web on 8090, devices (ADMS) on 8081 and 90
    python run.py --adms 90         # the port your terminals push to
    python run.py --web 80 --adms 8081,90

Every port serves the same application (web UI, API and /iclock ADMS), so a
terminal may also be pointed at the web port. A device port that cannot be
opened (in use, or needs administrator rights) is skipped with a warning.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import socket
import sys

import uvicorn


def _bind(host: str, port: int) -> socket.socket:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    if os.name != "nt":
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(2048)
    sock.set_inheritable(True)
    return sock


def main() -> None:
    ap = argparse.ArgumentParser(description="ZK Attendance Pro server")
    ap.add_argument("--host", help="listen address (default 0.0.0.0)")
    ap.add_argument("--web", type=int, help="web UI port (default 8090)")
    ap.add_argument("--adms", help="ADMS port(s) for terminals, comma separated (default 8081,90)")
    ap.add_argument("--data", help="data folder (database, photos, backups)")
    args = ap.parse_args()
    if args.host:
        os.environ["ZK_HOST"] = args.host
    if args.web:
        os.environ["ZK_WEB_PORT"] = str(args.web)
    if args.adms:
        os.environ["ZK_ADMS_PORTS"] = args.adms
    if args.data:
        os.environ["ZK_DATA_DIR"] = args.data

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from zkpro.config import settings
    from zkpro.app import app
    from zkpro.version import APP_NAME, VERSION

    try:
        web_sock = _bind(settings.host, settings.web_port)
    except OSError as exc:
        print(f"\n  Cannot open web port {settings.web_port}: {exc}\n  Another program (BioTime, IIS...) may be "
              f"using it. Use: run.py --web <other port>\n", file=sys.stderr)
        sys.exit(1)
    from zkpro.adms import ports as port_status
    socks = [(settings.web_port, web_sock)]
    port_status.set_mode(settings.web_port, "own", "web + devices")
    waiting: list[int] = []
    for port in settings.adms_ports:
        if port == settings.web_port:
            continue
        try:
            socks.append((port, _bind(settings.host, port)))
            port_status.set_mode(port, "own")
        except OSError as exc:
            # e.g. ZKBioTime holds port 90: keep trying, take it the moment it is released.
            waiting.append(port)
            port_status.set_mode(port, "waiting", str(exc))
            print(f"  ! Port {port} is used by another program (ZKBioTime?). "
                  f"It will be taken automatically when released.", file=sys.stderr)

    print(f"\n  {APP_NAME} {VERSION}")
    print(f"  Web interface : http://127.0.0.1:{settings.web_port}   (first login: admin / admin)")
    for port, _ in socks[1:]:
        print(f"  Devices (ADMS): port {port}  -> on the terminal: Cloud Server = this PC's IP, port {port}")
    print(f"  Data folder   : {settings.data_dir}\n")

    servers = []
    for i, (port, sock) in enumerate(socks):
        cfg = uvicorn.Config(app, log_level="warning", access_log=False,
                             lifespan="on" if i == 0 else "off", timeout_keep_alive=65)
        servers.append((uvicorn.Server(cfg), sock))

    async def claim_when_free(port: int):
        while True:
            await asyncio.sleep(10)
            try:
                sock = _bind(settings.host, port)
            except OSError as exc:
                port_status.set_mode(port, "waiting", str(exc))
                continue
            port_status.set_mode(port, "own", "taken after it was released")
            logging.getLogger("zkpro").info("port %d is free now: devices are served here", port)
            cfg = uvicorn.Config(app, log_level="warning", access_log=False, lifespan="off",
                                 timeout_keep_alive=65)
            await uvicorn.Server(cfg).serve(sockets=[sock])
            return

    async def serve_all():
        await asyncio.gather(*(srv.serve(sockets=[sock]) for srv, sock in servers),
                             *(claim_when_free(p) for p in waiting))

    try:
        asyncio.run(serve_all())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
