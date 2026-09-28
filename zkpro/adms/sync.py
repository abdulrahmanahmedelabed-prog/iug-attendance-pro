"""Device-side business logic shared by the ADMS endpoints and the web API.

* queueing commands (with de-duplication of identical pending commands)
* BioTime's area model: an employee is kept on every device of their areas
* storing what devices upload (users, templates, photos, punches, logs)
* redistributing templates enrolled on one terminal to the others
"""
from __future__ import annotations

import base64
import json
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import store
from ..config import settings
from ..db import now
from .. import models as m
from . import commands as C
from .protocol import AttRecord, OperItem, parse_time

log = logging.getLogger("zkpro.adms")


# --------------------------------------------------------------------------
# Command queue
# --------------------------------------------------------------------------

def queue(db: Session, sn: str, content: str, title: str = "") -> m.DeviceCommand | None:
    """Queue a command unless the very same one is already waiting for this device."""
    exists = db.scalar(select(m.DeviceCommand.id).where(
        m.DeviceCommand.device_sn == sn, m.DeviceCommand.status == "pending",
        m.DeviceCommand.content == content).limit(1))
    if exists:
        return None
    cmd = m.DeviceCommand(device_sn=sn, content=content, title=title or content.split(" PIN=")[0][:120])
    db.add(cmd)
    db.flush()
    return cmd


def next_commands(db: Session, sn: str, max_bytes: int = 64_000, max_count: int = 60) -> list[m.DeviceCommand]:
    rows = db.scalars(select(m.DeviceCommand).where(
        m.DeviceCommand.device_sn == sn, m.DeviceCommand.status == "pending")
        .order_by(m.DeviceCommand.id).limit(max_count)).all()
    picked, size = [], 0
    for c in rows:
        size += len(c.content) + 16
        if picked and size > max_bytes:
            break
        picked.append(c)
    ts = now()
    for c in picked:
        c.status, c.sent_at, c.attempts = "sent", ts, c.attempts + 1
    return picked


def requeue_stale(db: Session, older_than_minutes: int = 15, max_attempts: int = 3) -> int:
    """Commands delivered but never acknowledged (device rebooted, network cut)."""
    limit = datetime.fromtimestamp(now().timestamp() - older_than_minutes * 60)
    n = 0
    for c in db.scalars(select(m.DeviceCommand).where(
            m.DeviceCommand.status == "sent", m.DeviceCommand.sent_at < limit)).all():
        if c.attempts >= max_attempts:
            c.status, c.result = "failed", "no reply from device"
        else:
            c.status = "pending"
        n += 1
    return n


# --------------------------------------------------------------------------
# Area model
# --------------------------------------------------------------------------

def area_devices(db: Session, area_ids) -> list[m.Device]:
    ids = [a for a in area_ids if a]
    if not ids:
        return []
    return list(db.scalars(select(m.Device).where(m.Device.area_id.in_(ids), m.Device.enabled.is_(True))).all())


def device_employees(db: Session, device: m.Device) -> list[m.Employee]:
    if not device.area_id:
        return []
    return list(db.scalars(select(m.Employee).join(m.employee_area).where(
        m.employee_area.c.area_id == device.area_id, m.Employee.status == "active",
        m.Employee.enable_att.is_(True)).order_by(m.Employee.emp_code)).all())


def _device_opts(device: m.Device) -> dict:
    try:
        return json.loads(device.options or "{}")
    except json.JSONDecodeError:
        return {}


def device_bio_support(device: m.Device) -> dict[int, str | None]:
    """{bio_type: algorithm major version or None if unknown} for this device.

    New firmware reports ``MultiBioDataSupport=0:1:0:0:0:0:0:0:1:1`` and
    ``MultiBioVersion=0:12.0:0:0:0:0:0:0:3.0:39.0`` (one slot per BIODATA type).
    Older firmware only reports the fingerprint / face algorithm versions.
    """
    opts = _device_opts(device)
    support = opts.get("MultiBioDataSupport", "")
    versions = opts.get("MultiBioVersion", "").split(":")
    result: dict[int, str | None] = {}
    if support:
        for i, flag in enumerate(support.split(":")):
            if flag.strip() == "1":
                ver = versions[i].split(".")[0] if i < len(versions) and versions[i] not in ("", "0") else None
                result[i] = ver
        return result
    if device.fp_alg or opts.get("FPVersion") or opts.get("FingerFunOn") == "1":
        result[1] = (device.fp_alg or opts.get("FPVersion") or "").split(".")[0] or None
    if device.face_alg or opts.get("FaceVersion") or opts.get("FaceFunOn") == "1":
        ver = (device.face_alg or opts.get("FaceVersion") or "").split(".")[0] or None
        result[2] = ver
    return result


