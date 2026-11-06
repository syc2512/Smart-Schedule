"""Timetable configuration, portable JSON import/export and rescheduling."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..constants import TIME_SLOTS, TOTAL_WEEKS
from ..models import Course, Holiday, ScheduleTimeSlot, TimetableSettings
from ..schemas import (
    CourseCreate,
    HolidayItem,
    JsonImportResult,
    RescheduleRequest,
    RescheduleResult,
    ScheduleConfigUpdate,
    TimeSlotItem,
    TimetableSettingsPayload,
)


def current_week_start() -> date:
    today = date.today()
    return today - timedelta(days=today.weekday())


def ensure_schedule_defaults(db: Session) -> TimetableSettings:
    settings = db.get(TimetableSettings, "default")
    if settings is None:
        settings = TimetableSettings(
            id="default",
            semester_start_date=current_week_start().isoformat(),
        )
        db.add(settings)
    if db.scalar(select(ScheduleTimeSlot).limit(1)) is None:
        for slot in TIME_SLOTS:
            db.add(
                ScheduleTimeSlot(
                    period=slot["period"],
                    start=slot["start"],
                    end=slot["end"],
                )
            )
    db.commit()
    db.refresh(settings)
    return settings


def get_schedule_config(db: Session) -> ScheduleConfigUpdate:
    settings = ensure_schedule_defaults(db)
    slots = db.scalars(select(ScheduleTimeSlot).order_by(ScheduleTimeSlot.period)).all()
    holidays = db.scalars(select(Holiday).order_by(Holiday.date)).all()
    return ScheduleConfigUpdate(
        settings=TimetableSettingsPayload(
            name=settings.name,
            semester_start_date=settings.semester_start_date,
            total_weeks=settings.total_weeks,
            first_day_of_week=settings.first_day_of_week,
            show_weekends=settings.show_weekends,
            display_mode=settings.display_mode,
            density=settings.density,
            background_theme=settings.background_theme,
            dark_mode=settings.dark_mode,
            card_opacity=settings.card_opacity,
            hide_teacher=settings.hide_teacher,
            hide_location=settings.hide_location,
            font_scale=settings.font_scale,
        ),
        time_slots=[
            TimeSlotItem(period=slot.period, start=slot.start, end=slot.end, alias=slot.alias)
            for slot in slots
        ],
        holidays=[HolidayItem(date=item.date, name=item.name) for item in holidays],
    )


def save_schedule_config(db: Session, payload: ScheduleConfigUpdate) -> ScheduleConfigUpdate:
    settings = ensure_schedule_defaults(db)
    values = payload.settings.model_dump()
    for key, value in values.items():
        setattr(settings, key, value)

    db.execute(delete(ScheduleTimeSlot))
    db.add_all(
        [
            ScheduleTimeSlot(
                period=slot.period,
                start=slot.start,
                end=slot.end,
                alias=slot.alias,
            )
            for slot in payload.time_slots
        ]
    )
    db.execute(delete(Holiday))
    db.add_all([Holiday(date=item.date, name=item.name) for item in payload.holidays])
    db.commit()
    return get_schedule_config(db)


def export_json(db: Session) -> dict[str, Any]:
    schedule = get_schedule_config(db)
    courses = db.scalars(select(Course).order_by(Course.created_at, Course.name)).all()
    return {
        "schema_version": 1,
        "source": "smart-timetable-pro",
        "exported_at": datetime.now().astimezone().isoformat(),
        "schedule": schedule.model_dump(mode="json"),
        "courses": [
            {
                "name": course.name,
                "teacher": course.teacher,
                "color_index": course.color_index,
                "week_type": course.week_type,
                "weeks": course.weeks,
                "sections": course.sections,
            }
            for course in courses
        ],
    }


def preview_json_import(content: str) -> JsonImportResult:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        return JsonImportResult(
            ok=False,
            source="unknown",
            warnings=[f"JSON 无法解析：{exc.msg}"],
        )
    if not isinstance(payload, dict):
        return JsonImportResult(ok=False, source="unknown", warnings=["JSON 顶层必须是对象"])

    source = payload.get("source")
    if source == "smart-timetable-pro" or payload.get("schema_version") == 1:
        return _parse_native_json(payload)
    if "courses" in payload and (
        "timeSlots" in payload or "config" in payload or _looks_like_shiguang(payload)
    ):
        return _parse_shiguang_json(payload)
    return JsonImportResult(
        ok=False,
        source="unknown",
        warnings=["无法识别该 JSON。支持智能课程表 Pro 备份或拾光课程表导出文件。"],
    )


def commit_json_import(
    db: Session,
    courses: list[CourseCreate],
    schedule: ScheduleConfigUpdate | None,
    replace_courses: bool,
) -> int:
    if replace_courses:
        db.execute(delete(Course))
    db.add_all([Course(**course.model_dump()) for course in courses])
    if schedule is not None:
        save_schedule_config(db, schedule)
    else:
        db.commit()
    return len(courses)


def reschedule_courses(db: Session, request: RescheduleRequest) -> RescheduleResult:
    total_weeks = get_schedule_config(db).settings.total_weeks
    courses = list(db.scalars(select(Course)).all())
    warnings: list[str] = []

    if request.mode == "overwrite":
        removed = _remove_occurrences(
            db, courses, request.target_week, request.target_day, total_weeks
        )
    else:
        removed = []

    source_moves = _remove_occurrences(
        db, courses, request.source_week, request.source_day, total_weeks
    )
    if request.mode == "exchange":
        # Re-read after source removal; target occurrences may belong to the same courses.
        courses = list(db.scalars(select(Course)).all())
        target_moves = _remove_occurrences(
            db, courses, request.target_week, request.target_day, total_weeks
        )
    else:
        target_moves = []

    for item in source_moves:
        _add_moved_course(db, item, request.target_week, request.target_day)
    for item in target_moves:
        _add_moved_course(db, item, request.source_week, request.source_day)

    if not source_moves:
        warnings.append("源日期没有可调动的课程")
    db.commit()
    return RescheduleResult(
        ok=bool(source_moves),
        moved=len(source_moves),
        removed_target_occurrences=len(removed),
        warnings=warnings,
    )


def _parse_native_json(payload: dict[str, Any]) -> JsonImportResult:
    courses, warnings = _validated_courses(payload.get("courses"))
    schedule = None
    try:
        schedule = ScheduleConfigUpdate.model_validate(payload["schedule"])
    except (KeyError, ValidationError) as exc:
        warnings.append(f"课表设置无效，将保留当前设置：{_first_validation_message(exc)}")
    return JsonImportResult(
        ok=bool(courses),
        source="smart-timetable-pro",
        courses=courses,
        schedule=schedule,
        warnings=warnings,
    )


def _parse_shiguang_json(payload: dict[str, Any]) -> JsonImportResult:
    raw_courses = payload.get("courses", [])
    warnings: list[str] = []
    courses: list[CourseCreate] = []
    if not isinstance(raw_courses, list):
        return JsonImportResult(
            ok=False, source="shiguangschedule", warnings=["courses 必须是数组"]
        )

    for index, item in enumerate(raw_courses, start=1):
        if not isinstance(item, dict):
            warnings.append(f"第 {index} 条课程不是对象")
            continue
        try:
            courses.append(_map_shiguang_course(item, index))
        except (ValidationError, ValueError, TypeError) as exc:
            warnings.append(f"第 {index} 条课程跳过：{_first_validation_message(exc)}")

    raw_slots = payload.get("timeSlots") or []
    slots: list[TimeSlotItem] = []
    if isinstance(raw_slots, list):
        for item in raw_slots:
            try:
                number = int(item.get("number", 0))
                start = str(item.get("startTime", ""))
                end = str(item.get("endTime", ""))
                slots.append(
                    TimeSlotItem(
                        period=number,
                        start=start,
                        end=end,
                        alias=str(item.get("alias") or ""),
                    )
                )
            except (AttributeError, ValidationError, ValueError):
                warnings.append("存在无效作息时间段，已跳过")
    if not slots:
        slots = [
            TimeSlotItem(period=slot["period"], start=slot["start"], end=slot["end"])
            for slot in TIME_SLOTS
        ]
    slots.sort(key=lambda slot: slot.period)
    if [slot.period for slot in slots] != list(range(1, len(slots) + 1)):
        warnings.append("作息节次不连续，已回退到默认作息")
        slots = [
            TimeSlotItem(period=slot["period"], start=slot["start"], end=slot["end"])
            for slot in TIME_SLOTS
        ]

    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    start_date = config.get("semesterStartDate") or current_week_start().isoformat()
    settings = TimetableSettingsPayload(
        name="拾光课程表导入",
        semester_start_date=str(start_date),
        total_weeks=int(config.get("semesterTotalWeeks") or TOTAL_WEEKS),
        first_day_of_week=int(config.get("firstDayOfWeek") or 1),
        show_weekends=True,
        display_mode="sections",
    )
    return JsonImportResult(
        ok=bool(courses),
        source="shiguangschedule",
        courses=courses,
        schedule=ScheduleConfigUpdate(settings=settings, time_slots=slots, holidays=[]),
        warnings=warnings,
    )


def _map_shiguang_course(item: dict[str, Any], index: int) -> CourseCreate:
    name = str(item.get("name") or "").strip()
    if not name:
        raise ValueError("课程名称为空")
    day = int(item.get("day") or 1)
    start_section = int(item.get("startSection") or 1)
    end_section = int(item.get("endSection") or start_section)
    weeks = item.get("weeks")
    if not isinstance(weeks, list) or not weeks:
        weeks = list(range(1, TOTAL_WEEKS + 1))
    custom_start = item.get("customStartTime") if item.get("isCustomTime") else None
    custom_end = item.get("customEndTime") if item.get("isCustomTime") else None
    return CourseCreate(
        name=name,
        teacher=str(item.get("teacher") or "")[:30],
        color_index=int(item.get("color") or item.get("colorInt") or index % 12),
        week_type=_derive_week_type(sorted({int(week) for week in weeks}), TOTAL_WEEKS),
        weeks=sorted({int(week) for week in weeks}),
        sections=[
            {
                "weekday": day,
                "start_period": start_section,
                "end_period": end_section,
                "location": str(item.get("position") or item.get("location") or "")[:40],
                "custom_start": custom_start,
                "custom_end": custom_end,
            }
        ],
    )


def _validated_courses(raw: Any) -> tuple[list[CourseCreate], list[str]]:
    if not isinstance(raw, list):
        return [], ["courses 必须是数组"]
    courses: list[CourseCreate] = []
    warnings: list[str] = []
    for index, item in enumerate(raw, start=1):
        try:
            courses.append(CourseCreate.model_validate(item))
        except ValidationError as exc:
            warnings.append(f"第 {index} 条课程无效：{_first_validation_message(exc)}")
    return courses, warnings


def _looks_like_shiguang(payload: dict[str, Any]) -> bool:
    courses = payload.get("courses")
    return bool(
        isinstance(courses, list)
        and courses
        and isinstance(courses[0], dict)
        and "day" in courses[0]
        and ("startSection" in courses[0] or "position" in courses[0])
    )


def _derive_week_type(weeks: list[int], total_weeks: int) -> str:
    if weeks == list(range(1, total_weeks + 1)):
        return "all"
    if weeks == list(range(1, total_weeks + 1, 2)):
        return "odd"
    if weeks == list(range(2, total_weeks + 1, 2)):
        return "even"
    return "custom"


def _active_weeks(course: Course, total_weeks: int) -> list[int]:
    if course.weeks:
        return [week for week in course.weeks if 1 <= week <= total_weeks]
    if course.week_type == "odd":
        return list(range(1, total_weeks + 1, 2))
    if course.week_type == "even":
        return list(range(2, total_weeks + 1, 2))
    return list(range(1, total_weeks + 1))


def _remove_occurrences(
    db: Session, courses: list[Course], week: int, day: int, total_weeks: int
) -> list[dict[str, Any]]:
    moves: list[dict[str, Any]] = []
    for course in courses:
        if week not in _active_weeks(course, total_weeks):
            continue
        source_sections = [section for section in course.sections if section.get("weekday") == day]
        if not source_sections:
            continue
        moves.append(
            {
                "name": course.name,
                "teacher": course.teacher,
                "color_index": course.color_index,
                "sections": [dict(section) for section in source_sections],
            }
        )
        other_sections = [section for section in course.sections if section.get("weekday") != day]
        remaining_weeks = [item for item in _active_weeks(course, total_weeks) if item != week]
        if other_sections:
            db.add(
                Course(
                    id=uuid4().hex,
                    name=course.name,
                    teacher=course.teacher,
                    color_index=course.color_index,
                    week_type=course.week_type,
                    weeks=list(course.weeks),
                    sections=other_sections,
                )
            )
        if remaining_weeks:
            course.weeks = remaining_weeks
            course.week_type = _derive_week_type(remaining_weeks, total_weeks)
            course.sections = source_sections
        else:
            db.delete(course)
    return moves


def _add_moved_course(db: Session, item: dict[str, Any], week: int, day: int) -> None:
    sections = []
    for section in item["sections"]:
        moved = dict(section)
        moved["weekday"] = day
        sections.append(moved)
    db.add(
        Course(
            id=uuid4().hex,
            name=item["name"],
            teacher=item["teacher"],
            color_index=item["color_index"],
            week_type="custom",
            weeks=[week],
            sections=sections,
        )
    )


def _first_validation_message(error: Exception) -> str:
    if isinstance(error, ValidationError):
        return str(error.errors()[0].get("msg", "字段校验失败"))
    return str(error)
