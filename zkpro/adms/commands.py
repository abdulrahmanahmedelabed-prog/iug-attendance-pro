"""Builders for the ``C:<id>:<command>`` strings queued for a terminal."""
from __future__ import annotations

from datetime import datetime

from .protocol import tsv, zk_encode_time


def user_update(emp) -> str:
    name = (emp.full_name or emp.emp_code)[:24]
    return "DATA UPDATE USERINFO " + tsv(
        PIN=emp.emp_code, Name=name, Pri=emp.dev_privilege or 0, Passwd=emp.dev_password or "",
        Card=emp.card_no or "", Grp=1, TZ="0000000100000000",
        Verify=emp.verify_mode if emp.verify_mode is not None else -1, ViceCard="",
        StartDatetime=0, EndDatetime=0)


def user_delete(pin: str) -> str:
    return "DATA DELETE USERINFO " + tsv(PIN=pin)


def biodata_update(pin: str, t) -> str:
    return "DATA UPDATE BIODATA " + tsv(
        Pin=pin, No=t.bio_no, Index=t.bio_index, Valid=t.valid, Duress=t.duress, Type=t.bio_type,
        MajorVer=t.major_ver or 0, MinorVer=t.minor_ver or 0, Format=t.bio_format, Tmp=t.template)


def fingertmp_update(pin: str, t) -> str:
    """Legacy (pre-BIODATA) fingerprint command, ZKFinger v10."""
    return "DATA UPDATE FINGERTMP " + tsv(PIN=pin, FID=t.bio_no, Size=len(t.template),
                                          Valid=t.valid, TMP=t.template)


def face_update(pin: str, t) -> str:
    """Legacy near-infrared face (ZKFace v7)."""
    return "DATA UPDATE FACE " + tsv(PIN=pin, FID=t.bio_no, Valid=t.valid, Size=len(t.template),
                                     TMP=t.template)


def fingertmp_delete(pin: str, fid: int | None = None) -> str:
    return "DATA DELETE FINGERTMP " + (tsv(PIN=pin) if fid is None else tsv(PIN=pin, FID=fid))


def face_delete(pin: str) -> str:
    return "DATA DELETE FACE " + tsv(PIN=pin)


def biodata_delete(pin: str, bio_type: int | None = None) -> str:
    if bio_type is None:
        return "DATA DELETE BIODATA " + tsv(Pin=pin)
    return "DATA DELETE BIODATA " + tsv(Pin=pin, Type=bio_type)


def userpic_update(pin: str, b64: str) -> str:
    return "DATA UPDATE USERPIC " + tsv(PIN=pin, Size=len(b64), Content=b64)


def biophoto_update(pin: str, bio_type: int, b64: str) -> str:
    return "DATA UPDATE BIOPHOTO " + tsv(PIN=pin, Type=bio_type, Size=len(b64), Content=b64,
                                         Format=0, Url="", PostBackTmpFlag=1)


def query_attlog(start: datetime, end: datetime) -> str:
    return "DATA QUERY ATTLOG " + tsv(StartTime=start.strftime("%Y-%m-%d %H:%M:%S"),
                                      EndTime=end.strftime("%Y-%m-%d %H:%M:%S"))


def query_table(table: str) -> str:
    return f"DATA QUERY tablename={table},fielddesc=*,filter=*"


def set_time(dt: datetime) -> str:
    return f"SET OPTION DateTime={zk_encode_time(dt)}"


def enroll_bio(pin: str, bio_type: int, finger: int = 0) -> str:
    if bio_type == 1:
        return "ENROLL_FP " + tsv(PIN=pin, FID=finger, RETRY=3, OVERWRITE=1)
    return "ENROLL_BIO " + tsv(TYPE=bio_type, PIN=pin, CardNo="", RETRY=3, OVERWRITE=1)


SIMPLE = {
    "check": "CHECK",          # device re-reads the option block
    "info": "INFO",            # device reports firmware / counters
    "reboot": "REBOOT",
    "clear_log": "CLEAR LOG",  # attendance records
    "clear_photo": "CLEAR PHOTO",
    "clear_data": "CLEAR DATA",  # users, templates and records
    "reload_options": "RELOAD OPTIONS",
}
