"""Create tables and seed the defaults a fresh installation needs."""
from __future__ import annotations

import json
from datetime import time

from sqlalchemy import inspect, select, text

from .db import Base, engine, session_scope
from . import models as m
from .security import PERMISSIONS, hash_password


def _add_missing_columns() -> None:
    """Minimal forward migration: add columns introduced by newer versions to
    existing tables (SQLite's create_all never alters a table)."""
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col.type.compile(dialect=engine.dialect)}'
                default = col.default.arg if col.default is not None and col.default.is_scalar else None
                if default is not None:
                    ddl += " DEFAULT " + (str(int(default)) if isinstance(default, bool)
                                          else repr(default) if isinstance(default, str) else str(default))
                conn.execute(text(ddl))
            for index in table.indexes:  # indexes added by newer versions
                index.create(conn, checkfirst=True)


def init_db() -> None:
    Base.metadata.create_all(engine)
    _add_missing_columns()
    with session_scope() as db:
        if not db.scalar(select(m.User).limit(1)):
            db.add(m.User(username="admin", full_name="Administrator", is_superuser=True,
                          password_hash=hash_password("admin"), must_change_password=True))
        if not db.scalar(select(m.Role).limit(1)):
            db.add_all([
                m.Role(name="HR Manager", permissions=json.dumps(
                    [p for p in PERMISSIONS if p != "system.admin"])),
                m.Role(name="Viewer", permissions=json.dumps(
                    ["personnel.view", "device.view", "attendance.view", "reports.view"])),
            ])
        if not db.scalar(select(m.Department).limit(1)):
            db.add(m.Department(code="1", name="الإدارة العامة / Head Office"))
        if not db.scalar(select(m.Area).limit(1)):
            db.add(m.Area(code="1", name="المقر الرئيسي / HQ"))
        if not db.scalar(select(m.Position).limit(1)):
            db.add(m.Position(code="1", name="موظف / Staff"))
        if not db.scalar(select(m.LeaveType).limit(1)):
            db.add_all([
                m.LeaveType(code="AL", name="إجازة سنوية / Annual", color="#43a047"),
                m.LeaveType(code="SL", name="إجازة مرضية / Sick", color="#e53935"),
                m.LeaveType(code="UL", name="بدون راتب / Unpaid", paid=False, color="#757575"),
                m.LeaveType(code="BT", name="مهمة عمل / Business trip", color="#1e88e5"),
            ])
        if not db.scalar(select(m.TimeTable).limit(1)):
            tt = m.TimeTable(alias="Day 08:00-16:00", check_in=time(8, 0), check_out=time(16, 0),
                             late_grace=10, early_grace=5)
            db.add(tt)
            db.flush()
            shift = m.Shift(alias="Sun-Thu", cycle_unit="week", cycle=1)
            # week index 0 = Monday ... 6 = Sunday
            shift.details = [m.ShiftDetail(day_index=d, timetable_id=tt.id) for d in (6, 0, 1, 2, 3)]
            db.add(shift)
