"""Device module: terminals, remote control, transactions and device logs."""
from __future__ import annotations

import json
from datetime import datetime, time, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from ..adms import commands as C
from ..adms import sync
from ..adms.protocol import VERIFY_TYPES
from ..adms.server import TRAFFIC
from ..config import settings
from ..db import get_db, now
from .. import models as m
from .crud import coerce
from .deps import audit, page, parse_date, parse_dt, require, ser

router = APIRouter(prefix="/api")


def is_online(d: m.Device) -> bool:
    return bool(d.last_activity and (now() - d.last_activity).total_seconds() <= max(
        settings.offline_after, d.heartbeat * 3))


def dev_dict(db: Session, d: m.Device) -> dict:
    out = ser(d)
    out["area"] = d.area.name if d.area else ""
    out["state"] = "disabled" if not d.enabled else ("online" if is_online(d) else "offline")
    out["pending"] = db.scalar(select(func.count()).select_from(m.DeviceCommand).where(
        m.DeviceCommand.device_sn == d.sn, m.DeviceCommand.status.in_(("pending", "sent")))) or 0
    # BioTime's green "transferring" arrows: online with commands still to deliver
    out["transferring"] = out["state"] == "online" and out["pending"] > 0
    try:
        out["options"] = json.loads(d.options or "{}")
    except json.JSONDecodeError:
        out["options"] = {}
    out["bio_support"] = {str(k): v for k, v in sync.device_bio_support(d).items()}
    out.pop("comm_key", None)
    return out


@router.get("/devices")
def list_devices(q: str = "", area_id: int | None = None, db: Session = Depends(get_db),
                 _=Depends(require("device.view"))):
    stmt = select(m.Device)
    if q:
        stmt = stmt.where(or_(m.Device.sn.ilike(f"%{q}%"), m.Device.alias.ilike(f"%{q}%"), m.Device.ip.ilike(f"%{q}%")))
    if area_id:
        stmt = stmt.where(m.Device.area_id == area_id)
    rows = db.scalars(stmt.order_by(m.Device.alias, m.Device.sn)).all()
    return {"total": len(rows), "rows": [dev_dict(db, d) for d in rows]}


@router.get("/devices/{dev_id}")
def get_device(dev_id: int, db: Session = Depends(get_db), _=Depends(require("device.view"))):
    d = db.get(m.Device, dev_id)
    if not d:
        raise HTTPException(404, "not found")
    return dev_dict(db, d)


@router.post("/devices")
def add_device(request: Request, data: dict = Body(...), db: Session = Depends(get_db),
               _=Depends(require("device.control"))):
    """Pre-register a terminal by serial number (it appears online once it connects)."""
    sn = (data.get("sn") or "").strip()
    if not sn:
        raise HTTPException(422, "serial number required")
    if db.scalar(select(m.Device.id).where(m.Device.sn == sn)):
        raise HTTPException(409, "device already exists")
    vals = coerce(m.Device, {k: v for k, v in data.items() if k in _EDITABLE})
    d = m.Device(sn=sn, **vals)
    d.alias = d.alias or sn
    db.add(d)
    db.flush()
    sync.sync_device(db, d)
    audit(db, request, "create", "device", sn)
    db.commit()
    return dev_dict(db, d)


_EDITABLE = {"alias", "area_id", "enabled", "is_attendance", "is_registration", "time_zone", "heartbeat",
             "trans_interval", "trans_times", "realtime", "comm_key", "tcp_port", "ip"}


@router.put("/devices/{dev_id}")
def update_device(dev_id: int, request: Request, data: dict = Body(...), db: Session = Depends(get_db),
                  _=Depends(require("device.control"))):
    d = db.get(m.Device, dev_id)
    if not d:
        raise HTTPException(404, "not found")
    old_area = d.area_id
    for k, v in coerce(m.Device, {k: v for k, v in data.items() if k in _EDITABLE}).items():
        setattr(d, k, v)
    db.flush()
    n = 0
    if d.area_id != old_area and d.area_id:
        # Moving a terminal to another area replaces its people (BioTime behaviour).
        n = sync.sync_device(db, d)
    if {"time_zone", "heartbeat", "trans_interval", "trans_times", "realtime"} & set(data):
        sync.queue(db, d.sn, C.SIMPLE["check"], "Reload options")
    audit(db, request, "update", "device", d.sn)
    db.commit()
    out = dev_dict(db, d)
    out["queued"] = n
    return out


@router.delete("/devices/{dev_id}")
def delete_device(dev_id: int, request: Request, db: Session = Depends(get_db),
                  _=Depends(require("device.control"))):
    d = db.get(m.Device, dev_id)
    if not d:
        raise HTTPException(404, "not found")
    db.execute(delete(m.DeviceCommand).where(m.DeviceCommand.device_sn == d.sn))
    audit(db, request, "delete", "device", d.sn)
    db.delete(d)
    db.commit()
    return {"ok": True}


