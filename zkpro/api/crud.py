"""Generic list/create/update/delete endpoints for the simple tables."""
from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text, Time, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from .deps import audit, page, parse_date, parse_dt, parse_time_str, require, ser


def coerce(model, data: dict, partial: bool = False) -> dict:
    out = {}
    cols = {c.key: c for c in model.__table__.columns}
    for key, value in data.items():
        col = cols.get(key)
        if col is None or key in ("id", "created_at", "updated_at", "password_hash"):
            continue
        t = col.type
        if value == "" and col.nullable and not isinstance(t, (String, Text)):
            value = None
        try:
            if value is None:
                pass
            elif isinstance(t, Boolean):
                value = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes", "on")
            elif isinstance(t, Integer):
                value = int(value)
            elif isinstance(t, Float):
                value = float(value)
            elif isinstance(t, DateTime):
                value = parse_dt(value)
            elif isinstance(t, Date):
                value = parse_date(value)
            elif isinstance(t, Time):
                value = parse_time_str(value)
            else:
                value = str(value).strip()
        except (TypeError, ValueError):
            raise HTTPException(422, f"invalid value for {key}")
        out[key] = value
    return out


def crud_router(model, path: str, view_perm: str, edit_perm: str, *,
                search: tuple[str, ...] = (), order=None,
                to_dict: Callable | None = None,
                before_save: Callable | None = None,
                after_save: Callable | None = None,
                filters: tuple[str, ...] = ()) -> APIRouter:
    r = APIRouter(prefix=path)
    dump = to_dict or (lambda db, o: ser(o))

    @r.get("")
    def list_(request: Request, q: str = "", offset: int = 0, limit: int = 200,
              db: Session = Depends(get_db), _=Depends(require(view_perm))):
        stmt = select(model)
        if q and search:
            stmt = stmt.where(or_(*[getattr(model, f).ilike(f"%{q}%") for f in search]))
        for f in filters:
            v = request.query_params.get(f)
            if v not in (None, ""):
                col = getattr(model, f)
                stmt = stmt.where(col.in_([int(x) for x in v.split(",")])) if f.endswith("_id") else stmt.where(col == v)
        stmt = stmt.order_by(order if order is not None else model.id)
        total, rows = page(db, stmt, offset, limit)
        return {"total": total, "rows": [dump(db, row[0]) for row in rows]}

    @r.get("/{obj_id}")
    def get_(obj_id: int, db: Session = Depends(get_db), _=Depends(require(view_perm))):
        obj = db.get(model, obj_id)
        if not obj:
            raise HTTPException(404, "not found")
        return dump(db, obj)

    @r.post("")
    def create(request: Request, data: dict = Body(...), db: Session = Depends(get_db),
               _=Depends(require(edit_perm))):
        obj = model(**coerce(model, data))
        for col in model.__table__.columns:  # make column defaults visible to validators
            if getattr(obj, col.key) is None and col.default is not None and col.default.is_scalar:
                setattr(obj, col.key, col.default.arg)
        if before_save:
            before_save(db, obj, data, True)
        db.add(obj)
        try:
            db.flush()
            if after_save:
                after_save(db, obj, data, True)
            audit(db, request, "create", model.__tablename__, str(obj.id))
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "duplicate or invalid reference")
        return dump(db, obj)

    @r.put("/{obj_id}")
    def update(obj_id: int, request: Request, data: dict = Body(...), db: Session = Depends(get_db),
               _=Depends(require(edit_perm))):
        obj = db.get(model, obj_id)
        if not obj:
            raise HTTPException(404, "not found")
        for k, v in coerce(model, data, partial=True).items():
            setattr(obj, k, v)
        if before_save:
            before_save(db, obj, data, False)
        try:
            db.flush()
            if after_save:
                after_save(db, obj, data, False)
            audit(db, request, "update", model.__tablename__, str(obj.id))
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "duplicate or invalid reference")
        return dump(db, obj)

    @r.delete("/{obj_id}")
    def delete(obj_id: int, request: Request, db: Session = Depends(get_db), _=Depends(require(edit_perm))):
        obj = db.get(model, obj_id)
        if not obj:
            raise HTTPException(404, "not found")
        db.delete(obj)
        try:
            audit(db, request, "delete", model.__tablename__, str(obj_id))
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "in use — remove the records that reference it first")
        return {"ok": True}

    return r
