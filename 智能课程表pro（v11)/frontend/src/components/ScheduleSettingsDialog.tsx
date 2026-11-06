import { useState } from "react";
import type {
  AppConfig,
  Course,
  Holiday,
  ScheduleConfig,
  TimeSlot,
} from "../types";
import { WEEKDAYS } from "../utils";
import { Icon } from "./Icon";
import { Modal } from "./Modal";

export function ScheduleSettingsDialog({
  config,
  courses,
  onClose,
  onSave,
  onExportJson,
  onOpenJsonImport,
  onOpenTabularImport,
  onOpenReschedule,
}: {
  config: AppConfig;
  courses: Course[];
  onClose: () => void;
  onSave: (schedule: ScheduleConfig) => Promise<void>;
  onExportJson: () => void;
  onOpenJsonImport: () => void;
  onOpenTabularImport: () => void;
  onOpenReschedule: () => void;
}) {
  const [schedule, setSchedule] = useState<ScheduleConfig>({
    settings: structuredClone(config.settings),
    time_slots: structuredClone(config.time_slots),
    holidays: structuredClone(config.holidays),
  });
  const [holidayDate, setHolidayDate] = useState("");
  const [holidayName, setHolidayName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const settings = schedule.settings;
  const usedMaxPeriod = Math.max(
    1,
    ...courses.flatMap((course) =>
      course.sections.map((section) => section.end_period),
    ),
  );

  const setSetting = <K extends keyof typeof settings,>(
    key: K,
    value: (typeof settings)[K],
  ) => {
    setSchedule((current) => ({
      ...current,
      settings: { ...current.settings, [key]: value },
    }));
  };

  const updateSlot = (index: number, patch: Partial<TimeSlot>) => {
    setSchedule((current) => ({
      ...current,
      time_slots: current.time_slots.map((slot, slotIndex) =>
        slotIndex === index ? { ...slot, ...patch } : slot,
      ),
    }));
  };

  const addSlot = () => {
    setSchedule((current) => {
      const last = current.time_slots.at(-1);
      const period = current.time_slots.length + 1;
      return {
        ...current,
        time_slots: [
          ...current.time_slots,
          {
            period,
            start: last?.end ?? "08:00",
            end: last ? addMinutes(last.end, 45) : "08:45",
          },
        ],
      };
    });
  };

  const removeSlot = (index: number) => {
    setSchedule((current) => ({
      ...current,
      time_slots: current.time_slots
        .filter((_, slotIndex) => slotIndex !== index)
        .map((slot, slotIndex) => ({ ...slot, period: slotIndex + 1 })),
    }));
  };

  const addHoliday = () => {
    if (!holidayDate) return;
    const next: Holiday = { date: holidayDate, name: holidayName.trim() };
    setSchedule((current) => ({
      ...current,
      holidays: [
        ...current.holidays.filter((item) => item.date !== holidayDate),
        next,
      ].sort((a, b) => a.date.localeCompare(b.date)),
    }));
    setHolidayDate("");
    setHolidayName("");
  };

  const save = async () => {
    setError("");
    for (let index = 0; index < schedule.time_slots.length; index += 1) {
      const slot = schedule.time_slots[index];
      if (slot.start >= slot.end) {
        setError(`第 ${slot.period} 节的开始时间必须早于结束时间`);
        return;
      }
      if (index > 0 && schedule.time_slots[index - 1].end > slot.start) {
        setError(`第 ${slot.period} 节与上一节时间重叠`);
        return;
      }
    }
    setBusy(true);
    try {
      await onSave(schedule);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "设置保存失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title="课表与显示设置" eyebrow="课表参数 · 个性化 · 数据" onClose={onClose} wide>
      <section className="settings-section">
        <div className="settings-section-title">
          <div>
            <p className="eyebrow">学期安排</p>
            <h3>学期与周次</h3>
          </div>
        </div>
        <div className="form-grid">
          <label className="field">
            <span>学期第一周起始日</span>
            <input
              type="date"
              value={settings.semester_start_date}
              onChange={(event) => setSetting("semester_start_date", event.target.value)}
            />
          </label>
          <label className="field">
            <span>学期总周数</span>
            <input
              type="number"
              min={1}
              max={30}
              value={settings.total_weeks}
              onChange={(event) =>
                setSetting("total_weeks", Math.max(1, Math.min(30, Number(event.target.value))))
              }
            />
          </label>
          <label className="field">
            <span>每周第一天</span>
            <select
              value={settings.first_day_of_week}
              onChange={(event) => setSetting("first_day_of_week", Number(event.target.value))}
            >
              {WEEKDAYS.map((day, index) => (
                <option value={index + 1} key={day}>
                  {day}
                </option>
              ))}
            </select>
          </label>
          <label className="switch-field">
            <span>显示周末</span>
            <input
              type="checkbox"
              checked={settings.show_weekends}
              onChange={(event) => setSetting("show_weekends", event.target.checked)}
            />
          </label>
        </div>
      </section>

      <section className="settings-section">
        <div className="settings-section-title">
          <div>
            <p className="eyebrow">显示方式</p>
            <h3>课表显示</h3>
          </div>
        </div>
        <div className="form-grid">
          <label className="field">
            <span>时间轴模式</span>
            <select
              value={settings.display_mode}
              onChange={(event) =>
                setSetting("display_mode", event.target.value as "sections" | "24h")
              }
            >
              <option value="sections">按节次</option>
              <option value="24h">24 小时时间轴</option>
            </select>
          </label>
          <label className="field">
            <span>网格密度</span>
            <select
              value={settings.density}
              onChange={(event) =>
                setSetting("density", event.target.value as "compact" | "comfortable")
              }
            >
              <option value="comfortable">舒展</option>
              <option value="compact">紧凑</option>
            </select>
          </label>
          <label className="field">
            <span>背景主题</span>
            <select
              value={settings.background_theme}
              onChange={(event) =>
                setSetting(
                  "background_theme",
                  event.target.value as "paper" | "mint" | "warm" | "slate",
                )
              }
            >
              <option value="paper">晨纸</option>
              <option value="mint">薄荷</option>
              <option value="warm">暖阳</option>
              <option value="slate">深海</option>
            </select>
          </label>
          <label className="field">
            <span>课程块不透明度 · {Math.round(settings.card_opacity * 100)}%</span>
            <input
              type="range"
              min={0.55}
              max={1}
              step={0.05}
              value={settings.card_opacity}
              onChange={(event) => setSetting("card_opacity", Number(event.target.value))}
            />
          </label>
          <label className="field">
            <span>字体缩放 · {Math.round(settings.font_scale * 100)}%</span>
            <input
              type="range"
              min={0.8}
              max={1.2}
              step={0.05}
              value={settings.font_scale}
              onChange={(event) => setSetting("font_scale", Number(event.target.value))}
            />
          </label>
        </div>
        <div className="setting-switches">
          <label className="switch-field">
            <span>深色模式</span>
            <input
              type="checkbox"
              checked={settings.dark_mode}
              onChange={(event) => setSetting("dark_mode", event.target.checked)}
            />
          </label>
          <label className="switch-field">
            <span>隐藏教师</span>
            <input
              type="checkbox"
              checked={settings.hide_teacher}
              onChange={(event) => setSetting("hide_teacher", event.target.checked)}
            />
          </label>
          <label className="switch-field">
            <span>隐藏地点</span>
            <input
              type="checkbox"
              checked={settings.hide_location}
              onChange={(event) => setSetting("hide_location", event.target.checked)}
            />
          </label>
        </div>
      </section>

      <section className="settings-section">
        <div className="settings-section-title">
          <div>
            <p className="eyebrow">作息时间</p>
            <h3>作息时间</h3>
          </div>
          <button className="button secondary small" type="button" onClick={addSlot}>
            <Icon name="plus" size={14} /> 添加节次
          </button>
        </div>
        <div className="slot-editor">
          {schedule.time_slots.map((slot, index) => (
            <div className="slot-editor-row" key={slot.period}>
              <strong>第 {slot.period} 节</strong>
              <input
                type="time"
                value={slot.start}
                onChange={(event) => updateSlot(index, { start: event.target.value })}
              />
              <span>至</span>
              <input
                type="time"
                value={slot.end}
                onChange={(event) => updateSlot(index, { end: event.target.value })}
              />
              <input
                value={slot.alias ?? ""}
                maxLength={30}
                placeholder="别名（可选）"
                onChange={(event) => updateSlot(index, { alias: event.target.value })}
              />
              <button
                className="icon-button danger small"
                type="button"
                aria-label={`删除第 ${slot.period} 节`}
                disabled={
                  schedule.time_slots.length === 1 ||
                  schedule.time_slots.length <= usedMaxPeriod
                }
                onClick={() => removeSlot(index)}
              >
                <Icon name="trash" size={14} />
              </button>
            </div>
          ))}
        </div>
        {schedule.time_slots.length <= usedMaxPeriod && (
          <p className="note">
            当前课程最晚使用第 {usedMaxPeriod} 节；如需删除后面的作息，请先调整相关课程。
          </p>
        )}
      </section>

      <section className="settings-section">
        <div className="settings-section-title">
          <div>
            <p className="eyebrow">假期安排</p>
            <h3>节假日</h3>
          </div>
          <span className="muted">已添加 {schedule.holidays.length} 天</span>
        </div>
        <div className="holiday-editor-row">
          <input
            type="date"
            value={holidayDate}
            onChange={(event) => setHolidayDate(event.target.value)}
          />
          <input
            value={holidayName}
            maxLength={40}
            placeholder="假期名称"
            onChange={(event) => setHolidayName(event.target.value)}
          />
          <button className="button secondary" type="button" onClick={addHoliday}>
            添加
          </button>
        </div>
        <div className="holiday-chip-list">
          {schedule.holidays.map((holiday) => (
            <span className="holiday-chip" key={holiday.date}>
              {holiday.date} · {holiday.name || "假期"}
              <button
                type="button"
                aria-label={`删除 ${holiday.date}`}
                onClick={() =>
                  setSchedule((current) => ({
                    ...current,
                    holidays: current.holidays.filter((item) => item.date !== holiday.date),
                  }))
                }
              >
                <Icon name="x" size={12} />
              </button>
            </span>
          ))}
        </div>
      </section>

      <section className="settings-section">
        <div className="settings-section-title">
          <div>
            <p className="eyebrow">数据工具</p>
            <h3>导入、导出与调课</h3>
          </div>
        </div>
        <div className="data-action-grid">
          <button className="data-action" type="button" onClick={onExportJson}>
            <Icon name="download" />
            <strong>导出 JSON</strong>
            <span>包含课程、作息、学期和假期</span>
          </button>
          <button className="data-action" type="button" onClick={onOpenJsonImport}>
            <Icon name="import" />
            <strong>导入 JSON</strong>
            <span>支持本项目和拾光课程表格式</span>
          </button>
          <button className="data-action" type="button" onClick={onOpenTabularImport}>
            <Icon name="import" />
            <strong>导入 Excel / CSV</strong>
            <span>列映射、规则解析与模板复用</span>
          </button>
          <button className="data-action" type="button" onClick={onOpenReschedule}>
            <Icon name="calendar" />
            <strong>课程调课</strong>
            <span>移动、覆盖或交换某周课程</span>
          </button>
        </div>
      </section>

      {error && <div className="notice error">{error}</div>}
      <div className="modal-actions">
        <span className="action-spacer" />
        <button className="button ghost" type="button" onClick={onClose} disabled={busy}>
          取消
        </button>
        <button className="button primary" type="button" onClick={save} disabled={busy}>
          {busy ? "保存中…" : "保存全部设置"}
        </button>
      </div>
    </Modal>
  );
}

function addMinutes(clock: string, amount: number): string {
  const [hour, minute] = clock.split(":").map(Number);
  const total = Math.min(23 * 60 + 59, hour * 60 + minute + amount);
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}
