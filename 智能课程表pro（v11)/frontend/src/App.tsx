import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { CourseForm } from "./components/CourseForm";
import { Icon } from "./components/Icon";
import { ImportDialog } from "./components/ImportDialog";
import { JsonImportDialog } from "./components/JsonImportDialog";
import { PlannerDialog } from "./components/PlannerDialog";
import { RescheduleDialog } from "./components/RescheduleDialog";
import { ScheduleSettingsDialog } from "./components/ScheduleSettingsDialog";
import { ScheduleView } from "./components/ScheduleView";
import { TabularImportDialog } from "./components/TabularImportDialog";
import { WeekPickerDialog } from "./components/WeekPickerDialog";
import type {
  AppConfig,
  Course,
  CourseDraft,
  ScheduleConfig,
  SelfPlan,
} from "./types";
import {
  WEEKDAYS,
  courseActive,
  dateString,
  parityForDate,
  planForDate,
  weekDates,
  weekOffsetForDate,
} from "./utils";

type DialogState =
  | { type: "add" }
  | { type: "course"; course: Course }
  | { type: "import" }
  | { type: "json" }
  | { type: "tabular" }
  | { type: "planner" }
  | { type: "settings" }
  | { type: "reschedule" }
  | { type: "weeks" }
  | null;