def _uses_biodata(device: m.Device) -> bool:
    opts = _device_opts(device)
    if "MultiBioDataSupport" in opts:
        return True
    try:
        return float((device.push_ver or "0").split("-")[0][:3]) >= 2.4
    except ValueError:
        return False


def compatible(support: dict[int, str | None], t: m.BioTemplate) -> bool:
    """Can a device with this bio support use template t as-is?"""
    if not support:
        return True  # capabilities unknown: send and let the device decide
    if t.bio_type not in support:
        return False
    dev_ver = support.get(t.bio_type)
    tpl_ver = (t.major_ver or "").split(".")[0] or None
    return not (dev_ver and tpl_ver and dev_ver != tpl_ver)


def template_commands(db: Session, device: m.Device, emp: m.Employee,
                      templates: list[m.BioTemplate] | None = None) -> list[tuple[str, str]]:
    """Commands that put an employee's templates on a device that can use them.

    A template is only sent when the device supports its type and (if both are
    known) the algorithm major version matches. For faces with a different
    algorithm the enrollment photo is sent instead, so the terminal extracts
    its own template — the same fallback BioTime uses between SpeedFace models.
    """
    want_photo = templates is None or any(t.bio_type in (2, 9) for t in templates)
    if templates is None:
        templates = list(db.scalars(select(m.BioTemplate).where(m.BioTemplate.employee_id == emp.id)).all())
    support = device_bio_support(device)
    biodata = _uses_biodata(device)
    out: list[tuple[str, str]] = []
    faces_covered = False
    for t in templates:
        if not compatible(support, t):
            continue
        if biodata:
            out.append((C.biodata_update(emp.emp_code, t), f"Template T{t.bio_type} {emp.emp_code}"))
        elif t.bio_type == 1:
            out.append((C.fingertmp_update(emp.emp_code, t), "Fingerprint " + emp.emp_code))
        elif t.bio_type == 2:
            out.append((C.face_update(emp.emp_code, t), "Face " + emp.emp_code))
        else:
            continue
        if t.bio_type == 9:
            faces_covered = True
    if want_photo and not faces_covered and (not support or 9 in support):
        photo = db.scalar(select(m.BioPhoto).where(m.BioPhoto.employee_id == emp.id, m.BioPhoto.bio_type == 9))
        if photo:
            out.append((C.biophoto_update(emp.emp_code, 9, photo.content), "Face photo " + emp.emp_code))
    return out


def push_employee_to_device(db: Session, device: m.Device, emp: m.Employee, with_bio: bool = True) -> int:
    n = 0
    if queue(db, device.sn, C.user_update(emp), "User " + emp.emp_code):
        n += 1
    if emp.photo:
        if queue(db, device.sn, C.userpic_update(emp.emp_code, emp.photo), "Photo " + emp.emp_code):
            n += 1
    if with_bio:
        for content, title in template_commands(db, device, emp):
            if queue(db, device.sn, content, title):
                n += 1
    return n


def sync_device(db: Session, device: m.Device) -> int:
    """BioTime 'Synchronize all data to device'."""
    return sum(push_employee_to_device(db, device, e) for e in device_employees(db, device))


