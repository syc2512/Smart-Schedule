"""API request and response contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

WeekType = Literal["all", "odd", "even", "custom"]


class Section(BaseModel):
    weekday: int = Field(ge=1, le=7)
    start_period: int = Field(ge=1, le=30)
    end_period: int = Field(ge=1, le=30)
    location: str = Field(default="", max_length=40)
    custom_start: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    custom_end: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")

    @model_validator(mode="after")
    def validate_section(self):
        if self.start_period > self.end_period:
            raise ValueError("start_period must not be after end_period")
        if bool(self.custom_start) != bool(self.custom_end):
            raise ValueError("custom_start and custom_end must be provided together")
        if self.custom_start and self.custom_end and self.custom_start >= self.custom_end:
            raise ValueError("custom_start must be before custom_end")
        return self


class CourseBase(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    teacher: str = Field(default="", max_length=30)
    color_index: int = Field(default=0, ge=0, le=11)
    week_type: WeekType = "all"
    weeks: list[int] = Field(default_factory=list, max_length=30)
    sections: list[Section] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def validate_weeks(self):
        if any(week < 1 or week > 30 for week in self.weeks):
            raise ValueError("weeks must be between 1 and 30")
        self.weeks = sorted(set(self.weeks))
        return self


class CourseCreate(CourseBase):
    pass


class CourseUpdate(CourseBase):
    pass


class CourseRead(CourseBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class SelfPlanCreate(BaseModel):
    title: str = Field(min_length=1, max_length=40)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    weekday: int = Field(ge=1, le=7)
    start_min: int = Field(ge=0, le=1439)
    end_min: int = Field(ge=1, le=1440)
    notes: str = Field(default="", max_length=400)
    category: Literal["personal", "kg", "kaoyan", "study"] = "study"

    @field_validator("date")
    @classmethod
    def validate_real_date(cls, value: str) -> str:
        return _validate_real_date(value)

    @model_validator(mode="after")
    def validate_time_order(self):
        if self.start_min >= self.end_min:
            raise ValueError("start_min must be before end_min")
        return self


class SelfPlanRead(SelfPlanCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime


class ImportRequest(BaseModel):
    text: str = Field(default="", max_length=20_000)
    image_data_url: str = Field(default="", max_length=9_000_000)

    @model_validator(mode="after")
    def validate_input(self):
        if not self.text.strip() and not self.image_data_url:
            raise ValueError("text or image_data_url is required")
        if self.image_data_url and not self.image_data_url.startswith("data:image/"):
            raise ValueError("image_data_url must be an image data URL")
        return self


class ImportResult(BaseModel):
    ok: bool
    degraded: bool = False
    reason: str | None = None
    model: str | None = None
    courses: list[CourseCreate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PlanRequest(BaseModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    weekday: int = Field(ge=1, le=7)
    parity: Literal["odd", "even"]
    free_blocks: list[tuple[int, int]] = Field(min_length=1, max_length=20)
    tasks: list[str] = Field(min_length=1, max_length=8)
    courses: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_blocks_and_tasks(self):
        for start, end in self.free_blocks:
            if start < 0 or end > 1440 or start >= end:
                raise ValueError("invalid free block")
        self.tasks = [task.strip()[:40] for task in self.tasks if task.strip()]
        if not self.tasks:
            raise ValueError("at least one task is required")
        return self


class PlanResult(BaseModel):
    ok: bool
    degraded: bool = False
    reason: str | None = None
    model: str | None = None
    plan: str


class TimeSlotItem(BaseModel):
    period: int = Field(ge=1, le=30)
    start: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    alias: str = Field(default="", max_length=30)

    @model_validator(mode="after")
    def validate_times(self):
        if self.start >= self.end:
            raise ValueError("start must be before end")
        return self


class HolidayItem(BaseModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    name: str = Field(default="", max_length=40)

    @field_validator("date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        return _validate_real_date(value)


class TimetableSettingsPayload(BaseModel):
    name: str = Field(default="我的课表", min_length=1, max_length=60)
    semester_start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    total_weeks: int = Field(default=18, ge=1, le=30)
    first_day_of_week: int = Field(default=1, ge=1, le=7)
    show_weekends: bool = True
    display_mode: Literal["sections", "24h"] = "sections"
    density: Literal["compact", "comfortable"] = "comfortable"
    background_theme: Literal["paper", "mint", "warm", "slate"] = "paper"
    dark_mode: bool = False
    card_opacity: float = Field(default=1.0, ge=0.55, le=1.0)
    hide_teacher: bool = False
    hide_location: bool = False
    font_scale: float = Field(default=1.0, ge=0.8, le=1.2)

    @field_validator("semester_start_date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        return _validate_real_date(value)


class ScheduleConfigUpdate(BaseModel):
    settings: TimetableSettingsPayload
    time_slots: list[TimeSlotItem] = Field(min_length=1, max_length=30)
    holidays: list[HolidayItem] = Field(default_factory=list, max_length=150)

    @model_validator(mode="after")
    def validate_slots(self):
        periods = [slot.period for slot in self.time_slots]
        if periods != list(range(1, len(periods) + 1)):
            raise ValueError("time slot periods must be continuous and start at 1")
        for previous, current in zip(self.time_slots, self.time_slots[1:], strict=False):
            if previous.end > current.start:
                raise ValueError("time slots must not overlap")
        holiday_dates = [item.date for item in self.holidays]
        if len(holiday_dates) != len(set(holiday_dates)):
            raise ValueError("holiday dates must be unique")
        return self


class ScheduleConfigRead(ScheduleConfigUpdate):
    pass


class JsonImportRequest(BaseModel):
    content: str = Field(min_length=2, max_length=2_000_000)


class JsonImportResult(BaseModel):
    ok: bool
    source: Literal["smart-timetable-pro", "shiguangschedule", "unknown"]
    courses: list[CourseCreate] = Field(default_factory=list)
    schedule: ScheduleConfigUpdate | None = None
    warnings: list[str] = Field(default_factory=list)


class JsonImportCommit(BaseModel):
    courses: list[CourseCreate] = Field(min_length=1)
    schedule: ScheduleConfigUpdate | None = None
    replace_courses: bool = False


class ImportProfilePayload(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    header_row: int = Field(default=0, ge=0, le=100)
    course_column: str = Field(default="", max_length=80)
    time_column: str = Field(default="", max_length=80)
    location_column: str = Field(default="", max_length=80)
    teacher_column: str = Field(default="", max_length=80)
    multi_separator: str = Field(default=";", min_length=1, max_length=10)
    odd_marker: str = Field(default="单周", min_length=1, max_length=10)
    even_marker: str = Field(default="双周", min_length=1, max_length=10)
    time_regex: str = Field(default="", max_length=500)
    campus_rules: dict[str, list[TimeSlotItem]] = Field(default_factory=dict)


class ImportProfileRead(ImportProfilePayload):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class TabularImportPreview(BaseModel):
    ok: bool
    source_name: str
    sheet_name: str | None = None
    rows_read: int = 0
    skipped_rows: int = 0
    detected_columns: dict[str, str] = Field(default_factory=dict)
    headers: list[str] = Field(default_factory=list)
    courses: list[CourseCreate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TabularImportCommit(BaseModel):
    courses: list[CourseCreate] = Field(min_length=1)
    strategy: Literal["append", "skip_duplicates", "overwrite_names", "replace"] = "append"
    profile: ImportProfilePayload | None = None


class TabularImportCommitResult(BaseModel):
    ok: bool
    imported: int
    skipped: int = 0
    profile_id: str | None = None
    warnings: list[str] = Field(default_factory=list)


class RescheduleRequest(BaseModel):
    mode: Literal["merge", "overwrite", "exchange"]
    source_week: int = Field(ge=1, le=30)
    source_day: int = Field(ge=1, le=7)
    target_week: int = Field(ge=1, le=30)
    target_day: int = Field(ge=1, le=7)

    @model_validator(mode="after")
    def validate_location(self):
        if self.source_week == self.target_week and self.source_day == self.target_day:
            raise ValueError("source and target must be different")
        return self


class RescheduleResult(BaseModel):
    ok: bool
    moved: int
    removed_target_occurrences: int
    warnings: list[str] = Field(default_factory=list)


def _validate_real_date(value: str) -> str:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("invalid calendar date") from exc
    return value
