"""Turn AI output or messy timetable text into validated course drafts."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from ..constants import TOTAL_WEEKS
from ..schemas import CourseCreate, Section

WEEKDAY_MAP = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "日": 7,
    "天": 7,
}
WEEKDAY_PATTERN = re.compile(r"(?:星期|周)\s*([一二三四五六日天])")
PERIOD_PATTERN = re.compile(r"(?:第\s*)?(\d{1,2})\s*[-~—–至]\s*(\d{1,2})\s*(?:节|课时)?")
SINGLE_PERIOD_PATTERN = re.compile(r"第\s*(\d{1,2})\s*节")
WEEK_PATTERN = re.compile(r"(?:第\s*)?(\d{1,2})\s*[-~—–至]\s*(\d{1,2})\s*周")
TEACHER_PATTERN = re.compile(r"(?:任课教师|教师|老师)\s*[:：]\s*([^\s|｜,，;；]+)")
LOCATION_PATTERN = re.compile(r"(?:上课地点|地点|教室)\s*[:：]\s*([^\s|｜,，;；]+)")


def extract_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("AI 未返回 JSON 对象") from None
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError("AI 返回的 JSON 无法解析") from exc
    if not isinstance(parsed, dict):
        raise ValueError("AI 返回值必须是 JSON 对象")
    return parsed


def courses_from_ai_payload(payload: dict[str, Any]) -> tuple[list[CourseCreate], list[str]]:
    candidates = payload.get("courses")
    if not isinstance(candidates, list):
        raise ValueError("AI JSON 缺少 courses 数组")

    courses: list[CourseCreate] = []
    warnings: list[str] = list(payload.get("warnings") or [])
    for index, item in enumerate(candidates, start=1):
        if not isinstance(item, dict):
            warnings.append(f"第 {index} 条课程不是对象，已跳过")
            continue
        normalized = _normalize_ai_course(item)
        try:
            courses.append(CourseCreate.model_validate(normalized))
        except ValidationError as exc:
            warnings.append(f"第 {index} 条课程校验失败，已跳过：{exc.errors()[0]['msg']}")
    return courses, warnings


def _normalize_ai_course(item: dict[str, Any]) -> dict[str, Any]:
    sections = item.get("sections")
    if not isinstance(sections, list) or not sections:
        sections = [
            {
                "weekday": item.get("weekday", 1),
                "start_period": item.get("start_period", 1),
                "end_period": item.get("end_period", item.get("start_period", 1)),
                "location": item.get("location", ""),
            }
        ]
    weeks = item.get("weeks")
    if not isinstance(weeks, list):
        weeks = weeks_for_type(str(item.get("week_type", "all")))
    week_type = item.get("week_type", "all")
    if week_type not in {"all", "odd", "even", "custom"}:
        week_type = "custom" if weeks else "all"
    return {
        "name": str(item.get("name", "")).strip(),
        "teacher": str(item.get("teacher", "")).strip(),
        "color_index": item.get("color_index", 0),
        "week_type": week_type,
        "weeks": weeks,
        "sections": sections,
    }


def weeks_for_type(week_type: str, total_weeks: int = TOTAL_WEEKS) -> list[int]:
    if week_type == "odd":
        return list(range(1, total_weeks + 1, 2))
    if week_type == "even":
        return list(range(2, total_weeks + 1, 2))
    return list(range(1, total_weeks + 1))


def parse_text_courses(raw: str) -> tuple[list[CourseCreate], list[str]]:
    """Best-effort parser for common Chinese university timetable lines."""
    courses: list[CourseCreate] = []
    warnings: list[str] = []
    seen: set[tuple] = set()

    for line_number, line in enumerate(raw.splitlines(), start=1):
        line = line.strip(" \t|｜")
        if not line or _looks_like_header(line):
            continue
        weekday_match = WEEKDAY_PATTERN.search(line)
        period_match = PERIOD_PATTERN.search(line) or SINGLE_PERIOD_PATTERN.search(line)
        if not weekday_match or not period_match:
            continue

        start_period = int(period_match.group(1))
        is_range = period_match.re is PERIOD_PATTERN
        end_period = int(period_match.group(2)) if is_range else start_period
        weekday = WEEKDAY_MAP[weekday_match.group(1)]
        week_type, weeks = _parse_weeks(line)
        teacher = _first_match(TEACHER_PATTERN, line)
        location = _first_match(LOCATION_PATTERN, line)
        name = _course_name(line, weekday_match.start())
        if not name:
            warnings.append(f"第 {line_number} 行未识别到课程名，已跳过")
            continue
        if not teacher:
            teacher = _find_token(line, ("老师", "教授", "讲师"))
        if not location:
            location = _find_token(line, ("楼", "馆", "教室", "中心", "机房", "校区", "室", "教"))

        try:
            course = CourseCreate(
                name=name,
                teacher=teacher[:30],
                color_index=max(0, len(courses) % 12),
                week_type=week_type,
                weeks=weeks,
                sections=[
                    Section(
                        weekday=weekday,
                        start_period=start_period,
                        end_period=end_period,
                        location=location[:40],
                    )
                ],
            )
        except ValidationError:
            warnings.append(f"第 {line_number} 行节次或字段不合法，已跳过")
            continue

        key = (
            course.name,
            weekday,
            start_period,
            end_period,
            tuple(course.weeks),
        )
        if key not in seen:
            seen.add(key)
            courses.append(course)

    if not courses:
        warnings.append("没有识别到课程，请检查文本中是否包含星期与节次")
    return courses, warnings


def _looks_like_header(line: str) -> bool:
    compact = re.sub(r"\s+", "", line)
    return compact in {"课程表", "我的课表", "教务课表"} or (
        "星期一" in compact and "星期二" in compact and "课程" in compact
    )


def _parse_weeks(text: str) -> tuple[str, list[int]]:
    week_type = "odd" if "单周" in text else "even" if "双周" in text else "all"
    match = WEEK_PATTERN.search(text)
    if match:
        start, end = int(match.group(1)), int(match.group(2))
        start, end = max(1, start), min(30, end)
        step = 2 if week_type in {"odd", "even"} else 1
        first = start
        if week_type == "odd" and first % 2 == 0:
            first += 1
        if week_type == "even" and first % 2 == 1:
            first += 1
        weeks = list(range(first, end + 1, step))
    else:
        weeks = weeks_for_type(week_type)
    if len(weeks) not in {TOTAL_WEEKS} and week_type in {"all", "odd", "even"}:
        week_type = "custom"
    return week_type, weeks


def _course_name(line: str, weekday_start: int) -> str:
    before = line[:weekday_start]
    tokens = [token for token in re.split(r"[|｜\t,，;；]+", before) if token.strip()]
    if tokens:
        candidate = tokens[-1].strip()
        candidate = re.sub(r"^\d+[.、]\s*", "", candidate)
        return candidate[:40]
    return ""


def _first_match(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def _find_token(text: str, suffixes: tuple[str, ...]) -> str:
    for token in reversed(re.split(r"\s+", text)):
        clean = token.strip("|｜,，;；()（）[]")
        if clean and any(suffix in clean for suffix in suffixes):
            return clean
    return ""
