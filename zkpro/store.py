"""Key/value system settings with typed defaults."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from .models import Setting

DEFAULTS: dict[str, Any] = {
    "company.name": "My Company",
    "company.name_ar": "شركتي",
    "system.language": "ar",
    # --- Attendance rules (BioTime "Attendance Rule") ---
    "att.dup_punch_minutes": 1,       # punches closer than this are one punch
    "att.no_in": "incomplete",        # incomplete | absent | late
    "att.no_in_minutes": 60,          # late minutes when no_in == late
    "att.no_out": "incomplete",       # incomplete | absent | early
    "att.no_out_minutes": 60,
    "att.late_full": True,            # past the grace -> count all minutes (else minus grace)
    "att.ot_mode": "auto",            # auto | approval | both
    "att.ot_min_minutes": 30,         # auto OT below this is ignored
    "att.ot_before_work": False,      # count early arrival as OT
    "att.dayoff_ot": True,            # work on a day off / holiday is OT
    "att.round_minutes": 0,           # round worked/OT down to a multiple of N (0 = off)
    "att.weekend": [4, 5],            # default day off for employees without a shift (0=Mon ... 4=Fri 5=Sat)
    # --- ADMS / device communication ---
    "adms.auto_add": True,            # auto-register unknown devices that connect
    "adms.default_area": 1,
    "adms.timezone": None,            # hours; None = server local offset
    "adms.sync_bio": True,            # distribute templates enrolled on one device to the area
    "adms.upload_photos": True,       # ask devices to upload attendance photos
    # Side-by-side with ZKBioTime: forward every terminal request to it (e.g. http://127.0.0.1:90)
    "adms.relay_url": "",
    "adms.relay_primary": "biotime",  # biotime | zkpro — whose replies the terminal follows
    # Read devices, people and punches from a running ZKBioTime through its REST API
    "biotime.enabled": False,
    "biotime.url": "",                # e.g. http://127.0.0.1:90
    "biotime.username": "",
    "biotime.password": "",
    "biotime.interval": 5,            # minutes between automatic syncs
    "biotime.history_days": 60,       # punches fetched on the first sync
    "biotime.last_punch": "",         # newest punch time already imported
    "biotime.last_run": "",
    "biotime.last_result": "",
    "biotime.write_back": False,      # send employees changed here to BioTime (it forwards them to the terminals)
    "biotime.push_queue": [],
    "biotime.push_result": "",
    # Direct reading of terminals over TCP 4370 (devices with "tcp_poll" ticked)
    "tcp.poll_minutes": 5,
    # --- Maintenance ---
    "backup.keep": 14,
    "backup.hour": 2,
}


def get(db: Session, key: str, default: Any = None) -> Any:
    row = db.get(Setting, key)
    if row is None:
        return DEFAULTS.get(key, default)
    try:
        return json.loads(row.value)
    except json.JSONDecodeError:
        return row.value


def set_(db: Session, key: str, value: Any) -> None:
    row = db.get(Setting, key)
    text = json.dumps(value, ensure_ascii=False)
    if row is None:
        db.add(Setting(key=key, value=text))
    else:
        row.value = text


def all_(db: Session, prefix: str = "") -> dict[str, Any]:
    out = {k: v for k, v in DEFAULTS.items() if k.startswith(prefix)}
    for row in db.query(Setting).all():
        if row.key.startswith(prefix):
            try:
                out[row.key] = json.loads(row.value)
            except json.JSONDecodeError:
                out[row.key] = row.value
    return out
