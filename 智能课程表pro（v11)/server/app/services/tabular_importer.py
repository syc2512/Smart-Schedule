"""Safe Excel/CSV timetable parsing with deterministic preview and commit."""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import openpyxl
import xlrd
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import Course, ImportProfile
from ..schemas import (
    CourseCreate,
    ImportProfilePayload,
    TabularImportCommit,
    TabularImportCommitResult,
    TabularImportPreview,
    TimeSlotItem,
)

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_ROWS = 5000
MAX_HEADER_SCAN = 20
INVALID_VALUES = {"", "nan", "none", "nat", "null", "无", "-"}

COLUMN_ALIASES = {
    "course": ["课程名称", "课程名", "课程", "名称", "course", "subject"],
    "time": ["上课时间", "课程时间", "时间", "节次", "time", "schedule"],
    "location": ["上课地点", "地点", "教室", "场地", "location", "room"],
    "teacher": ["教师名称", "任课教师", "教师", "老师", "teacher"],
}

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


class TabularImportError(ValueError):
    pass


@dataclass(frozen=True)
class TabularOptions:
    header_row: int = 0
    course_column: str = ""
    time_column: str = ""
    location_column: str = ""
    teacher_column: str = ""
    multi_separator: str = ";"
    odd_marker: str = "单周"
    even_marker: str = "双周"
    time_regex: str = ""
    campus_rules: dict[str, list[TimeSlotItem]] | None = None


def preview_tabular(
    *,
    filename: str,
    data: bytes,
    options: TabularOptions,
    total_weeks: int,
    slot_periods: set[int],
) -> TabularImportPreview:
    if len(data) > MAX_FILE_BYTES:
        raise TabularImportError("文件不能超过 5MB")
    extension = Path(filename).suffix.lower()
    if extension == ".xlsm":
        raise TabularImportError("不支持含宏的 .xlsm 文件")
    if extension not in {".xlsx", ".xls", ".csv"}:
        raise TabularImportError("仅支持 .xlsx、.xls 和 .csv")

    sheet_name: str | None
    if extension == ".csv":
        rows, sheet_name = _read_csv(data)
    elif extension == ".xls":
        rows, sheet_name = _read_xls(data)
    else:
        rows, sheet_name = _read_xlsx(data)

    if not rows:
        raise TabularImportError("表格为空")
    if len(rows) > MAX_ROWS + MAX_HEADER_SCAN:
        raise TabularImportError(f"表格最多支持 {MAX_ROWS} 行数据")
    custom_time_pattern = None
    if options.time_regex.strip():
        try:
            custom_time_pattern = re.compile(options.time_regex.strip())
        except re.error as exc:
            raise TabularImportError(f"自定义时间正则无效：{exc}") from exc
        if custom_time_pattern.groups < 3:
            raise TabularImportError("自定义时间正则必须包含星期、节次、周次三个捕获组")

    headers, data_rows, header_index = _resolve_table(rows, options.header_row)
    columns, warnings = _resolve_columns(headers, options)
    if not columns.get("course") or not columns.get("time"):
        raise TabularImportError("未识别课程名称列或上课时间列，请手动指定列名")

    courses: list[CourseCreate] = []
    skipped = 0
    seen: set[tuple[Any, ...]] = set()
    name_colors: dict[str, int] = {}

    for row_number, row in enumerate(data_rows, start=header_index + 2):
        course_name = _cell(row, headers, columns["course"])
        if _invalid(course_name):
            skipped += 1
            continue
        time_text = _cell(row, headers, columns["time"])
        if _invalid(time_text):
            warnings.append(f"第 {row_number} 行没有上课时间，已跳过")
            skipped += 1
            continue
        teacher = _cell(row, headers, columns.get("teacher", ""))
        location_text = _cell(row, headers, columns.get("location", ""))
        if teacher.lower() in INVALID_VALUES:
            teacher = ""

        segments = _split_multi(time_text, options.multi_separator)
        locations = _split_multi(location_text, options.multi_separator)
        if len(locations) > 1 and len(locations) != len(segments):
            warnings.append(
                f"第 {row_number} 行有 {len(segments)} 个时间段，但地点有 "
                f"{len(locations)} 个；无法对应的地点将留空"
            )
        if course_name not in name_colors:
            name_colors[course_name] = len(name_colors) % 12

        row_added = False
        for index, segment in enumerate(segments):
            parsed = _parse_time_segment(
                segment,
                total_weeks=total_weeks,
                odd_marker=options.odd_marker,
                even_marker=options.even_marker,
                custom_pattern=custom_time_pattern,
            )
            if parsed is None:
                warnings.append(f"第 {row_number} 行无法解析时间：{segment}")
                continue
            weekday, periods, weeks = parsed
            if index < len(locations):
                location = locations[index]
            elif len(locations) == 1:
                location = locations[0]
            else:
                location = ""
            campus_slots = _campus_slots(location, options.campus_rules or {})
            available_periods = (
                {slot.period for slot in campus_slots} if campus_slots else slot_periods
            )
            if any(period not in available_periods for period in periods):
                missing = sorted(period for period in periods if period not in available_periods)
                warnings.append(f"第 {row_number} 行节次 {missing} 未在当前作息中配置，已跳过")
                continue
            week_type = _derive_week_type(weeks, total_weeks)
            custom_times: dict[str, str] = {}
            if campus_slots:
                campus_map = {slot.period: slot for slot in campus_slots}
                custom_times = {
                    "custom_start": campus_map[min(periods)].start,
                    "custom_end": campus_map[max(periods)].end,
                }
            section = {
                "weekday": weekday,
                "start_period": min(periods),
                "end_period": max(periods),
                "location": location[:40],
                **custom_times,
            }
            try:
                course = CourseCreate(
                    name=course_name[:40],
                    teacher=teacher[:30],
                    color_index=name_colors[course_name],
                    week_type=week_type,
                    weeks=weeks,
                    sections=[section],
                )
            except ValidationError as exc:
                warnings.append(f"第 {row_number} 行课程校验失败：{exc.errors()[0].get('msg', '')}")
                continue
            signature = (
                course.name,
                course.teacher,
                tuple(course.weeks),
                tuple(
                    (item.weekday, item.start_period, item.end_period, item.location)
                    for item in course.sections
                ),
            )
            if signature in seen:
                warnings.append(f"第 {row_number} 行与前面的课程重复，已去重")
                continue
            seen.add(signature)
            courses.append(course)
            row_added = True
        if not row_added:
            skipped += 1

    return TabularImportPreview(
        ok=bool(courses),
        source_name=filename,
        sheet_name=sheet_name,
        rows_read=max(0, len(data_rows)),
        skipped_rows=skipped,
        detected_columns=columns,
        headers=[str(header) for header in headers if str(header).strip()],
        courses=courses,
        warnings=warnings,
    )


