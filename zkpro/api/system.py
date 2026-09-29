"""Login, dashboard, reports, system settings, users/roles, audit, backup."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, time, timedelta
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import store
from ..config import settings
from ..db import engine as db_engine, get_db, now
from .. import models as m
from ..engine import Engine
from .. import reports as R
from ..security import PERMISSIONS, hash_password, make_token, user_permissions, verify_password
from ..version import APP_NAME, VERSION
from .crud import crud_router
from .deps import COOKIE, audit, current_user, ids_param, page, parse_date, require, ser
from .devices import is_online

router = APIRouter(prefix="/api")

# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------

_FAILS: dict[str, list[float]] = {}


def _user_dict(u: m.User) -> dict:
    return {"id": u.id, "username": u.username, "full_name": u.full_name, "is_superuser": u.is_superuser,
            "role": u.role.name if u.role else "", "permissions": sorted(user_permissions(u)),
            "language": u.language, "must_change_password": u.must_change_password}


@router.post("/auth/login")
def login(request: Request, response: Response, data: dict = Body(...), db: Session = Depends(get_db)):
    username = str(data.get("username", "")).strip()
    key = (request.client.host if request.client else "") + "|" + username.lower()
    recent = [t for t in _FAILS.get(key, []) if t > now().timestamp() - 300]
    if len(recent) >= 5:
        raise HTTPException(429, "too many failed attempts, try again in 5 minutes")
    user = db.scalar(select(m.User).where(func.lower(m.User.username) == username.lower()))
    if not user or not user.active or not verify_password(str(data.get("password", "")), user.password_hash):
        _FAILS[key] = recent + [now().timestamp()]
        db.add(m.AuditLog(username=username[:50], action="login_failed",
                          ip=request.client.host if request.client else ""))
        db.commit()
        raise HTTPException(401, "wrong username or password")
    _FAILS.pop(key, None)
    user.last_login = now()
    token = make_token(user.id, user.password_hash)
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=settings.session_hours * 3600)
    db.add(m.AuditLog(username=user.username, action="login", ip=request.client.host if request.client else ""))
    db.commit()
    return {"token": token, "user": _user_dict(user)}


@router.post("/auth/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"ok": True}


@router.get("/auth/me")
def me(user: m.User = Depends(current_user)):
    return _user_dict(user)


@router.post("/auth/password")
def change_password(request: Request, response: Response, data: dict = Body(...), db: Session = Depends(get_db),
                    user: m.User = Depends(current_user)):
    if not verify_password(str(data.get("old_password", "")), user.password_hash):
        raise HTTPException(422, "current password is wrong")
    new = str(data.get("new_password", ""))
    if len(new) < 6:
        raise HTTPException(422, "password must be at least 6 characters")
    user.password_hash = hash_password(new)
    user.must_change_password = False
    audit(db, request, "password", "user", user.username)
    db.commit()
    token = make_token(user.id, user.password_hash)
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=settings.session_hours * 3600)
    return {"ok": True, "token": token}


@router.post("/auth/language")
def set_language(data: dict = Body(...), db: Session = Depends(get_db), user: m.User = Depends(current_user)):
    if data.get("language") in ("ar", "en"):
        user.language = data["language"]
        db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------

@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), _=Depends(current_user)):
    today = now().date()
    devices = db.scalars(select(m.Device)).all()
    online = sum(1 for d in devices if d.enabled and is_online(d))
    busy = set(db.scalars(select(m.DeviceCommand.device_sn).where(
        m.DeviceCommand.status.in_(("pending", "sent"))).distinct()).all())
    employees = db.scalar(select(func.count()).select_from(m.Employee).where(m.Employee.status == "active")) or 0
    lo = datetime.combine(today, time.min)
    punches_today = db.scalar(select(func.count()).select_from(m.Transaction).where(
        m.Transaction.punch_time >= lo, m.Transaction.punch_time < lo + timedelta(days=1))) or 0
    days = Engine(db, today, today, include_resigned=False).run()
    counts: dict[str, int] = {}
    for r in days:
        counts[r.status] = counts.get(r.status, 0) + 1
    present = sum(counts.get(k, 0) for k in ("present", "late", "early", "late_early", "incomplete"))
    present += sum(1 for r in days if r.status == "unscheduled" and r.clock_in)
    # 7-day trend
    week_start = today - timedelta(days=6)
    trend = []
    wk = Engine(db, week_start, today, include_resigned=False).run()
    for i in range(7):
        d = week_start + timedelta(days=i)
        rows = [r for r in wk if r.att_date == d]
        trend.append({"date": d.isoformat(),
                      "present": sum(1 for r in rows if r.clock_in or r.clock_out),
                      "late": sum(1 for r in rows if r.late),
                      "absent": sum(1 for r in rows if r.status == "absent")})
    depts: dict[str, dict] = {}
    for r in days:
        x = depts.setdefault(r.department or "-", {"department": r.department or "-", "total": 0, "present": 0})
        x["total"] += 1
        x["present"] += 1 if (r.clock_in or r.clock_out) else 0
    pending = {
        "leaves": db.scalar(select(func.count()).select_from(m.Leave).where(m.Leave.status == "pending")) or 0,
        "manual": db.scalar(select(func.count()).select_from(m.ManualLog).where(m.ManualLog.status == "pending")) or 0,
        "overtime": db.scalar(select(func.count()).select_from(m.Overtime).where(m.Overtime.status == "pending")) or 0,
        "commands": db.scalar(select(func.count()).select_from(m.DeviceCommand).where(
            m.DeviceCommand.status.in_(("pending", "sent")))) or 0,
    }
    return {
        "date": today.isoformat(), "employees": employees, "devices": len(devices), "online": online,
        "offline": sum(1 for d in devices if d.enabled) - online, "punches_today": punches_today,
        "present": present, "late": counts.get("late", 0) + counts.get("late_early", 0),
        "absent": counts.get("absent", 0), "leave": counts.get("leave", 0), "off": counts.get("off", 0) + counts.get("holiday", 0),
        "incomplete": counts.get("incomplete", 0), "not_yet": counts.get("pending", 0),
        "trend": trend, "departments": sorted(depts.values(), key=lambda x: x["department"]),
        "device_list": [{"id": d.id, "sn": d.sn, "alias": d.alias, "ip": d.ip, "area": d.area.name if d.area else "",
                         "state": "disabled" if not d.enabled else ("online" if is_online(d) else "offline"),
                         "last_activity": d.last_activity.strftime("%Y-%m-%d %H:%M:%S") if d.last_activity else "",
                         "users": d.user_count, "faces": d.face_count, "fps": d.fp_count, "palms": d.palm_count,
                         "transferring": d.enabled and is_online(d) and d.sn in busy}
                        for d in devices],
        "pending": pending,
    }


# --------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------

@router.get("/reports")
def report_list(_=Depends(require("reports.view"))):
    return [{"key": k, "title_ar": v[0], "title_en": v[1], "kind": v[2]} for k, v in R.REPORTS.items()]


@router.get("/reports/{key}")
def report(key: str, start: str = "", end: str = "", employee_ids: str = "", department_ids: str = "",
           device: str = "", lang: str = "ar", fmt: str = "json", db: Session = Depends(get_db),
           _=Depends(require("reports.view"))):
    if key not in R.REPORTS:
        raise HTTPException(404, "unknown report")
    today = now().date()
    ds = parse_date(start, today.replace(day=1))
    de = parse_date(end, today)
    if de < ds or (de - ds).days > 400:
        raise HTTPException(422, "invalid range (max 400 days)")
    rep = R.build(db, key, ds, de, lang=lang, employee_ids=ids_param(employee_ids),
                  department_ids=ids_param(department_ids), device_sn=device or None)
    name = f"{key}_{ds}_{de}"
    if fmt == "csv":
        return Response(R.to_csv(rep), media_type="text/csv",
                        headers={"Content-Disposition": f"attachment; filename={name}.csv"})
    if fmt == "xlsx":
        company = store.get(db, "company.name_ar" if lang == "ar" else "company.name")
        return Response(R.to_xlsx(rep, company=company, rtl=(lang == "ar")),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f"attachment; filename={name}.xlsx"})
    return rep


# --------------------------------------------------------------------------
# Settings, users, roles, audit, backup
# --------------------------------------------------------------------------

SECRET_MASK = "********"


@router.get("/settings")
def get_settings(db: Session = Depends(get_db), _=Depends(current_user)):
    s = store.all_(db)
    if s.get("biotime.password"):
        s["biotime.password"] = SECRET_MASK
    s["_server"] = {"app": APP_NAME, "version": VERSION, "web_port": settings.web_port,
                    "adms_ports": settings.adms_ports, "data_dir": str(settings.data_dir)}
    return s


@router.put("/settings")
def put_settings(request: Request, data: dict = Body(...), db: Session = Depends(get_db),
                 _=Depends(require("system.admin"))):
    for k, v in data.items():
        if k == "biotime.password" and v == SECRET_MASK:
            continue  # unchanged
        if k in store.DEFAULTS:
            store.set_(db, k, v)
    from ..adms import relay
    relay.invalidate()
    audit(db, request, "update", "settings", ", ".join(data)[:500])
    db.commit()
    return store.all_(db)


def _user_out(db, u: m.User) -> dict:
    d = ser(u)
    d.pop("password_hash", None)
    d["role"] = u.role.name if u.role else ""
    return d


def _user_before(db, u: m.User, data: dict, is_new: bool) -> None:
    pw = data.get("password")
    if is_new and not pw:
        raise HTTPException(422, "password required")
    if pw:
        if len(pw) < 6:
            raise HTTPException(422, "password must be at least 6 characters")
        u.password_hash = hash_password(pw)
    if not u.username:
        raise HTTPException(422, "username required")


router.include_router(crud_router(m.User, "/users", "system.admin", "system.admin", search=("username", "full_name"),
                                  order=m.User.username, to_dict=_user_out, before_save=_user_before))


def _role_out(db, r: m.Role) -> dict:
    d = ser(r)
    d["permissions"] = json.loads(r.permissions or "[]")
    return d


def _role_before(db, r: m.Role, data: dict, is_new: bool) -> None:
    perms = data.get("permissions")
    if isinstance(perms, list):
        r.permissions = json.dumps([p for p in perms if p in PERMISSIONS])


router.include_router(crud_router(m.Role, "/roles", "system.admin", "system.admin", order=m.Role.name,
                                  to_dict=_role_out, before_save=_role_before))


@router.get("/permissions")
def permissions(_=Depends(current_user)):
    return PERMISSIONS


@router.get("/audit")
def audit_log(q: str = "", offset: int = 0, limit: int = 100, db: Session = Depends(get_db),
              _=Depends(require("system.admin"))):
    stmt = select(m.AuditLog)
    if q:
        stmt = stmt.where(m.AuditLog.username.ilike(f"%{q}%") | m.AuditLog.action.ilike(f"%{q}%")
                          | m.AuditLog.target.ilike(f"%{q}%"))
    total, rows = page(db, stmt.order_by(m.AuditLog.id.desc()), offset, limit)
    return {"total": total, "rows": [ser(r[0]) for r in rows]}


def make_backup(label: str = "manual") -> Path:
    """Consistent SQLite snapshot using the online backup API."""
    if not settings.database_url.startswith("sqlite"):
        raise HTTPException(422, "backup is only built in for SQLite")
    src_path = settings.database_url.split("///", 1)[1]
    dest = settings.backups_dir / f"zkpro_{now():%Y%m%d_%H%M%S}_{label}.db"
    src = sqlite3.connect(src_path)
    try:
        dst = sqlite3.connect(dest)
        with dst:
            src.backup(dst)
        dst.close()
    finally:
        src.close()
    return dest


def prune_backups(keep: int) -> None:
    files = sorted(settings.backups_dir.glob("zkpro_*.db"))
    for f in files[:-keep] if keep > 0 else []:
        f.unlink(missing_ok=True)


@router.get("/backups")
def list_backups(_=Depends(require("system.admin"))):
    files = sorted(settings.backups_dir.glob("zkpro_*.db"), reverse=True)
    return {"rows": [{"name": f.name, "size": f.stat().st_size,
                      "time": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")} for f in files]}


@router.post("/backups")
def create_backup(request: Request, db: Session = Depends(get_db), _=Depends(require("system.admin"))):
    path = make_backup()
    prune_backups(int(store.get(db, "backup.keep") or 14))
    audit(db, request, "backup", "system", path.name)
    db.commit()
    return {"name": path.name}


@router.get("/backups/{name}")
def download_backup(name: str, _=Depends(require("system.admin"))):
    path = settings.backups_dir / Path(name).name
    if not path.exists() or not path.name.startswith("zkpro_"):
        raise HTTPException(404, "not found")
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@router.post("/backups/{name}/restore")
def restore_backup(name: str, request: Request, _=Depends(require("system.admin"))):
    path = settings.backups_dir / Path(name).name
    if not path.exists() or not path.name.startswith("zkpro_"):
        raise HTTPException(404, "not found")
    if not settings.database_url.startswith("sqlite"):
        raise HTTPException(422, "restore is only built in for SQLite")
    make_backup("before_restore")
    target = settings.database_url.split("///", 1)[1]
    src = sqlite3.connect(path)
    try:
        db_engine.dispose()
        dst = sqlite3.connect(target)
        with dst:
            src.backup(dst)
        dst.close()
    finally:
        src.close()
    return {"ok": True}


@router.get("/relay")
def relay_status(_=Depends(require("device.view"))):
    from ..adms import relay
    cfg = relay.config(ttl=0)
    st = relay.STATUS
    return {"enabled": bool(cfg), "url": cfg.url if cfg else "", "primary": cfg.primary if cfg else "",
            "ok": st.ok, "failed": st.failed, "last_ok": st.last_ok, "last_error": st.last_error,
            "last_error_at": st.last_error_at}


@router.post("/relay/test")
def relay_test(data: dict = Body(...), _=Depends(require("system.admin"))):
    """Check that the BioTime address answers (before turning the relay on)."""
    import urllib.error
    import urllib.request
    url = str(data.get("url", "")).strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise HTTPException(422, "address must start with http://")
    try:
        with urllib.request.urlopen(url + "/iclock/ping?SN=ZKPRO-TEST", timeout=8) as r:
            return {"ok": True, "status": r.status, "reply": r.read(200).decode("utf-8", "replace")}
    except urllib.error.HTTPError as exc:
        return {"ok": True, "status": exc.code, "reply": exc.read(200).decode("utf-8", "replace")}
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.post("/biotime/test")
def biotime_test(data: dict = Body(...), db: Session = Depends(get_db), _=Depends(require("system.admin"))):
    """Log in to BioTime's API and count what would be imported (nothing is written)."""
    from ..biotime_sync import BioTimeClient, BioTimeError
    pw = data.get("password")
    if pw in (None, "", SECRET_MASK):
        pw = store.get(db, "biotime.password") or ""
    client = BioTimeClient(str(data.get("url", "")).strip(), str(data.get("username", "")), pw, timeout=15)
    try:
        client.login()
        terminals = list(client.items("/iclock/api/terminals/", page_size=200, max_pages=5))
        emp_page = client._request("GET", "/personnel/api/employees/", {"page": 1, "page_size": 1})
    except BioTimeError as exc:
        return {"ok": False, "error": str(exc)}
    employees = emp_page.get("count") if isinstance(emp_page, dict) else None
    return {"ok": True, "terminals": [{"sn": t.get("sn"), "alias": t.get("alias"),
                                       "ip": t.get("ip_address")} for t in terminals],
            "employees": employees}


@router.post("/biotime/sync")
def biotime_sync_now(request: Request, db: Session = Depends(get_db), _=Depends(require("system.admin"))):
    from ..biotime_sync import BioTimeError, run_logged
    try:
        result = run_logged()
    except BioTimeError as exc:
        raise HTTPException(502, str(exc))
    audit(db, request, "biotime.sync", "system", json.dumps(result))
    db.commit()
    return result


@router.get("/about")
def about():
    return {"app": APP_NAME, "version": VERSION}
