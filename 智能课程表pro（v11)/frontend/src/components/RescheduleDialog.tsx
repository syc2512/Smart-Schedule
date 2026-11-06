import { useState } from "react";
import { api } from "../api";
import type { RescheduleResult } from "../types";
import { WEEKDAYS } from "../utils";
import { Icon } from "./Icon";
import { Modal } from "./Modal";

const MODES = [
  ["merge", "移动", "将源日期课程移动到目标日期，保留目标课程"],
  ["overwrite", "覆盖", "移除目标日期原有课程，再移动源日期课程"],
  ["exchange", "交换", "把源日期与目标日期的课程互换"],
] as const;

export function RescheduleDialog({
  currentWeek,
  totalWeeks,
  onClose,
  onCompleted,
}: {
  currentWeek: number;
  totalWeeks: number;
  onClose: () => void;
  onCompleted: (result: RescheduleResult) => Promise<void>;
}) {
  const [mode, setMode] = useState<"merge" | "overwrite" | "exchange">("merge");
  const [sourceWeek, setSourceWeek] = useState(currentWeek);
  const [sourceDay, setSourceDay] = useState(1);
  const [targetWeek, setTargetWeek] = useState(
    Math.min(totalWeeks, Math.max(1, currentWeek + 1)),
  );
  const [targetDay, setTargetDay] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<RescheduleResult | null>(null);

  const execute = async () => {
    setError("");
    if (sourceWeek === targetWeek && sourceDay === targetDay) {
      setError("源日期和目标日期不能相同");
      return;
    }
    setBusy(true);
    try {
      const response = await api.reschedule({
        mode,
        source_week: sourceWeek,
        source_day: sourceDay,
        target_week: targetWeek,
        target_day: targetDay,
      });
      setResult(response);
      if (!response.ok) setError(response.warnings.join("；") || "没有可调动的课程");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "调课失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title="课程调课" eyebrow="移动 · 覆盖 · 交换" onClose={onClose} wide>
      <div className="reschedule-route">
        <DateSelector
          title="源日期"
          week={sourceWeek}
          day={sourceDay}
          totalWeeks={totalWeeks}
          onWeek={setSourceWeek}
          onDay={setSourceDay}
        />
        <div className="reschedule-arrow">
          <Icon name={mode === "exchange" ? "download" : "chevron-right"} size={24} />
        </div>
        <DateSelector
          title="目标日期"
          week={targetWeek}
          day={targetDay}
          totalWeeks={totalWeeks}
          onWeek={setTargetWeek}
          onDay={setTargetDay}
        />
      </div>

      <div className="field">
        <span>处理方式</span>
        <div className="mode-card-grid">
          {MODES.map(([value, label, description]) => (
            <button
              className={`mode-card ${mode === value ? "selected" : ""}`}
              key={value}
              type="button"
              onClick={() => {
                setMode(value);
                setResult(null);
              }}
            >
              <strong>{label}</strong>
              <span>{description}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="notice warning">
        <Icon name="warning" />
        调课会修改数据库中的该周课程实例，并立即影响课表和日历导出。操作前建议先导出 JSON 备份。
      </div>
      {error && <div className="notice error">{error}</div>}
      {result?.ok && (
        <div className="notice success">
          <Icon name="calendar" />
          已移动 {result.moved} 个课程段，移除目标日期 {result.removed_target_occurrences} 个原课程段。
        </div>
      )}
      <div className="modal-actions">
        <span className="action-spacer" />
        <button className="button ghost" type="button" onClick={onClose} disabled={busy}>
          关闭
        </button>
        {result?.ok ? (
          <button
            className="button primary"
            type="button"
            onClick={() => void onCompleted(result)}
          >
            完成并刷新
          </button>
        ) : (
          <button className="button primary" type="button" onClick={execute} disabled={busy}>
            {busy ? "执行中…" : `确认${MODES.find(([value]) => value === mode)?.[1]}`}
          </button>
        )}
      </div>
    </Modal>
  );
}

function DateSelector({
  title,
  week,
  day,
  totalWeeks,
  onWeek,
  onDay,
}: {
  title: string;
  week: number;
  day: number;
  totalWeeks: number;
  onWeek: (value: number) => void;
  onDay: (value: number) => void;
}) {
  return (
    <div className="date-selector">
      <p className="eyebrow">{title}</p>
      <label className="field">
        <span>周次</span>
        <select value={week} onChange={(event) => onWeek(Number(event.target.value))}>
          {Array.from({ length: totalWeeks }, (_, index) => index + 1).map((value) => (
            <option value={value} key={value}>第 {value} 周</option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>星期</span>
        <select value={day} onChange={(event) => onDay(Number(event.target.value))}>
          {WEEKDAYS.map((value, index) => (
            <option value={index + 1} key={value}>{value}</option>
          ))}
        </select>
      </label>
    </div>
  );
}
