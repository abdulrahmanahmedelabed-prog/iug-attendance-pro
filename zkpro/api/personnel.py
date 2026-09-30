"""Personnel module: departments, positions, areas, employees, biometrics."""
from __future__ import annotations

import base64
import csv
import io

from fastapi import APIRouter, Body, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import biotime_push
from ..adms import sync
from ..db import get_db, now
from .. import models as m
from .crud import coerce, crud_router
from .deps import audit, page, parse_date, require, ser

router = APIRouter(prefix="/api")


def _dept_dict(db, d):
    out = ser(d)
    out["employees"] = db.scalar(select(func.count()).select_from(m.Employee).where(
        m.Employee.department_id == d.id, m.Employee.status == "active")) or 0
    return out


def _area_dict(db, a):
    out = ser(a)
    out["employees"] = db.scalar(select(func.count()).select_from(m.employee_area).where(
        m.employee_area.c.area_id == a.id)) or 0
    out["devices"] = db.scalar(select(func.count()).select_from(m.Device).where(m.Device.area_id == a.id)) or 0
    return out


router.include_router(crud_router(m.Department, "/departments", "personnel.view", "personnel.edit",
                                  search=("code", "name"), order=m.Department.code, to_dict=_dept_dict))
router.include_router(crud_router(m.Position, "/positions", "personnel.view", "personnel.edit",
                                  search=("code", "name"), order=m.Position.code))
router.include_router(crud_router(m.Area, "/areas", "personnel.view", "personnel.edit",
                                  search=("code", "name"), order=m.Area.code, to_dict=_area_dict))


# --------------------------------------------------------------------------
# Employees
# --------------------------------------------------------------------------

def emp_dict(db: Session, e: m.Employee, full: bool = False) -> dict:
    d = ser(e)
    d.pop("photo", None)
    d["name"] = e.full_name
    d["department"] = e.department.name if e.department else ""
    d["position"] = e.position.name if e.position else ""
    d["area_ids"] = [a.id for a in e.areas]
    d["areas"] = ", ".join(a.name for a in e.areas)
    d["has_photo"] = bool(e.photo)
    counts = dict(db.execute(select(m.BioTemplate.bio_type, func.count()).where(
        m.BioTemplate.employee_id == e.id).group_by(m.BioTemplate.bio_type)).all())
    d["fp_count"] = counts.get(1, 0)
    d["face_count"] = counts.get(2, 0) + counts.get(9, 0)
    d["palm_count"] = counts.get(8, 0) + counts.get(6, 0)
    d["vein_count"] = counts.get(7, 0)
    return d


def _validate_code(code: str) -> str:
    code = (code or "").strip()
    if not code or len(code) > 30 or not code.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(422, "Employee ID must be 1-30 letters/digits")
    return code


@router.get("/employees")
def list_employees(q: str = "", department_id: str = "", area_id: int | None = None, status: str = "active",
                   offset: int = 0, limit: int = 50, db: Session = Depends(get_db),
                   _=Depends(require("personnel.view"))):
    stmt = select(m.Employee)
    if status in ("active", "resigned"):
        stmt = stmt.where(m.Employee.status == status)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(m.Employee.emp_code.ilike(like), m.Employee.first_name.ilike(like),
                              m.Employee.last_name.ilike(like), m.Employee.card_no.ilike(like),
                              m.Employee.mobile.ilike(like), m.Employee.national_id.ilike(like)))
    if department_id:
        stmt = stmt.where(m.Employee.department_id.in_([int(x) for x in department_id.split(",")]))
    if area_id:
        stmt = stmt.join(m.employee_area).where(m.employee_area.c.area_id == area_id)
    total, rows = page(db, stmt.order_by(m.Employee.emp_code), offset, limit)
    return {"total": total, "rows": [emp_dict(db, r[0]) for r in rows]}


@router.get("/employees/{emp_id}")
def get_employee(emp_id: int, db: Session = Depends(get_db), _=Depends(require("personnel.view"))):
    e = db.get(m.Employee, emp_id)
    if not e:
        raise HTTPException(404, "not found")
    d = emp_dict(db, e)
    d["templates"] = [{"id": t.id, "bio_type": t.bio_type, "type": m.BIO_TYPES.get(t.bio_type, str(t.bio_type)),
                       "no": t.bio_no, "index": t.bio_index, "version": f"{t.major_ver}.{t.minor_ver}",
                       "source": t.source_sn, "updated_at": t.updated_at.strftime("%Y-%m-%d %H:%M")}
                      for t in db.scalars(select(m.BioTemplate).where(m.BioTemplate.employee_id == e.id)
                                          .order_by(m.BioTemplate.bio_type, m.BioTemplate.bio_no)).all()]
    d["bio_photos"] = [p.bio_type for p in db.scalars(select(m.BioPhoto).where(m.BioPhoto.employee_id == e.id)).all()]
    return d


