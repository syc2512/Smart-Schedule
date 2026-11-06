import { useRef, useState } from "react";
import { api } from "../api";
import type { JsonImportResult } from "../types";
import { Icon } from "./Icon";
import { Modal } from "./Modal";

export function JsonImportDialog({
  onClose,
  onImported,
}: {
  onClose: () => void;
  onImported: (count: number) => Promise<void>;
}) {
  const [content, setContent] = useState("");
  const [fileName, setFileName] = useState("");
  const [preview, setPreview] = useState<JsonImportResult | null>(null);
  const [replaceCourses, setReplaceCourses] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const readFile = async (file: File | undefined) => {
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) {
      setError("JSON 文件不能超过 2MB");
      return;
    }
    try {
      const text = await file.text();
      setContent(text);
      setFileName(file.name);
      setPreview(null);
      setError("");
    } catch {
      setError("文件读取失败");
    }
  };

  const parse = async () => {
    setError("");
    if (!content.trim()) {
      setError("请选择 JSON 文件或粘贴 JSON 内容");
      return;
    }
    setBusy(true);
    try {
      const result = await api.previewJson(content);
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
    setBusy(true);
    setError("");
    try {
      const response = await api.commitJson(
        preview.courses,
        preview.schedule,
        replaceCourses,
      );
      await onImported(response.imported);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "导入失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title="导入 JSON 课表" eyebrow="数据互操作" onClose={onClose} wide>
      <div className="import-layout">
        <section>
          <label className="field">
            <span>JSON 内容</span>
            <textarea
              rows={10}
              value={content}
              onChange={(event) => {
                setContent(event.target.value);
                setFileName("");
                setPreview(null);
              }}
              placeholder="选择文件，或在此粘贴 JSON"
            />
          </label>
        </section>
        <section className="image-upload-panel">
          <span>选择 JSON 文件</span>
          <input
            ref={inputRef}
            hidden
            type="file"
            accept="application/json,.json"
            onChange={(event) => void readFile(event.target.files?.[0])}
          />
          <button
            className="upload-drop"
            type="button"
            onClick={() => inputRef.current?.click()}
          >
            <Icon name="import" size={28} />
            <strong>{fileName || "选择课表 JSON"}</strong>
            <span>支持智能课程表 Pro 与拾光课程表格式</span>
          </button>
        </section>
      </div>

      <div className="import-action-row">
        <p>
          导入前会映射字段并重新校验。拾光文件中的作息和学期设置会一并预览。
        </p>
        <button className="button primary" type="button" onClick={parse} disabled={busy}>
          {busy ? "校验中…" : "解析并预览"}
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
                {preview.schedule && <span className="muted"> · 含课表设置</span>}
              </h3>
            </div>
            <span className={`status-badge ${preview.source === "unknown" ? "amber" : "green"}`}>
              {sourceLabel(preview.source)}
            </span>
          </div>
          {preview.warnings.length > 0 && (
            <div className="notice warning">
              <Icon name="warning" />
              {preview.warnings.join("；")}
            </div>
          )}
          <div className="import-stat-grid">
            <div><strong>{preview.courses.length}</strong><span>课程</span></div>
            <div><strong>{preview.schedule?.time_slots.length ?? 0}</strong><span>作息节次</span></div>
            <div><strong>{preview.schedule?.holidays.length ?? 0}</strong><span>节假日</span></div>
          </div>
          <div className="preview-courses">
            {preview.courses.slice(0, 8).map((course, index) => (
              <div className="preview-course selected" key={`${course.name}-${index}`}>
                <div className="preview-course-main">
                  <strong>{course.name}</strong>
                  <span>{course.teacher || "教师未知"}</span>
                  <span>{course.sections[0]?.location || "地点未知"}</span>
                </div>
                <em>{course.weeks.length} 周</em>
              </div>
            ))}
          </div>
          {preview.courses.length > 8 && (
            <p className="muted">另有 {preview.courses.length - 8} 门课程未展开。</p>
          )}
          <label className="switch-field warning-switch">
            <span>覆盖当前全部课程</span>
            <input
              type="checkbox"
              checked={replaceCourses}
              onChange={(event) => setReplaceCourses(event.target.checked)}
            />
          </label>
          <div className="modal-actions">
            <span className="action-spacer" />
            <button className="button ghost" type="button" onClick={onClose}>取消</button>
            <button
              className="button primary"
              type="button"
              onClick={commit}
              disabled={busy || !preview.courses.length || preview.source === "unknown"}
            >
              确认导入 {preview.courses.length} 门课程
            </button>
          </div>
        </section>
      )}
    </Modal>
  );
}

function sourceLabel(source: JsonImportResult["source"]): string {
  if (source === "shiguangschedule") return "拾光兼容格式";
  if (source === "smart-timetable-pro") return "智能课程表 Pro";
  return "未知格式";
}