def commit_tabular(db: Session, payload: TabularImportCommit) -> TabularImportCommitResult:
    existing = list(db.scalars(select(Course)).all())
    imported = list(payload.courses)
    skipped = 0
    warnings: list[str] = []

    if payload.strategy == "replace":
        db.execute(delete(Course))
    elif payload.strategy == "overwrite_names":
        names = {course.name for course in imported}
        for course in existing:
            if course.name in names:
                db.delete(course)
    elif payload.strategy == "skip_duplicates":
        signatures = {_course_signature(course) for course in existing}
        unique = []
        for course in imported:
            signature = _course_signature(course)
            if signature in signatures:
                skipped += 1
            else:
                signatures.add(signature)
                unique.append(course)
        imported = unique

    db.add_all([Course(**course.model_dump()) for course in imported])
    profile = None
    if payload.profile is not None:
        profile = _save_profile(db, payload.profile)
    db.commit()
    if not imported:
        warnings.append("没有新课程需要写入")
    return TabularImportCommitResult(
        ok=True,
        imported=len(imported),
        skipped=skipped,
        profile_id=profile.id if profile else None,
        warnings=warnings,
    )


def list_profiles(db: Session) -> list[ImportProfile]:
    return list(db.scalars(select(ImportProfile).order_by(ImportProfile.name)).all())


def delete_profile(db: Session, profile_id: str) -> bool:
    profile = db.get(ImportProfile, profile_id)
    if not profile:
        return False
    db.delete(profile)
    db.commit()
    return True


def _read_csv(data: bytes) -> tuple[list[list[Any]], None]:
    text = None
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise TabularImportError("CSV 编码无法识别")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel
    rows = [list(row) for row in csv.reader(io.StringIO(text), dialect)]
    return rows, None


def _read_xlsx(data: bytes) -> tuple[list[list[Any]], str]:
    _validate_xlsx_archive(data)
    workbook = openpyxl.load_workbook(
        io.BytesIO(data),
        read_only=True,
        data_only=True,
    )
    try:
        sheet = workbook.active
        rows = [list(row) for row in sheet.iter_rows(values_only=True)]
        return rows, sheet.title
    finally:
        workbook.close()