def _apply_employee(db: Session, e: m.Employee, data: dict) -> None:
    values = coerce(m.Employee, {k: v for k, v in data.items() if k not in ("photo", "status", "emp_code")})
    for k, v in values.items():
        setattr(e, k, v)
    if "area_ids" in data:
        ids = [int(x) for x in data.get("area_ids") or []]
        e.areas = list(db.scalars(select(m.Area).where(m.Area.id.in_(ids))).all()) if ids else []


@router.post("/employees")
def create_employee(request: Request, data: dict = Body(...), db: Session = Depends(get_db),
                    _=Depends(require("personnel.edit"))):
    code = _validate_code(data.get("emp_code", ""))
    if db.scalar(select(m.Employee.id).where(m.Employee.emp_code == code)):
        raise HTTPException(409, "Employee ID already exists")
    e = m.Employee(emp_code=code)
    _apply_employee(db, e, data)
    if "area_ids" not in data:
        first_area = db.scalar(select(m.Area).order_by(m.Area.id).limit(1))
        e.areas = [first_area] if first_area else []
    db.add(e)
    db.flush()
    sync.link_transactions(db, e)
    sync.employee_changed(db, e, set(), with_bio=True)
    biotime_push.mark(db, [code])
    audit(db, request, "create", "employee", code)
    db.commit()
    return emp_dict(db, e)


@router.put("/employees/{emp_id}")
def update_employee(emp_id: int, request: Request, data: dict = Body(...), db: Session = Depends(get_db),
                    _=Depends(require("personnel.edit"))):
    e = db.get(m.Employee, emp_id)
    if not e:
        raise HTTPException(404, "not found")
    old_areas = {a.id for a in e.areas}
    _apply_employee(db, e, data)
    db.flush()
    sync.employee_changed(db, e, old_areas)
    biotime_push.mark(db, [e.emp_code])
    audit(db, request, "update", "employee", e.emp_code)
    db.commit()
    return emp_dict(db, e)


@router.delete("/employees/{emp_id}")
def delete_employee(emp_id: int, request: Request, db: Session = Depends(get_db),
                    _=Depends(require("personnel.edit"))):
    e = db.get(m.Employee, emp_id)
    if not e:
        raise HTTPException(404, "not found")
    sync.employee_deleted(db, e.emp_code, {a.id for a in e.areas})
    biotime_push.mark(db, [e.emp_code], "delete")
    audit(db, request, "delete", "employee", e.emp_code)
    db.delete(e)
    db.commit()
    return {"ok": True}


@router.post("/employees/batch")
def batch_employees(request: Request, data: dict = Body(...), db: Session = Depends(get_db),
                    _=Depends(require("personnel.edit"))):
    """Batch actions: set_department, set_areas, add_areas, resign, reinstate, sync, delete."""
    ids = [int(x) for x in data.get("ids", [])]
    action = data.get("action")
    emps = list(db.scalars(select(m.Employee).where(m.Employee.id.in_(ids))).all())
    n = 0
    for e in emps:
        old_areas = {a.id for a in e.areas}
        if action == "set_department":
            e.department_id = int(data["department_id"])
        elif action == "set_position":
            e.position_id = int(data["position_id"])
        elif action in ("set_areas", "add_areas"):
            new = list(db.scalars(select(m.Area).where(m.Area.id.in_([int(x) for x in data.get("area_ids", [])]))).all())
            e.areas = new if action == "set_areas" else list({a.id: a for a in e.areas + new}.values())
            db.flush()
            n += sync.employee_changed(db, e, old_areas)
            continue
        elif action == "resign":
            e.status = "resigned"
            e.resign_date = parse_date(data.get("resign_date")) or now().date()
            e.resign_type = data.get("resign_type", "")
            e.resign_reason = data.get("resign_reason", "")
            db.flush()
            n += sync.employee_changed(db, e, old_areas)
            continue
        elif action == "reinstate":
            e.status, e.resign_date = "active", None
            db.flush()
            n += sync.employee_changed(db, e, set(), with_bio=True)
            continue
        elif action == "sync":
            for dev in sync.area_devices(db, old_areas):
                n += sync.push_employee_to_device(db, dev, e)
            continue
        elif action == "delete":
            sync.employee_deleted(db, e.emp_code, old_areas)
            db.delete(e)
            continue
        else:
            raise HTTPException(422, "unknown action")
    biotime_push.mark(db, [e.emp_code for e in emps],
                      {"resign": "resign", "delete": "delete"}.get(action, "upsert"))
    audit(db, request, "batch." + str(action), "employee", f"{len(emps)} employees")
    db.commit()
    return {"ok": True, "employees": len(emps), "commands": n}


