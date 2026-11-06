"""FastAPI entry point for Smart Timetable Pro."""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Annotated

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import PROJECT_ROOT, AIConfig, load_dotenv
from .constants import COLOR_PALETTE
from .database import build_session_factory, run_migrations, sqlite_url
from .models import AppMeta, Course, SelfPlan
from .schemas import (
    CourseCreate,
    CourseRead,
    CourseUpdate,
    ImportProfileRead,
    ImportRequest,
    ImportResult,
    JsonImportCommit,
    JsonImportRequest,
    JsonImportResult,
    PlanRequest,
    PlanResult,
    RescheduleRequest,
    RescheduleResult,
    ScheduleConfigRead,
    ScheduleConfigUpdate,
    SelfPlanCreate,
    SelfPlanRead,
    TabularImportCommit,
    TabularImportCommitResult,
    TabularImportPreview,
    TimeSlotItem,
)
from .services.ai import import_timetable, plan_study_time
from .services.ics import build_calendar_with_schedule
from .services.schedule import (
    commit_json_import,
    ensure_schedule_defaults,
    export_json,
    get_schedule_config,
    preview_json_import,
    reschedule_courses,
    save_schedule_config,
)
from .services.tabular_importer import (
    MAX_FILE_BYTES,
    TabularImportError,
    TabularOptions,
    commit_tabular,
    delete_profile,
    list_profiles,
    preview_tabular,
)

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("timetable")

# Some Windows installations map .js to text/plain, which browsers reject for ES modules.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("application/manifest+json", ".webmanifest")


def get_db(request: Request):
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


DbSession = Annotated[Session, Depends(get_db)]


