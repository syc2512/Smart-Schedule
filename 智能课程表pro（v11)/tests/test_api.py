from __future__ import annotations

import json

from fastapi.testclient import TestClient

from server.app.main import create_app


def make_client(path, seed=True):
    app = create_app(f"sqlite:///{path.as_posix()}", seed=seed)
    return TestClient(app)


def test_seeded_courses_and_persistence(tmp_path):
    db_url = f"sqlite:///{(tmp_path / 'persistent.db').as_posix()}"
    with TestClient(create_app(db_url, seed=True)) as client:
        initial = client.get("/api/courses")
        assert initial.status_code == 200
        assert len(initial.json()) == 22

        payload = {
            "name": "人工智能导论",
            "teacher": "测试教师",
            "color_index": 5,
            "week_type": "odd",
            "weeks": [],
            "sections": [
                {
                    "weekday": 3,
                    "start_period": 7,
                    "end_period": 8,
                    "location": "实验楼-301",
                }
            ],
        }
        created = client.post("/api/courses", json=payload)
        assert created.status_code == 201
        course_id = created.json()["id"]

    with TestClient(create_app(db_url, seed=True)) as client:
        courses = client.get("/api/courses").json()
        assert any(course["id"] == course_id for course in courses)
        assert len(courses) == 23

        updated = client.put(
            f"/api/courses/{course_id}",
            json={**payload, "name": "机器学习导论"},
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "机器学习导论"

        assert client.delete(f"/api/courses/{course_id}").status_code == 204
        assert len(client.get("/api/courses").json()) == 22


def test_rejects_invalid_period_order(tmp_path):
    with make_client(tmp_path / "invalid.db") as client:
        response = client.post(
            "/api/courses",
            json={
                "name": "非法课程",
                "sections": [
                    {
                        "weekday": 1,
                        "start_period": 4,
                        "end_period": 2,
                        "location": "",
                    }
                ],
            },
        )
        assert response.status_code == 422


def test_text_import_uses_local_fallback_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("TIMETABLE_AI_API_KEY", raising=False)
    with make_client(tmp_path / "import.db") as client:
        response = client.post(
            "/api/import/courses",
            json={
                "text": "高等数学 周一 第1-2节 1-16周 张老师 教三-201\n"
                "大学英语 周二 第3-4节 双周 李老师 外语楼-305"
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["degraded"] is True
        assert len(body["courses"]) == 2
        assert body["courses"][0]["sections"][0]["location"] == "教三-201"


def test_planner_fallback_and_ics(tmp_path, monkeypatch):
    monkeypatch.delenv("TIMETABLE_AI_API_KEY", raising=False)
    with make_client(tmp_path / "planner.db") as client:
        plan = client.post(
            "/api/ai/plan",
            json={
                "date": "2026-11-05",
                "weekday": 4,
                "parity": "odd",
                "free_blocks": [[1080, 1200]],
                "tasks": ["复习高数"],
                "courses": ["操作系统"],
            },
        )
        assert plan.status_code == 200
        assert plan.json()["degraded"] is True
        assert "复习高数" in plan.json()["plan"]

        calendar = client.get("/api/export/ics?semester_start=2026-09-07&weeks=18")
        assert calendar.status_code == 200
        text = calendar.text
        assert "BEGIN:VCALENDAR" in text
        assert "DTSTAMP:" in text
        assert "DTSTART;TZID=Asia/Shanghai:" in text
        assert "BEGIN:VEVENT" in text


def test_schedule_config_custom_times_and_holiday(tmp_path):
    with make_client(tmp_path / "config.db", seed=False) as client:
        schedule = client.get("/api/schedule-config").json()
        schedule["settings"].update(
            {
                "semester_start_date": "2026-09-07",
                "total_weeks": 16,
                "first_day_of_week": 1,
                "display_mode": "24h",
                "dark_mode": True,
            }
        )
        schedule["time_slots"] = [
            {"period": 1, "start": "08:00", "end": "08:45", "alias": ""},
            {"period": 2, "start": "09:00", "end": "09:45", "alias": ""},
        ]
        schedule["holidays"] = [{"date": "2026-09-07", "name": "校庆"}]
        saved = client.put("/api/schedule-config", json=schedule)
        assert saved.status_code == 200
        assert saved.json()["settings"]["display_mode"] == "24h"
        assert saved.json()["holidays"][0]["name"] == "校庆"

        course = client.post(
            "/api/courses",
            json={
                "name": "晨间实验",
                "teacher": "王老师",
                "color_index": 1,
                "week_type": "all",
                "weeks": [],
                "sections": [
                    {
                        "weekday": 1,
                        "start_period": 1,
                        "end_period": 2,
                        "location": "实验楼",
                        "custom_start": "08:10",
                        "custom_end": "09:20",
                    }
                ],
            },
        )
        assert course.status_code == 201
        calendar = client.get("/api/export/ics").text
        assert "20260907T081000" not in calendar

        schedule["holidays"] = []
        assert client.put("/api/schedule-config", json=schedule).status_code == 200
        calendar = client.get("/api/export/ics").text
        assert "晨间实验" in calendar
        assert "DTSTART;TZID=Asia/Shanghai:20260907T081000" in calendar


def test_json_import_supports_native_and_shiguang_formats(tmp_path):
    with make_client(tmp_path / "json.db") as client:
        native = client.get("/api/export/json")
        assert native.status_code == 200
        preview = client.post(
            "/api/import/json/preview",
            json={"content": native.text},
        )
        assert preview.status_code == 200
        assert preview.json()["source"] == "smart-timetable-pro"
        assert len(preview.json()["courses"]) == 22

        shiguang = {
            "courses": [
                {
                    "name": "编译原理",
                    "teacher": "陈老师",
                    "position": "信息楼-301",
                    "day": 3,
                    "startSection": 5,
                    "endSection": 6,
                    "weeks": [1, 3, 5],
                }
            ],
            "timeSlots": [
                {"number": 1, "startTime": "08:00", "endTime": "08:45"},
                {"number": 2, "startTime": "08:50", "endTime": "09:35"},
            ],
            "config": {
                "semesterStartDate": "2026-09-07",
                "semesterTotalWeeks": 18,
                "firstDayOfWeek": 1,
            },
        }
        preview = client.post(
            "/api/import/json/preview",
            json={"content": json.dumps(shiguang, ensure_ascii=False)},
        )
        assert preview.status_code == 200
        body = preview.json()
        assert body["source"] == "shiguangschedule"
        assert body["courses"][0]["sections"][0]["weekday"] == 3
        assert body["schedule"]["time_slots"][0]["start"] == "08:00"


def test_reschedule_merge_overwrite_and_exchange(tmp_path):
    def payload(name, day):
        return {
            "name": name,
            "teacher": "",
            "color_index": 0,
            "week_type": "custom",
            "weeks": [1],
            "sections": [
                {
                    "weekday": day,
                    "start_period": 1,
                    "end_period": 2,
                    "location": "",
                }
            ],
        }

    with make_client(tmp_path / "tweak.db", seed=False) as client:
        client.post("/api/courses", json=payload("源课程", 1))
        target = client.post("/api/courses", json=payload("目标课程", 2)).json()

        merged = client.post(
            "/api/courses/reschedule",
            json={
                "mode": "merge",
                "source_week": 1,
                "source_day": 1,
                "target_week": 2,
                "target_day": 3,
            },
        )
        assert merged.status_code == 200
        assert merged.json()["moved"] == 1
        courses = client.get("/api/courses").json()
        moved = next(item for item in courses if item["name"] == "源课程")
        assert moved["weeks"] == [2]
        assert moved["sections"][0]["weekday"] == 3
        assert any(item["id"] == target["id"] for item in courses)

        client.delete(f"/api/courses/{target['id']}")
        client.post("/api/courses", json=payload("第二轮源", 4))
        second_target = client.post("/api/courses", json=payload("第二轮目标", 5)).json()
        overwritten = client.post(
            "/api/courses/reschedule",
            json={
                "mode": "overwrite",
                "source_week": 1,
                "source_day": 4,
                "target_week": 1,
                "target_day": 5,
            },
        )
        assert overwritten.status_code == 200
        remaining = client.get("/api/courses").json()
        assert not any(item["id"] == second_target["id"] for item in remaining)
        assert any(item["name"] == "第二轮源" for item in remaining)

        client.post("/api/courses", json=payload("左", 6))
        client.post("/api/courses", json=payload("右", 7))
        exchanged = client.post(
            "/api/courses/reschedule",
            json={
                "mode": "exchange",
                "source_week": 1,
                "source_day": 6,
                "target_week": 1,
                "target_day": 7,
            },
        )
        assert exchanged.status_code == 200
        after_exchange = client.get("/api/courses").json()
        left_moved = next(item for item in after_exchange if item["name"] == "左")
        right_moved = next(item for item in after_exchange if item["name"] == "右")
        assert left_moved["sections"][0]["weekday"] == 7
        assert right_moved["sections"][0]["weekday"] == 6
