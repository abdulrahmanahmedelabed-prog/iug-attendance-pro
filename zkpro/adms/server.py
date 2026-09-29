"""HTTP endpoints the terminals talk to (``/iclock/*``).

Replies are plain text; a device treats anything other than the expected
"OK"/option block as an error and retries, so every handler answers even
when a line in the body cannot be parsed. Database work runs in the thread
pool so a slow upload from one terminal never stalls the others.
"""
from __future__ import annotations

import logging
import time as _time
from collections import deque
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from .. import store
from ..db import now, session_scope
from .. import models as m
from ..version import PUSH_PROTOCOL_VERSION
from . import protocol as P
from . import relay, sync

log = logging.getLogger("zkpro.adms")
router = APIRouter(prefix="/iclock", tags=["adms"])

# Recent requests per device, shown in Device > Communication monitor (memory only).
TRAFFIC: deque = deque(maxlen=500)


class NotRegistered(Exception):
    """Unknown (auto-add off) or disabled terminal. The upload is refused with 403
    so the terminal keeps the data and re-sends it once the device is approved,
    instead of believing it was stored and deleting it from its queue."""


def _text(body: str, status: int = 200) -> PlainTextResponse:
    return PlainTextResponse(body, status_code=status, media_type="text/plain")


def _sn(request: Request) -> str:
    q = request.query_params
    return (q.get("SN") or q.get("sn") or "").strip()[:50]


def _ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _trace(sn: str, request: Request, body_len: int, reply: str) -> None:
    TRAFFIC.append({
        "time": now().isoformat(sep=" "), "sn": sn, "method": request.method,
        "path": request.url.path, "query": str(request.url.query)[:300], "bytes": body_len,
        "reply": reply if len(reply) <= 400 else reply[:400] + " …",
    })


def server_timezone(db, device: m.Device | None) -> int:
    if device is not None and device.time_zone is not None:
        return device.time_zone
    tz = store.get(db, "adms.timezone")
    if tz in (None, ""):
        return round(_time.localtime().tm_gmtoff / 3600)
    return int(tz)


# --------------------------------------------------------------------------
# Handlers (synchronous, run in the thread pool)
# --------------------------------------------------------------------------

def handle_handshake(sn: str, ip: str, params: dict) -> str:
    with session_scope() as db:
        dev = sync.get_or_register(db, sn, ip)
        if dev is None or not dev.enabled:
            raise NotRegistered("UNKNOWN DEVICE" if dev is None else "DEVICE DISABLED")
        if params.get("pushver"):
            dev.push_ver = params["pushver"]
        dev.last_init = now()
        return P.option_block(
            sn, att_stamp=dev.att_stamp, op_stamp=dev.op_stamp, photo_stamp=dev.photo_stamp,
            time_zone=server_timezone(db, dev), delay=dev.heartbeat, trans_interval=dev.trans_interval,
            trans_times=dev.trans_times, realtime=dev.realtime,
            upload_photos=bool(store.get(db, "adms.upload_photos")), server_ver=PUSH_PROTOCOL_VERSION)


_BIO_TABLES = {"BIODATA": "BIODATA", "USERINFO": "USER", "USER": "USER", "FINGERTMP": "FP",
               "FACE": "FACE", "USERPIC": "USERPIC", "BIOPHOTO": "BIOPHOTO"}


def handle_upload(sn: str, ip: str, table: str, stamp: str | None, raw: bytes) -> str:
    with session_scope() as db:
        dev = sync.get_or_register(db, sn, ip)
        if dev is None or not dev.enabled:
            raise NotRegistered("UNKNOWN DEVICE" if dev is None else "DEVICE DISABLED")
        count = 0
        if table in ("ATTLOG", "ATTLOGS"):
            records = P.parse_attlog(P.decode_body(raw))
            sync.save_punches(db, dev, records)
            count = len(records)
            if stamp:
                dev.att_stamp = stamp
        elif table == "OPERLOG":
            items = P.parse_operlog(P.decode_body(raw))
            sync.apply_oper_items(db, dev, items)
            count = len(items)  # lines received (a skipped bad line must not make it re-send)
            if stamp:
                dev.op_stamp = stamp
        elif table in _BIO_TABLES:
            items = P.parse_bio_lines(P.decode_body(raw))
            for it in items:
                if it.kind not in ("USER", "FP", "FACE", "BIODATA", "USERPIC", "BIOPHOTO"):
                    it.kind = _BIO_TABLES[table]
            sync.apply_oper_items(db, dev, items)
            count = len(items)
        elif table == "ATTPHOTO":
            meta, data = P.parse_attphoto(raw)
            count = 1 if sync.save_attphoto(sn, meta, data) else 0
            if stamp:
                dev.photo_stamp = stamp
        elif table == "OPTIONS":
            sync.apply_device_info(dev, P.parse_options(P.decode_body(raw)))
            count = 1
        elif table == "ERRORLOG":
            for line in P.decode_body(raw).splitlines():
                d = P.parse_kv(line)
                if d:
                    db.add(m.DeviceErrorLog(device_sn=sn, err_code=d.get("errcode", ""),
                                            err_msg=d.get("errmsg", ""), data=line[:2000]))
                    count += 1
        else:
            log.info("%s uploaded unhandled table %r (%d bytes)", sn, table, len(raw))
        if count and table != "OPTIONS":
            dev.last_sync = now()
    return f"OK: {count}" if table in ("ATTLOG", "ATTLOGS", "OPERLOG", "BIODATA") else "OK"


