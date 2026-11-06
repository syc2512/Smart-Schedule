import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type {
  ImportProfile,
  TabularImportOptions,
  TabularImportPreview,
} from "../types";
import { Icon } from "./Icon";
import { Modal } from "./Modal";

const EMPTY_OPTIONS: TabularImportOptions = {
  header_row: 0,
  course_column: "",
  time_column: "",
  location_column: "",
  teacher_column: "",
  multi_separator: ";",
  odd_marker: "单周",
  even_marker: "双周",
  time_regex: "",
  campus_rules: {},
};

export function TabularImportDialog({
  onClose,
  onImported,
}: {
  onClose: () => void;
  onImported: (count: number, skipped: number) => Promise<void>;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [options, setOptions] = useState<TabularImportOptions>(EMPTY_OPTIONS);
  const [profiles, setProfiles] = useState<ImportProfile[]>([]);
  const [selectedProfile, setSelectedProfile] = useState("");
  const [preview, setPreview] = useState<TabularImportPreview | null>(null);
  const [strategy, setStrategy] = useState<
    "append" | "skip_duplicates" | "overwrite_names" | "replace"
  >("append");
  const [saveProfile, setSaveProfile] = useState(true);
  const [profileName, setProfileName] = useState("");
  const [campusRulesText, setCampusRulesText] = useState("{}");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void api.importProfiles().then(setProfiles).catch(() => setProfiles([]));
  }, []);

  const updateOption = <K extends keyof TabularImportOptions,>(
    key: K,
    value: TabularImportOptions[K],
  ) => {
    setOptions((current) => ({ ...current, [key]: value }));
    setPreview(null);
  };

  const chooseProfile = (id: string) => {
    setSelectedProfile(id);
    const profile = profiles.find((item) => item.id === id);
    if (!profile) return;
    setOptions({
      header_row: profile.header_row,
      course_column: profile.course_column,
      time_column: profile.time_column,
      location_column: profile.location_column,
      teacher_column: profile.teacher_column,
      multi_separator: profile.multi_separator,
      odd_marker: profile.odd_marker,
      even_marker: profile.even_marker,
      time_regex: profile.time_regex ?? "",
      campus_rules: profile.campus_rules ?? {},
    });
    setProfileName(profile.name);
    setCampusRulesText(JSON.stringify(profile.campus_rules ?? {}, null, 2));
    setPreview(null);
  };

  const deleteSelectedProfile = async () => {
    if (!selectedProfile) return;
    setBusy(true);
    try {
      await api.deleteImportProfile(selectedProfile);
      setProfiles(profiles.filter((item) => item.id !== selectedProfile));
      setSelectedProfile("");
      setProfileName("");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "删除模板失败");
    } finally {
      setBusy(false);
    }
  };

  const parse = async () => {
    setError("");
    if (!file) {
      setError("请选择 Excel 或 CSV 文件");
      return;
    }
    setBusy(true);
    try {
      let campusRules: TabularImportOptions["campus_rules"] = {};
      try {
        const parsedRules = JSON.parse(campusRulesText || "{}");
        if (
          !parsedRules ||
          typeof parsedRules !== "object" ||
          Array.isArray(parsedRules)
        ) {
          throw new Error("多校区作息必须是 JSON 对象");
        }
        campusRules = parsedRules as TabularImportOptions["campus_rules"];
      } catch (rulesError) {
        throw new Error(
          rulesError instanceof Error
            ? `多校区作息格式错误：${rulesError.message}`
            : "多校区作息格式错误",
        );
      }
      const resolvedOptions = { ...options, campus_rules: campusRules };
      setOptions(resolvedOptions);
      const result = await api.previewTabular(file, resolvedOptions);
      setPreview(result);
      if (!result.ok) setError(result.warnings.join("；") || "未识别到课程");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "解析失败");
    } finally {
      setBusy(false);
    }
  };

  const commit = async () => {
    if (!preview?.courses.length) return;
    if (saveProfile && !profileName.trim()) {
      setError("请填写导入模板名称，或取消保存模板");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await api.commitTabular(
        preview.courses,
        strategy,
        saveProfile ? { ...options, name: profileName.trim() } : undefined,
      );
      await onImported(result.imported, result.skipped);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "导入失败");
    } finally {
      setBusy(false);
    }
  };

  const columnOptions = preview?.headers ?? [];

  return (
    <Modal title="Excel / CSV 课表导入" eyebrow="规则解析 · 预览 · 模板" onClose={onClose} wide>
      <section className="tabular-upload-grid">
        <div>
          <input
            ref={inputRef}
            hidden
            type="file"
            accept=".xlsx,.xls,.csv"
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              setPreview(null);
              setError("");
              if (event.target.files?.[0]) {
                setProfileName(event.target.files[0].name.replace(/\.[^.]+$/, " 模板"));
              }
            }}
          />
          <button
            className="upload-drop tabular-upload"
            type="button"
            onClick={() => inputRef.current?.click()}
          >
            <Icon name="import" size={28} />
            <strong>{file?.name || "选择教务 Excel / CSV"}</strong>
            <span>支持 .xlsx、.xls、.csv，最大 5MB</span>
          </button>
        </div>
        <div className="profile-panel">
          <label className="field">
            <span>已有导入模板</span>
            <select value={selectedProfile} onChange={(event) => chooseProfile(event.target.value)}>
              <option value="">使用自动识别</option>
              {profiles.map((profile) => (
                <option value={profile.id} key={profile.id}>{profile.name}</option>
              ))}
            </select>
          </label>
          {selectedProfile && (
            <button
              className="text-button danger"
              type="button"
              onClick={() => void deleteSelectedProfile()}
              disabled={busy}
            >
              删除当前模板
            </button>
          )}
          <p className="note">模板会保存列映射、表头行、分隔符和单双周标记。</p>
        </div>
      </section>

      <section className="settings-section tabular-options">
        <div className="settings-section-title">
          <div>
            <p className="eyebrow">列映射</p>
            <h3>列映射</h3>
          </div>
          <span className="muted">留空时自动识别</span>
        </div>
        <div className="tabular-option-grid">
          <label className="field">
            <span>表头行（0=自动）</span>
            <input
              type="number"
              min={0}
              max={100}
              value={options.header_row}
              onChange={(event) => updateOption("header_row", Number(event.target.value))}
            />
          </label>
          {[
            ["course_column", "课程列"],
            ["time_column", "时间列"],
            ["location_column", "地点列"],
            ["teacher_column", "教师列"],
          ].map(([key, label]) => (
            <label className="field" key={key}>
              <span>{label}</span>
              {columnOptions.length ? (
                <select
                  value={options[key as keyof TabularImportOptions] as string}
                  onChange={(event) =>
                    updateOption(
                      key as keyof TabularImportOptions,
                      event.target.value as never,
                    )
                  }
                >
                  <option value="">自动 / 不使用</option>
                  {columnOptions.map((column) => (
                    <option value={column} key={column}>{column}</option>
                  ))}
                </select>
              ) : (
                <input
                  value={options[key as keyof TabularImportOptions] as string}
                  placeholder="解析后自动填入"
                  onChange={(event) =>
                    updateOption(
                      key as keyof TabularImportOptions,
                      event.target.value as never,
                    )
                  }
                />
              )}
            </label>
          ))}
          <label className="field">
            <span>多段分隔符</span>
            <input
              maxLength={10}
              value={options.multi_separator}
              onChange={(event) => updateOption("multi_separator", event.target.value)}
            />
          </label>
          <label className="field">
            <span>单周标记</span>
            <input
              maxLength={10}
              value={options.odd_marker}
              onChange={(event) => updateOption("odd_marker", event.target.value)}
            />
          </label>
          <label className="field">
            <span>双周标记</span>
            <input
              maxLength={10}
              value={options.even_marker}
              onChange={(event) => updateOption("even_marker", event.target.value)}
            />
          </label>
          <label className="field">
            <span>自定义时间正则（可选）</span>
            <input
              maxLength={500}
              value={options.time_regex}
              onChange={(event) => updateOption("time_regex", event.target.value)}
              placeholder="3 个捕获组：星期、节次、周次"
            />
          </label>
        </div>
        <label className="field campus-rules-field">
          <span>多校区作息（可选 JSON）</span>
          <textarea
            rows={5}
            value={campusRulesText}
            onChange={(event) => {
              setCampusRulesText(event.target.value);
              setPreview(null);
            }}
            placeholder={'{"东校区":[{"period":1,"start":"08:30","end":"09:15"}]}'}
          />
          <small className="note">
            地点包含校区关键词时优先使用对应作息，并写入精确起止时间。
          </small>
        </label>
      </section>

      <div className="import-action-row">
        <p>文件只在内存中解析，不会保存原始 Excel。识别结果必须确认后才会写入数据库。</p>
        <button className="button primary" type="button" onClick={parse} disabled={busy || !file}>
          <Icon name="spark" />
          {busy ? "解析中…" : "解析并预览"}
        </button>
      </div>

      {error && <div className="notice error">{error}</div>}
      {preview && (
        <section className="preview-panel">
          <div className="preview-head">
            <div>
              <p className="eyebrow">导入预览</p>
              <h3>
                {preview.courses.length} 门课程
                {preview.sheet_name && <span className="muted"> · {preview.sheet_name}</span>}
              </h3>
            </div>
            <span className={`status-badge ${preview.ok ? "green" : "amber"}`}>
              读取 {preview.rows_read} 行
            </span>
          </div>
          <div className="import-stat-grid">
            <div><strong>{preview.courses.length}</strong><span>可导入课程</span></div>
            <div><strong>{preview.skipped_rows}</strong><span>跳过行</span></div>
            <div><strong>{preview.warnings.length}</strong><span>警告</span></div>
          </div>
          {Object.keys(preview.detected_columns).length > 0 && (
            <div className="mapping-summary">
              {Object.entries(preview.detected_columns).map(([key, value]) => (
                <span key={key}>
                  <b>{columnLabel(key)}</b>
                  {value || "未映射"}
                </span>
              ))}
            </div>
          )}
          {preview.warnings.length > 0 && (
            <div className="notice warning">
              <Icon name="warning" />
              <div>
                {preview.warnings.slice(0, 12).map((warning) => (
                  <p key={warning}>{warning}</p>
                ))}
                {preview.warnings.length > 12 && (
                  <p>另有 {preview.warnings.length - 12} 条警告</p>
                )}
              </div>
            </div>
          )}
          <div className="tabular-preview-table">
            <div className="tabular-preview-row head">
              <span>课程</span><span>星期 / 节次</span><span>教师</span><span>地点</span><span>周次</span>
            </div>
            {preview.courses.slice(0, 10).map((course, index) => (
              <div className="tabular-preview-row" key={`${course.name}-${index}`}>
                <strong>{course.name}</strong>
                <span>{weekdayText(course.sections[0]?.weekday)} · {course.sections[0]?.start_period}-{course.sections[0]?.end_period} 节</span>
                <span>{course.teacher || "—"}</span>
                <span>{course.sections[0]?.location || "—"}</span>
                <span>{course.weeks.length} 周</span>
              </div>
            ))}
          </div>

          <div className="tabular-commit-grid">
            <label className="field">
              <span>重复课程策略</span>
              <select
                value={strategy}
                onChange={(event) =>
                  setStrategy(event.target.value as typeof strategy)
                }
              >
                <option value="append">追加全部课程</option>
                <option value="skip_duplicates">跳过完全重复课程</option>
                <option value="overwrite_names">覆盖同名课程</option>
                <option value="replace">替换全部课程</option>
              </select>
            </label>
            <label className="switch-field">
              <span>保存为导入模板</span>
              <input
                type="checkbox"
                checked={saveProfile}
                onChange={(event) => setSaveProfile(event.target.checked)}
              />
            </label>
            {saveProfile && (
              <label className="field">
                <span>模板名称</span>
                <input
                  maxLength={60}
                  value={profileName}
                  onChange={(event) => setProfileName(event.target.value)}
                  placeholder="例如：计算机学院教务模板"
                />
              </label>
            )}
          </div>

          <div className="modal-actions">
            <span className="action-spacer" />
            <button className="button ghost" type="button" onClick={onClose}>取消</button>
            <button
              className="button primary"
              type="button"
              onClick={commit}
              disabled={busy || !preview.courses.length}
            >
              {busy ? "导入中…" : `确认导入 ${preview.courses.length} 门课程`}
            </button>
          </div>
        </section>
      )}
    </Modal>
  );
}

function columnLabel(key: string): string {
  return {
    course: "课程",
    time: "时间",
    location: "地点",
    teacher: "教师",
  }[key] ?? key;
}

function weekdayText(day: number | undefined): string {
  return day ? ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][day - 1] : "未知";
}
