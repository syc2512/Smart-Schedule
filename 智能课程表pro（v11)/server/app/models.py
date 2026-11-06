"""SQLAlchemy persistence models."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: uuid4().hex)
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    teacher: Mapped[str] = mapped_column(String(30), default="")
    color_index: Mapped[int] = mapped_column(Integer, default=0)
    week_type: Mapped[str] = mapped_column(String(10), default="all")
    weeks: Mapped[list[int]] = mapped_column(JSON, default=list)
    sections: Mapped[list[dict]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SelfPlan(Base):
    __tablename__ = "self_plans"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: uuid4().hex)
    title: Mapped[str] = mapped_column(String(40), nullable=False)
    date: Mapped[str] = mapped_column(String(10), nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    start_min: Mapped[int] = mapped_column(Integer, nullable=False)
    end_min: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str] = mapped_column(String(400), default="")
    category: Mapped[str] = mapped_column(String(20), default="study")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AppMeta(Base):
    __tablename__ = "app_meta"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(String(200), default="")


class TimetableSettings(Base):
    __tablename__ = "timetable_settings"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default="default")
    name: Mapped[str] = mapped_column(String(60), default="我的课表")
    semester_start_date: Mapped[str] = mapped_column(String(10), default="")
    total_weeks: Mapped[int] = mapped_column(Integer, default=18)
    first_day_of_week: Mapped[int] = mapped_column(Integer, default=1)
    show_weekends: Mapped[bool] = mapped_column(Boolean, default=True)
    display_mode: Mapped[str] = mapped_column(String(20), default="sections")
    density: Mapped[str] = mapped_column(String(20), default="comfortable")
    background_theme: Mapped[str] = mapped_column(String(20), default="paper")
    dark_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    card_opacity: Mapped[float] = mapped_column(Float, default=1.0)
    hide_teacher: Mapped[bool] = mapped_column(Boolean, default=False)
    hide_location: Mapped[bool] = mapped_column(Boolean, default=False)
    font_scale: Mapped[float] = mapped_column(Float, default=1.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ScheduleTimeSlot(Base):
    __tablename__ = "schedule_time_slots"

    period: Mapped[int] = mapped_column(Integer, primary_key=True)
    start: Mapped[str] = mapped_column(String(5), nullable=False)
    end: Mapped[str] = mapped_column(String(5), nullable=False)
    alias: Mapped[str] = mapped_column(String(30), default="")


class Holiday(Base):
    __tablename__ = "holidays"

    date: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(40), default="")


class ImportProfile(Base):
    __tablename__ = "import_profiles"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: uuid4().hex)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    header_row: Mapped[int] = mapped_column(Integer, default=0)
    course_column: Mapped[str] = mapped_column(String(80), default="")
    time_column: Mapped[str] = mapped_column(String(80), default="")
    location_column: Mapped[str] = mapped_column(String(80), default="")
    teacher_column: Mapped[str] = mapped_column(String(80), default="")
    multi_separator: Mapped[str] = mapped_column(String(10), default=";")
    odd_marker: Mapped[str] = mapped_column(String(10), default="单周")
    even_marker: Mapped[str] = mapped_column(String(10), default="双周")
    time_regex: Mapped[str] = mapped_column(String(500), default="")
    campus_rules: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