ACTIONS = {
    "sync_all": "مزامنة كل البيانات إلى الجهاز",
    "upload_users": "سحب المستخدمين والبصمات من الجهاز",
    "upload_att": "سحب سجل الحضور من الجهاز",
    "reupload_all": "إعادة رفع كل البيانات من الجهاز",
    "sync_time": "مزامنة الوقت",
    "info": "قراءة معلومات الجهاز",
    "check": "إعادة تحميل الإعدادات",
    "reboot": "إعادة تشغيل",
    "clear_log": "حذف سجلات الحضور من الجهاز",
    "clear_photo": "حذف صور الحضور من الجهاز",
    "clear_data": "حذف كل البيانات من الجهاز",
    "enroll": "تسجيل بصمة عن بعد",
    "delete_user": "حذف مستخدم من الجهاز",
    "custom": "أمر مخصص",
}


@router.post("/devices/{dev_id}/action")
def device_action(dev_id: int, request: Request, data: dict = Body(...), db: Session = Depends(get_db),
                  user=Depends(require("device.control"))):
    d = db.get(m.Device, dev_id)
    if not d:
        raise HTTPException(404, "not found")
    act = data.get("action")
    if act not in ACTIONS:
        raise HTTPException(422, "unknown action")
    n = 0

    def q(content, title=""):
        nonlocal n
        if sync.queue(db, d.sn, content, title):
            n += 1

    if act == "sync_all":
        n = sync.sync_device(db, d)
    elif act == "upload_users":
        q(C.query_table("user"), "Upload users")
        q(C.query_table("biodata"), "Upload templates")
        d.op_stamp = "0"
        q(C.SIMPLE["check"], "Reload options")
    elif act == "upload_att":
        start = parse_dt(data.get("start")) or datetime.combine(now().date() - timedelta(days=31), time.min)
        end = parse_dt(data.get("end")) or now()
        q(C.query_attlog(start, end), "Upload transactions")
    elif act == "reupload_all":
        sync.reset_stamps(d)
        q(C.SIMPLE["check"], "Reload options")
    elif act == "sync_time":
        q(C.set_time(now()), "Sync time")
    elif act in ("info", "check", "reboot", "clear_log", "clear_photo", "clear_data"):
        if act == "clear_data" and not user.is_superuser:
            raise HTTPException(403, "only a super administrator can wipe a device")
        q(C.SIMPLE[act], ACTIONS[act])
    elif act == "enroll":
        pin = str(data.get("emp_code", "")).strip()
        if not pin:
            raise HTTPException(422, "employee required")
        q(C.enroll_bio(pin, int(data.get("bio_type", 9)), int(data.get("finger", 0))), "Remote enroll " + pin)
    elif act == "delete_user":
        pin = str(data.get("emp_code", "")).strip()
        q(C.user_delete(pin), "Delete user " + pin)
    elif act == "custom":
        if not user.is_superuser:
            raise HTTPException(403, "only a super administrator can send raw commands")
        content = str(data.get("command", "")).strip()
        if not content or "\n" in content:
            raise HTTPException(422, "one command line required")
        q(content, "Custom")
    audit(db, request, "device." + act, "device", d.sn)
    db.commit()
    return {"ok": True, "queued": n}


@router.get("/device-commands")
def list_commands(sn: str = "", status: str = "", offset: int = 0, limit: int = 100,
                  db: Session = Depends(get_db), _=Depends(require("device.view"))):
    stmt = select(m.DeviceCommand)
    if sn:
        stmt = stmt.where(m.DeviceCommand.device_sn == sn)
    if status:
        stmt = stmt.where(m.DeviceCommand.status == status)
    total, rows = page(db, stmt.order_by(m.DeviceCommand.id.desc()), offset, limit)
    out = []
    for (c,) in rows:
        d = ser(c)
        d["content"] = c.content if len(c.content) < 200 else c.content[:200] + "…"
        out.append(d)
    return {"total": total, "rows": out}


@router.post("/device-commands/clear")
def clear_commands(request: Request, data: dict = Body(default={}), db: Session = Depends(get_db),
                   _=Depends(require("device.control"))):
    stmt = delete(m.DeviceCommand).where(m.DeviceCommand.status.in_(data.get("status") or ["done", "failed"]))
    if data.get("sn"):
        stmt = stmt.where(m.DeviceCommand.device_sn == data["sn"])
    res = db.execute(stmt)
    audit(db, request, "clear", "device_command", str(res.rowcount))
    db.commit()
    return {"deleted": res.rowcount}


@router.get("/device-traffic")
def device_traffic(sn: str = "", _=Depends(require("device.view"))):
    rows = [t for t in reversed(TRAFFIC) if not sn or t["sn"] == sn]
    return {"rows": rows[:300]}


# --------------------------------------------------------------------------
# Transactions
# --------------------------------------------------------------------------

def tx_dict(t: m.Transaction, e: m.Employee | None, aliases: dict) -> dict:
    d = ser(t)
    d["name"] = e.full_name if e else ""
    d["department"] = e.department.name if e and e.department else ""
    d["device"] = aliases.get(t.device_sn, t.device_sn)
    d["verify"] = VERIFY_TYPES.get(t.verify_type, "other")
    d["has_photo"] = bool(t.device_sn) and sync.photo_path_for(t.device_sn, t.emp_code, t.punch_time).exists()
    return d


