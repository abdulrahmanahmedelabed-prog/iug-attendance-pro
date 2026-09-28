"""Attendance module: timetables, shifts, schedules, holidays, leave,
manual punches, overtime and the calculated attendance view."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import get_db, now
from .. import models as m
from ..engine import Engine, summarize
from .crud import crud_router
from .deps import audit, ids_param, parse_date, require, ser

router = APIRouter(prefix="/api")


def _tt_before(db, obj, data, is_new):
    if obj.kind not in ("normal", "flexible"):
        raise HTTPException(422, "kind must be normal or flexible")
    for f in ("in_ahead", "in_above", "out_ahead", "out_above", "late_grace", "early_grace"):
        if (getattr(obj, f) or 0) < 0:
            raise HTTPException(422, f"{f} cannot be negative")


router.include_router(crud_router(m.TimeTable, "/timetables", "attendance.view", "attendance.edit",
                                  search=("alias",), order=m.TimeTable.alias, before_save=_tt_before))
router.include_router(crud_router(m.Holiday, "/holidays", "attendance.view", "attendance.edit",
                                  search=("alias",), order=m.Holiday.start_date.desc()))
router.include_router(crud_router(m.LeaveType, "/leave-types", "attendance.view", "attendance.edit",
                                  search=("code", "name"), order=m.LeaveType.code))


# --------------------------------------------------------------------------
# Shifts
# --------------------------------------------------------------------------

def shift_dict(db, s: m.Shift) -> dict:
    d = ser(s)
    d["details"] = [{"day_index": x.day_index, "timetable_id": x.timetable_id} for x in s.details]
    names = {t.id: t.alias for t in db.scalars(select(m.TimeTable)).all()}
    d["summary"] = ", ".join(sorted({names.get(x.timetable_id, "?") for x in s.details}))
    return d


def _save_shift(db: Session, s: m.Shift, data: dict) -> None:
    s.alias = (data.get("alias") or s.alias or "").strip()
    if not s.alias:
        raise HTTPException(422, "name required")
    s.cycle_unit = data.get("cycle_unit", s.cycle_unit or "week")
    if s.cycle_unit not in ("day", "week", "month"):
        raise HTTPException(422, "cycle unit must be day, week or month")
    s.cycle = max(1, int(data.get("cycle", s.cycle or 1)))
    if "details" in data:
        span = s.cycle * {"day": 1, "week": 7, "month": 31}[s.cycle_unit]
        s.details = [m.ShiftDetail(day_index=int(x["day_index"]), timetable_id=int(x["timetable_id"]))
                     for x in data["details"] if 0 <= int(x["day_index"]) < span]


@router.get("/shifts")
def list_shifts(db: Session = Depends(get_db), _=Depends(require("attendance.view"))):
    rows = db.scalars(select(m.Shift).order_by(m.Shift.alias)).all()
    return {"total": len(rows), "rows": [shift_dict(db, s) for s in rows]}


@router.post("/shifts")
def create_shift(request: Request, data: dict = Body(...), db: Session = Depends(get_db),
                 _=Depends(require("attendance.edit"))):
    s = m.Shift()
    _save_shift(db, s, data)
    db.add(s)
    db.flush()
    audit(db, request, "create", "shift", s.alias)
    db.commit()
    return shift_dict(db, s)


@router.put("/shifts/{shift_id}")
def update_shift(shift_id: int, request: Request, data: dict = Body(...), db: Session = Depends(get_db),
                 _=Depends(require("attendance.edit"))):
    s = db.get(m.Shift, shift_id)
    if not s:
        raise HTTPException(404, "not found")
    _save_shift(db, s, data)
    audit(db, request, "update", "shift", s.alias)
    db.commit()
    return shift_dict(db, s)


@router.delete("/shifts/{shift_id}")
def delete_shift(shift_id: int, request: Request, db: Session = Depends(get_db),
                 _=Depends(require("attendance.edit"))):
    s = db.get(m.Shift, shift_id)
    if not s:
        raise HTTPException(404, "not found")
    db.delete(s)
    audit(db, request, "delete", "shift", s.alias)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------
# Schedules
# --------------------------------------------------------------------------

@router.get("/schedules")
def list_schedules(employee_id: int | None = None, q: str = "", db: Session = Depends(get_db),
                   _=Depends(require("attendance.view"))):
    stmt = select(m.Schedule, m.Employee, m.Shift).join(m.Employee, m.Employee.id == m.Schedule.employee_id).join(
        m.Shift, m.Shift.id == m.Schedule.shift_id)
    if employee_id:
        stmt = stmt.where(m.Schedule.employee_id == employee_id)
    if q:
        stmt = stmt.where((m.Employee.emp_code.ilike(f"%{q}%")) | (m.Employee.first_name.ilike(f"%{q}%")))
    rows = db.execute(stmt.order_by(m.Employee.emp_code, m.Schedule.start_date).limit(2000)).all()
    return {"total": len(rows), "rows": [ser(s) | {"emp_code": e.emp_code, "name": e.full_name,
                                                   "department": e.department.name if e.department else "",
                                                   "shift": sh.alias} for s, e, sh in rows]}


@router.post("/schedules")
def assign_schedule(request: Request, data: dict = Body(...), db: Session = Depends(get_db),
                    _=Depends(require("attendance.edit"))):
    """Assign a shift to employees (or whole departments) for a date range.
    Overlapping existing assignments are trimmed, like BioTime does."""
    shift_id = int(data.get("shift_id") or 0)
    if not db.get(m.Shift, shift_id):
        raise HTTPException(422, "shift required")
    start = parse_date(data.get("start_date"))
    end = parse_date(data.get("end_date"))
    if not start or not end or end < start:
        raise HTTPException(422, "valid date range required")
    emp_ids = {int(x) for x in data.get("employee_ids") or []}
    dept_ids = [int(x) for x in data.get("department_ids") or []]
    if dept_ids:
        emp_ids |= set(db.scalars(select(m.Employee.id).where(m.Employee.department_id.in_(dept_ids),
                                                              m.Employee.status == "active")).all())
    if not emp_ids:
        raise HTTPException(422, "choose employees or departments")
    for emp_id in emp_ids:
        for old in db.scalars(select(m.Schedule).where(
                m.Schedule.employee_id == emp_id, m.Schedule.start_date <= end,
                m.Schedule.end_date >= start)).all():
            if old.start_date >= start and old.end_date <= end:
                db.delete(old)
            elif old.start_date < start and old.end_date > end:
                db.add(m.Schedule(employee_id=emp_id, shift_id=old.shift_id,
                                  start_date=end + timedelta(days=1), end_date=old.end_date))
                old.end_date = start - timedelta(days=1)
            elif old.start_date < start:
                old.end_date = start - timedelta(days=1)
            else:
                old.start_date = end + timedelta(days=1)
        db.add(m.Schedule(employee_id=emp_id, shift_id=shift_id, start_date=start, end_date=end))
    audit(db, request, "assign", "schedule", f"{len(emp_ids)} employees")
    db.commit()
    return {"ok": True, "employees": len(emp_ids)}


@router.delete("/schedules/{sched_id}")
def delete_schedule(sched_id: int, request: Request, db: Session = Depends(get_db),
                    _=Depends(require("attendance.edit"))):
    s = db.get(m.Schedule, sched_id)
    if not s:
        raise HTTPException(404, "not found")
    db.delete(s)
    audit(db, request, "delete", "schedule", str(sched_id))
    db.commit()
    return {"ok": True}


def _dsched_dict(db, s):
    d = ser(s)
    dep = db.get(m.Department, s.department_id)
    sh = db.get(m.Shift, s.shift_id)
    d["department"] = dep.name if dep else ""
    d["shift"] = sh.alias if sh else ""
    return d


router.include_router(crud_router(m.DeptSchedule, "/dept-schedules", "attendance.view", "attendance.edit",
                                  order=m.DeptSchedule.start_date.desc(), to_dict=_dsched_dict))


@router.get("/temp-schedules")
def list_temp(start: str = "", end: str = "", employee_id: int | None = None, db: Session = Depends(get_db),
              _=Depends(require("attendance.view"))):
    stmt = select(m.TempSchedule, m.Employee).join(m.Employee, m.Employee.id == m.TempSchedule.employee_id)
    if start:
        stmt = stmt.where(m.TempSchedule.att_date >= parse_date(start))
    if end:
        stmt = stmt.where(m.TempSchedule.att_date <= parse_date(end))
    if employee_id:
        stmt = stmt.where(m.TempSchedule.employee_id == employee_id)
    names = {t.id: t.alias for t in db.scalars(select(m.TimeTable)).all()}
    rows = db.execute(stmt.order_by(m.TempSchedule.att_date.desc()).limit(2000)).all()
    return {"total": len(rows), "rows": [ser(t) | {"emp_code": e.emp_code, "name": e.full_name,
                                                   "timetable": names.get(t.timetable_id, "—")} for t, e in rows]}


@router.post("/temp-schedules")
def set_temp(request: Request, data: dict = Body(...), db: Session = Depends(get_db),
             _=Depends(require("attendance.edit"))):
    """Replace the day's schedule for employees; timetable_ids=[] means day off."""
    emp_ids = [int(x) for x in data.get("employee_ids") or []]
    start = parse_date(data.get("start_date") or data.get("att_date"))
    end = parse_date(data.get("end_date")) or start
    if not emp_ids or not start or end < start or (end - start).days > 366:
        raise HTTPException(422, "employees and a valid date range required")
    tt_ids = [int(x) for x in data.get("timetable_ids") or []]
    d = start
    while d <= end:
        db.execute(delete(m.TempSchedule).where(m.TempSchedule.employee_id.in_(emp_ids),
                                                m.TempSchedule.att_date == d))
        for emp_id in emp_ids:
            for tt in (tt_ids or [None]):
                db.add(m.TempSchedule(employee_id=emp_id, att_date=d, timetable_id=tt))
        d += timedelta(days=1)
    audit(db, request, "set", "temp_schedule", f"{len(emp_ids)} employees {start}..{end}")
    db.commit()
    return {"ok": True}


