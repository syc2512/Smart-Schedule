import { useMemo, useState } from "react";
import { api } from "../api";
import type { AppConfig, Course, SelfPlan } from "../types";
import {
  WEEKDAYS,
  dateString,
  formatDuration,
  freeBlocks,
  parityForDate,
  splitBlocks,
  toClock,
  weekOffsetForDate,
} from "../utils";
import { Icon } from "./Icon";
import { Modal } from "./Modal";

const SUGGESTIONS = ["课后复习", "考研英语", "数学刷题", "行测刷题", "整理笔记"];

export function PlannerDialog({
  courses,
  config,
  semesterStart,
  initialDate,
  onClose,
  onCreated,
}: {
  courses: Course[];
  config: AppConfig;
  semesterStart: Date;
  initialDate: Date;
  onClose: () => void;
  onCreated: (count: number) => Promise<void>;
}) {
  const [selectedDate, setSelectedDate] = useState(dateString(initialDate));
  const [tasks, setTasks] = useState<string[]>(["课后复习", "考研英语"]);
  const [customTask, setCustomTask] = useState("");
  const [selectedBlocks, setSelectedBlocks] = useState<Set<string>>(new Set());
  const [aiNotes, setAiNotes] = useState("");
  const [degraded, setDegraded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const date = useMemo(() => new Date(`${selectedDate}T00:00:00`), [selectedDate]);
  const weekday = date.getDay() === 0 ? 7 : date.getDay();
  const weekOffset = weekOffsetForDate(
    date,
    semesterStart,
    config.settings.first_day_of_week,
  );
  const weekNumber = weekOffset + 1;
  const parity = parityForDate(
    date,
    semesterStart,
    config.settings.first_day_of_week,
  );
  const isHoliday = config.holidays.some((holiday) => holiday.date === selectedDate);
  const blocks = isHoliday
    ? []
    : freeBlocks(
        courses,
        weekNumber,
        weekday,
        parity,
        config.time_slots,
      );
  const sourceBlocks = blocks.filter(([start, end]) =>
    selectedBlocks.size ? selectedBlocks.has(`${start}-${end}`) : true,
  );
  const segments = splitBlocks(sourceBlocks, tasks.length);
  const courseNames = courses
    .filter(
      (course) =>
        course.weeks.length
          ? course.weeks.includes(weekNumber)
          : course.week_type === "all" || course.week_type === parity,
    )
    .filter((course) => course.sections.some((section) => section.weekday === weekday))
    .map((course) => course.name);

  const toggleBlock = (start: number, end: number) => {
    const key = `${start}-${end}`;
    const next = new Set(selectedBlocks);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setSelectedBlocks(next);
    setAiNotes("");
  };

  const addTask = (task: string) => {
    const clean = task.trim().slice(0, 40);
    if (!clean || tasks.includes(clean) || tasks.length >= 8) return;
    setTasks([...tasks, clean]);
    setCustomTask("");
    setAiNotes("");
  };

  const askAI = async () => {
    if (!segments.length) {
      setError("现有空闲时间不足以安排当前任务");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const response = await api.aiPlan({
        date: selectedDate,
        weekday,
        parity,
        free_blocks: segments,
        tasks,
        courses: courseNames,
      });
      setAiNotes(response.plan);
      setDegraded(response.degraded);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "规划生成失败");
    } finally {
      setBusy(false);
    }
  };

  const commit = async () => {
    if (!segments.length) {
      setError("请选择有足够时间的空闲段");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await Promise.all(
        segments.map(([start, end], index) =>
          api.createPlan({
            title: tasks[index],
            date: selectedDate,
            weekday,
            start_min: start,
            end_min: end,
            notes: aiNotes,
            category: classify(tasks[index]),
          }),
        ),
      );
      await onCreated(segments.length);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "写入失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title="空闲规划助手" eyebrow="发现空档 · 生成计划" onClose={onClose} wide>
      <div className="planner-top">
        <label className="field">
          <span>规划日期</span>
          <input
            type="date"
            value={selectedDate}
            onChange={(event) => {
              setSelectedDate(event.target.value);
              setSelectedBlocks(new Set());
              setAiNotes("");
            }}
          />
        </label>
        <div className="day-summary">
          <span>{WEEKDAYS[weekday - 1]}</span>
          <strong>{parity === "odd" ? "单周" : "双周"}</strong>
          <span>{courseNames.length ? `当日 ${courseNames.length} 门课程` : "当日无课"}</span>
        </div>
      </div>

      <div className="field">
        <span>本次学习任务</span>
        <div className="tag-row">
          {tasks.map((task) => (
            <button
              className="task-chip selected"
              key={task}
              type="button"
              onClick={() => setTasks(tasks.filter((item) => item !== task))}
              title="点击移除"
            >
              {task}
              <Icon name="x" size={12} />
            </button>
          ))}
        </div>
        <div className="inline-input">
          <input
            maxLength={40}
            value={customTask}
            placeholder="输入自定义任务，如：复习数据结构"
            onChange={(event) => setCustomTask(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                addTask(customTask);
              }
            }}
          />
          <button className="button secondary" type="button" onClick={() => addTask(customTask)}>
            添加
          </button>
        </div>
        <div className="suggestions">
          {SUGGESTIONS.filter((item) => !tasks.includes(item)).map((item) => (
            <button className="suggestion-chip" type="button" key={item} onClick={() => addTask(item)}>
              + {item}
            </button>
          ))}
        </div>
      </div>

      <div className="field">
        <span>可用空闲时间</span>
        {blocks.length ? (
          <div className="free-block-grid">
            {blocks.map(([start, end]) => {
              const key = `${start}-${end}`;
              return (
                <button
                  className={`free-block ${selectedBlocks.has(key) ? "selected" : ""}`}
                  type="button"
                  key={key}
                  onClick={() => toggleBlock(start, end)}
                >
                  <Icon name="clock" />
                  <strong>
                    {toClock(start)}–{toClock(end)}
                  </strong>
                  <span>{formatDuration(end - start)}</span>
                  <em>{selectedBlocks.has(key) ? "已选" : "选择"}</em>
                </button>
              );
            })}
          </div>
        ) : (
          <div className="empty-inline">当日没有可规划的空闲时间。</div>
        )}
      </div>

      {segments.length > 0 ? (
        <section className="plan-preview">
          <div className="preview-head">
            <div>
              <p className="eyebrow">自动分配结果</p>
              <h3>{segments.length} 个专注时段</h3>
            </div>
            <button className="button ai" type="button" onClick={askAI} disabled={busy}>
              <Icon name="spark" />
              {busy ? "生成中…" : "AI 生成建议"}
            </button>
          </div>
          <ol className="plan-list">
            {segments.map(([start, end], index) => (
              <li key={`${start}-${end}`}>
                <span className={`category-dot ${classify(tasks[index])}`} />
                <div>
                  <strong>{tasks[index]}</strong>
                  <span>
                    {toClock(start)}–{toClock(end)} · {formatDuration(end - start)}
                  </span>
                  {aiNotes && <p>{aiNotes}</p>}
                </div>
              </li>
            ))}
          </ol>
          {aiNotes && (
            <div className={`notice ${degraded ? "warning" : "success"}`}>
              <Icon name={degraded ? "warning" : "spark"} />
              <div>
                <strong>{degraded ? "当前使用本地规划" : "AI 建议已生成"}</strong>
                <p className="preserve-lines">{aiNotes}</p>
              </div>
            </div>
          )}
        </section>
      ) : (
        <div className="notice warning">
          <Icon name="warning" />
          空闲时间不足以分配当前任务，每个任务至少需要 20 分钟。
        </div>
      )}

      {error && <div className="notice error">{error}</div>}
      <div className="modal-actions">
        <span className="action-spacer" />
        <button className="button ghost" type="button" onClick={onClose}>
          取消
        </button>
        <button
          className="button primary"
          type="button"
          onClick={commit}
          disabled={busy || !segments.length}
        >
          写入课程表
        </button>
      </div>
    </Modal>
  );
}

function classify(task: string): SelfPlan["category"] {
  if (/考公|行测|申论|公务员/.test(task)) return "kg";
  if (/考研|英一|英二|数学[一二三]|专业课/.test(task)) return "kaoyan";
  if (/整理|复习|阅读|刷题|笔记|学习/.test(task)) return "study";
  return "personal";
}
