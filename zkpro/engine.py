"""Attendance calculation engine (BioTime-style).

For every employee and day it resolves the scheduled timetables
(temporary schedule > personal schedule > department schedule > none),
matches punches to check-in / check-out windows and derives late, early
leave, absence, worked time, overtime, leave and holiday status.

Results are computed on demand from the raw data, so a late punch upload,
an edited timetable or an approved leave is reflected immediately — there
is no stale "calculated" table to forget to refresh.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import models as m
from . import store

DAY = timedelta(days=1)


def minutes(td: timedelta) -> int:
    return max(0, int(td.total_seconds() // 60))


def overlap(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> int:
    lo, hi = max(a0, b0), min(a1, b1)
    return minutes(hi - lo) if hi > lo else 0


@dataclass
class Rules:
    dup_punch_minutes: int = 1
    no_in: str = "incomplete"
    no_in_minutes: int = 60
    no_out: str = "incomplete"
    no_out_minutes: int = 60
    late_full: bool = True
    ot_mode: str = "auto"
    ot_min_minutes: int = 30
    ot_before_work: bool = False
    dayoff_ot: bool = True
    round_minutes: int = 0
    weekend: tuple = (4, 5)

    @classmethod
    def load(cls, db: Session) -> "Rules":
        r = cls()
        for k in r.__dataclass_fields__:
            v = store.get(db, "att." + k)
            if v is not None:
                setattr(r, k, tuple(v) if k == "weekend" else v)
        return r

    def rnd(self, mins: int) -> int:
        n = int(self.round_minutes or 0)
        return (mins // n) * n if n > 1 else mins


@dataclass
class Segment:
    timetable: str
    sched_in: datetime | None
    sched_out: datetime | None
    clock_in: datetime | None = None
    clock_out: datetime | None = None
    required: int = 0
    worked: int = 0
    late: int = 0
    early: int = 0
    absent: int = 0
    leave: int = 0
    ot: int = 0
    workday: float = 1.0
    exceptions: list[str] = field(default_factory=list)


@dataclass
class DayResult:
    employee_id: int
    emp_code: str
    name: str
    department: str
    att_date: date
    status: str = ""
    timetable: str = ""
    sched_in: datetime | None = None
    sched_out: datetime | None = None
    clock_in: datetime | None = None
    clock_out: datetime | None = None
    punches: list[datetime] = field(default_factory=list)
    required: int = 0
    worked: int = 0
    late: int = 0
    early: int = 0
    absent: int = 0
    leave: int = 0
    ot: int = 0
    workday: float = 0.0
    present: float = 0.0
    leave_codes: list[str] = field(default_factory=list)
    holiday: str = ""
    exceptions: list[str] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)

    def as_dict(self) -> dict:
        f = lambda d: d.strftime("%Y-%m-%d %H:%M") if d else ""  # noqa: E731
        return {
            "employee_id": self.employee_id, "emp_code": self.emp_code, "name": self.name,
            "department": self.department, "date": self.att_date.isoformat(),
            "weekday": self.att_date.weekday(), "status": self.status, "timetable": self.timetable,
            "sched_in": f(self.sched_in), "sched_out": f(self.sched_out),
            "clock_in": f(self.clock_in), "clock_out": f(self.clock_out),
            "punches": [p.strftime("%H:%M") for p in self.punches],
            "required": self.required, "worked": self.worked, "late": self.late, "early": self.early,
            "absent": self.absent, "leave": self.leave, "ot": self.ot, "workday": self.workday,
            "present": self.present, "leave_codes": self.leave_codes, "holiday": self.holiday,
            "exceptions": self.exceptions,
        }


class Engine:
    def __init__(self, db: Session, start: date, end: date, employee_ids: list[int] | None = None,
                 department_ids: list[int] | None = None, include_resigned: bool = True):
        self.db, self.start, self.end = db, start, end
        self.rules = Rules.load(db)
        q = select(m.Employee).where(m.Employee.enable_att.is_(True))
        if employee_ids:
            q = q.where(m.Employee.id.in_(employee_ids))
        if department_ids:
            q = q.where(m.Employee.department_id.in_(department_ids))
        if not include_resigned:
            q = q.where(m.Employee.status == "active")
        self.employees = list(db.scalars(q.order_by(m.Employee.emp_code)).all())
        self._load()

    # ------------------------------------------------------------------ load
    def _load(self) -> None:
        db, ids = self.db, [e.id for e in self.employees]
        lo = datetime.combine(self.start - DAY, time.min)
        hi = datetime.combine(self.end + 2 * DAY, time.min)
        self.timetables = {t.id: t for t in db.scalars(select(m.TimeTable)).all()}
        self.shifts = {s.id: s for s in db.scalars(select(m.Shift)).all()}
        self.schedules = defaultdict(list)
        self.dept_schedules = defaultdict(list)
        self.temp = defaultdict(list)
        self.punches = defaultdict(list)
        self.leaves = defaultdict(list)
        self.overtimes = defaultdict(list)
        if not ids:
            self.holidays = []
            return
        for s in db.scalars(select(m.Schedule).where(
                m.Schedule.employee_id.in_(ids), m.Schedule.start_date <= self.end + DAY,
                m.Schedule.end_date >= self.start - DAY)).all():
            self.schedules[s.employee_id].append(s)
        for s in db.scalars(select(m.DeptSchedule).where(
                m.DeptSchedule.start_date <= self.end + DAY,
                m.DeptSchedule.end_date >= self.start - DAY)).all():
            self.dept_schedules[s.department_id].append(s)
        for t in db.scalars(select(m.TempSchedule).where(
                m.TempSchedule.employee_id.in_(ids), m.TempSchedule.att_date >= self.start - DAY,
                m.TempSchedule.att_date <= self.end + DAY)).all():
            self.temp[(t.employee_id, t.att_date)].append(t.timetable_id)
        self.holidays = list(db.scalars(select(m.Holiday).where(
            m.Holiday.start_date <= self.end,
            m.Holiday.start_date >= self.start - timedelta(days=366))).all())
        # Punches from attendance terminals (+ imports / manual punches without a device).
        att_devices = select(m.Device.sn).where(m.Device.is_attendance.is_(True))
        for emp_id, ts in db.execute(select(m.Transaction.employee_id, m.Transaction.punch_time).where(
                m.Transaction.employee_id.in_(ids), m.Transaction.punch_time >= lo,
                m.Transaction.punch_time < hi,
                or_(m.Transaction.device_sn == "", m.Transaction.device_sn.in_(att_devices)))).all():
            self.punches[emp_id].append(ts)
        for emp_id, ts in db.execute(select(m.ManualLog.employee_id, m.ManualLog.punch_time).where(
                m.ManualLog.employee_id.in_(ids), m.ManualLog.status == "approved",
                m.ManualLog.punch_time >= lo, m.ManualLog.punch_time < hi)).all():
            self.punches[emp_id].append(ts)
        for emp_id in list(self.punches):
            self.punches[emp_id] = self._dedupe(sorted(self.punches[emp_id]))
        codes = {lt.id: lt.code for lt in db.scalars(select(m.LeaveType)).all()}
        for lv in db.scalars(select(m.Leave).where(
                m.Leave.employee_id.in_(ids), m.Leave.status == "approved",
                m.Leave.start_time < hi, m.Leave.end_time > lo)).all():
            self.leaves[lv.employee_id].append((lv.start_time, lv.end_time, codes.get(lv.leave_type_id, "")))
        for ot in db.scalars(select(m.Overtime).where(
                m.Overtime.employee_id.in_(ids), m.Overtime.status == "approved",
                m.Overtime.start_time < hi, m.Overtime.end_time > lo)).all():
            self.overtimes[ot.employee_id].append((ot.start_time, ot.end_time))

    def _dedupe(self, punches: list[datetime]) -> list[datetime]:
        gap = timedelta(minutes=max(0, int(self.rules.dup_punch_minutes or 0)))
        out: list[datetime] = []
        for p in punches:
            if out and p - out[-1] < gap:
                continue
            if out and p == out[-1]:
                continue
            out.append(p)
        return out

    # -------------------------------------------------------------- schedule
    @staticmethod
    def _shift_index(shift: m.Shift, anchor: date, day: date) -> int:
        cycle = max(1, shift.cycle or 1)
        if shift.cycle_unit == "day":
            return (day - anchor).days % cycle
        if shift.cycle_unit == "month":
            months = (day.year - anchor.year) * 12 + day.month - anchor.month
            return (months % cycle) * 31 + day.day - 1
        weeks = ((day - timedelta(days=day.weekday())) - (anchor - timedelta(days=anchor.weekday()))).days // 7
        return (weeks % cycle) * 7 + day.weekday()

    def _from_shift(self, shift_id: int, anchor: date, day: date) -> list[m.TimeTable]:
        shift = self.shifts.get(shift_id)
        if not shift:
            return []
        idx = self._shift_index(shift, anchor, day)
        tts = [self.timetables[d.timetable_id] for d in shift.details
               if d.day_index == idx and d.timetable_id in self.timetables]
        return sorted(tts, key=lambda t: t.check_in)

    def timetables_for(self, emp: m.Employee, day: date) -> list[m.TimeTable] | None:
        """None = no schedule at all; [] = scheduled day off."""
        if (emp.id, day) in self.temp:
            return sorted([self.timetables[t] for t in self.temp[(emp.id, day)] if t in self.timetables],
                          key=lambda t: t.check_in)
        for s in sorted(self.schedules.get(emp.id, []), key=lambda s: s.start_date, reverse=True):
            if s.start_date <= day <= s.end_date:
                return self._from_shift(s.shift_id, s.start_date, day)
        for s in sorted(self.dept_schedules.get(emp.department_id, []), key=lambda s: s.start_date, reverse=True):
            if s.start_date <= day <= s.end_date:
                return self._from_shift(s.shift_id, s.start_date, day)
        return None

    def holiday_for(self, emp: m.Employee, day: date) -> str:
        for h in self.holidays:
            if h.start_date <= day < h.start_date + timedelta(days=max(1, h.days)):
                if h.department_id in (None, emp.department_id):
                    return h.alias
        return ""

    # ------------------------------------------------------------ calculate
    def _window(self, punches, lo: datetime, hi: datetime) -> list[datetime]:
        i = bisect_left(punches, lo)
        out = []
        while i < len(punches) and punches[i] <= hi:
            out.append(punches[i])
            i += 1
        return out

    def _leave_overlap(self, emp_id: int, a: datetime, b: datetime) -> tuple[int, list[str]]:
        total, codes = 0, []
        for s, e, code in self.leaves.get(emp_id, []):
            o = overlap(a, b, s, e)
            if o:
                total += o
                if code and code not in codes:
                    codes.append(code)
        return total, codes

    def _break(self, tt: m.TimeTable, s_in: datetime) -> tuple[datetime, datetime] | None:
        if not tt.break_start or not tt.break_end:
            return None
        b0 = datetime.combine(s_in.date(), tt.break_start)
        if b0 < s_in:
            b0 += DAY
        b1 = datetime.combine(b0.date(), tt.break_end)
        if b1 <= b0:
            b1 += DAY
        return b0, b1

    def _approved_ot(self, emp_id: int, a: datetime, b: datetime) -> int:
        return sum(overlap(a, b, s, e) for s, e in self.overtimes.get(emp_id, []))

    @staticmethod
    def _bounds(day: date, tt: m.TimeTable) -> tuple[datetime, datetime]:
        s_in = datetime.combine(day, tt.check_in)
        s_out = datetime.combine(day, tt.check_out)
        if s_out <= s_in:
            s_out += DAY
        return s_in, s_out

    def _segment(self, emp: m.Employee, day: date, tt: m.TimeTable, punches: list[datetime],
                 used: set[datetime], rules: Rules, is_holiday: bool,
                 lo_bound: datetime | None = None, hi_bound: datetime | None = None) -> Segment:
        """lo_bound / hi_bound: half-way points to the neighbouring shifts, so a
        night shift's check-out is not taken as the next morning's check-in."""
        s_in, s_out = self._bounds(day, tt)
        seg = Segment(timetable=tt.alias, sched_in=s_in, sched_out=s_out, workday=tt.workday or 1.0)
        brk = self._break(tt, s_in)
        brk_min = overlap(s_in, s_out, *brk) if brk else 0

        def net(a: datetime, b: datetime) -> int:
            return max(0, minutes(b - a) - (overlap(a, b, *brk) if brk else 0))

        free = [p for p in punches if p not in used]
        if tt.kind == "flexible":
            win = self._window(free, s_in, s_out if s_out > s_in else s_in + DAY)
            seg.required = tt.work_minutes or 480
            if win:
                seg.clock_in = win[0]
                if len(win) > 1:
                    seg.clock_out = win[-1]
                used.update(win)
        else:
            seg.required = minutes(s_out - s_in) - brk_min
            in_lo = s_in - timedelta(minutes=tt.in_ahead)
            out_hi = s_out + timedelta(minutes=tt.out_above)
            if lo_bound and lo_bound > in_lo:
                in_lo = lo_bound
            if hi_bound and hi_bound < out_hi:
                out_hi = hi_bound
            in_win = [p for p in self._window(free, in_lo, s_in + timedelta(minutes=tt.in_above))
                      if not lo_bound or p > lo_bound]
            out_win = [p for p in self._window(free, s_out - timedelta(minutes=tt.out_ahead), out_hi)
                       if not hi_bound or p < hi_bound]
            if in_win:
                seg.clock_in = in_win[0]
            later = [p for p in out_win if seg.clock_in is None or p > seg.clock_in]
            if later:
                seg.clock_out = later[-1]
            # A single punch sitting in both windows belongs to the closer boundary.
            if seg.clock_in and seg.clock_out is None and seg.clock_in in out_win:
                if abs((seg.clock_in - s_out).total_seconds()) < abs((seg.clock_in - s_in).total_seconds()):
                    seg.clock_in, seg.clock_out = None, seg.clock_in
            used.update(p for p in (seg.clock_in, seg.clock_out) if p)

        seg.leave, codes = self._leave_overlap(emp.id, s_in, s_out)
        seg.leave = min(seg.leave, seg.required)
        seg.exceptions = []
        if is_holiday:
            seg.required = 0
            if seg.clock_in and seg.clock_out and rules.dayoff_ot:
                seg.worked = net(seg.clock_in, seg.clock_out)
                seg.ot = rules.rnd(seg.worked)
            return seg
        if seg.leave >= seg.required and seg.required > 0:
            if seg.clock_in and seg.clock_out:
                seg.worked = net(max(seg.clock_in, s_in), min(seg.clock_out, s_out))
            return seg

        ci, co = seg.clock_in, seg.clock_out
        if ci is None and not tt.must_check_in and co is not None:
            ci = s_in
        if co is None and not tt.must_check_out and ci is not None:
            co = s_out
        if ci is None and co is None:
            seg.absent = max(0, seg.required - seg.leave)
            seg.exceptions.append("absent")
            return seg

        if tt.kind == "flexible":
            if ci and co:
                seg.worked = rules.rnd(net(ci, co))
                short = seg.required - seg.worked - seg.leave
                if short > 0:
                    seg.early = short
                if seg.worked > seg.required and rules.ot_mode in ("auto", "both"):
                    extra = seg.worked - seg.required
                    seg.ot = rules.rnd(extra) if extra >= rules.ot_min_minutes else 0
            else:
                seg.exceptions.append("missed_out")
            return seg

        # --- late / missing check-in
        if ci is None:
            seg.exceptions.append("missed_in")
            if rules.no_in == "absent":
                seg.absent = max(0, seg.required - seg.leave)
                return seg
            if rules.no_in == "late":
                seg.late = int(rules.no_in_minutes)
        elif ci > s_in:
            diff = minutes(ci - s_in) - (overlap(s_in, ci, *brk) if brk else 0)
            diff -= self._leave_overlap(emp.id, s_in, ci)[0]
            if diff > tt.late_grace:
                seg.late = diff if rules.late_full else diff - tt.late_grace
        # --- early leave / missing check-out
        if co is None:
            seg.exceptions.append("missed_out")
            if rules.no_out == "absent":
                seg.absent = max(0, seg.required - seg.leave)
                seg.late = 0
                return seg
            if rules.no_out == "early":
                seg.early = int(rules.no_out_minutes)
        elif co < s_out:
            diff = minutes(s_out - co) - (overlap(co, s_out, *brk) if brk else 0)
            diff -= self._leave_overlap(emp.id, co, s_out)[0]
            if diff > tt.early_grace:
                seg.early = diff if rules.late_full else diff - tt.early_grace
        if seg.late:
            seg.exceptions.append("late")
        if seg.early:
            seg.exceptions.append("early")
        # --- worked & overtime
        if ci and co:
            seg.worked = rules.rnd(net(max(ci, s_in), min(co, s_out)))
            auto = 0
            if co > s_out and minutes(co - s_out) >= rules.ot_min_minutes:
                auto += minutes(co - s_out)
            if rules.ot_before_work and ci < s_in and minutes(s_in - ci) >= rules.ot_min_minutes:
                auto += minutes(s_in - ci)
            approved = self._approved_ot(emp.id, s_in - timedelta(hours=12), s_out + timedelta(hours=12))
            seg.ot = rules.rnd({"auto": auto, "approval": approved}.get(rules.ot_mode, max(auto, approved)))
        return seg

    def _free_day(self, emp: m.Employee, day: date, res: DayResult, rules: Rules) -> None:
        """Day off / holiday / unscheduled: punches inside the calendar day."""
        lo = datetime.combine(day, time.min)
        win = self._window(self.punches.get(emp.id, []), lo, lo + DAY - timedelta(seconds=1))
        if win:
            res.clock_in = win[0]
            if len(win) > 1:
                res.clock_out = win[-1]
                res.worked = rules.rnd(minutes(win[-1] - win[0]))

    def day(self, emp: m.Employee, day: date, today: date) -> DayResult | None:
        if emp.hire_date and day < emp.hire_date:
            return None
        if emp.status == "resigned" and emp.resign_date and day > emp.resign_date:
            return None
        rules = self.rules
        res = DayResult(emp.id, emp.emp_code, emp.full_name,
                        emp.department.name if emp.department else "", day)
        res.holiday = self.holiday_for(emp, day)
        tts = self.timetables_for(emp, day)
        all_p = self.punches.get(emp.id, [])
        future = day > today
        res.leave_codes = self._leave_overlap(emp.id, datetime.combine(day, time.min),
                                              datetime.combine(day, time.min) + DAY)[1]

        if tts is None or not tts:
            self._free_day(emp, day, res, rules)
            if tts is None and day.weekday() not in rules.weekend and not res.holiday:
                res.status = "unscheduled" if not future else ""
                res.present = 1.0 if res.clock_in else 0.0
            else:
                res.status = "holiday" if res.holiday else "off"
                if res.worked and rules.dayoff_ot:
                    res.ot = res.worked
            res.punches = self._window(all_p, datetime.combine(day, time.min),
                                       datetime.combine(day, time.max))
            return res

        used: set[datetime] = set()
        current = datetime.now()
        span_lo = datetime.combine(day, tts[0].check_in) - timedelta(minutes=tts[0].in_ahead)
        span_hi = datetime.combine(day, time.min)
        normal = [t for t in tts if t.kind != "flexible"]
        prev_tts = [t for t in (self.timetables_for(emp, day - DAY) or []) if t.kind != "flexible"]
        next_tts = [t for t in (self.timetables_for(emp, day + DAY) or []) if t.kind != "flexible"]
        prev_out = max((self._bounds(day - DAY, t)[1] for t in prev_tts), default=None)
        next_in = min((self._bounds(day + DAY, t)[0] for t in next_tts), default=None)
        for tt in tts:
            lo_b = hi_b = None
            if tt.kind != "flexible":
                s_in, s_out = self._bounds(day, tt)
                i = normal.index(tt)
                before = self._bounds(day, normal[i - 1])[1] if i > 0 else prev_out
                after = self._bounds(day, normal[i + 1])[0] if i + 1 < len(normal) else next_in
                if before and before <= s_in:
                    lo_b = before + (s_in - before) / 2
                if after and after >= s_out:
                    hi_b = s_out + (after - s_out) / 2
            seg = self._segment(emp, day, tt, all_p, used, rules, bool(res.holiday), lo_b, hi_b)
            if future:
                seg.absent, seg.late, seg.early, seg.exceptions = 0, 0, 0, []
            elif seg.sched_out and current < seg.sched_out:
                # Shift still running: nothing is missing yet.
                seg.absent, seg.early = 0, 0
                seg.exceptions = [x for x in seg.exceptions if x not in ("absent", "missed_out", "early")]
                if seg.clock_in is None:
                    seg.late = 0
                    seg.exceptions = [x for x in seg.exceptions if x not in ("missed_in", "late")]
            res.segments.append(seg)
            span_hi = max(span_hi, seg.sched_out + timedelta(minutes=tt.out_above))
        res.punches = self._window(all_p, span_lo, span_hi)
        segs = res.segments
        res.timetable = " + ".join(s.timetable for s in segs)
        res.sched_in, res.sched_out = segs[0].sched_in, segs[-1].sched_out
        res.clock_in = next((s.clock_in for s in segs if s.clock_in), None)
        res.clock_out = next((s.clock_out for s in reversed(segs) if s.clock_out), None)
        for attr in ("required", "worked", "late", "early", "absent", "leave", "ot"):
            setattr(res, attr, sum(getattr(s, attr) for s in segs))
        res.exceptions = [x for s in segs for x in s.exceptions]
        res.workday = 0.0 if res.holiday else sum(s.workday for s in segs)
        if res.holiday:
            res.status = "holiday"
        elif future:
            res.status = "leave" if res.leave and res.leave >= res.required else ""
        elif res.required and res.leave >= res.required:
            res.status = "leave"
        elif not res.clock_in and not res.clock_out and current < res.sched_out:
            res.status = "pending"
        elif res.absent and res.absent >= res.required - res.leave:
            res.status = "absent"
        elif "missed_in" in res.exceptions or "missed_out" in res.exceptions:
            res.status = "incomplete"
        elif res.late and res.early:
            res.status = "late_early"
        elif res.late:
            res.status = "late"
        elif res.early:
            res.status = "early"
        else:
            res.status = "present"
        if res.required:
            done = sum(s.workday for s in segs if s.clock_in or s.clock_out)
            res.present = round(done, 2) if res.status not in ("absent", "leave") else 0.0
        return res

    def run(self) -> list[DayResult]:
        today = date.today()
        out: list[DayResult] = []
        for emp in self.employees:
            d = self.start
            while d <= self.end:
                r = self.day(emp, d, today)
                if r is not None:
                    out.append(r)
                d += DAY
        return out


def calculate(db: Session, start: date, end: date, **kw) -> list[DayResult]:
    return Engine(db, start, end, **kw).run()


def summarize(days: list[DayResult]) -> list[dict]:
    """Monthly / period summary per employee (BioTime 'Monthly Summary')."""
    by_emp: dict[int, dict] = {}
    for r in days:
        s = by_emp.setdefault(r.employee_id, {
            "employee_id": r.employee_id, "emp_code": r.emp_code, "name": r.name,
            "department": r.department, "scheduled_days": 0.0, "present_days": 0.0,
            "absent_days": 0, "late_count": 0, "late": 0, "early_count": 0, "early": 0,
            "required": 0, "worked": 0, "ot": 0, "leave": 0, "leave_days": 0, "holidays": 0,
            "off_days": 0, "missed_punch": 0, "unscheduled_days": 0, "leave_by_code": {},
        })
        s["scheduled_days"] += r.workday
        s["present_days"] += r.present
        s["absent_days"] += 1 if r.status == "absent" else 0
        s["late_count"] += 1 if r.late else 0
        s["late"] += r.late
        s["early_count"] += 1 if r.early else 0
        s["early"] += r.early
        s["required"] += r.required
        s["worked"] += r.worked
        s["ot"] += r.ot
        s["leave"] += r.leave
        s["leave_days"] += 1 if r.status == "leave" else 0
        s["holidays"] += 1 if r.status == "holiday" else 0
        s["off_days"] += 1 if r.status == "off" else 0
        s["unscheduled_days"] += 1 if r.status == "unscheduled" and r.clock_in else 0
        s["missed_punch"] += sum(1 for x in r.exceptions if x in ("missed_in", "missed_out"))
        if r.status == "leave":
            for c in r.leave_codes or ["?"]:
                s["leave_by_code"][c] = s["leave_by_code"].get(c, 0) + 1
    for s in by_emp.values():
        s["scheduled_days"] = round(s["scheduled_days"], 2)
        s["present_days"] = round(s["present_days"], 2)
    return list(by_emp.values())