def employee_changed(db: Session, emp: m.Employee, old_area_ids: set[int] | None = None,
                     with_bio: bool = False) -> int:
    """Call after saving an employee: adds/updates it on its devices, removes it
    from devices of areas it left, removes it everywhere when resigned."""
    new_ids = {a.id for a in emp.areas}
    old_ids = set(old_area_ids or set())
    n = 0
    active = emp.status == "active" and emp.enable_att
    for dev in area_devices(db, new_ids if active else set()):
        n += push_employee_to_device(db, dev, emp, with_bio=with_bio or dev.area_id not in old_ids)
    gone = (old_ids - new_ids) if active else (old_ids | new_ids)
    for dev in area_devices(db, gone):
        if queue(db, dev.sn, C.user_delete(emp.emp_code), "Delete user " + emp.emp_code):
            n += 1
    return n


def employee_deleted(db: Session, emp_code: str, area_ids: set[int]) -> int:
    n = 0
    for dev in area_devices(db, area_ids):
        if queue(db, dev.sn, C.user_delete(emp_code), "Delete user " + emp_code):
            n += 1
    return n


# --------------------------------------------------------------------------
# Incoming data
# --------------------------------------------------------------------------

def get_or_register(db: Session, sn: str, ip: str = "") -> m.Device | None:
    dev = db.scalar(select(m.Device).where(m.Device.sn == sn))
    if dev is None:
        if not store.get(db, "adms.auto_add"):
            return None
        area_id = store.get(db, "adms.default_area") or None
        if area_id and not db.get(m.Area, area_id):
            area_id = None
        dev = m.Device(sn=sn, alias=sn, area_id=area_id, ip=ip)
        db.add(dev)
        db.flush()
        log.info("new device registered: %s (%s)", sn, ip)
        db.add(m.AuditLog(username="adms", action="device.register", target=sn, detail=ip))
        # Put this area's employees on the new terminal, and ask it for what it already has.
        sync_device(db, dev)
        queue(db, sn, C.query_table("user"), "Upload users")
    if ip:
        dev.ip = ip
    dev.last_activity = now()
    return dev


def _employee_for_pin(db: Session, pin: str, device: m.Device | None, create: bool,
                      name: str = "") -> m.Employee | None:
    emp = db.scalar(select(m.Employee).where(m.Employee.emp_code == pin))
    if emp or not create:
        return emp
    first, _, last = (name or "").partition(" ")
    emp = m.Employee(emp_code=pin, first_name=first, last_name=last,
                     department_id=db.scalar(select(m.Department.id).order_by(m.Department.id).limit(1)))
    if device and device.area:
        emp.areas = [device.area]
    db.add(emp)
    db.flush()
    return emp


def save_punches(db: Session, device: m.Device | None, records: list[AttRecord],
                 source: str = "device") -> list[AttRecord]:
    """Insert punches, skipping duplicates (the device re-sends after a lost reply).
    Returns the records that were new."""
    sn = device.sn if device else ""
    if not records:
        return []
    pins = {r.pin for r in records}
    emp_ids = dict(db.execute(select(m.Employee.emp_code, m.Employee.id)
                              .where(m.Employee.emp_code.in_(pins))).all())
    tmin, tmax = min(r.time for r in records), max(r.time for r in records)
    have = set(db.execute(select(m.Transaction.emp_code, m.Transaction.punch_time).where(
        m.Transaction.device_sn == sn, m.Transaction.punch_time >= tmin,
        m.Transaction.punch_time <= tmax, m.Transaction.emp_code.in_(pins))).all())
    added: list[AttRecord] = []
    for r in records:
        key = (r.pin, r.time)
        if key in have:
            continue
        have.add(key)
        if r.pin not in emp_ids and device is not None:
            emp = _employee_for_pin(db, r.pin, device, create=True)
            emp_ids[r.pin] = emp.id
        db.add(m.Transaction(emp_code=r.pin, employee_id=emp_ids.get(r.pin), punch_time=r.time,
                             punch_state=r.state, verify_type=r.verify, work_code=r.work_code,
                             device_sn=sn, temperature=r.temperature, mask=r.mask, source=source))
        added.append(r)
    db.flush()
    return added