@router.post("/employees/{emp_id}/photo")
async def upload_photo(emp_id: int, request: Request, file: UploadFile = File(...),
                       db: Session = Depends(get_db), _=Depends(require("personnel.edit"))):
    data = await file.read()
    if len(data) > 2_000_000 or not data.startswith(b"\xff\xd8"):
        raise HTTPException(422, "JPEG photo up to 2 MB required")
    e = db.get(m.Employee, emp_id)
    if not e:
        raise HTTPException(404, "not found")
    e.photo = base64.b64encode(data).decode()
    db.flush()
    for dev in sync.area_devices(db, {a.id for a in e.areas}):
        from ..adms import commands as C
        sync.queue(db, dev.sn, C.userpic_update(e.emp_code, e.photo), "Photo " + e.emp_code)
    audit(db, request, "photo", "employee", e.emp_code)
    db.commit()
    return {"ok": True}


@router.get("/employees/{emp_id}/photo")
def get_photo(emp_id: int, db: Session = Depends(get_db), _=Depends(require("personnel.view"))):
    e = db.get(m.Employee, emp_id)
    if not e or not e.photo:
        raise HTTPException(404, "no photo")
    return Response(base64.b64decode(e.photo), media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=60"})


@router.delete("/employees/{emp_id}/templates/{tpl_id}")
def delete_template(emp_id: int, tpl_id: int, request: Request, db: Session = Depends(get_db),
                    _=Depends(require("personnel.edit"))):
    t = db.get(m.BioTemplate, tpl_id)
    e = db.get(m.Employee, emp_id)
    if not t or not e or t.employee_id != emp_id:
        raise HTTPException(404, "not found")
    for dev in sync.area_devices(db, {a.id for a in e.areas}):
        cmd = sync.template_delete_command(dev, e.emp_code, t.bio_type, t.bio_no)
        if cmd:
            sync.queue(db, dev.sn, cmd, f"Delete T{t.bio_type} {e.emp_code}")
    db.delete(t)
    audit(db, request, "delete_template", "employee", e.emp_code)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------
# Import / export
# --------------------------------------------------------------------------

IMPORT_FIELDS = ["emp_code", "first_name", "last_name", "department", "position", "card_no", "gender",
                 "hire_date", "mobile", "email", "national_id"]
_ALIASES = {"id": "emp_code", "pin": "emp_code", "code": "emp_code", "رقم": "emp_code", "الرقم": "emp_code",
            "name": "first_name", "الاسم": "first_name", "القسم": "department", "dept": "department",
            "card": "card_no", "البطاقة": "card_no", "الوظيفة": "position"}


def _read_table(filename: str, data: bytes) -> list[dict]:
    if filename.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        ws = load_workbook(io.BytesIO(data), read_only=True, data_only=True).active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        head = [str(h or "").strip() for h in rows[0]]
        return [{head[i]: ("" if v is None else str(v)) for i, v in enumerate(r) if i < len(head)} for r in rows[1:]]
    text = data.decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


@router.post("/employees/import")
async def import_employees(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db),
                           _=Depends(require("personnel.edit"))):
    rows = _read_table(file.filename or "", await file.read())
    depts = {d.name: d for d in db.scalars(select(m.Department)).all()}
    positions = {p.name: p for p in db.scalars(select(m.Position)).all()}
    default_area = db.scalar(select(m.Area).order_by(m.Area.id).limit(1))
    created = updated = 0
    errors = []
    for i, raw in enumerate(rows, start=2):
        row = {}
        for k, v in raw.items():
            key = _ALIASES.get(str(k).strip().lower(), str(k).strip().lower())
            row[key] = (v or "").strip()
        try:
            code = _validate_code(row.get("emp_code", ""))
        except HTTPException as exc:
            errors.append(f"row {i}: {exc.detail}")
            continue
        e = db.scalar(select(m.Employee).where(m.Employee.emp_code == code))
        is_new = e is None
        if is_new:
            e = m.Employee(emp_code=code, areas=[default_area] if default_area else [])
            db.add(e)
        dname = row.get("department")
        if dname:
            if dname not in depts:
                depts[dname] = m.Department(code=f"D{len(depts) + 1}-{dname[:20]}", name=dname)
                db.add(depts[dname])
                db.flush()
            e.department = depts[dname]
        elif is_new:
            e.department_id = db.scalar(select(m.Department.id).order_by(m.Department.id).limit(1))
        pname = row.get("position")
        if pname:
            if pname not in positions:
                positions[pname] = m.Position(code=f"P{len(positions) + 1}-{pname[:20]}", name=pname)
                db.add(positions[pname])
                db.flush()
            e.position = positions[pname]
        vals = coerce(m.Employee, {k: row[k] for k in ("first_name", "last_name", "card_no", "gender",
                                                       "hire_date", "mobile", "email", "national_id")
                                   if row.get(k)})
        for k, v in vals.items():
            setattr(e, k, v)
        db.flush()
        if is_new:
            sync.link_transactions(db, e)
        sync.employee_changed(db, e, set() if is_new else {a.id for a in e.areas}, with_bio=is_new)
        biotime_push.mark(db, [code])
        created += is_new
        updated += not is_new
    audit(db, request, "import", "employee", f"{created} new, {updated} updated")
    db.commit()
    return {"created": created, "updated": updated, "errors": errors[:50]}


