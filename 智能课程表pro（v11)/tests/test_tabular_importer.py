from __future__ import annotations

import io
import json

from fastapi.testclient import TestClient
from openpyxl import Workbook

from server.app.main import create_app


def make_client(path):
    return TestClient(create_app(f"sqlite:///{path.as_posix()}", seed=False))


def worksheet_bytes(rows: list[list[str]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "课表"
    for row in rows:
        sheet.append(row)
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_xlsx_preview_parses_ranges_odd_even_and_locations(tmp_path):
    data = worksheet_bytes(
        [
            ["某学院课程表"],
            ["课程名称", "上课时间", "上课地点", "教师名称"],
            ["高等数学", "周一第1、2节{第4-5,8-19周}", "教三-201", "张老师"],
            [
                "大学英语",
                "周二第3、4节{第1-16周(单周)};周三第5-6节{第7周}",
                "外语楼-305;语音室",
                "李老师",
            ],
            ["体育", "周四第13-14节{第2周}", "体育馆", "赵老师"],
        ]
    )
    with make_client(tmp_path / "table.db") as client:
        response = client.post(
            "/api/import/tabular/preview",
            files={
                "file": (
                    "课表.xlsx",
                    data,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
            data={"header_row": "0"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["sheet_name"] == "课表"
        assert body["detected_columns"]["course"] == "课程名称"
        assert body["detected_columns"]["time"] == "上课时间"
        assert len(body["courses"]) == 3

        english = [course for course in body["courses"] if course["name"] == "大学英语"]
        assert len(english) == 2
        odd_weeks = next(course["weeks"] for course in english if course["weeks"][0] == 1)
        assert odd_weeks == list(range(1, 17, 2))
        assert any(course["sections"][0]["location"] == "语音室" for course in english)
        assert any("节次 [13, 14]" in warning for warning in body["warnings"])


def test_csv_with_explicit_mapping_and_commit_strategies(tmp_path):
    csv_data = (
        "科目,时间,教室,老师\n"
        "编译原理,周三 5-6节 1-4周,信息楼-301,陈老师\n"
        "编译原理,周三 5-6节 1-4周,信息楼-301,陈老师\n"
    ).encode("utf-8-sig")
    with make_client(tmp_path / "csv.db") as client:
        preview = client.post(
            "/api/import/tabular/preview",
            files={"file": ("课表.csv", csv_data, "text/csv")},
            data={
                "header_row": "1",
                "course_column": "科目",
                "time_column": "时间",
                "location_column": "教室",
                "teacher_column": "老师",
            },
        )
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert body["ok"] is True
        assert len(body["courses"]) == 1
        assert any("重复" in warning for warning in body["warnings"])

        committed = client.post(
            "/api/import/tabular/commit",
            json={
                "courses": body["courses"],
                "strategy": "append",
                "profile": {
                    "name": "测试教务模板",
                    "header_row": 1,
                    "course_column": "科目",
                    "time_column": "时间",
                    "location_column": "教室",
                    "teacher_column": "老师",
                    "multi_separator": ";",
                    "odd_marker": "单周",
                    "even_marker": "双周",
                },
            },
        )
        assert committed.status_code == 200
        assert committed.json()["imported"] == 1
        profiles = client.get("/api/import-profiles").json()
        assert profiles[0]["name"] == "测试教务模板"

        skipped = client.post(
            "/api/import/tabular/commit",
            json={"courses": body["courses"], "strategy": "skip_duplicates"},
        )
        assert skipped.status_code == 200
        assert skipped.json()["imported"] == 0
        assert skipped.json()["skipped"] == 1


def test_campus_specific_time_slots_are_applied(tmp_path):
    csv_data = (
        "课程名称,上课时间,上课地点,教师名称\n校区实验,周一第13节{第2周},东校区实验楼,王老师\n"
    ).encode()
    campus_rules = {"东校区": [{"period": 13, "start": "17:30", "end": "18:15", "alias": ""}]}
    with make_client(tmp_path / "campus.db") as client:
        response = client.post(
            "/api/import/tabular/preview",
            files={"file": ("校区.csv", csv_data, "text/csv")},
            data={
                "header_row": "1",
                "campus_rules_json": json.dumps(campus_rules, ensure_ascii=False),
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"] is True
        section = body["courses"][0]["sections"][0]
        assert section["custom_start"] == "17:30"
        assert section["custom_end"] == "18:15"


def test_custom_time_regex_is_saved_and_used(tmp_path):
    csv_data = (
        "课程名称,上课时间,上课地点,教师名称\n"
        '"形式语言","星期一[5,6][1-4周]",信息楼-201,周老师\n'
    ).encode()
    pattern = r"星期([一二三四五六日天])\[([\d,]+)\]\[(.+?)\]"
    with make_client(tmp_path / "regex.db") as client:
        response = client.post(
            "/api/import/tabular/preview",
            files={"file": ("正则.csv", csv_data, "text/csv")},
            data={
                "header_row": "1",
                "time_regex": pattern,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"] is True
        assert body["courses"][0]["weeks"] == [1, 2, 3, 4]
        assert body["courses"][0]["sections"][0]["weekday"] == 1

        committed = client.post(
            "/api/import/tabular/commit",
            json={
                "courses": body["courses"],
                "strategy": "append",
                "profile": {
                    "name": "正则模板",
                    "header_row": 1,
                    "course_column": "",
                    "time_column": "",
                    "location_column": "",
                    "teacher_column": "",
                    "multi_separator": ";",
                    "odd_marker": "单周",
                    "even_marker": "双周",
                    "time_regex": pattern,
                    "campus_rules": {},
                },
            },
        )
        assert committed.status_code == 200
        profile = client.get("/api/import-profiles").json()[0]
        assert profile["time_regex"] == pattern