def _upsert_template(db: Session, emp: m.Employee, *, bio_type: int, no: int, index: int, valid: int,
                     duress: int, major: str, minor: str, fmt: int, tmp: str, sn: str) -> tuple[m.BioTemplate, bool]:
    row = db.scalar(select(m.BioTemplate).where(
        m.BioTemplate.employee_id == emp.id, m.BioTemplate.bio_type == bio_type,
        m.BioTemplate.bio_no == no, m.BioTemplate.bio_index == index, m.BioTemplate.major_ver == major))
    changed = True
    if row is None:
        row = m.BioTemplate(employee_id=emp.id, bio_type=bio_type, bio_no=no, bio_index=index,
                            major_ver=major, template=tmp)
        db.add(row)
    else:
        changed = row.template != tmp
    row.valid, row.duress, row.minor_ver, row.bio_format, row.template, row.source_sn = (
        valid, duress, minor, fmt, tmp, sn)
    db.flush()
    return row, changed


def _distribute_template(db: Session, emp: m.Employee, tpl: m.BioTemplate, source_sn: str) -> None:
    if not store.get(db, "adms.sync_bio") or emp.status != "active":
        return
    for dev in area_devices(db, {a.id for a in emp.areas}):
        if dev.sn == source_sn:
            continue
        for content, title in template_commands(db, dev, emp, [tpl]):
            queue(db, dev.sn, content, title)


def _distribute_photo(db: Session, emp: m.Employee, bio_type: int, content: str, source_sn: str) -> None:
    """Send an enrollment photo to devices that have no usable template of that type."""
    if not store.get(db, "adms.sync_bio") or emp.status != "active" or bio_type != 9:
        return
    faces = list(db.scalars(select(m.BioTemplate).where(m.BioTemplate.employee_id == emp.id,
                                                        m.BioTemplate.bio_type == bio_type)).all())
    for dev in area_devices(db, {a.id for a in emp.areas}):
        if dev.sn == source_sn:
            continue
        support = device_bio_support(dev)
        if support and bio_type not in support:
            continue
        if not any(compatible(support, t) for t in faces):
            queue(db, dev.sn, C.biophoto_update(emp.emp_code, bio_type, content), "Face photo " + emp.emp_code)


def _apply_user(db: Session, device: m.Device | None, d: dict[str, str]) -> None:
    pin = d.get("pin") or d.get("pin2") or ""
    if not pin:
        return
    name = d.get("name", "")
    emp = _employee_for_pin(db, pin, device, create=True, name=name)
    if name and not emp.full_name:
        first, _, last = name.partition(" ")
        emp.first_name, emp.last_name = first, last
    if d.get("card") not in (None, "", "0", "[0000000000]"):
        emp.card_no = d["card"].strip("[]")
    if "cardno" in d and d["cardno"] not in ("", "0"):
        emp.card_no = d["cardno"]
    pw = d.get("passwd", d.get("password"))
    if pw is not None:
        emp.dev_password = pw
    pri = d.get("pri", d.get("privilege"))
    if pri not in (None, ""):
        try:
            emp.dev_privilege = int(pri)
        except ValueError:
            pass