export default function App() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [courses, setCourses] = useState<Course[]>([]);
  const [plans, setPlans] = useState<SelfPlan[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [view, setView] = useState<"week" | "day">("week");
  const [weekOffset, setWeekOffset] = useState(0);
  const [selectedDate, setSelectedDate] = useState(new Date());
  const [query, setQuery] = useState("");
  const [dialog, setDialog] = useState<DialogState>(null);
  const [toast, setToast] = useState("");

  const loadData = useCallback(async () => {
    setLoadError("");
    try {
      const [nextConfig, nextCourses, nextPlans] = await Promise.all([
        api.config(),
        api.courses(),
        api.selfPlans(),
      ]);
      let resolvedConfig = nextConfig;
      if (!localStorage.getItem("stp_semester_migrated")) {
        const localStart = localStorage.getItem("stp_semester_start");
        const localWeeks = Number(localStorage.getItem("stp_total_weeks") || 0);
        if (localStart || (localWeeks >= 1 && localWeeks <= 30)) {
          const migrated = await api.updateScheduleConfig({
            settings: {
              ...nextConfig.settings,
              semester_start_date: localStart || nextConfig.settings.semester_start_date,
              total_weeks:
                localWeeks >= 1 && localWeeks <= 30
                  ? localWeeks
                  : nextConfig.settings.total_weeks,
            },
            time_slots: nextConfig.time_slots,
            holidays: nextConfig.holidays,
          });
          resolvedConfig = {
            ...nextConfig,
            settings: migrated.settings,
            time_slots: migrated.time_slots,
            holidays: migrated.holidays,
            total_weeks: migrated.settings.total_weeks,
          };
        }
        localStorage.removeItem("stp_semester_start");
        localStorage.removeItem("stp_total_weeks");
        localStorage.setItem("stp_semester_migrated", "1");
      }
      setConfig(resolvedConfig);
      setCourses(nextCourses);
      setPlans(nextPlans);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "数据加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 2800);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const settings = config?.settings;
  const semesterStart = new Date(
    `${settings?.semester_start_date ?? dateString(new Date())}T00:00:00`,
  );
  const semesterStartTime = semesterStart.getTime();
  const firstDay = settings?.first_day_of_week ?? 1;
  const todayWeek =
    weekOffsetForDate(new Date(), semesterStart, firstDay) + 1;
  const allDates = useMemo(
    () => weekDates(semesterStart, weekOffset, firstDay),
    [semesterStartTime, firstDay, weekOffset],
  );
  const visibleDates = allDates.filter(
    (date) => settings?.show_weekends || isoWeekday(date) <= 5,
  );
  const parity = parityForDate(
    view === "week" ? allDates[0] : selectedDate,
    semesterStart,
    firstDay,
  );
  const viewStart =
    view === "week"
      ? visibleDates[0] ?? allDates[0]
      : new Date(selectedDate.getFullYear(), selectedDate.getMonth(), selectedDate.getDate());
  const viewEnd =
    view === "week"
      ? visibleDates.at(-1) ?? allDates.at(-1) ?? viewStart
      : viewStart;
  const displayedPlans =
    view === "day" &&
    !config?.holidays.some((holiday) => holiday.date === dateString(selectedDate))
      ? planForDate(plans, selectedDate)
      : [];
  const activeWeekOffset =
    view === "week"
      ? weekOffset
      : weekOffsetForDate(selectedDate, semesterStart, firstDay);
  const activeWeekNumber = activeWeekOffset + 1;
  const activeWeekCourseCount = courses.filter((course) =>
    courseActive(course, activeWeekNumber, parity),
  ).length;
  const activePlanCount = plans.filter(
    (plan) =>
      plan.date >= dateString(viewStart) && plan.date <= dateString(viewEnd),
  ).length;
  const academicStartYear =
    semesterStart.getMonth() >= 7
      ? semesterStart.getFullYear()
      : semesterStart.getFullYear() - 1;
  const academicYear = `${academicStartYear}—${academicStartYear + 1}`;
  const termLabel = semesterStart.getMonth() >= 7 ? "秋季学期" : "春季学期";

  const saveCourse = async (draft: CourseDraft) => {
    if (dialog?.type === "course") {
      await api.updateCourse(dialog.course.id, draft);
      setToast("课程修改已保存");
    } else {
      await api.createCourse(draft);
      setToast("课程已添加并保存");
    }
    setDialog(null);
    await loadData();
  };

  const deleteCourse = async (course: Course) => {
    await api.deleteCourse(course.id);
    setDialog(null);
    setToast(`已删除「${course.name}」`);
    await loadData();
  };

  const deletePlan = async (plan: SelfPlan) => {
    if (!window.confirm(`删除自主规划「${plan.title}」？`)) return;
    await api.deletePlan(plan.id);
    setToast("自主规划已删除");
    await loadData();
  };

  const moveDate = (delta: number) => {
    if (view === "week") {
      setWeekOffset((value) => value + delta);
      return;
    }
    const next = new Date(selectedDate);
    next.setDate(next.getDate() + delta);
    setSelectedDate(next);
  };

  const goToday = () => {
    const today = new Date();
    setSelectedDate(today);
    setWeekOffset(weekOffsetForDate(today, semesterStart, firstDay));
  };

  const exportCalendar = () => {
    const weeks = config?.settings.total_weeks ?? 18;
    window.location.href = `/api/export/ics?semester_start=${dateString(semesterStart)}&weeks=${weeks}`;
  };

  const saveSchedule = async (schedule: ScheduleConfig) => {
    await api.updateScheduleConfig(schedule);
    setDialog(null);
    setToast("课表设置已保存");
    await loadData();
  };

  const toggleWeekends = async () => {
    if (!config) return;
    try {
      await api.updateScheduleConfig({
        settings: {
          ...config.settings,
          show_weekends: !config.settings.show_weekends,
        },
        time_slots: config.time_slots,
        holidays: config.holidays,
      });
      await loadData();
      setToast(config.settings.show_weekends ? "已隐藏周末" : "已显示周末");
    } catch (error) {
      setToast(error instanceof Error ? error.message : "切换失败");
    }
  };

  if (loading) {
    return (
      <main className="loading-screen">
        <div className="brand-mark large">
          <Icon name="calendar" size={30} />
        </div>
        <h1>正在整理你的课程表</h1>
        <div className="skeleton-row"><span /><span /><span /></div>
      </main>
    );
  }

  if (!config || loadError) {
    return (
      <main className="error-screen">
        <div className="brand-mark large"><Icon name="warning" size={28} /></div>
        <h1>暂时无法连接服务</h1>
        <p>{loadError || "请确认 FastAPI 后端已启动。"}</p>
        <button className="button primary" type="button" onClick={() => void loadData()}>
          重新连接
        </button>
      </main>
    );
  }

  return (
    <div
      className={`app-shell theme-${config.settings.background_theme}`}
      data-theme={config.settings.dark_mode ? "dark" : "light"}
    >
      <header className="topbar">
        <button className="brand" type="button" onClick={goToday}>
          <span className="brand-mark"><Icon name="calendar" size={24} /></span>
          <span>
            <strong>智能课程表 Pro</strong>
            <small>AI 学习规划</small>
          </span>
        </button>
        <nav className="view-tabs" aria-label="课表视图">
          <button
            className={view === "week" ? "active" : ""}
            type="button"
            onClick={() => setView("week")}
          >
            周课表
          </button>
          <button
            className={view === "day" ? "active" : ""}
            type="button"
            onClick={() => setView("day")}
          >
            日课表
          </button>
        </nav>
        <div className="top-actions">
          <button className="icon-button" type="button" aria-label="设置" onClick={() => setDialog({ type: "settings" })}>
            <Icon name="settings" />
          </button>
        </div>
      </header>

      <main className="planner-shell">
        <aside className="week-rail">
          <div className="rail-heading">
            <span>{academicYear}</span>
            <span>{termLabel}</span>
          </div>
          <button
            className="week-stamp"
            type="button"
            onClick={() => {
              setWeekOffset(activeWeekOffset);
              setView("week");
              setDialog({ type: "weeks" });
            }}
            title="快速选择周次"
          >
            <span>第</span>
            <strong>{String(activeWeekNumber).padStart(2, "0")}</strong>
            <span>周</span>
          </button>
          <p className="rail-date">
            {viewStart.getMonth() + 1} 月 {viewStart.getDate()} 日
            <span>至</span>
            {viewEnd.getMonth() + 1} 月 {viewEnd.getDate()} 日
          </p>
          <div className="rail-actions">
            <button className="button rail-primary" type="button" onClick={() => setDialog({ type: "import" })}>
              <Icon name="spark" />
              导入课表
            </button>
            <button className="rail-action" type="button" onClick={() => setDialog({ type: "planner" })}>
              <Icon name="clock" />
              规划空闲时间
            </button>
            <button className="rail-action" type="button" onClick={() => setDialog({ type: "add" })}>
              <Icon name="plus" />
              手动添加课程
            </button>
          </div>
          <dl className="rail-stats">
            <div>
              <dt>本周课程</dt>
              <dd>{activeWeekCourseCount}</dd>
            </div>
            <div>
              <dt>学习安排</dt>
              <dd>{activePlanCount}</dd>
            </div>
            <div>
              <dt>时间轴</dt>
              <dd>{config.settings.display_mode === "24h" ? "24 小时" : "节次"}</dd>
            </div>
          </dl>
          <button className="rail-settings" type="button" onClick={() => setDialog({ type: "settings" })}>
            <Icon name="settings" size={16} />
            课表与显示设置
          </button>
          <p className="rail-mode">
            <span className={config.ai_enabled ? "status-dot online" : "status-dot"} />
            {config.ai_enabled ? "AI 服务已连接" : "本地模式，仍可完整使用"}
          </p>
        </aside>

        <section className="planner-board">
          <header className="board-head">
            <div>
              <p className="board-kicker">{view === "week" ? "周课表" : "日课表"}</p>
              <h1>
                {view === "week"
                  ? activeWeekNumber === todayWeek
                    ? "本周课程"
                    : `第 ${activeWeekNumber} 周课程`
                  : `${WEEKDAYS[isoWeekday(selectedDate) - 1]}课程`}
              </h1>
              <p className="board-range">
                {viewStart.getMonth() + 1}/{viewStart.getDate()} –{" "}
                {viewEnd.getMonth() + 1}/{viewEnd.getDate()}
                <span className={`parity-pill ${parity}`}>
                  {parity === "odd" ? "单周" : "双周"}
                </span>
              </p>
            </div>
            <div className="board-head-actions">
              <label className="search-field">
                <Icon name="search" />
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="搜索课程或教师"
                />
                {query && (
                  <button type="button" onClick={() => setQuery("")} aria-label="清除搜索">
                    <Icon name="x" size={14} />
                  </button>
                )}
              </label>
              <button className="button ghost compact-button" type="button" onClick={exportCalendar}>
                <Icon name="download" />
                导出日历
              </button>
            </div>
          </header>

          <div className="board-controls">
            <div className="week-navigation">
              <button className="icon-button" type="button" aria-label="上一周期" onClick={() => moveDate(-1)}>
                <Icon name="chevron-left" />
              </button>
              <button className="today-button" type="button" onClick={goToday}>今天</button>
              <button className="icon-button" type="button" aria-label="下一周期" onClick={() => moveDate(1)}>
                <Icon name="chevron-right" />
              </button>
              <button className="today-button" type="button" onClick={() => void toggleWeekends()}>
                {config.settings.show_weekends ? "只看工作日" : "显示周末"}
              </button>
            </div>
            <p className="board-note">
              点击课程查看详情，重叠课程会自动并排显示
            </p>
          </div>

          {displayedPlans.length > 0 && (
            <div className="plan-summary-bar">
              <Icon name="spark" />
              <span>今日有 {displayedPlans.length} 项学习安排</span>
              <span>{displayedPlans.map((plan) => plan.title).join("、")}</span>
            </div>
          )}

          <ScheduleView
            courses={courses}
            plans={plans}
            config={config}
            semesterStart={semesterStart}
            weekOffset={weekOffset}
            view={view}
            selectedDate={selectedDate}
            query={query}
            onCourse={(course) => setDialog({ type: "course", course })}
            onDeletePlan={(plan) => void deletePlan(plan)}
          />
        </section>

        <footer className="app-footer">
          <span>数据保存在本地 SQLite · AI 不可用时自动降级</span>
          <span>{config.settings.semester_start_date} 开学 · 共 {config.settings.total_weeks} 周</span>
        </footer>
      </main>

      {(dialog?.type === "add" || dialog?.type === "course") && (
        <CourseForm
          course={dialog.type === "course" ? dialog.course : null}
          courses={courses}
          config={config}
          onClose={() => setDialog(null)}
          onSave={saveCourse}
          onDelete={deleteCourse}
        />
      )}
      {dialog?.type === "import" && (
        <ImportDialog
          onClose={() => setDialog(null)}
          onOpenTabular={() => setDialog({ type: "tabular" })}
          onImported={async (count) => {
            setDialog(null);
            setToast(`已从解析结果导入 ${count} 门课程`);
            await loadData();
          }}
        />
      )}
      {dialog?.type === "tabular" && (
        <TabularImportDialog
          onClose={() => setDialog(null)}
          onImported={async (count, skipped) => {
            setDialog(null);
            setToast(
              skipped
                ? `已导入 ${count} 门课程，跳过 ${skipped} 门重复课程`
                : `已从表格导入 ${count} 门课程`,
            );
            await loadData();
          }}
        />
      )}
      {dialog?.type === "json" && (
        <JsonImportDialog
          onClose={() => setDialog(null)}
          onImported={async (count) => {
            setDialog(null);
            setToast(`已导入 ${count} 门课程和课表设置`);
            await loadData();
          }}
        />
      )}
      {dialog?.type === "planner" && (
        <PlannerDialog
          courses={courses}
          config={config}
          semesterStart={semesterStart}
          initialDate={selectedDate}
          onClose={() => setDialog(null)}
          onCreated={async (count) => {
            setDialog(null);
            setToast(`已生成 ${count} 项学习规划`);
            await loadData();
          }}
        />
      )}
      {dialog?.type === "settings" && (
        <ScheduleSettingsDialog
          config={config}
          courses={courses}
          onClose={() => setDialog(null)}
          onSave={saveSchedule}
          onExportJson={() => {
            window.location.href = "/api/export/json";
          }}
          onOpenJsonImport={() => setDialog({ type: "json" })}
          onOpenTabularImport={() => setDialog({ type: "tabular" })}
          onOpenReschedule={() => setDialog({ type: "reschedule" })}
        />
      )}
      {dialog?.type === "reschedule" && (
        <RescheduleDialog
          currentWeek={weekOffset + 1}
          totalWeeks={config.settings.total_weeks}
          onClose={() => setDialog(null)}
          onCompleted={async (result) => {
            setDialog(null);
            setToast(`调课完成，移动了 ${result.moved} 个课程段`);
            await loadData();
          }}
        />
      )}
      {dialog?.type === "weeks" && (
        <WeekPickerDialog
          currentWeek={weekOffset}
          todayWeek={todayWeek}
          totalWeeks={config.settings.total_weeks}
          onSelect={setWeekOffset}
          onClose={() => setDialog(null)}
        />
      )}

      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}

function isoWeekday(date: Date): number {
  return date.getDay() === 0 ? 7 : date.getDay();
}