def handle_heartbeat(sn: str, ip: str, info: str | None, id_offset: int = 0) -> str:
    with session_scope() as db:
        dev = sync.get_or_register(db, sn, ip)
        if dev is None or not dev.enabled:
            return "OK"
        if info:
            sync.apply_device_info(dev, P.parse_info_param(info))
        else:
            sync.refresh_info_if_due(db, dev)  # keep user/face/record counters current
        cmds = sync.next_commands(db, sn)
        return "".join(f"C:{c.id + id_offset}:{c.content}\n" for c in cmds) if cmds else "OK"


def handle_cmd_result(sn: str, ip: str, raw: bytes, relay_on: bool = False) -> str:
    with session_scope() as db:
        dev = sync.get_or_register(db, sn, ip) if sn else None
        for r in P.parse_devicecmd(P.decode_body(raw)):
            if r.id >= relay.OFFSET:
                r.id -= relay.OFFSET
            elif relay_on:
                continue  # BioTime's command (forwarded separately)
            cmd = db.get(m.DeviceCommand, r.id)
            if cmd is None or (sn and cmd.device_sn != sn):
                continue
            cmd.return_code = str(r.ret)
            cmd.returned_at = now()
            cmd.status = "done" if r.ret >= 0 else "failed"
            cmd.result = r.raw[:4000]
            if dev is not None and r.extra and cmd.content.startswith("INFO"):
                sync.apply_device_info(dev, r.extra)
    return "OK"


def handle_querydata(sn: str, ip: str, table: str, raw: bytes) -> str:
    with session_scope() as db:
        dev = sync.get_or_register(db, sn, ip) if sn else None
        if dev is None or not dev.enabled:
            raise NotRegistered("UNKNOWN DEVICE")
        rows = P.parse_querydata(P.decode_body(raw))
        items, punches = [], []
        for name, d in rows:
            if name == "user":
                items.append(P.OperItem("USER", data=d))
            elif name in ("biodata", "templatev10", "fingertmp"):
                d.setdefault("no", d.get("fingerid", "0"))
                d.setdefault("tmp", d.get("template", ""))
                if name == "biodata":
                    items.append(P.OperItem("BIODATA", data=d))
                else:
                    d.setdefault("fid", d["no"])
                    items.append(P.OperItem("FP", data=d))
            elif name in ("userpic", "biophoto"):
                d.setdefault("content", d.get("tmp", ""))
                items.append(P.OperItem(name.upper(), data=d))
            elif name in ("transaction", "attlog"):
                ts = P.parse_time(d.get("time", d.get("checktime", "")))
                if ts and d.get("pin"):
                    punches.append(P.AttRecord(pin=d["pin"], time=ts, state=int(d.get("status", 0) or 0),
                                               verify=int(d.get("verified", d.get("verify", 0)) or 0),
                                               work_code=d.get("workcode", "")))
        sync.apply_oper_items(db, dev, items)
        sync.save_punches(db, dev, punches)
        if dev is not None and rows:
            dev.last_sync = now()
    return f"{table}={len(rows)}" if table else "OK"


def handle_ping(sn: str) -> str:
    with session_scope() as db:
        dev = db.scalar(select(m.Device).where(m.Device.sn == sn))
        if dev:
            dev.last_activity = now()
    return "OK"


def handle_time(sn: str, ip: str) -> str:
    with session_scope() as db:
        dev = sync.get_or_register(db, sn, ip) if sn else None
        tz = server_timezone(db, dev)
    sign = "+" if tz >= 0 else "-"
    return f"DateTime={P.zk_encode_time(datetime.now())},ServerTZ={sign}{abs(tz):02d}00"