@router.get("/employees-export")
def export_employees(fmt: str = "xlsx", status: str = "active", db: Session = Depends(get_db),
                     _=Depends(require("personnel.view"))):
    from ..reports import to_csv, to_xlsx
    emps = db.scalars(select(m.Employee).where(m.Employee.status == status).order_by(m.Employee.emp_code)).all()
    cols = [("emp_code", "الرقم"), ("first_name", "الاسم الأول"), ("last_name", "اسم العائلة"),
            ("department", "القسم"), ("position", "الوظيفة"), ("card_no", "البطاقة"), ("gender", "الجنس"),
            ("hire_date", "تاريخ التعيين"), ("mobile", "الجوال"), ("email", "البريد"),
            ("national_id", "رقم الهوية"), ("areas", "المناطق")]
    rows = []
    for e in emps:
        rows.append({"emp_code": e.emp_code, "first_name": e.first_name, "last_name": e.last_name,
                     "department": e.department.name if e.department else "",
                     "position": e.position.name if e.position else "", "card_no": e.card_no,
                     "gender": e.gender, "hire_date": e.hire_date.isoformat() if e.hire_date else "",
                     "mobile": e.mobile, "email": e.email, "national_id": e.national_id,
                     "areas": ", ".join(a.name for a in e.areas)})
    rep = {"title": "Employees", "columns": [{"key": k, "label": k if fmt == "csv" else lbl} for k, lbl in cols],
           "rows": rows}
    if fmt == "csv":
        return Response(to_csv(rep), media_type="text/csv",
                        headers={"Content-Disposition": "attachment; filename=employees.csv"})
    return Response(to_xlsx(rep), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename=employees.xlsx"})


@router.get("/lookups")
def lookups(db: Session = Depends(get_db), _=Depends(require("personnel.view"))):
    """Small reference lists for the UI's select boxes."""
    return {
        "departments": [{"id": d.id, "name": d.name, "code": d.code, "parent_id": d.parent_id}
                        for d in db.scalars(select(m.Department).order_by(m.Department.code)).all()],
        "positions": [{"id": p.id, "name": p.name} for p in db.scalars(select(m.Position).order_by(m.Position.code)).all()],
        "areas": [{"id": a.id, "name": a.name} for a in db.scalars(select(m.Area).order_by(m.Area.code)).all()],
        "timetables": [{"id": t.id, "name": t.alias, "color": t.color, "check_in": t.check_in.strftime("%H:%M"),
                        "check_out": t.check_out.strftime("%H:%M")}
                       for t in db.scalars(select(m.TimeTable).order_by(m.TimeTable.alias)).all()],
        "shifts": [{"id": s.id, "name": s.alias} for s in db.scalars(select(m.Shift).order_by(m.Shift.alias)).all()],
        "leave_types": [{"id": t.id, "name": t.name, "code": t.code, "color": t.color}
                        for t in db.scalars(select(m.LeaveType).order_by(m.LeaveType.code)).all()],
        "devices": [{"sn": d.sn, "name": d.alias or d.sn} for d in db.scalars(select(m.Device).order_by(m.Device.alias)).all()],
        "roles": [{"id": r.id, "name": r.name} for r in db.scalars(select(m.Role).order_by(m.Role.name)).all()],
    }


@router.get("/employees-search")
def search_employees(q: str = "", limit: int = 20, db: Session = Depends(get_db),
                     _=Depends(require("personnel.view"))):
    like = f"%{q}%"
    rows = db.scalars(select(m.Employee).where(or_(
        m.Employee.emp_code.ilike(like), m.Employee.first_name.ilike(like), m.Employee.last_name.ilike(like)))
        .order_by(m.Employee.emp_code).limit(limit)).all()
    return [{"id": e.id, "emp_code": e.emp_code, "name": e.full_name,
             "department": e.department.name if e.department else ""} for e in rows]
