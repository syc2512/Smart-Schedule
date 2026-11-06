"""RFC 5545 calendar export."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from ..models import Course
from ..schemas import TimeSlotItem

DAY_CODES = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


def build_calendar(courses: list[Course], semester_start: date, total_weeks: int = 18) -> str:
    return build_calendar_with_schedule(
        courses,
        semester_start,
        total_weeks,
        slots=[],
        holiday_dates=set(),
        first_day_of_week=1,
    )


def build_calendar_with_schedule(
    courses: list[Course],
    semester_start: date,
    total_weeks: int,
    slots: list[TimeSlotItem],
    holiday_dates: set[str],
    first_day_of_week: int = 1,
) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//SmartTimetablePro//AI Study Planner//CN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:智能课程表 Pro",
        "BEGIN:VTIMEZONE",
        "TZID:Asia/Shanghai",
        "BEGIN:STANDARD",
        "DTSTART:19700101T000000",
        "TZOFFSETFROM:+0800",
        "TZOFFSETTO:+0800",
        "END:STANDARD",
        "END:VTIMEZONE",
    ]
    slot_map = {slot.period: slot for slot in slots}
    aligned_start = semester_start - timedelta(
        days=(semester_start.isoweekday() - first_day_of_week + 7) % 7
    )

    for course in courses:
        active_weeks = _active_weeks(course, total_weeks)
        for section_index, section in enumerate(course.sections):
            weekday = int(section["weekday"])
            start_period = int(section["start_period"])
            end_period = int(section["end_period"])
            custom_start = section.get("custom_start")
            custom_end = section.get("custom_end")
            if custom_start and custom_end:
                start_clock, end_clock = custom_start, custom_end
            else:
                start_slot = slot_map.get(start_period)
                end_slot = slot_map.get(end_period)
                if not start_slot or not end_slot:
                    continue
                start_clock, end_clock = start_slot.start, end_slot.end
            day_offset = (weekday - first_day_of_week + 7) % 7
            for week in active_weeks:
                event_date = aligned_start + timedelta(days=(week - 1) * 7 + day_offset)
                if event_date.isoformat() in holiday_dates:
                    continue
                start = f"{event_date:%Y%m%d}T{start_clock.replace(':', '')}00"
                end = f"{event_date:%Y%m%d}T{end_clock.replace(':', '')}00"
                lines.extend(
                    [
                        "BEGIN:VEVENT",
                        f"UID:{course.id}-w{week}-s{section_index}@smart-timetable-pro",
                        f"DTSTAMP:{stamp}",
                        f"DTSTART;TZID=Asia/Shanghai:{start}",
                        f"DTEND;TZID=Asia/Shanghai:{end}",
                        f"SUMMARY:{escape_ics(course.name)}",
                        f"LOCATION:{escape_ics(section.get('location', ''))}",
                        "DESCRIPTION:"
                        + escape_ics(
                            f"教师：{course.teacher or '未填写'}；第 {week} 周；"
                            f"{DAY_CODES[weekday - 1]}"
                        ),
                        "END:VEVENT",
                    ]
                )
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold_line(line) for line in lines) + "\r\n"


def _active_weeks(course: Course, total_weeks: int) -> list[int]:
    if course.weeks:
        return [week for week in course.weeks if 1 <= week <= total_weeks]
    if course.week_type == "odd":
        return list(range(1, total_weeks + 1, 2))
    if course.week_type == "even":
        return list(range(2, total_weeks + 1, 2))
    return list(range(1, total_weeks + 1))


def escape_ics(value: str) -> str:
    return (
        str(value or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def fold_line(line: str, limit: int = 75) -> str:
    """Fold a text line without splitting UTF-8 code points."""
    if len(line.encode("utf-8")) <= limit:
        return line
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0
    for char in line:
        size = len(char.encode("utf-8"))
        if current and current_size + size > limit:
            chunks.append("".join(current))
            current = []
            current_size = 0
        current.append(char)
        current_size += size
    if current:
        chunks.append("".join(current))
    return "\r\n ".join(chunks)