def handle_registry(sn: str, ip: str, raw: bytes) -> str:
    with session_scope() as db:
        dev = sync.get_or_register(db, sn, ip)
        if dev is None:
            return "406"
        info = P.parse_options(P.decode_body(raw))
        if info:
            sync.apply_device_info(dev, info)
    return f"RegistryCode={sn}"


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

async def _call(fn, *args) -> tuple[str, int]:
    try:
        return await run_in_threadpool(fn, *args), 200
    except NotRegistered as exc:
        return str(exc), 403


async def _local(fn, *args, relayed: bool) -> tuple[str, int]:
    """Run our handler. When relaying, a problem on our side must never keep the
    terminal from reaching BioTime, so errors are logged instead of raised."""
    if not relayed:
        return await _call(fn, *args)
    try:
        return await _call(fn, *args)
    except Exception:  # noqa: BLE001
        log.exception("local handling failed while relaying")
        return "ERROR", 500


async def _relay(cfg, request: Request, body: bytes = b"") -> tuple[int, bytes] | None:
    return await run_in_threadpool(relay.forward, cfg, request.method, request.url.path,
                                   request.url.query, body, _ip(request))


def _raw(body: bytes, status: int = 200) -> Response:
    return Response(content=body, status_code=status, media_type="text/plain")


_UNAVAILABLE = b"BioTime server unavailable, retry later"


async def _relayed_reply(cfg, request: Request, body: bytes, local: tuple[str, int], sn: str) -> Response:
    """Forward a request and answer the terminal like the primary server would."""
    remote = await _relay(cfg, request, body)
    if cfg.biotime_primary:
        if remote is None:
            _trace(sn, request, len(body), "[relay] BioTime unreachable -> 503")
            return _raw(_UNAVAILABLE, 503)
        _trace(sn, request, len(body), "[relay] " + remote[1].decode("utf-8", "replace"))
        return _raw(remote[1], remote[0])
    _trace(sn, request, len(body), local[0])
    return _text(local[0], local[1])


@router.get("/cdata")
async def cdata_get(request: Request):
    sn = _sn(request)
    if not sn:
        return _text("ERROR: missing SN", 400)
    cfg = await run_in_threadpool(relay.config)
    local = await _local(handle_handshake, sn, _ip(request), dict(request.query_params), relayed=bool(cfg))
    if cfg:
        return await _relayed_reply(cfg, request, b"", local, sn)
    _trace(sn, request, 0, local[0])
    return _text(*local)


@router.post("/cdata")
async def cdata_post(request: Request):
    sn = _sn(request)
    raw = await request.body()
    if not sn:
        return _text("ERROR: missing SN", 400)
    q = request.query_params
    table = (q.get("table") or "").upper()
    cfg = await run_in_threadpool(relay.config)
    if table == "TABLEDATA":
        # Push 3.x firmware: users / templates / photos as "user uid=..\tpin=.." lines.
        local = await _local(handle_querydata, sn, _ip(request), (q.get("tablename") or "").lower(), raw,
                             relayed=bool(cfg))
    else:
        local = await _local(handle_upload, sn, _ip(request), table, q.get("Stamp") or q.get("stamp"), raw,
                             relayed=bool(cfg))
    if cfg:
        return await _relayed_reply(cfg, request, raw, local, sn)
    _trace(sn, request, len(raw), local[0])
    return _text(*local)


@router.get("/getrequest")
async def getrequest(request: Request):
    sn = _sn(request)
    if not sn:
        return _text("ERROR: missing SN", 400)
    cfg = await run_in_threadpool(relay.config)
    info = request.query_params.get("INFO")
    if not cfg:
        reply = await run_in_threadpool(handle_heartbeat, sn, _ip(request), info)
        _trace(sn, request, 0, reply)
        return _text(reply)
    # Merge BioTime's queued commands with ours (ours carry id + OFFSET).
    remote = await _relay(cfg, request)
    try:
        ours = await run_in_threadpool(handle_heartbeat, sn, _ip(request), info, relay.OFFSET)
    except Exception:  # noqa: BLE001
        log.exception("heartbeat handling failed while relaying")
        ours = "OK"
    lines = relay.command_lines(remote[1]) if remote else []
    lines += relay.command_lines(ours.encode("utf-8"))
    body = b"\n".join(lines) + b"\n" if lines else b"OK"
    _trace(sn, request, 0, "[relay] " + body.decode("utf-8", "replace"))
    return _raw(body)


