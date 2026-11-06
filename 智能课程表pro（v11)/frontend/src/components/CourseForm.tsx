import { useMemo, useState } from "react";
import type { AppConfig, Course, CourseDraft, CourseSection, WeekType } from "../types";
import { WEEKDAYS, courseConflicts } from "../utils";
import { Icon } from "./Icon";
import { Modal } from "./Modal";

const emptySection = (): CourseSection => ({
  weekday: 1,
  start_period: 1,
  end_period: 2,
  location: "",
});

export function CourseForm({
  course,
  courses,
  config,
  onClose,
  onSave,
  onDelete,
}: {
  course: Course | null;
  courses: Course[];
  config: AppConfig;
  onClose: () => void;
  onSave: (draft: CourseDraft) => Promise<void>;
  onDelete?: (course: Course) => Promise<void>;
}) {
  const [draft, setDraft] = useState<CourseDraft>(() => ({
    name: course?.name ?? "",
    teacher: course?.teacher ?? "",
    color_index: course?.color_index ?? nextColor(courses),
    week_type: course?.week_type ?? "all",
    weeks: course?.weeks ?? [],
    sections: course?.sections?.length ? structuredClone(course.sections) : [emptySection()],
  }));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const previewCourse = useMemo<Course>(
    () => ({
      ...draft,
      id: course?.id ?? "preview",
      created_at: "",
      updated_at: "",
    }),
    [course?.id, draft],
  );
  const conflicts = courseConflicts(
    previewCourse,
    courses.filter((item) => item.id !== course?.id),
  );

  const updateSection = (index: number, patch: Partial<CourseSection>) => {
    setDraft((current) => ({
      ...current,
      sections: current.sections.map((section, sectionIndex) =>
        sectionIndex === index ? { ...section, ...patch } : section,
      ),
    }));
  };

  const submit = async () => {
    setError("");
    if (!draft.name.trim()) {
      setError("请填写课程名称");
      return;
    }
    if (draft.sections.some((section) => section.start_period > section.end_period)) {
      setError("结束节次不能早于开始节次");
      return;
    }
    if (
      draft.sections.some(
        (section) =>
          Boolean(section.custom_start) !== Boolean(section.custom_end) ||
          (section.custom_start &&
            section.custom_end &&
            section.custom_start >= section.custom_end),
      )
    ) {
      setError("自定义时间的开始时间必须早于结束时间");
      return;
    }
    if (draft.week_type === "custom" && draft.weeks.length === 0) {
      setError("自定义周次至少选择一周");
      return;
    }
    setBusy(true);
    try {
      await onSave({
        ...draft,
        name: draft.name.trim(),
        teacher: draft.teacher.trim(),
        sections: draft.sections.map((section) => ({
          ...section,
          location: section.location.trim(),
        })),
      });
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "保存失败");
    } finally {
      setBusy(false);
    }
  };

  const changeWeekType = (weekType: WeekType) => {
    setDraft((current) => ({
      ...current,
      week_type: weekType,
      weeks:
        weekType === "custom"
          ? current.weeks.length
            ? current.weeks
            : [1, 2, 3]
          : [],
    }));
  };

  return (
    <Modal title={course ? "编辑课程" : "添加课程"} eyebrow="课程信息" onClose={onClose} wide>
      <div className="form-grid">
        <label className="field">
          <span>
            课程名称 <b className="required">*</b>
          </span>
          <input
            autoFocus
            maxLength={40}
            value={draft.name}
            onChange={(event) => setDraft({ ...draft, name: event.target.value })}
            placeholder="例如：高等数学"
          />
        </label>
        <label className="field">
          <span>任课教师</span>
          <input
            maxLength={30}
            value={draft.teacher}
            onChange={(event) => setDraft({ ...draft, teacher: event.target.value })}
            placeholder="例如：张老师"
          />
        </label>
      </div>

      <div className="field">
        <span>上课周次</span>
        <div className="segmented-control">
          {[
            ["all", "每周"],
            ["odd", "单周"],
            ["even", "双周"],
            ["custom", "自定义"],
          ].map(([value, label]) => (
            <button
              className={draft.week_type === value ? "active" : ""}
              key={value}
              type="button"
              onClick={() => changeWeekType(value as WeekType)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {draft.week_type === "custom" && (
        <div className="week-picker" aria-label="自定义周次">
          {Array.from({ length: config.total_weeks }, (_, index) => index + 1).map((week) => (
            <button
              className={draft.weeks.includes(week) ? "selected" : ""}
              key={week}
              type="button"
              onClick={() =>
                setDraft({
                  ...draft,
                  weeks: draft.weeks.includes(week)
                    ? draft.weeks.filter((item) => item !== week)
                    : [...draft.weeks, week].sort((a, b) => a - b),
                })
              }
            >
              {week}
            </button>
          ))}
        </div>
      )}

      <div className="section-list">
        <div className="section-title-row">
          <div>
            <p className="eyebrow">时间段</p>
            <h3>课程安排</h3>
          </div>
          <button
            className="button secondary small"
            type="button"
            onClick={() => setDraft({ ...draft, sections: [...draft.sections, emptySection()] })}
            disabled={draft.sections.length >= 6}
          >
            <Icon name="plus" size={15} />
            添加时间段
          </button>
        </div>
        {draft.sections.map((section, index) => (
          <div className="section-row" key={`section-${index}`}>
            <div className="section-time-toggle">
              <span>时间方式</span>
              <div className="segmented-control compact">
                <button
                  className={!section.custom_start ? "active" : ""}
                  type="button"
                  onClick={() =>
                    updateSection(index, { custom_start: null, custom_end: null })
                  }
                >
                  节次
                </button>
                <button
                  className={section.custom_start ? "active" : ""}
                  type="button"
                  onClick={() => {
                    const startSlot =
                      config.time_slots.find((slot) => slot.period === section.start_period) ??
                      config.time_slots[0];
                    const endSlot =
                      config.time_slots.find((slot) => slot.period === section.end_period) ??
                      startSlot;
                    updateSection(index, {
                      custom_start: startSlot?.start ?? "08:00",
                      custom_end: endSlot?.end ?? "09:40",
                    });
                  }}
                >
                  精确时间
                </button>
              </div>
            </div>
            <label className="field">
              <span>星期</span>
              <select
                value={section.weekday}
                onChange={(event) => updateSection(index, { weekday: Number(event.target.value) })}
              >
                {WEEKDAYS.map((day, dayIndex) => (
                  <option value={dayIndex + 1} key={day}>
                    {day}
                  </option>
                ))}
              </select>
            </label>
            {section.custom_start ? (
              <>
                <label className="field">
                  <span>开始时间</span>
                  <input
                    type="time"
                    value={section.custom_start}
                    onChange={(event) =>
                      updateSection(index, { custom_start: event.target.value })
                    }
                  />
                </label>
                <label className="field">
                  <span>结束时间</span>
                  <input
                    type="time"
                    value={section.custom_end ?? ""}
                    onChange={(event) =>
                      updateSection(index, { custom_end: event.target.value })
                    }
                  />
                </label>
              </>
            ) : (
              <>
                <label className="field">
                  <span>开始节次</span>
                  <select
                    value={section.start_period}
                    onChange={(event) => {
                      const start = Number(event.target.value);
                      updateSection(index, {
                        start_period: start,
                        end_period: Math.max(start, section.end_period),
                      });
                    }}
                  >
                    {config.time_slots.map((slot) => (
                      <option value={slot.period} key={slot.period}>
                        第 {slot.period} 节 {slot.start}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>结束节次</span>
                  <select
                    value={section.end_period}
                    onChange={(event) =>
                      updateSection(index, { end_period: Number(event.target.value) })
                    }
                  >
                    {config.time_slots.map((slot) => (
                      <option value={slot.period} key={slot.period}>
                        第 {slot.period} 节 {slot.end}
                      </option>
                    ))}
                  </select>
                </label>
              </>
            )}
            <label className="field location-field">
              <span>上课地点</span>
              <input
                maxLength={40}
                value={section.location}
                onChange={(event) => updateSection(index, { location: event.target.value })}
                placeholder="教学楼-101"
              />
            </label>
            <button
              className="icon-button danger section-delete"
              type="button"
              aria-label="删除时间段"
              disabled={draft.sections.length === 1}
              onClick={() =>
                setDraft({
                  ...draft,
                  sections: draft.sections.filter((_, sectionIndex) => sectionIndex !== index),
                })
              }
            >
              <Icon name="trash" size={16} />
            </button>
          </div>
        ))}
      </div>

      <div className="field">
        <span>课程颜色</span>
        <div className="color-picker">
          {config.color_palette.map((color, index) => (
            <button
              className={draft.color_index === index ? "selected" : ""}
              key={color.stripe}
              type="button"
              aria-label={`颜色 ${index + 1}`}
              style={{ background: color.bg, borderLeftColor: color.stripe }}
              onClick={() => setDraft({ ...draft, color_index: index })}
            />
          ))}
        </div>
      </div>

      {conflicts.length > 0 && (
        <div className="notice warning">
          <Icon name="warning" />
          与「{conflicts.map((item) => item.name).join("、")}」存在时间段重叠，仍可保存并在课表中查看提示。
        </div>
      )}
      {error && <div className="notice error">{error}</div>}

      <div className="modal-actions">
        {course && onDelete && (
          <button
            className="button danger ghost"
            type="button"
            disabled={busy}
            onClick={async () => {
              if (!window.confirm(`确认删除「${course.name}」？`)) return;
              setBusy(true);
              try {
                await onDelete(course);
              } finally {
                setBusy(false);
              }
            }}
          >
            <Icon name="trash" />
            删除课程
          </button>
        )}
        <span className="action-spacer" />
        <button className="button ghost" type="button" onClick={onClose} disabled={busy}>
          取消
        </button>
        <button className="button primary" type="button" onClick={submit} disabled={busy}>
          {busy ? "保存中…" : course ? "保存修改" : "添加课程"}
        </button>
      </div>
    </Modal>
  );
}

function nextColor(courses: Course[]): number {
  const used = new Map<number, number>();
  courses.forEach((course) =>
    used.set(course.color_index, (used.get(course.color_index) ?? 0) + 1),
  );
  let candidate = 0;
  for (let index = 1; index < 12; index += 1) {
    if ((used.get(index) ?? 0) < (used.get(candidate) ?? 0)) candidate = index;
  }
  return candidate;
}
