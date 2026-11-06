import type { CSSProperties } from "react";
import type { AppConfig, Course, SelfPlan } from "../types";
import { buildScheduleLayout } from "../scheduleLayout";
import {
  WEEKDAYS,
  dateString,
  formatDuration,
  parityForDate,
  planForDate,
  toClock,
  toMinutes,
  weekDates,
  weekOffsetForDate,
} from "../utils";
import { Icon } from "./Icon";

export function ScheduleView({
  courses,
  plans,
  config,
  semesterStart,
  weekOffset,
  view,
  selectedDate,
  query,
  onCourse,
  onDeletePlan,
}: {
  courses: Course[];
  plans: SelfPlan[];
  config: AppConfig;
  semesterStart: Date;
  weekOffset: number;
  view: "week" | "day";
  selectedDate: Date;
  query: string;
  onCourse: (course: Course) => void;
  onDeletePlan: (plan: SelfPlan) => void;
}) {
  const settings = config.settings;
  const mode = settings.display_mode;
  const rowHeight =
    mode === "24h"
      ? settings.density === "compact"
        ? 30
        : 38
      : settings.density === "compact"
        ? 52
        : 62;
  const weekdayOrder = orderedWeekdays(settings.first_day_of_week).filter(
    (weekday) => settings.show_weekends || weekday <= 5,
  );
  const weekDatesForConfig = weekDates(
    semesterStart,
    weekOffset,
    settings.first_day_of_week,
  );
  const dates =
    view === "week"
      ? weekDatesForConfig.filter((date) => weekdayOrder.includes(isoWeekday(date)))
      : [
          new Date(
            selectedDate.getFullYear(),
            selectedDate.getMonth(),
            selectedDate.getDate(),
          ),
        ];
  const activeWeek =
    view === "week"
      ? weekOffset + 1
      : weekOffsetForDate(selectedDate, semesterStart, settings.first_day_of_week) + 1;
  const parity = parityForDate(
    view === "week" ? weekDatesForConfig[0] : selectedDate,
    semesterStart,
    settings.first_day_of_week,
  );
  const layout = buildScheduleLayout(
    courses,
    activeWeek,
    parity,
    weekdayOrder,
    config.time_slots,
    mode,
  );
  const holidayMap = new Map(config.holidays.map((holiday) => [holiday.date, holiday]));

  return (
    <div
      className={`schedule ${view === "day" ? "schedule-day" : ""}`}
      style={{ "--font-scale": settings.font_scale } as CSSProperties}
    >
      <div
        className="week-grid"
        style={{
          gridTemplateColumns: `64px repeat(${dates.length}, minmax(${view === "day" ? 280 : 112}px, 1fr))`,
        }}
      >
        <div className="grid-corner">{mode === "24h" ? "时间" : "节次"}</div>
        {dates.map((date) => {
          const weekday = isoWeekday(date);
          const holiday = holidayMap.get(dateString(date));
          return (
            <div
              className={`day-header ${isToday(date) ? "is-today" : ""} ${holiday ? "is-holiday" : ""}`}
              key={dateString(date)}
            >
              <strong>{WEEKDAYS[weekday - 1]}</strong>
              <span>
                {date.getMonth() + 1}/{date.getDate()}
              </span>
              {holiday && <em>{holiday.name || "假期"}</em>}
            </div>
          );
        })}

        <div className="time-axis">
          {Array.from({ length: layout.axisCount }, (_, index) => {
            const axis = axisData(mode, index + 1, config.time_slots);
            return (
              <div className="time-cell" style={{ height: rowHeight }} key={axis.primary}>
                <b>{axis.primary}</b>
                <span>{axis.start}</span>
                <span>{axis.end}</span>
              </div>
            );
          })}
        </div>

        {dates.map((date) => {
          const weekday = isoWeekday(date);
          const dayLayout =
            layout.dayLayouts.find((item) => item.weekday === weekday)?.blocks ?? [];
          const dayPlans = planForDate(plans, date);
          const holiday = holidayMap.get(dateString(date));
          return (
            <div
              className={`day-column ${isToday(date) ? "is-today" : ""} ${holiday ? "is-holiday" : ""}`}
              style={{ height: layout.axisCount * rowHeight }}
              key={`column-${dateString(date)}`}
            >
              {holiday ? (
                <div className="holiday-card">
                  <Icon name="calendar" size={20} />
                  <strong>{holiday.name || "今天放假"}</strong>
                  <span>课程与规划暂停</span>
                </div>
              ) : (
                <>
                  {dayLayout.map((block) => {
                    const dim = query
                      ? !`${block.course.name} ${block.course.teacher}`
                          .toLowerCase()
                          .includes(query.toLowerCase())
                      : false;
                    const color =
                      config.color_palette[block.course.color_index] ??
                      config.color_palette[0];
                    return (
                      <button
                        className={`course-card ${dim ? "is-dim" : ""} ${block.laneCount > 1 ? "is-conflict" : ""}`}
                        key={`${block.course.id}-${block.sectionIndex}`}
                        type="button"
                        onClick={() => onCourse(block.course)}
                        style={{
                          top: block.start * rowHeight + 4,
                          height: Math.max(28, (block.end - block.start) * rowHeight - 8),
                          left: `calc(${(block.lane / block.laneCount) * 100}% + 3px)`,
                          width: `calc(${100 / block.laneCount}% - 6px)`,
                          background: withAlpha(color.bg, settings.card_opacity),
                          borderLeftColor: color.stripe,
                        }}
                        title={
                          block.laneCount > 1
                            ? `冲突课程，共 ${block.laneCount} 个并排显示`
                            : block.course.name
                        }
                      >
                        <span className="course-name">{block.course.name}</span>
                        {!settings.hide_location && (
                          <span className="meta">
                            <Icon name="location" size={12} />
                            {block.section.location || "未填写地点"}
                          </span>
                        )}
                        {!settings.hide_teacher && (
                          <span className="meta">
                            <Icon name="user" size={12} />
                            {block.course.teacher || "未填写教师"}
                          </span>
                        )}
                        <span className="card-badges">
                          {block.course.week_type !== "all" && (
                            <em className={`week-badge ${block.course.week_type}`}>
                              {block.course.week_type === "odd"
                                ? "单"
                                : block.course.week_type === "even"
                                  ? "双"
                                  : "定"}
                            </em>
                          )}
                          {block.laneCount > 1 && <em className="conflict-badge">冲突</em>}
                        </span>
                      </button>
                    );
                  })}
                  {dayPlans.map((plan) => {
                    const start = minuteToAxis(plan.start_min, config.time_slots, mode);
                    const end = minuteToAxis(plan.end_min, config.time_slots, mode);
                    return (
                      <button
                        className="course-card plan-card"
                        key={plan.id}
                        type="button"
                        onClick={() => onDeletePlan(plan)}
                        style={{
                          top: Math.max(4, start * rowHeight),
                          height: Math.max(34, (end - start) * rowHeight - 4),
                          background: withAlpha("#ede9fe", settings.card_opacity),
                        }}
                        title="点击删除该自主规划"
                      >
                        <span className="course-name">{plan.title}</span>
                        <span className="meta">
                          <Icon name="clock" size={12} />
                          {toClock(plan.start_min)}–{toClock(plan.end_min)}
                        </span>
                        <span className="plan-duration">
                          {formatDuration(plan.end_min - plan.start_min)}
                        </span>
                        <em className="week-badge custom">自</em>
                      </button>
                    );
                  })}
                </>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function orderedWeekdays(firstDay: number): number[] {
  return Array.from({ length: 7 }, (_, index) => ((firstDay - 1 + index) % 7) + 1);
}

function isoWeekday(date: Date): number {
  return date.getDay() === 0 ? 7 : date.getDay();
}

function isToday(date: Date): boolean {
  return dateString(date) === dateString(new Date());
}

function axisData(
  mode: "sections" | "24h",
  index: number,
  slots: AppConfig["time_slots"],
): { primary: string; start: string; end: string } {
  if (mode === "24h") {
    return {
      primary: String(index),
      start: `${String(index - 1).padStart(2, "0")}:00`,
      end: `${String(index).padStart(2, "0")}:00`,
    };
  }
  const slot = slots[index - 1];
  return {
    primary: String(slot?.period ?? index),
    start: slot?.start ?? "—",
    end: slot?.end ?? "—",
  };
}

function minuteToAxis(
  minute: number,
  slots: AppConfig["time_slots"],
  mode: "sections" | "24h",
): number {
  if (mode === "24h") return minute / 60;
  const slotIndex = slots.findIndex((slot) => minute <= toMinutes(slot.end));
  if (slotIndex < 0) return slots.length;
  const slot = slots[slotIndex];
  const start = toMinutes(slot.start);
  const end = Math.max(start + 1, toMinutes(slot.end));
  return slotIndex + Math.max(0, Math.min(1, (minute - start) / (end - start)));
}

function withAlpha(hex: string, alpha: number): string {
  const normalized = hex.replace("#", "");
  if (normalized.length !== 6) return hex;
  const alphaHex = Math.round(Math.max(0, Math.min(1, alpha)) * 255)
    .toString(16)
    .padStart(2, "0");
  return `#${normalized}${alphaHex}`;
}