@router.post("/devicecmd")
async def devicecmd(request: Request):
    sn = _sn(request)
    raw = await request.body()
    cfg = await run_in_threadpool(relay.config)
    if not cfg:
        reply = await run_in_threadpool(handle_cmd_result, sn, _ip(request), raw)
        _trace(sn, request, len(raw), reply)
        return _text(reply)
    ours, theirs = relay.split_results(raw)
    if ours:
        await _local(handle_cmd_result, sn, _ip(request), ours, True, relayed=True)
    if theirs:
        remote = await run_in_threadpool(relay.forward, cfg, "POST", request.url.path, request.url.query,
                                         theirs + b"\n", _ip(request))
        if remote is None and cfg.biotime_primary:
            _trace(sn, request, len(raw), "[relay] BioTime unreachable -> 503")
            return _raw(_UNAVAILABLE, 503)
    _trace(sn, request, len(raw), "OK")
    return _text("OK")


@router.post("/querydata")
async def querydata(request: Request):
    sn = _sn(request)
    raw = await request.body()
    table = (request.query_params.get("tablename") or "").lower()
    cfg = await run_in_threadpool(relay.config)
    local = await _local(handle_querydata, sn, _ip(request), table, raw, relayed=bool(cfg))
    try:
        mine = int(request.query_params.get("cmdid") or 0) >= relay.OFFSET
    except ValueError:
        mine = False
    if cfg and not mine:  # an answer to one of BioTime's queries
        return await _relayed_reply(cfg, request, raw, local, sn)
    _trace(sn, request, len(raw), local[0])
    return _text(*local)


@router.api_route("/ping", methods=["GET", "POST"])
async def ping(request: Request):
    sn = _sn(request)
    raw = await request.body()
    if sn:
        await run_in_threadpool(handle_ping, sn)
    cfg = await run_in_threadpool(relay.config)
    if cfg:
        return await _relayed_reply(cfg, request, raw, ("OK", 200), sn)
    return _text("OK")


@router.get("/rtdata")
async def rtdata(request: Request):
    sn = _sn(request)
    reply = await run_in_threadpool(handle_time, sn, _ip(request))
    cfg = await run_in_threadpool(relay.config)
    if cfg:
        return await _relayed_reply(cfg, request, b"", (reply, 200), sn)
    _trace(sn, request, 0, reply)
    return _text(reply)


@router.api_route("/registry", methods=["GET", "POST"])
async def registry(request: Request):
    sn = _sn(request)
    raw = await request.body()
    cfg = await run_in_threadpool(relay.config)
    local = await _local(handle_registry, sn, _ip(request), raw, relayed=bool(cfg)) if sn else ("406", 200)
    if cfg:
        return await _relayed_reply(cfg, request, raw, local, sn)
    _trace(sn, request, len(raw), local[0])
    return _text(*local)


@router.api_route("/push", methods=["GET", "POST"])
async def push_config(request: Request):
    sn = _sn(request)
    raw = await request.body()
    reply = ("ServerVersion=3.1.2\nServerName=ZKPro\nPushVersion=3.1.2\nErrorDelay=30\n"
             "RequestDelay=10\nTransTimes=00:00\t14:00\nTransInterval=1\n"
             "TransTables=User\tTransaction\nRealtime=1\nSessionID=" + sn + "\nTimeoutSec=10\n")
    cfg = await run_in_threadpool(relay.config)
    if cfg:
        return await _relayed_reply(cfg, request, raw, (reply, 200), sn)
    _trace(sn, request, 0, reply)
    return _text(reply)


@router.api_route("/fdata", methods=["GET", "POST"])
async def fdata(request: Request):
    sn = _sn(request)
    raw = await request.body()
    if raw and sn:
        meta, data = P.parse_attphoto(raw)
        await run_in_threadpool(sync.save_attphoto, sn, meta, data)
    cfg = await run_in_threadpool(relay.config)
    if cfg:
        return await _relayed_reply(cfg, request, raw, ("OK", 200), sn)
    _trace(sn, request, len(raw), "OK")
    return _text("OK")


# Older iClock firmware appends ".aspx" to every path (/iclock/cdata.aspx ...).
for _route in list(router.routes):
    if _route.path.startswith("/iclock/") and _route.path.count("/") == 2:
        # add_api_route prepends the router prefix itself
        router.add_api_route(_route.path[len(router.prefix):] + ".aspx", _route.endpoint,
                             methods=list(_route.methods), include_in_schema=False)