def create_app(database_url: str | None = None, seed: bool = True) -> FastAPI:
    db_url = database_url or os.environ.get(
        "DATABASE_URL", sqlite_url(PROJECT_ROOT / "data" / "timetable.db")
    )
    engine, session_factory = build_session_factory(db_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        run_migrations(db_url, PROJECT_ROOT)
        if seed:
            _seed_database(session_factory)
        ensure_schedule_defaults(session_factory())
        app.state.engine = engine
        app.state.session_factory = session_factory
        log.info("Smart Timetable Pro started")
        yield
        engine.dispose()

    app = FastAPI(
        title="Smart Timetable Pro API",
        version="2.0.0",
        description="AI-assisted timetable import and study planning API.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_logging(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception(
                json.dumps(
                    {
                        "event": "request_failed",
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.url.path,
                    },
                    ensure_ascii=False,
                )
            )
            raise
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        response.headers["X-Request-ID"] = request_id
        log.info(
            json.dumps(
                {
                    "event": "request_complete",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": elapsed_ms,
                },
                ensure_ascii=False,
            )
        )
        return response

    @app.get("/api/health")
    def health(db: DbSession):
        db.execute(select(1))
        return {"ok": True, "version": app.version, "time": datetime.now().isoformat()}

    @app.get("/api/config")
    def get_config(db: DbSession):
        schedule = get_schedule_config(db)
        return {
            "time_slots": [slot.model_dump() for slot in schedule.time_slots],
            "color_palette": COLOR_PALETTE,
            "total_weeks": schedule.settings.total_weeks,
            "settings": schedule.settings.model_dump(mode="json"),
            "holidays": [item.model_dump() for item in schedule.holidays],
            "ai_enabled": AIConfig.from_env().enabled,
        }

    @app.get("/api/schedule-config", response_model=ScheduleConfigRead)
    def read_schedule_config(db: DbSession):
        return get_schedule_config(db)

    @app.put("/api/schedule-config", response_model=ScheduleConfigRead)
    def update_schedule_config(payload: ScheduleConfigUpdate, db: DbSession):
        courses = list(db.scalars(select(Course)).all())
        max_used_period = max(
            (
                int(section.get("end_period", 1))
                for course in courses
                for section in course.sections
            ),
            default=1,
        )
        if max_used_period > len(payload.time_slots):
            raise HTTPException(
                status_code=400,
                detail=f"当前课程最晚使用第 {max_used_period} 节，不能删除对应作息",
            )
        return save_schedule_config(db, payload)

    @app.get("/api/courses", response_model=list[CourseRead])
    def list_courses(db: DbSession):
        return db.scalars(select(Course).order_by(Course.created_at, Course.name)).all()

    @app.post("/api/courses", response_model=CourseRead, status_code=201)
    def create_course(payload: CourseCreate, db: DbSession):
        course = Course(**payload.model_dump())
        db.add(course)
        db.commit()
        db.refresh(course)
        return course

    @app.post("/api/courses/import", response_model=list[CourseRead], status_code=201)
    def import_courses(payload: list[CourseCreate], db: DbSession):
        if not payload:
            raise HTTPException(status_code=400, detail="at least one course is required")
        courses = [Course(**item.model_dump()) for item in payload]
        db.add_all(courses)
        db.commit()
        for course in courses:
            db.refresh(course)
        return courses

    @app.post("/api/courses/reschedule", response_model=RescheduleResult)
    def reschedule(payload: RescheduleRequest, db: DbSession):
        return reschedule_courses(db, payload)

    @app.put("/api/courses/{course_id}", response_model=CourseRead)
    def update_course(course_id: str, payload: CourseUpdate, db: DbSession):
        course = db.get(Course, course_id)
        if not course:
            raise HTTPException(status_code=404, detail="course not found")
        for key, value in payload.model_dump().items():
            setattr(course, key, value)
        db.commit()
        db.refresh(course)
        return course

    @app.delete("/api/courses/{course_id}", status_code=204)
    def delete_course(course_id: str, db: DbSession):
        course = db.get(Course, course_id)
        if not course:
            raise HTTPException(status_code=404, detail="course not found")
        db.delete(course)
        db.commit()
        return Response(status_code=204)

    @app.get("/api/self-plans", response_model=list[SelfPlanRead])
    def list_self_plans(db: DbSession):
        return db.scalars(select(SelfPlan).order_by(SelfPlan.date, SelfPlan.start_min)).all()

    @app.post("/api/self-plans", response_model=SelfPlanRead, status_code=201)
    def create_self_plan(payload: SelfPlanCreate, db: DbSession):
        plan = SelfPlan(**payload.model_dump())
        db.add(plan)
        db.commit()
        db.refresh(plan)
        return plan

    @app.delete("/api/self-plans/{plan_id}", status_code=204)
    def delete_self_plan(plan_id: str, db: DbSession):
        plan = db.get(SelfPlan, plan_id)
        if not plan:
            raise HTTPException(status_code=404, detail="self plan not found")
        db.delete(plan)
        db.commit()
        return Response(status_code=204)

    @app.post("/api/import/courses", response_model=ImportResult)
    def import_course_text(payload: ImportRequest):
        return import_timetable(payload, AIConfig.from_env())

    @app.post("/api/ai/plan", response_model=PlanResult)
    def create_ai_plan(payload: PlanRequest):
        return plan_study_time(payload, AIConfig.from_env())

    @app.post("/api/import/json/preview", response_model=JsonImportResult)
    def preview_json(payload: JsonImportRequest):
        return preview_json_import(payload.content)

    @app.post("/api/import/json/commit")
    def commit_json(payload: JsonImportCommit, db: DbSession):
        count = commit_json_import(
            db,
            payload.courses,
            payload.schedule,
            payload.replace_courses,
        )
        return {"ok": True, "imported": count}

    @app.post("/api/import/tabular/preview", response_model=TabularImportPreview)
    async def preview_tabular_import(
        db: DbSession,
        file: Annotated[UploadFile, File()],
        header_row: Annotated[int, Form()] = 0,
        course_column: Annotated[str, Form()] = "",
        time_column: Annotated[str, Form()] = "",
        location_column: Annotated[str, Form()] = "",
        teacher_column: Annotated[str, Form()] = "",
        multi_separator: Annotated[str, Form()] = ";",
        odd_marker: Annotated[str, Form()] = "单周",
        even_marker: Annotated[str, Form()] = "双周",
        time_regex: Annotated[str, Form()] = "",
        campus_rules_json: Annotated[str, Form()] = "{}",
    ):
        content = await file.read(MAX_FILE_BYTES + 1)
        if len(content) > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail="文件不能超过 5MB")
        schedule = get_schedule_config(db)
        try:
            raw_campus_rules = json.loads(campus_rules_json or "{}")
            if not isinstance(raw_campus_rules, dict):
                raise ValueError("campus_rules_json must be an object")
            campus_rules = {
                str(keyword): [TimeSlotItem.model_validate(slot) for slot in rules]
                for keyword, rules in raw_campus_rules.items()
                if isinstance(rules, list)
            }
            return preview_tabular(
                filename=file.filename or "upload.xlsx",
                data=content,
                options=TabularOptions(
                    header_row=max(0, min(header_row, 100)),
                    course_column=course_column.strip(),
                    time_column=time_column.strip(),
                    location_column=location_column.strip(),
                    teacher_column=teacher_column.strip(),
                    multi_separator=multi_separator[:10] or ";",
                    odd_marker=odd_marker[:10] or "单周",
                    even_marker=even_marker[:10] or "双周",
                    time_regex=time_regex[:500],
                    campus_rules=campus_rules,
                ),
                total_weeks=schedule.settings.total_weeks,
                slot_periods={slot.period for slot in schedule.time_slots},
            )
        except (TabularImportError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/import/tabular/commit", response_model=TabularImportCommitResult)
    def commit_tabular_import(payload: TabularImportCommit, db: DbSession):
        return commit_tabular(db, payload)

    @app.get("/api/import-profiles", response_model=list[ImportProfileRead])
    def get_import_profiles(db: DbSession):
        return list_profiles(db)

    @app.delete("/api/import-profiles/{profile_id}", status_code=204)
    def remove_import_profile(profile_id: str, db: DbSession):
        if not delete_profile(db, profile_id):
            raise HTTPException(status_code=404, detail="import profile not found")
        return Response(status_code=204)

    @app.get("/api/export/json")
    def export_timetable_json(db: DbSession):
        body = json.dumps(export_json(db), ensure_ascii=False, indent=2).encode("utf-8")
        return Response(
            content=body,
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="smart-timetable.json"'},
        )

    @app.get("/api/export/ics")
    def export_calendar(
        db: DbSession,
        semester_start: date | None = None,
        weeks: int | None = Query(default=None, ge=1, le=30),
    ):
        schedule = get_schedule_config(db)
        weeks = weeks or schedule.settings.total_weeks
        semester_start = semester_start or date.fromisoformat(schedule.settings.semester_start_date)
        courses = list(db.scalars(select(Course)).all())
        content = build_calendar_with_schedule(
            courses,
            semester_start,
            weeks,
            schedule.time_slots,
            {item.date for item in schedule.holidays},
            schedule.settings.first_day_of_week,
        )
        return Response(
            content=content.encode("utf-8"),
            media_type="text/calendar; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="smart-timetable.ics"'},
        )

    _mount_frontend(app)
    return app


def _seed_database(session_factory) -> None:
    with session_factory() as db:
        if db.get(AppMeta, "seeded"):
            return
        seed_file = Path(__file__).with_name("seed_courses.json")
        rows = json.loads(seed_file.read_text(encoding="utf-8"))
        for row in rows:
            db.add(
                Course(
                    name=row["name"],
                    teacher=row["teacher"],
                    color_index=row["color_index"],
                    week_type=row["week_type"],
                    weeks=[],
                    sections=[
                        {
                            "weekday": row["weekday"],
                            "start_period": row["start_period"],
                            "end_period": row["end_period"],
                            "location": row["location"],
                        }
                    ],
                )
            )
        db.add(AppMeta(key="seeded", value=datetime.now().isoformat()))
        db.commit()
        log.info("Seeded %d demo courses", len(rows))


def _mount_frontend(app: FastAPI) -> None:
    dist = PROJECT_ROOT / "frontend" / "dist"
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_frontend(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        if dist.is_dir():
            candidate = (dist / full_path).resolve()
            if candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(
                    candidate,
                    headers={"Cache-Control": "no-cache"}
                    if candidate.suffix.lower() == ".html"
                    else None,
                )
            index = dist / "index.html"
            if index.is_file():
                return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return {
            "message": "Frontend build not found.",
            "next": "cd frontend && npm install && npm run build",
            "api_docs": "/docs",
        }


app = create_app()