@router.delete("/temp-schedules/{tid}")
def delete_temp(tid: int, db: Session = Depends(get_db), _=Depends(require("attendance.edit"))):
    t = db.get(m.TempSchedule, tid)
    if t:
        db.delete(t)
        db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------
# Leave / manual punch / overtime (with approval)
# --------------------------------------------------------------------------

def _with_emp(db, obj):
    d = ser(obj)
    e = db.get(m.Employee, obj.employee_id)
    d["emp_code"] = e.emp_code if e else ""
    d["name"] = e.full_name if e else ""
    d["department"] = e.department.name if e and e.department else ""
    if isinstance(obj, m.Leave):
        lt = db.get(m.LeaveType, obj.leave_type_id)
        d["leave_type"] = lt.name if lt else ""
    return d


def _check_range(db, obj, data, is_new):
    if hasattr(obj, "end_time") and obj.end_time <= obj.start_time:
        raise HTTPException(422, "end must be after start")
    if obj.status not in m.APPROVAL_STATES:
        raise HTTPException(422, "invalid status")


for _model, _path in ((m.Leave, "/leaves"), (m.ManualLog, "/manual-logs"), (m.Overtime, "/overtimes")):
    router.include_router(crud_router(_model, _path, "attendance.view", "attendance.edit",
                                      order=_model.id.desc(), to_dict=_with_emp, before_save=_check_range,
                                      filters=("employee_id", "status")))


