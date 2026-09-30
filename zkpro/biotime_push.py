"""Write-back to ZKBioTime: changes made here reach the terminals *through BioTime*.

While BioTime keeps port 90 the terminals only talk to BioTime, so the way to
get an employee onto them without touching the terminals is to give it to
BioTime, which then sends it to the devices of the employee's areas on port 90.

Changed employees are queued in the settings table (survives a restart) and
pushed every minute by the maintenance loop: create/update, resign, delete.
The queue is pushed before each pull, and queued employees are skipped by the
pull, so a local edit is never overwritten by BioTime's older copy.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from . import store
from .biotime_sync import BioTimeClient, BioTimeError
from .db import now, session_scope

log = logging.getLogger("zkpro.biotime")
QUEUE_KEY = "biotime.push_queue"


def enabled(db: Session) -> bool:
    return bool(store.get(db, "biotime.write_back")) and bool(store.get(db, "biotime.url"))


def mark(db: Session, codes, op: str = "upsert") -> None:
    """Queue employees for BioTime (op: upsert / resign / delete). No-op when write-back is off."""
    if not enabled(db):
        return
    q = {item["code"]: item for item in (store.get(db, QUEUE_KEY) or [])}
    for code in codes:
        if code:
            q[str(code)] = {"code": str(code), "op": op}
    store.set_(db, QUEUE_KEY, list(q.values()))


def pending_codes(db: Session) -> set[str]:
    return {item["code"] for item in (store.get(db, QUEUE_KEY) or [])}


class _Lookups:
    """BioTime ids for departments / areas / positions, creating missing ones."""

    def __init__(self, client: BioTimeClient):
        self.c = client
        self.depts = {str(d.get("dept_code")): d["id"] for d in client.items("/personnel/api/departments/")}
        self.areas = {str(a.get("area_code")): a["id"] for a in client.items("/personnel/api/areas/")}
        self.positions = {str(p.get("position_code")): p["id"] for p in client.items("/personnel/api/positions/")}

    def _ensure(self, cache: dict, path: str, code_key: str, name_key: str, code: str, name: str):
        if code not in cache:
            res = self.c._request("POST", path, body={code_key: code, name_key: name or code})
            cache[code] = (res or {}).get("id") or ((res or {}).get("data") or {}).get("id")
        return cache[code]

    def dept(self, d: m.Department | None):
        return self._ensure(self.depts, "/personnel/api/departments/", "dept_code", "dept_name",
                            d.code, d.name) if d else None

    def area(self, a: m.Area):
        return self._ensure(self.areas, "/personnel/api/areas/", "area_code", "area_name", a.code, a.name)

    def position(self, p: m.Position | None):
        return self._ensure(self.positions, "/personnel/api/positions/", "position_code", "position_name",
                            p.code, p.name) if p else None


def _find(client: BioTimeClient, code: str):
    res = client._request("GET", "/personnel/api/employees/", {"emp_code": code, "page_size": 50})
    rows = (res or {}).get("data") if isinstance(res, dict) else res
    if rows is None and isinstance(res, dict):
        rows = res.get("results", [])
    for row in rows or []:
        if str(row.get("emp_code")) == code:
            return row.get("id")
    return None


def _payload(e: m.Employee, look: _Lookups) -> dict:
    body = {"emp_code": e.emp_code, "first_name": e.first_name or e.emp_code, "last_name": e.last_name or "",
            "department": look.dept(e.department), "area": [look.area(a) for a in e.areas],
            "card_no": e.card_no or "", "mobile": e.mobile or "", "email": e.email or "",
            "gender": e.gender or ""}
    if e.position:
        body["position"] = look.position(e.position)
    if e.hire_date:
        body["hire_date"] = e.hire_date.isoformat()
    return {k: v for k, v in body.items() if v not in (None, "")} | {"area": body["area"]}


def push_pending(client: BioTimeClient | None = None) -> dict:
    with session_scope() as db:
        if not enabled(db):
            return {"pushed": 0, "left": 0}
        queue = list(store.get(db, QUEUE_KEY) or [])
        cfg = {k: store.get(db, "biotime." + k) for k in ("url", "username", "password")}
    if not queue:
        return {"pushed": 0, "left": 0}
    if client is None:
        client = BioTimeClient(cfg["url"], cfg["username"] or "", cfg["password"] or "")
    done, errors = [], []
    try:
        client.login()
        look = _Lookups(client)
        for item in queue:
            code, op = item["code"], item["op"]
            try:
                bt_id = _find(client, code)
                with session_scope() as db:
                    emp = db.scalar(select(m.Employee).where(m.Employee.emp_code == code))
                    if op == "delete" or emp is None:
                        if bt_id:
                            client._request("DELETE", f"/personnel/api/employees/{bt_id}/")
                    elif op == "resign" or emp.status == "resigned":
                        if bt_id:
                            client._request("POST", "/personnel/api/resigns/", body={
                                "employee": bt_id, "resign_date": (emp.resign_date or now().date()).isoformat(),
                                "resign_type": 1, "reason": emp.resign_reason or ""})
                    else:
                        body = _payload(emp, look)
                        if bt_id:
                            client._request("PATCH", f"/personnel/api/employees/{bt_id}/", body=body)
                        else:
                            client._request("POST", "/personnel/api/employees/", body=body)
                done.append(code)
            except BioTimeError as exc:
                errors.append(f"{code}: {exc}")
    except BioTimeError as exc:  # login / lookups failed: keep everything queued
        errors.append(str(exc))
    with session_scope() as db:
        left = [i for i in (store.get(db, QUEUE_KEY) or []) if i["code"] not in done]
        store.set_(db, QUEUE_KEY, left)
        store.set_(db, "biotime.push_result", json.dumps(
            {"time": now().strftime("%Y-%m-%d %H:%M:%S"), "pushed": len(done), "left": len(left),
             "errors": errors[:20]}, ensure_ascii=False))
    if errors:
        log.warning("BioTime write-back: %d pushed, %d errors: %s", len(done), len(errors), errors[:3])
    return {"pushed": len(done), "left": len(left), "errors": errors[:20]}
