"""Read areas, departments, positions, employees, terminals and punches from a
running ZKBioTime (8.x / 9.x) through its REST API — no change to the terminals
or to BioTime is needed. Terminals imported this way are marked
``managed_by="biotime"``: we show them (state, counters) but send them no
commands, because they talk to BioTime. The mark is cleared automatically
when a terminal starts talking to this server (ADMS or relay).

BioTime API: token from ``/jwt-api-token-auth/`` (``Authorization: JWT ...``)
or ``/api-token-auth/`` (``Authorization: Token ...``); lists are paginated
``{"count", "next", "data"|"results"}``. Field names differ a little between
versions, so every field is read with fallbacks.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from . import store
from .adms import sync
from .adms.protocol import AttRecord, parse_time
from .db import now, session_scope

log = logging.getLogger("zkpro.biotime")


class BioTimeError(Exception):
    pass


class BioTimeClient:
    def __init__(self, url: str, username: str, password: str, timeout: float = 30):
        self.url = url.rstrip("/")
        self.username, self.password, self.timeout = username, password, timeout
        self.auth = ""

    def _request(self, method: str, path: str, params: dict | None = None, body: dict | None = None):
        url = self.url + path + ("?" + urllib.parse.urlencode(params) if params else "")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.auth:
            headers["Authorization"] = self.auth
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8") or "null")
        except urllib.error.HTTPError as exc:
            detail = exc.read(300).decode("utf-8", "replace")
            raise BioTimeError(f"HTTP {exc.code} {path}: {detail}") from exc
        except (OSError, ValueError) as exc:
            raise BioTimeError(f"{type(exc).__name__}: {exc}") from exc

    def login(self) -> None:
        errors = []
        for path, scheme in (("/jwt-api-token-auth/", "JWT"), ("/api-token-auth/", "Token")):
            try:
                res = self._request("POST", path, body={"username": self.username, "password": self.password})
            except BioTimeError as exc:
                errors.append(str(exc))
                continue
            token = (res or {}).get("token") if isinstance(res, dict) else None
            if token:
                self.auth = f"{scheme} {token}"
                return
            errors.append(f"{path}: no token in reply")
        raise BioTimeError("BioTime login failed — " + " | ".join(errors))

    def items(self, path: str, params: dict | None = None, page_size: int = 500, max_pages: int = 10_000):
        page, fetched = 1, 0
        while page <= max_pages:
            res = self._request("GET", path, dict(params or {}, page=page, page_size=page_size))
            if isinstance(res, list):
                yield from res
                return
            rows = (res or {}).get("data")
            if rows is None:
                rows = (res or {}).get("results", [])
            if isinstance(rows, dict):  # some versions nest the list once more
                rows = rows.get("data") or rows.get("results") or []
            yield from rows
            fetched += len(rows)
            # The server may cap page_size, so follow "next"/"count", never len(rows) < page_size.
            count = res.get("count")
            if not rows or not (res.get("next") or (isinstance(count, int) and fetched < count)):
                return
            page += 1


# --------------------------------------------------------------------------
# Field helpers (tolerant to version differences)
# --------------------------------------------------------------------------

def _get(d: dict, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ""):
            return d[k]
    return default


def _ref(value, by_id: dict, *code_keys) -> str | None:
    """A related object may come as a nested dict, an id, or a code."""
    if value in (None, ""):
        return None
    if isinstance(value, dict):
        code = _get(value, *code_keys)
        if code is None and value.get("id") in by_id:
            return by_id[value["id"]]
        return str(code) if code is not None else None
    if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
        return by_id.get(int(value), str(value) if isinstance(value, str) else None)
    return str(value)


def _int(v, default=0) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def _date(v):
    if not v:
        return None
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


_STATE_LABELS = {"check in": 0, "check out": 1, "break out": 2, "break in": 3, "overtime in": 4,
                 "overtime out": 5, "ot in": 4, "ot out": 5}


def _punch_state(v) -> int:
    if isinstance(v, int) or (isinstance(v, str) and v.strip().isdigit()):
        return int(v)
    return _STATE_LABELS.get(str(v or "").strip().lower(), 0)


# --------------------------------------------------------------------------
# Sync
# --------------------------------------------------------------------------

def _upsert_coded(db: Session, model, code: str, name: str):
    row = db.scalar(select(model).where(model.code == code))
    if row is None:
        row = model(code=code, name=name or code)
        db.add(row)
        db.flush()
    elif name and row.name != name:
        row.name = name
    return row


def run(client: BioTimeClient | None = None) -> dict:
    """One synchronisation pass. Returns counters for the UI."""
    with session_scope() as db:
        cfg = {k: store.get(db, "biotime." + k) for k in ("url", "username", "password", "history_days", "last_punch")}
    if client is None:
        if not cfg["url"]:
            raise BioTimeError("BioTime address is not set")
        client = BioTimeClient(cfg["url"], cfg["username"] or "", cfg["password"] or "")
    client.login()
    out = {"areas": 0, "departments": 0, "positions": 0, "employees": 0, "terminals": 0, "punches": 0}

    areas = list(client.items("/personnel/api/areas/"))
    depts = list(client.items("/personnel/api/departments/"))
    positions = list(client.items("/personnel/api/positions/"))
    area_code = {a.get("id"): str(_get(a, "area_code", "code", default=a.get("id"))) for a in areas}
    dept_code = {d.get("id"): str(_get(d, "dept_code", "code", default=d.get("id"))) for d in depts}
    pos_code = {p.get("id"): str(_get(p, "position_code", "code", default=p.get("id"))) for p in positions}

    with session_scope() as db:
        area_rows = {}
        for a in areas:
            code = area_code[a.get("id")]
            area_rows[code] = _upsert_coded(db, m.Area, code, _get(a, "area_name", "name", default=code))
        out["areas"] = len(areas)
        dept_rows = {}
        for d in depts:
            code = dept_code[d.get("id")]
            dept_rows[code] = _upsert_coded(db, m.Department, code, _get(d, "dept_name", "name", default=code))
        out["departments"] = len(depts)
        pos_rows = {}
        for p in positions:
            code = pos_code[p.get("id")]
            pos_rows[code] = _upsert_coded(db, m.Position, code, _get(p, "position_name", "name", default=code))
        out["positions"] = len(positions)

    # Employees: written directly (no device commands — BioTime already manages the terminals).
    # Employees with a local change still waiting to be written back are left alone.
    from .biotime_push import pending_codes
    with session_scope() as db:
        waiting = pending_codes(db)
    for e in client.items("/personnel/api/employees/"):
        code = str(_get(e, "emp_code", "pin", default="")).strip()
        if not code or code in waiting:
            continue
        with session_scope() as db:
            emp = db.scalar(select(m.Employee).where(m.Employee.emp_code == code))
            is_new = emp is None
            if is_new:
                emp = m.Employee(emp_code=code)
                db.add(emp)
            emp.first_name = str(_get(e, "first_name", default=emp.first_name or ""))
            emp.last_name = str(_get(e, "last_name", default=emp.last_name or ""))
            dcode = _ref(e.get("department"), dept_code, "dept_code", "code")
            if dcode:
                dept = db.scalar(select(m.Department).where(m.Department.code == dcode))
                if dept is None:
                    dept = _upsert_coded(db, m.Department, dcode, _get(e.get("department") or {}, "dept_name", default=dcode))
                emp.department_id = dept.id
            elif is_new:
                emp.department_id = db.scalar(select(m.Department.id).order_by(m.Department.id).limit(1))
            pcode = _ref(e.get("position"), pos_code, "position_code", "code")
            if pcode:
                pos = db.scalar(select(m.Position).where(m.Position.code == pcode))
                if pos is not None:
                    emp.position_id = pos.id
            raw_areas = e.get("area") or e.get("areas") or []
            if not isinstance(raw_areas, list):
                raw_areas = [raw_areas]
            codes = [c for c in (_ref(a, area_code, "area_code", "code") for a in raw_areas) if c]
            if codes:
                emp.areas = list(db.scalars(select(m.Area).where(m.Area.code.in_(codes))).all())
            for attr, keys in (("card_no", ("card_no", "cardno")), ("mobile", ("mobile",)),
                               ("email", ("email",)), ("national_id", ("ssn", "national", "national_num"))):
                v = _get(e, *keys)
                if v is not None:
                    setattr(emp, attr, str(v))
            g = str(_get(e, "gender", default="") or "")
            if g[:1].upper() in ("M", "F"):
                emp.gender = g[:1].upper()
            if _date(_get(e, "hire_date")):
                emp.hire_date = _date(_get(e, "hire_date"))
            if _date(_get(e, "birthday")):
                emp.birthday = _date(_get(e, "birthday"))
            db.flush()
            if is_new:
                sync.link_transactions(db, emp)
        out["employees"] += 1

    # Terminals
    for t in client.items("/iclock/api/terminals/"):
        sn = str(_get(t, "sn", "SN", default="")).strip()
        if not sn:
            continue
        with session_scope() as db:
            dev = db.scalar(select(m.Device).where(m.Device.sn == sn))
            if dev is None:
                dev = m.Device(sn=sn, managed_by="biotime")
                db.add(dev)
            dev.alias = str(_get(t, "alias", "terminal_name", default=dev.alias or sn))
            acode = _ref(t.get("area"), area_code, "area_code", "code")
            if acode:
                area = db.scalar(select(m.Area).where(m.Area.code == acode))
                if area:
                    dev.area_id = area.id
            if dev.managed_by == "biotime":  # a terminal talking to us directly reports its own data
                dev.ip = str(_get(t, "ip_address", "ip", default=dev.ip or ""))
                dev.firmware = str(_get(t, "fw_ver", "firmware", default=dev.firmware or ""))
                dev.model = str(_get(t, "terminal_name", "model", "product_name", default=dev.model or ""))
                la = parse_time(str(_get(t, "last_activity", default="") or "")[:19])
                if la:
                    dev.last_activity = la
                for attr, keys in (("user_count", ("user_count",)), ("fp_count", ("fp_count",)),
                                   ("face_count", ("face_count",)), ("palm_count", ("palm_count", "pv_count")),
                                   ("att_count", ("transaction_count", "att_count"))):
                    v = _get(t, *keys)
                    if v is not None:
                        setattr(dev, attr, _int(v))
        out["terminals"] += 1

    # Punches (incremental by punch time; duplicates are skipped by save_punches)
    last = parse_time(cfg["last_punch"] or "")
    # Re-read the last 3 days every time: a terminal that was offline uploads old punches late.
    start = (last - timedelta(days=3)) if last else now() - timedelta(days=int(cfg["history_days"] or 60))
    params = {"start_time": start.strftime("%Y-%m-%d %H:%M:%S"), "end_time": now().strftime("%Y-%m-%d %H:%M:%S")}
    batch: list[tuple[str, AttRecord]] = []
    newest = last

    def flush():
        nonlocal batch
        by_sn: dict[str, list[AttRecord]] = {}
        for sn, rec in batch:
            by_sn.setdefault(sn, []).append(rec)
        with session_scope() as db:
            for sn, recs in by_sn.items():
                dev = db.scalar(select(m.Device).where(m.Device.sn == sn)) if sn else None
                if dev is None and sn:
                    dev = m.Device(sn=sn, alias=sn, managed_by="biotime")
                    db.add(dev)
                    db.flush()
                out["punches"] += len(sync.save_punches(db, dev, recs, source="biotime"))
        batch = []

    for p in client.items("/iclock/api/transactions/", params):
        ts = parse_time(str(_get(p, "punch_time", default=""))[:19])
        pin = str(_get(p, "emp_code", default="")).strip()
        if not ts or not pin:
            continue
        rec = AttRecord(pin=pin, time=ts, state=_punch_state(p.get("punch_state")),
                        verify=_int(p.get("verify_type")), work_code=str(p.get("work_code") or ""))
        temp = p.get("temperature")
        try:
            if temp not in (None, "") and 25 <= float(temp) <= 45:
                rec.temperature = float(temp)
        except (TypeError, ValueError):
            pass
        batch.append((str(_get(p, "terminal_sn", "sn", default="")), rec))
        newest = ts if newest is None or ts > newest else newest
        if len(batch) >= 2000:
            flush()
    if batch:
        flush()

    with session_scope() as db:
        if newest:
            store.set_(db, "biotime.last_punch", newest.strftime("%Y-%m-%d %H:%M:%S"))
        store.set_(db, "biotime.last_run", now().strftime("%Y-%m-%d %H:%M:%S"))
        store.set_(db, "biotime.last_result", json.dumps(out))
    log.info("BioTime sync: %s", out)
    return out


def run_logged() -> dict:
    """Used by the scheduler and the API: records failures for the UI."""
    try:
        return run()
    except Exception as exc:  # noqa: BLE001
        with session_scope() as db:
            store.set_(db, "biotime.last_run", now().strftime("%Y-%m-%d %H:%M:%S"))
            store.set_(db, "biotime.last_result", json.dumps({"error": str(exc)}, ensure_ascii=False))
        log.warning("BioTime sync failed: %s", exc)
        raise