def _read_xls(data: bytes) -> tuple[list[list[Any]], str]:
    workbook = xlrd.open_workbook(file_contents=data, on_demand=True)
    try:
        sheet = workbook.sheet_by_index(0)
        rows = [
            [sheet.cell_value(row_index, column_index) for column_index in range(sheet.ncols)]
            for row_index in range(sheet.nrows)
        ]
        return rows, sheet.name
    finally:
        workbook.release_resources()


def _validate_xlsx_archive(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > 10_000:
                raise TabularImportError("Excel 压缩包文件数量异常")
            total_size = sum(info.file_size for info in infos)
            compressed_size = sum(max(1, info.compress_size) for info in infos)
            if total_size > MAX_UNCOMPRESSED_BYTES:
                raise TabularImportError("Excel 解压后超过 50MB")
            if total_size / compressed_size > 100:
                raise TabularImportError("Excel 压缩比异常，已拒绝解析")
    except zipfile.BadZipFile as exc:
        raise TabularImportError("无效的 .xlsx 文件") from exc


def _resolve_table(
    rows: list[list[Any]], configured_header_row: int
) -> tuple[list[str], list[list[Any]], int]:
    scan_limit = min(len(rows), MAX_HEADER_SCAN)
    if configured_header_row > 0:
        header_index = min(configured_header_row - 1, len(rows) - 1)
    else:
        best_index, best_score = 0, -1
        for index in range(scan_limit):
            score = sum(1 for cell in rows[index] if _normalize_header(cell) in _all_aliases())
            if score > best_score:
                best_index, best_score = index, score
        header_index = best_index
    headers = [str(cell).strip() if cell is not None else "" for cell in rows[header_index]]
    data_rows = [
        row
        for row in rows[header_index + 1 :]
        if any(cell is not None and str(cell).strip() for cell in row)
    ]
    return headers, data_rows, header_index


def _resolve_columns(
    headers: list[str], options: TabularOptions
) -> tuple[dict[str, str], list[str]]:
    normalized = {_normalize_header(header): header for header in headers if header}
    configured = {
        "course": options.course_column,
        "time": options.time_column,
        "location": options.location_column,
        "teacher": options.teacher_column,
    }
    resolved: dict[str, str] = {}
    warnings: list[str] = []
    for key, aliases in COLUMN_ALIASES.items():
        value = configured[key].strip()
        if value:
            resolved[key] = value
            if value not in headers:
                warnings.append(f"指定的 {value} 列不存在")
            continue
        for alias in aliases:
            if alias.lower() in normalized:
                resolved[key] = normalized[alias.lower()]
                break
    return resolved, warnings


def _parse_time_segment(
    text: str,
    *,
    total_weeks: int,
    odd_marker: str,
    even_marker: str,
    custom_pattern: re.Pattern[str] | None = None,
) -> tuple[int, list[int], list[int]] | None:
    if custom_pattern is not None:
        match = custom_pattern.match(text[:1000])
        if not match:
            return None
        weekday_text, period_text, week_text = match.groups()[:3]
        weekday_match = re.search(r"[一二三四五六日天]", weekday_text)
        if not weekday_match:
            return None
        periods = _parse_number_list(period_text)
        weeks = _parse_number_list(week_text)
        if not periods:
            return None
        if not weeks:
            weeks = list(range(1, total_weeks + 1))
        weekday = WEEKDAY_MAP[weekday_match.group(0)]
        return (
            weekday,
            periods,
            _apply_week_markers(
                text,
                weeks,
                odd_marker,
                even_marker,
            ),
        )

    weekday_match = re.search(r"(?:周|星期)\s*([一二三四五六日天])", text)
    if not weekday_match:
        return None
    period_match = re.search(
        r"(?:第\s*)?([\d一二三四五六七八九十]+(?:[、,，\-~—–至]\s*(?:第\s*)?[\d一二三四五六七八九十]+)*)\s*节",
        text,
    )
    if not period_match:
        return None
    periods = _parse_number_list(period_match.group(1))
    if not periods:
        return None
    after_periods = text[period_match.end() :]
    braces = re.search(r"\{([^}]*)\}", after_periods)
    week_expression = braces.group(1) if braces else after_periods
    weeks = _parse_number_list(week_expression)
    if not weeks:
        weeks = list(range(1, total_weeks + 1))

    weeks = _apply_week_markers(text, weeks, odd_marker, even_marker)
    if not weeks:
        return None
    return WEEKDAY_MAP[weekday_match.group(1)], periods, weeks


def _apply_week_markers(
    text: str,
    weeks: list[int],
    odd_marker: str,
    even_marker: str,
) -> list[int]:
    is_odd = bool(odd_marker and odd_marker in text)
    is_even = bool(even_marker and even_marker in text)
    if is_odd and not is_even:
        weeks = [week for week in weeks if week % 2 == 1]
    elif is_even and not is_odd:
        weeks = [week for week in weeks if week % 2 == 0]
    return sorted({week for week in weeks if 1 <= week <= 30})


def _parse_number_list(value: str) -> list[int]:
    numbers: list[int] = []
    for token in re.findall(
        r"[\d一二三四五六七八九十]+(?:\s*[-~—–至]\s*[\d一二三四五六七八九十]+)?",
        value,
    ):
        parts = re.split(r"\s*[-~—–至]\s*", token)
        try:
            converted = [_parse_number(part) for part in parts]
        except ValueError:
            continue
        if len(converted) == 2 and converted[0] <= converted[1]:
            numbers.extend(range(converted[0], converted[1] + 1))
        else:
            numbers.extend(converted)
    return sorted(set(numbers))


def _parse_number(value: str) -> int:
    value = value.strip()
    if value.isdigit():
        return int(value)
    digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if value == "十":
        return 10
    if value.startswith("十"):
        return 10 + digits[value[1]]
    if value.endswith("十"):
        return digits[value[0]] * 10
    if "十" in value:
        left, right = value.split("十", 1)
        return digits[left] * 10 + (digits[right] if right else 0)
    if value in digits:
        return digits[value]
    raise ValueError("unsupported number")


def _split_multi(text: Any, separator: str) -> list[str]:
    if text is None:
        return []
    separators = re.escape(separator)
    if separator == ";":
        separators = r"[;；]"
    return [item.strip() for item in re.split(separators, str(text)) if item.strip()]


def _campus_slots(location: str, rules: dict[str, list[TimeSlotItem]]) -> list[TimeSlotItem] | None:
    normalized_location = location.casefold()
    for keyword, slots in rules.items():
        if keyword and keyword.casefold() in normalized_location:
            return sorted(slots, key=lambda slot: slot.period)
    return None


def _derive_week_type(weeks: list[int], total_weeks: int) -> str:
    if weeks == list(range(1, total_weeks + 1)):
        return "all"
    if weeks == list(range(1, total_weeks + 1, 2)):
        return "odd"
    if weeks == list(range(2, total_weeks + 1, 2)):
        return "even"
    return "custom"


def _cell(row: list[Any], headers: list[str], column: str) -> str:
    if not column or column not in headers:
        return ""
    index = headers.index(column)
    if index >= len(row):
        return ""
    value = row[index]
    return "" if value is None else str(value).strip()


def _invalid(value: str) -> bool:
    return value.strip().lower() in INVALID_VALUES


def _normalize_header(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _all_aliases() -> set[str]:
    return {_normalize_header(alias) for aliases in COLUMN_ALIASES.values() for alias in aliases}


def _course_signature(course: Course | CourseCreate) -> tuple[Any, ...]:
    if isinstance(course, CourseCreate):
        sections = tuple(
            (
                item.weekday,
                item.start_period,
                item.end_period,
                item.location,
                item.custom_start,
                item.custom_end,
            )
            for item in course.sections
        )
    else:
        sections = tuple(
            (
                int(item.get("weekday", 1)),
                int(item.get("start_period", 1)),
                int(item.get("end_period", 1)),
                str(item.get("location", "")),
                item.get("custom_start"),
                item.get("custom_end"),
            )
            for item in course.sections
        )
    weeks = course.weeks
    return (
        course.name,
        course.teacher,
        tuple(weeks),
        sections,
    )


def _save_profile(db: Session, payload: ImportProfilePayload) -> ImportProfile:
    profile = db.scalar(select(ImportProfile).where(ImportProfile.name == payload.name))
    if profile is None:
        profile = ImportProfile(id=uuid4().hex, **payload.model_dump())
        db.add(profile)
    else:
        for key, value in payload.model_dump().items():
            setattr(profile, key, value)
    db.flush()
    return profile