def apply_oper_items(db: Session, device: m.Device | None, items: list[OperItem]) -> int:
    sn = device.sn if device else ""
    count = 0
    for it in items:
        d = it.data
        try:
            if it.kind in ("USER", "USERINFO"):
                _apply_user(db, device, d)
            elif it.kind in ("FP", "FINGERTMP", "FACE", "BIODATA"):
                pin = d.get("pin", "")
                tmp = d.get("tmp", "")
                if not pin or not tmp:
                    continue
                emp = _employee_for_pin(db, pin, device, create=True)
                if it.kind in ("FP", "FINGERTMP"):
                    kw = dict(bio_type=1, no=int(d.get("fid", 0) or 0), index=0,
                              major=(device.fp_alg.split(".")[0] if device and device.fp_alg else "10"), minor="0")
                elif it.kind == "FACE":
                    kw = dict(bio_type=2, no=int(d.get("fid", 0) or 0), index=0,
                              major=(device.face_alg.split(".")[0] if device and device.face_alg else "7"), minor="0")
                else:
                    kw = dict(bio_type=int(d.get("type", 0) or 0), no=int(d.get("no", 0) or 0),
                              index=int(d.get("index", 0) or 0), major=d.get("majorver", ""),
                              minor=d.get("minorver", ""))
                tpl, changed = _upsert_template(
                    db, emp, valid=int(d.get("valid", 1) or 1), duress=int(d.get("duress", 0) or 0),
                    fmt=int(d.get("format", 0) or 0), tmp=tmp, sn=sn, **kw)
                if changed:
                    _distribute_template(db, emp, tpl, sn)
            elif it.kind == "USERPIC":
                pin, content = d.get("pin", ""), d.get("content", "")
                if pin and content:
                    emp = _employee_for_pin(db, pin, device, create=True)
                    emp.photo = content
            elif it.kind == "BIOPHOTO":
                pin, content = d.get("pin", ""), d.get("content", "")
                if pin and content:
                    emp = _employee_for_pin(db, pin, device, create=True)
                    btype = int(d.get("type", 9) or 9)
                    row = db.scalar(select(m.BioPhoto).where(m.BioPhoto.employee_id == emp.id,
                                                             m.BioPhoto.bio_type == btype))
                    if row is None:
                        db.add(m.BioPhoto(employee_id=emp.id, bio_type=btype, content=content, source_sn=sn))
                    else:
                        row.content, row.source_sn = content, sn
                    if not emp.photo:
                        emp.photo = content
                    db.flush()
                    _distribute_photo(db, emp, btype, content, sn)
            elif it.kind == "OPLOG":
                f = it.fields + [""] * 7
                db.add(m.DeviceOpLog(device_sn=sn, op_code=int(f[0] or 0) if f[0].isdigit() else 0,
                                     admin=f[1], op_time=parse_time(f[2]),
                                     obj1=f[3], obj2=f[4], obj3=f[5], obj4=f[6]))
            else:
                continue
            count += 1
        except (ValueError, IntegrityError) as exc:  # one bad line must not lose the batch
            log.warning("skipping %s line from %s: %s", it.kind, sn, exc)
    return count


def save_attphoto(sn: str, meta: dict[str, str], data: bytes) -> str | None:
    name = (meta.get("pin") or "").replace("/", "_").replace("\\", "_")
    if not name or not data:
        return None
    folder = settings.photos_dir / sn.replace("/", "_")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(data)
    return str(path)


def photo_path_for(sn: str, pin: str, ts: datetime):
    """Where the device's ATTPHOTO for a punch lands (``YYYYmmddHHMMSS-PIN.jpg``)."""
    return settings.photos_dir / sn / f"{ts:%Y%m%d%H%M%S}-{pin}.jpg"


def apply_device_info(device: m.Device, info: dict[str, str]) -> None:
    """Merge option/INFO keys into the device record."""
    opts = _device_opts(device)
    opts.update(info)
    device.options = json.dumps(opts, ensure_ascii=False)

    def pick(*keys):
        for k in keys:
            if info.get(k) not in (None, ""):
                return info[k]
        return None

    def as_int(v):
        try:
            return int(str(v).strip())
        except (TypeError, ValueError):
            return None

    v = pick("DeviceName", "~DeviceName")
    if v:
        device.model = v
    v = pick("FWVersion", "FirmVer", "firmware")
    if v:
        device.firmware = v
    v = pick("MAC")
    if v:
        device.mac = v
    v = pick("Platform", "~Platform")
    if v:
        device.platform = v
    v = pick("FPVersion", "~ZKFPVersion", "fp_alg")
    if v:
        device.fp_alg = v
    v = pick("FaceVersion", "face_alg")
    if v:
        device.face_alg = v
    v = pick("PushVersion", "PushVer")
    if v:
        device.push_ver = v
    for attr, keys in (("user_count", ("UserCount", "user_count")), ("fp_count", ("FPCount", "fp_count")),
                       ("face_count", ("FaceCount", "face_count")),
                       ("att_count", ("TransactionCount", "AttLogCount", "att_count")),
                       ("palm_count", ("PvCount", "PalmCount"))):
        val = as_int(pick(*keys))
        if val is not None:
            setattr(device, attr, val)


def photo_b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def reset_stamps(device: m.Device, att: bool = True, op: bool = True) -> None:
    """Make the device upload everything again at its next handshake."""
    if att:
        device.att_stamp = "0"
    if op:
        device.op_stamp = "0"
