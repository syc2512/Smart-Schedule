from server.app.services.importer import (
    courses_from_ai_payload,
    extract_json_object,
    parse_text_courses,
)


def test_extracts_json_from_markdown_fence():
    payload = extract_json_object('```json\n{"courses": [], "warnings": []}\n```')
    assert payload["courses"] == []


def test_ai_payload_is_validated():
    courses, warnings = courses_from_ai_payload(
        {
            "courses": [
                {
                    "name": "数据结构",
                    "week_type": "odd",
                    "weeks": [],
                    "sections": [
                        {
                            "weekday": 2,
                            "start_period": 3,
                            "end_period": 4,
                            "location": "计算机楼",
                        }
                    ],
                }
            ],
            "warnings": [],
        }
    )
    assert len(courses) == 1
    assert courses[0].week_type == "odd"
    assert warnings == []


def test_parser_skips_rows_without_day_or_period():
    courses, warnings = parse_text_courses("课程表\n高等数学 张老师\n体育 周三 第9-10节 体育馆")
    assert len(courses) == 1
    assert courses[0].name == "体育"
    assert not any("第 1 行" in warning for warning in warnings)