@router.get("/transactions")
def list_transactions(q: str = "", start: str = "", end: str = "", sn: str = "", department_id: str = "",
                      offset: int = 0, limit: int = 50, db: Session = Depends(get_db),
                      _=Depends(require("attendance.view"))):
    stmt = select(m.Transaction, m.Employee).outerjoin(m.Employee, m.Employee.id == m.Transaction.employee_id)
    if q:
        stmt = stmt.where(or_(m.Transaction.emp_code.ilike(f"%{q}%"), m.Employee.first_name.ilike(f"%{q}%"),
                              m.Employee.last_name.ilike(f"%{q}%")))
    ds, de = parse_date(start), parse_date(end)
    if ds:
        stmt = stmt.where(m.Transaction.punch_time >= datetime.combine(ds, time.min))
    if de:
        stmt = stmt.where(m.Transaction.punch_time < datetime.combine(de + timedelta(days=1), time.min))
    if sn:
        stmt = stmt.where(m.Transaction.device_sn == sn)
    if department_id:
        stmt = stmt.where(m.Employee.department_id.in_([int(x) for x in department_id.split(",")]))
    total, rows = page(db, stmt.order_by(m.Transaction.punch_time.desc(), m.Transaction.id.desc()), offset, limit)
    aliases = dict(db.execute(select(m.Device.sn, m.Device.alias)).all())
    return {"total": total, "rows": [tx_dict(t, e, aliases) for t, e in rows]}


@router.get("/transactions/{tx_id}/photo")
def transaction_photo(tx_id: int, db: Session = Depends(get_db), _=Depends(require("attendance.view"))):
    t = db.get(m.Transaction, tx_id)
    if not t:
        raise HTTPException(404, "not found")
    p = sync.photo_path_for(t.device_sn, t.emp_code, t.punch_time)
    if not p.exists():
        raise HTTPException(404, "no photo")
    return FileResponse(p, media_type="image/jpeg")


@router.get("/monitor")
def realtime_monitor(after_id: int = 0, db: Session = Depends(get_db), _=Depends(require("attendance.view"))):
    """Real-time monitor: the newest punches (poll with after_id)."""
    stmt = select(m.Transaction, m.Employee).outerjoin(m.Employee, m.Employee.id == m.Transaction.employee_id)
    if after_id:
        stmt = stmt.where(m.Transaction.id > after_id).order_by(m.Transaction.id).limit(100)
    else:
        stmt = stmt.order_by(m.Transaction.id.desc()).limit(30)
    rows = db.execute(stmt).all()
    aliases = dict(db.execute(select(m.Device.sn, m.Device.alias)).all())
    out = [tx_dict(t, e, aliases) | {"employee_has_photo": bool(e and e.photo)} for t, e in rows]
    out.sort(key=lambda r: r["id"])
    return {"rows": out, "last_id": out[-1]["id"] if out else after_id}


@router.get("/device-oplogs")
def list_oplogs(sn: str = "", offset: int = 0, limit: int = 100, db: Session = Depends(get_db),
                _=Depends(require("device.view"))):
    stmt = select(m.DeviceOpLog)
    if sn:
        stmt = stmt.where(m.DeviceOpLog.device_sn == sn)
    total, rows = page(db, stmt.order_by(m.DeviceOpLog.id.desc()), offset, limit)
    return {"total": total, "rows": [ser(r[0]) for r in rows]}


@router.get("/device-errorlogs")
def list_errorlogs(sn: str = "", offset: int = 0, limit: int = 100, db: Session = Depends(get_db),
                   _=Depends(require("device.view"))):
    stmt = select(m.DeviceErrorLog)
    if sn:
        stmt = stmt.where(m.DeviceErrorLog.device_sn == sn)
    total, rows = page(db, stmt.order_by(m.DeviceErrorLog.id.desc()), offset, limit)
    return {"total": total, "rows": [ser(r[0]) for r in rows]}


@router.post("/devices/{dev_id}/pull")
def tcp_pull(dev_id: int, request: Request, db: Session = Depends(get_db), _=Depends(require("device.control"))):
    """Fallback for terminals that cannot use ADMS: read punches over TCP 4370."""
    from ..tcp_pull import pull_attendance, TcpPullError
    d = db.get(m.Device, dev_id)
    if not d:
        raise HTTPException(404, "not found")
    if not d.ip:
        raise HTTPException(422, "device IP address is not set")
    try:
        records, info = pull_attendance(d.ip, d.tcp_port or 4370, d.comm_key or "0")
    except TcpPullError as exc:
        raise HTTPException(502, str(exc))
    new = sync.save_punches(db, d, records, source="tcp")
    if info:
        sync.apply_device_info(d, info)
    audit(db, request, "device.tcp_pull", "device", f"{d.sn}: {len(new)} new")
    db.commit()
    return {"read": len(records), "new": len(new)}