@router.post("/approvals/{kind}")
def approve(kind: str, request: Request, data: dict = Body(...), db: Session = Depends(get_db),
            user=Depends(require("attendance.approve"))):
    model = {"leaves": m.Leave, "manual-logs": m.ManualLog, "overtimes": m.Overtime}.get(kind)
    status = data.get("status")
    if model is None or status not in ("approved", "rejected", "pending"):
        raise HTTPException(422, "invalid request")
    ids = [int(x) for x in data.get("ids", [])]
    for obj in db.scalars(select(model).where(model.id.in_(ids))).all():
        obj.status = status
        obj.approver = user.username
    audit(db, request, status, kind, ",".join(map(str, ids))[:200])
    db.commit()
    return {"ok": True, "count": len(ids)}


# --------------------------------------------------------------------------
# Calculated attendance
# --------------------------------------------------------------------------

@router.get("/attendance/daily")
def daily(start: str = "", end: str = "", employee_ids: str = "", department_ids: str = "",
          status: str = "", db: Session = Depends(get_db), _=Depends(require("attendance.view"))):
    today = now().date()
    ds = parse_date(start, today)
    de = parse_date(end, ds)
    if (de - ds).days > 400:
        raise HTTPException(422, "range too long (max 400 days)")
    rows = Engine(db, ds, de, employee_ids=ids_param(employee_ids),
                  department_ids=ids_param(department_ids)).run()
    out = [r.as_dict() for r in rows if not status or r.status in status.split(",")]
    return {"total": len(out), "rows": out}


@router.get("/attendance/summary")
def summary(start: str = "", end: str = "", employee_ids: str = "", department_ids: str = "",
            db: Session = Depends(get_db), _=Depends(require("attendance.view"))):
    today = now().date()
    ds = parse_date(start, today.replace(day=1))
    de = parse_date(end, today)
    rows = Engine(db, ds, de, employee_ids=ids_param(employee_ids),
                  department_ids=ids_param(department_ids)).run()
    return {"rows": summarize(rows)}


@router.get("/attendance/calendar/{emp_id}")
def calendar(emp_id: int, month: str = "", db: Session = Depends(get_db), _=Depends(require("attendance.view"))):
    """One employee's month (for the schedule / attendance calendar view)."""
    today = now().date()
    first = parse_date(month + "-01" if month and len(month) == 7 else month, today.replace(day=1)).replace(day=1)
    last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    rows = Engine(db, first, last, employee_ids=[emp_id]).run()
    return {"month": first.strftime("%Y-%m"), "days": [r.as_dict() for r in rows],
            "summary": (summarize(rows) or [{}])[0]}
